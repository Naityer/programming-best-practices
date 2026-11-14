"""Python frontend: `stdlib ast` only, Level B (spec §6/§7).

Never imports the audited project (spec §16/§29's `RepositoryWithoutRepository
Pattern` and friends must fail structurally, not by accident of import
machinery) — only `ast.parse` is used, nothing is executed.

Everything this module infers comes from the AST's actual shape: assignments,
call expressions, decorators, real base classes like `abc.ABC`. It never
branches on an identifier's *text* to decide what pattern it implies — a
class or method name is carried through into `Entity.name` for humans and for
the (later, `supporting`-only) name checks, and nowhere else.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from ..ir import DiscriminatorBranch, Entity, Relation
from .base import SourceUnit

LEVEL = "B"

_ABSTRACT_SENTINELS = {"ABC", "ABCMeta", "Protocol"}
_COLLECTION_ANNOTATIONS = {"list", "set", "frozenset", "sequence", "iterable", "tuple", "dict", "mutablesequence"}


def _entity_id(file: str, qualified_name: str) -> str:
    return hashlib.sha1(f"{file}:{qualified_name}".encode("utf-8")).hexdigest()[:16]


def _dotted_name(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _simple_name(node: ast.AST | None) -> str | None:
    dotted = _dotted_name(node)
    return dotted.rsplit(".", 1)[-1] if dotted else None


def _annotation_name(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Subscript):
        inner = node.slice
        if isinstance(inner, ast.Tuple) and inner.elts:
            inner = inner.elts[0]
        return _annotation_name(inner) or _simple_name(node.value)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return _simple_name(node)


def _is_collection_annotation(node: ast.expr | None) -> bool:
    if isinstance(node, ast.Subscript):
        base = _simple_name(node.value) or ""
        return base.lower() in _COLLECTION_ANNOTATIONS
    return False


def _iter_own_nodes(node: ast.AST):
    """Descendants of `node`, excluding bodies of nested defs/lambdas/classes
    so a closure's calls are never misattributed to the enclosing method."""
    for child in ast.iter_child_nodes(node):
        yield child
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            yield from _iter_own_nodes(child)


def _is_docstring(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)


def _body_without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    return [s for s in body if not _is_docstring(s)]


def _raises_not_implemented(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Raise)
        and stmt.exc is not None
        and _simple_name(stmt.exc.func if isinstance(stmt.exc, ast.Call) else stmt.exc) == "NotImplementedError"
    )


def _is_abstract_shaped_body(body: list[ast.stmt]) -> bool:
    rest = _body_without_docstring(body)
    if not rest:
        return True
    if len(rest) == 1:
        stmt = rest[0]
        if isinstance(stmt, ast.Pass):
            return True
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis:
            return True
        if _raises_not_implemented(stmt):
            return True
    return False


@dataclass
class _FieldInfo:
    name: str
    line: int
    type_name: str | None = None
    is_collection: bool = False
    element_type: str | None = None
    assigned_types: set[str] = field(default_factory=set)  # across ALL methods, for TRANSITIONS_TO


@dataclass
class _MethodInfo:
    name: str
    line: int
    params: tuple[str, ...]
    param_types: dict[str, str]
    decorator_names: tuple[str, ...]
    is_abstract_shaped: bool
    returns_self: bool
    self_call_sequence: tuple[str, ...]
    delegated_calls: tuple[tuple[str, str], ...]  # (attr, method)
    typed_calls: tuple[tuple[str, str], ...]      # (tipo anotado del parámetro, método) para `parametro.metodo(...)`
    instantiated_names: tuple[str, ...]           # bare `Name(...)` call targets
    clones_self: bool
    cache_fields: tuple[str, ...]
    fan_out: tuple[tuple[str, str], ...]          # (collection_field, method_called_per_element)
    accept_delegate: tuple[str, str] | None       # (visitor_param, delegated_method)
    discriminator_branches: tuple[DiscriminatorBranch, ...]


