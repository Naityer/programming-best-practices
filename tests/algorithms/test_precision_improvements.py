"""Mejoras de precisión de los detectores de eficiencia de Python, sacadas de los falsos positivos y los huecos que midió el banco de pruebas."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skill" / "programming-best-practices" / "scripts"
PACKAGE = SCRIPTS / "algorithms"
SPEC = importlib.util.spec_from_file_location("pbp_algorithm_precision", PACKAGE / "__init__.py", submodule_search_locations=[str(PACKAGE)])
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

MEMBERSHIP = "pbp.algorithm.search.repeated-linear-membership"
FIBONACCI = "pbp.algorithm.dp.overlapping-recursion"
POP_ZERO = "pbp.algorithm.graph.bfs-list-pop-zero"
INDEX_LOOP = "pbp.algorithm.search.repeated-linear-index"
LIST_REBUILD = "pbp.algorithm.sequence.repeated-list-rebuild"


class PrecisionTests(unittest.TestCase):
    def rules(self, source: str) -> dict[str, list[int]]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "case.py").write_text(textwrap.dedent(source), encoding="utf-8")
            found: dict[str, list[int]] = {}
            for item in MODULE.analyze_repository(root)["algorithms"]:
                found.setdefault(item["rule_id"], []).append(item["primary_location"]["line"])
            return found


class MembershipTests(PrecisionTests):
    def test_membership_in_a_name_already_built_as_a_hash_container_is_not_reported(self) -> None:
        for build in ("set(b)", "frozenset(b)", "{x for x in b}", "{x: 1 for x in b}", "dict.fromkeys(b)", "{1, 2, 3}"):
            with self.subTest(build=build):
                found = self.rules(f"""
                    def f(a, b):
                        indice = {build}
                        return [c for c in a if c in indice]
                """)
                self.assertNotIn(MEMBERSHIP, found)

    def test_membership_in_a_list_is_still_reported(self) -> None:
        for build in ("list(b)", "[x for x in b]", "sorted(b)"):
            with self.subTest(build=build):
                found = self.rules(f"""
                    def f(a, b):
                        indice = {build}
                        return [c for c in a if c in indice]
                """)
                self.assertIn(MEMBERSHIP, found)

    def test_a_parameter_with_unknown_type_is_still_reported(self) -> None:
        self.assertIn(MEMBERSHIP, self.rules("""
            def f(a, b):
                return [c for c in a if c in b]
        """))

    def test_a_parameter_annotated_as_a_set_is_not_reported(self) -> None:
        for annotation in ("set[str]", "frozenset[str]", "dict[str, int]", "Set[str]", "AbstractSet[str]", "Mapping[str, int]"):
            with self.subTest(annotation=annotation):
                self.assertNotIn(MEMBERSHIP, self.rules(f"""
                    def f(a, b: {annotation}):
                        return [c for c in a if c in b]
                """))

    def test_the_set_must_be_the_one_in_scope(self) -> None:
        # `indice` es un conjunto en una función y una lista en otra: no se mezclan.
        found = self.rules("""
            def uno(a, b):
                indice = set(b)
                return [c for c in a if c in indice]

            def dos(a, b):
                indice = list(b)
                return [c for c in a if c in indice]
        """)
        self.assertEqual(len(found.get(MEMBERSHIP, [])), 1)


class MemoizationTests(PrecisionTests):
    PLAIN = """
        def fib(n):
            if n < 2:
                return n
            return fib(n - 1) + fib(n - 2)
    """

    def test_a_plain_recursion_is_reported(self) -> None:
        self.assertIn(FIBONACCI, self.rules(self.PLAIN))

    def test_a_cached_recursion_is_not_reported(self) -> None:
        for decorator in ("@lru_cache", "@lru_cache(maxsize=None)", "@functools.lru_cache(maxsize=128)", "@functools.cache", "@cache", "@memoize", "@functools.cached_property"):
            with self.subTest(decorator=decorator):
                found = self.rules(f"""
                    import functools
                    from functools import cache, lru_cache

                    {decorator}
                    def fib(n):
                        if n < 2:
                            return n
                        return fib(n - 1) + fib(n - 2)
                """)
                self.assertNotIn(FIBONACCI, found)

    def test_an_unrelated_decorator_does_not_hide_it(self) -> None:
        self.assertIn(FIBONACCI, self.rules("""
            import functools

            @functools.wraps(print)
            def fib(n):
                if n < 2:
                    return n
                return fib(n - 1) + fib(n - 2)
        """))


class PopZeroTests(PrecisionTests):
    def test_a_parameter_annotated_as_a_list_is_reported(self) -> None:
        for annotation in ("list[str]", "list", "List[int]", "typing.List[int]", "list[str] | None"):
            with self.subTest(annotation=annotation):
                self.assertIn(POP_ZERO, self.rules(f"""
                    def drain(cola: {annotation}):
                        hechas = []
                        while cola:
                            hechas.append(cola.pop(0))
                        return hechas
                """))

    def test_a_parameter_without_annotation_is_not_assumed_to_be_a_list(self) -> None:
        # `pop(0)` en una deque no existe, pero en otros tipos sí: sin evidencia de que sea una lista, se calla.
        self.assertNotIn(POP_ZERO, self.rules("""
            def drain(cola):
                while cola:
                    cola.pop(0)
        """))

    def test_a_deque_parameter_is_not_reported(self) -> None:
        self.assertNotIn(POP_ZERO, self.rules("""
            from collections import deque

            def drain(cola: deque):
                while cola:
                    cola.popleft()
        """))

    def test_pop_zero_outside_a_loop_is_not_reported(self) -> None:
        self.assertNotIn(POP_ZERO, self.rules("""
            def primero(cola: list[int]):
                return cola.pop(0)
        """))


class IndexInLoopTests(PrecisionTests):
    def test_list_index_inside_a_loop_over_a_list_is_reported(self) -> None:
        self.assertIn(INDEX_LOOP, self.rules("""
            def posiciones(valores: list[str], buscados: list[str]):
                resultado = []
                for buscado in buscados:
                    resultado.append(valores.index(buscado))
                return resultado
        """))

    def test_index_on_a_list_built_in_the_function_is_reported(self) -> None:
        self.assertIn(INDEX_LOOP, self.rules("""
            def posiciones(buscados):
                valores = ["a", "b", "c"] * 100
                return [valores.index(b) for b in buscados]
        """))

    def test_str_index_and_unknown_receivers_are_not_reported(self) -> None:
        self.assertNotIn(INDEX_LOOP, self.rules("""
            def f(texto: str, otros):
                return [texto.index(c) for c in "abc"] + [otros.index(c) for c in "abc"]
        """))

    def test_index_outside_a_loop_is_not_reported(self) -> None:
        self.assertNotIn(INDEX_LOOP, self.rules("""
            def una_vez(valores: list[str], x):
                return valores.index(x)
        """))

    def test_a_tiny_literal_list_is_not_reported(self) -> None:
        self.assertNotIn(INDEX_LOOP, self.rules("""
            def f(xs):
                return [["a", "b", "c"].index(x) for x in xs]
        """))


class ListRebuildTests(PrecisionTests):
    def test_rebuilding_a_list_with_plus_inside_a_loop_is_reported(self) -> None:
        self.assertIn(LIST_REBUILD, self.rules("""
            def acumular(valores):
                resultado = []
                for valor in valores:
                    resultado = resultado + [valor * 2]
                return resultado
        """))

    def test_the_other_side_is_reported_too(self) -> None:
        self.assertIn(LIST_REBUILD, self.rules("""
            def acumular(valores):
                resultado = []
                for valor in valores:
                    resultado = [valor] + resultado
                return resultado
        """))

    def test_append_extend_and_numeric_sums_are_not_reported(self) -> None:
        found = self.rules("""
            def a(valores):
                resultado = []
                for valor in valores:
                    resultado.append(valor)
                    resultado.extend([valor])
                return resultado

            def b(valores):
                total = 0
                for valor in valores:
                    total = total + valor
                return total

            def c(a, b):
                x = []
                x = x + [1]
                return x
        """)
        self.assertNotIn(LIST_REBUILD, found)

    def test_plus_between_two_different_names_is_not_a_rebuild(self) -> None:
        self.assertNotIn(LIST_REBUILD, self.rules("""
            def f(valores, otros):
                resultado = []
                for valor in valores:
                    resultado = otros + [valor]
                return resultado
        """))


if __name__ == "__main__":
    unittest.main()