@dataclass
class _ClassInfo:
    name: str
    qualified_name: str
    file: str
    line: int
    bases: tuple[str, ...]
    is_abstract: bool
    methods: dict[str, _MethodInfo]
    fields: dict[str, _FieldInfo]


_ITERATION_WRAPPERS = {"list", "tuple", "sorted", "iter", "reversed"}
_COLLECTION_VIEWS = {"get", "values", "copy", "items"}


def _iterated_self_field(node: ast.AST) -> str | None:
    """El campo `self.<x>` sobre el que se itera, aunque se itere una copia o una vista: `list(self._x)`, `self._x.get(k, [])`, `self._x[k]`…

    Los suscriptores se copian antes de recorrerlos para poder darse de baja durante la notificación; sin esto, ese patrón (el habitual) se perdía."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
        return node.attr
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _ITERATION_WRAPPERS and node.args:
        return _iterated_self_field(node.args[0])
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _COLLECTION_VIEWS:
        return _iterated_self_field(node.func.value)
    if isinstance(node, ast.Subscript):
        return _iterated_self_field(node.value)
    return None


def _guarded_class_attribute(test: ast.AST) -> str | None:
    """El atributo que comprueba una guarda de «aún no hay instancia»: `X.a is None` o `not X.a`."""
    if isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Is) and isinstance(test.comparators[0], ast.Constant) \
            and test.comparators[0].value is None and isinstance(test.left, ast.Attribute) and isinstance(test.left.value, ast.Name):
        return test.left.attr
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) and isinstance(test.operand, ast.Attribute) and isinstance(test.operand.value, ast.Name):
        return test.operand.attr
    return None


def _creates_own_instance(value: ast.AST, class_name: str) -> bool:
    """`Clase()`, `cls()`, `super().__new__(cls)` u `object.__new__(cls)` dentro de la propia clase."""
    if not isinstance(value, ast.Call):
        return False
    function = value.func
    if isinstance(function, ast.Name):
        return function.id in {"cls", class_name}
    return isinstance(function, ast.Attribute) and function.attr == "__new__" and bool(value.args) \
        and isinstance(value.args[0], ast.Name) and value.args[0].id in {"cls", class_name}


def _class_level_singleton_attributes(node: ast.FunctionDef | ast.AsyncFunctionDef, class_name: str) -> set[str]:
    """Singleton con atributo de CLASE: `if cls._x is None: cls._x = <la propia clase>` (en un `get_instance` o en `__new__`).

    Evidencia estructural dura: una guarda que comprueba que el atributo está vacío Y una asignación a ese mismo atributo de una instancia de la
    propia clase. No se mira cómo se llama el método: un `instance()` que no hace eso no cuenta."""
    attributes: set[str] = set()
    for guard in (n for n in _iter_own_nodes(node) if isinstance(n, ast.If)):
        attribute = _guarded_class_attribute(guard.test)
        if attribute is None:
            continue
        for statement in ast.walk(ast.Module(body=guard.body, type_ignores=[])):
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
                target = statement.targets[0]
                if isinstance(target, ast.Attribute) and target.attr == attribute and isinstance(target.value, ast.Name) \
                        and target.value.id in {"cls", class_name} and _creates_own_instance(statement.value, class_name):
                    attributes.add(attribute)
    return attributes


def _analyze_method(node: ast.FunctionDef | ast.AsyncFunctionDef, fields: dict[str, _FieldInfo], class_name: str = "") -> _MethodInfo:
    args = node.args
    all_args = [*args.posonlyargs, *args.args, *args.kwonlyargs]
    params = tuple(a.arg for a in all_args if a.arg != "self")
    param_types = {a.arg: name for a in all_args if a.arg != "self" and (name := _annotation_name(a.annotation))}
    decorator_names = tuple(name for dec in node.decorator_list if (name := _simple_name(dec)))
    is_abstract_shaped = "abstractmethod" in decorator_names or _is_abstract_shaped_body(node.body)

    returns_self = False
    self_call_sequence: list[str] = []
    delegated_calls: list[tuple[str, str]] = []
    typed_calls: list[tuple[str, str]] = []
    instantiated_names: list[str] = []
    clones_self = False
    cache_fields: set[str] = set()
    fan_out: list[tuple[str, str]] = []
    accept_delegate: tuple[str, str] | None = None

    is_init = node.name == "__init__"

    own_singleton_attributes = _class_level_singleton_attributes(node, class_name) if class_name else set()
    if own_singleton_attributes:
        cache_fields.update(own_singleton_attributes)
        instantiated_names.append(class_name)  # `super().__new__(cls)` no es una llamada a un nombre: se anota la propia clase

    for n in _iter_own_nodes(node):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Name) and n.value.id == "self":
            returns_self = True

        elif isinstance(n, ast.Assign) and len(n.targets) == 1:
            target = n.targets[0]
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                fname = target.attr
                info = fields.setdefault(fname, _FieldInfo(name=fname, line=n.lineno))
                value = n.value
                if isinstance(value, ast.Name) and value.id in param_types:
                    info.type_name = info.type_name or param_types[value.id]
                    info.assigned_types.add(param_types[value.id])
                elif isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                    type_name = value.func.id
                    info.type_name = info.type_name or type_name
                    info.assigned_types.add(type_name)
                    if not is_init:
                        instantiated_names.append(type_name)
                elif isinstance(value, (ast.List, ast.Set)) and not value.elts:
                    info.is_collection = True
                elif isinstance(value, ast.Dict) and not value.keys:
                    info.is_collection = True

        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Attribute) \
                and isinstance(n.target.value, ast.Name) and n.target.value.id == "self":
            fname = n.target.attr
            info = fields.setdefault(fname, _FieldInfo(name=fname, line=n.lineno))
            if _is_collection_annotation(n.annotation):
                info.is_collection = True
                info.element_type = _annotation_name(n.annotation)
            else:
                info.type_name = info.type_name or _annotation_name(n.annotation)

        elif isinstance(n, ast.Call):
            func = n.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Attribute) \
                    and isinstance(func.value.value, ast.Name) and func.value.value.id == "self" \
                    and func.attr == "setdefault":
                # self.<cache_field>.setdefault(key, factory()) — a cache write.
                cache_fields.add(func.value.attr)
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Attribute) \
                    and isinstance(func.value.value, ast.Name) and func.value.value.id == "self":
                delegated_calls.append((func.value.attr, func.attr))
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in param_types and func.value.id != "self":
                typed_calls.append((param_types[func.value.id], func.attr))
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "self":
                if func.attr == "__class__":
                    clones_self = True  # self.__class__(...) — Prototype-shaped clone
                else:
                    self_call_sequence.append(func.attr)
            elif isinstance(func, ast.Attribute) and func.attr == "deepcopy" \
                    and n.args and isinstance(n.args[0], ast.Name) and n.args[0].id == "self":
                clones_self = True  # copy.deepcopy(self)
            elif isinstance(func, ast.Call) and isinstance(func.func, ast.Name) and func.func.id == "type" \
                    and func.args and isinstance(func.args[0], ast.Name) and func.args[0].id == "self":
                clones_self = True  # type(self)(...)
            elif isinstance(func, ast.Name):
                instantiated_names.append(func.id)

        elif isinstance(n, ast.If):
            test = n.test
            if isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.NotIn):
                right = test.comparators[0]
                if isinstance(right, ast.Attribute) and isinstance(right.value, ast.Name) and right.value.id == "self":
                    for stmt in n.body:
                        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                            tgt = stmt.targets[0]
                            if isinstance(tgt, ast.Subscript) and isinstance(tgt.value, ast.Attribute) \
                                    and isinstance(tgt.value.value, ast.Name) and tgt.value.value.id == "self" \
                                    and tgt.value.attr == right.attr:
                                cache_fields.add(right.attr)

        elif isinstance(n, ast.For):
            iterated_field = _iterated_self_field(n.iter)
            if iterated_field is not None and isinstance(n.target, ast.Name):
                loop_var = n.target.id
                for stmt in n.body:
                    call = stmt.value if isinstance(stmt, ast.Expr) else None
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) \
                            and isinstance(call.func.value, ast.Name) and call.func.value.id == loop_var:
                        fan_out.append((iterated_field, call.func.attr))
                    elif isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == loop_var:
                        fan_out.append((iterated_field, "__call__"))  # el elemento es un callback: `for f in self._x: f(datos)`

    # Visitor-shape: exactly one non-self parameter, body is a single
    # statement that calls `<param>.<anything>(...)`.
    if len(params) == 1:
        rest = _body_without_docstring(node.body)
        if len(rest) == 1:
            stmt = rest[0]
            call = None
            if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Call):
                call = stmt.value
            elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                call = stmt.value
            if call is not None and isinstance(call.func, ast.Attribute) \
                    and isinstance(call.func.value, ast.Name) and call.func.value.id == params[0]:
                accept_delegate = (params[0], call.func.attr)

    return _MethodInfo(
        name=node.name,
        line=node.lineno,
        params=params,
        param_types=param_types,
        decorator_names=decorator_names,
        is_abstract_shaped=is_abstract_shaped,
        returns_self=returns_self,
        self_call_sequence=tuple(self_call_sequence),
        delegated_calls=tuple(delegated_calls),
        typed_calls=tuple(typed_calls),
        instantiated_names=tuple(instantiated_names),
        clones_self=clones_self,
        cache_fields=tuple(sorted(cache_fields)),
        fan_out=tuple(fan_out),
        accept_delegate=accept_delegate,
        # function_id filled in by the caller once the entity id is known.
        discriminator_branches=tuple(_discriminator_branches(node, function_id="")),
    )


def _analyze_class(node: ast.ClassDef, file: str, module_qualifier: str) -> _ClassInfo:
    qualified_name = f"{module_qualifier}.{node.name}" if module_qualifier else node.name
    bases = tuple(name for base in node.bases if (name := _dotted_name(base)))
    fields: dict[str, _FieldInfo] = {}
    methods: dict[str, _MethodInfo] = {}
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods[item.name] = _analyze_method(item, fields, node.name)
    non_init_methods = [m for name, m in methods.items() if name != "__init__"]
    is_abstract = any(_simple_name_raw(b) in _ABSTRACT_SENTINELS for b in bases) or (
        bool(non_init_methods) and any(m.is_abstract_shaped for m in non_init_methods)
    )
    return _ClassInfo(
        name=node.name, qualified_name=qualified_name, file=file, line=node.lineno,
        bases=bases, is_abstract=is_abstract, methods=methods, fields=fields,
    )


def _simple_name_raw(dotted: str) -> str:
    return dotted.rsplit(".", 1)[-1]


def _discriminator_branches(node: ast.FunctionDef | ast.AsyncFunctionDef, function_id: str) -> list[DiscriminatorBranch]:
    """spec §13 anchor: a top-level `if/elif` chain comparing ONE parameter
    against literal constants. Feeds opportunities.py, not the pattern engine.
    """
    branches: list[DiscriminatorBranch] = []
    param_names = {a.arg for a in node.args.args if a.arg != "self"}
    for stmt in node.body:
        if not isinstance(stmt, ast.If):
            continue
        values: list[str] = []
        discriminator: str | None = None
        current: ast.If | None = stmt
        while current is not None:
            test = current.test
            if isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq):
                left, right = test.left, test.comparators[0]
                name, literal = None, None
                if isinstance(left, ast.Name) and isinstance(right, ast.Constant):
                    name, literal = left.id, right.value
                elif isinstance(right, ast.Name) and isinstance(left, ast.Constant):
                    name, literal = right.id, left.value
                if name in param_names and literal is not None:
                    discriminator = discriminator or name
                    if name == discriminator:
                        values.append(str(literal))
            nxt = current.orelse
            if len(nxt) == 1 and isinstance(nxt[0], ast.If):
                current = nxt[0]
            else:
                current = None
        if discriminator and len(values) >= 2:
            branches.append(DiscriminatorBranch(
                function_id=function_id, discriminator_param=discriminator,
                branch_values=tuple(values), line=stmt.lineno,
            ))
    return branches


class PythonFrontend:
    level = LEVEL

    def __init__(self) -> None:
        # Accumulates across every parse() call so build_relations() can link
        # references that cross files (spec §5.2/§17). One frontend instance
        # per analysis run — see analyze_design_patterns.py.
        self._classes: dict[str, _ClassInfo] = {}

    def supports(self, path: Path) -> bool:
        return path.suffix == ".py"

    def parse(self, source: str, path: Path) -> SourceUnit:
        file = path.as_posix()
        try:
            tree = ast.parse(source, filename=file)
        except SyntaxError:
            return SourceUnit(file=file, language="python")

        entities: list[Entity] = []
        discriminator_branches: list[DiscriminatorBranch] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                info = _analyze_class(node, file, module_qualifier="")
                self._classes[_entity_id(file, info.qualified_name)] = info

        for class_id, info in list(self._classes.items()):
            if info.file != file:
                continue
            kind = "interface" if info.is_abstract else "class"
            entities.append(Entity(
                id=class_id, language="python", kind=kind, name=info.name,
                qualified_name=info.qualified_name, file=info.file, line=info.line,
            ))
            for method_name, method in info.methods.items():
                method_qname = f"{info.qualified_name}.{method_name}"
                method_kind = "constructor" if method_name == "__init__" else "method"
                entities.append(Entity(
                    id=_entity_id(file, method_qname), language="python", kind=method_kind,
                    name=method_name, qualified_name=method_qname, file=file, line=method.line,
                    modifiers=method.decorator_names, parameters=method.params,
                    # Reuses return_type (rather than a new relation type) to
                    # carry the Builder anchor: "this method returns the
                    # builder's own type" (spec §11, chaining).
                    return_type=info.qualified_name if method.returns_self else None,
                ))
                function_id = _entity_id(file, method_qname)
                for branch in method.discriminator_branches:
                    discriminator_branches.append(dataclasses.replace(branch, function_id=function_id))
            for field_name, finfo in info.fields.items():
                field_qname = f"{info.qualified_name}.{field_name}"
                entities.append(Entity(
                    id=_entity_id(file, field_qname), language="python", kind="field",
                    name=field_name, qualified_name=field_qname, file=file, line=finfo.line,
                    return_type=finfo.type_name,
                ))

        return SourceUnit(file=file, language="python", entities=entities, discriminator_branches=discriminator_branches)

    def build_relations(self, units: list[SourceUnit]) -> tuple[list[Relation], list[str]]:
        """Cross-file linking pass (spec §5.2's example spans 3 files)."""
        limitations: list[str] = []
        by_simple: dict[str, list[str]] = {}  # class simple name -> [entity_id, ...]
        entity_by_id: dict[str, Entity] = {}
        for unit in units:
            for entity in unit.entities:
                entity_by_id[entity.id] = entity
                if entity.kind in {"class", "interface"}:
                    by_simple.setdefault(entity.name, []).append(entity.id)

        def resolve(name: str) -> str | None:
            candidates = by_simple.get(name, [])
            return candidates[0] if len(candidates) == 1 else None

        relations: list[Relation] = []
        unresolved_count = 0

        for class_id, info in self._classes.items():
            for base in info.bases:
                simple = _simple_name_raw(base)
                if simple in _ABSTRACT_SENTINELS:
                    continue
                target = resolve(simple)
                if target is None:
                    unresolved_count += 1
                    relations.append(Relation(type="INHERITS", source_id=class_id, target_unresolved=simple))
                    continue
                target_entity = entity_by_id[target]
                relation_type = "IMPLEMENTS" if target_entity.kind == "interface" else "INHERITS"
                relations.append(Relation(type=relation_type, source_id=class_id, target_id=target))

            for field_name, finfo in info.fields.items():
                field_id = _entity_id(info.file, f"{info.qualified_name}.{field_name}")
                if finfo.type_name:
                    target = resolve(finfo.type_name)
                    if target:
                        relations.append(Relation(type="CONTAINS", source_id=class_id, target_id=field_id, detail=field_name))
                        relations.append(Relation(type="REFERENCES", source_id=field_id, target_id=target))
                elif finfo.is_collection:
                    relations.append(Relation(type="CONTAINS", source_id=class_id, target_id=field_id, detail=field_name))
                if len(finfo.assigned_types) >= 2:
                    for assigned in sorted(finfo.assigned_types):
                        target = resolve(assigned)
                        if target:
                            relations.append(Relation(type="TRANSITIONS_TO", source_id=class_id, target_id=target, detail=field_name))

            for method_name, method in info.methods.items():
                method_id = _entity_id(info.file, f"{info.qualified_name}.{method_name}")
                relations.append(Relation(type="CONTAINS", source_id=class_id, target_id=method_id, detail=method_name))

                for name in method.instantiated_names:
                    target = resolve(name)
                    if target:
                        relations.append(Relation(type="INSTANTIATES", source_id=class_id, target_id=target, detail=method_name))
                    else:
                        unresolved_count += 1

                def call_into(type_name: str, called: str) -> None:
                    """CALLS hacia el método `called` de la clase `type_name` (si existe y se resuelve a una sola clase)."""
                    owner_id = resolve(type_name)
                    owner = self._classes.get(owner_id) if owner_id else None
                    if owner is None or called not in owner.methods or owner_id == class_id:
                        return
                    target_method = _entity_id(owner.file, f"{owner.qualified_name}.{called}")
                    if target_method in entity_by_id:
                        relations.append(Relation(type="CALLS", source_id=method_id, target_id=target_method))

                for type_name, called in method.typed_calls:
                    call_into(type_name, called)

                for attr, delegated_method in method.delegated_calls:
                    finfo = info.fields.get(attr)
                    if finfo and finfo.type_name:
                        call_into(finfo.type_name, delegated_method)
                        target = resolve(finfo.type_name)
                        if target:
                            relations.append(Relation(
                                type="DELEGATES_TO", source_id=method_id, target_id=target,
                                detail=delegated_method,
                            ))
                            continue
                    unresolved_count += 1

                for own_method in method.self_call_sequence:
                    target_id = _entity_id(info.file, f"{info.qualified_name}.{own_method}")
                    if target_id in entity_by_id:
                        relations.append(Relation(type="CALLS", source_id=method_id, target_id=target_id))

                if method.clones_self:
                    relations.append(Relation(type="CLONES", source_id=class_id, target_id=class_id))

                for cache_field in method.cache_fields:
                    relations.append(Relation(type="CACHES", source_id=class_id, target_id=class_id, detail=cache_field))

                for collection_field, called_method in method.fan_out:
                    finfo = info.fields.get(collection_field)
                    field_id = _entity_id(info.file, f"{info.qualified_name}.{collection_field}")
                    if field_id not in entity_by_id:
                        unresolved_count += 1
                        continue
                    relations.append(Relation(type="ITERATES", source_id=method_id, target_id=field_id, detail=called_method))
                    element_target = resolve(finfo.element_type) if finfo and finfo.element_type else None
                    if element_target:
                        relations.append(Relation(type="NOTIFIES", source_id=class_id, target_id=element_target, detail=called_method))

                if method.accept_delegate:
                    visitor_param, delegated_method = method.accept_delegate
                    param_type = method.param_types.get(visitor_param)
                    target = resolve(param_type) if param_type else None
                    if target:
                        # "visit:" marks this as the accept(visitor)-shaped
                        # delegation (single param, single-statement body
                        # calling back onto it) so detect_visitor doesn't
                        # match ordinary field-based delegation instead —
                        # detail stays free text, the closed relation-type
                        # vocabulary (ir.py) is unaffected.
                        relations.append(Relation(
                            type="DELEGATES_TO", source_id=method_id, target_id=target,
                            detail=f"visit:{delegated_method}",
                        ))
                    else:
                        unresolved_count += 1

        if unresolved_count:
            limitations.append(
                f"python frontend: {unresolved_count} reference(s) to a name that could not be resolved "
                "to exactly one class in scope (ambiguous or external) — excluded from HARD evidence."
            )
        return relations, limitations
