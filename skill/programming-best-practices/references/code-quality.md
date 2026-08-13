# Code quality, smells, and refactoring

## Contents

1. Diagnosis
2. Universal smells
3. Object-oriented smells
4. Refactoring map
5. Pattern selection
6. Validation

## Diagnosis

Inspect behavior and change history before naming a smell. Ask whether a unit has a coherent responsibility, whether dependencies expose unnecessary details, whether one change fans out across unrelated modules, and whether infrastructure is mixed with domain policy.

Use metrics such as cognitive complexity, cycles, duplication, fan-in/fan-out, and churn as evidence that guides inspection. Do not convert metric thresholds directly into design conclusions.

## Universal smells

Look for long or mixed-purpose functions, large modules, excessive parameters, duplicate or dead code, magic values, primitive obsession, data clumps, deep nesting, complex conditionals, shotgun surgery, divergent change, feature envy, message chains, speculative generality, excessive indirection, hidden side effects, global mutable state, temporal coupling, and behavior-selecting booleans.

Confirm the impact. Similar-looking code may represent separate domain rules; a long function may still express one readable algorithm; a switch may be clearer than a hierarchy.

## Object-oriented smells

Consider refused inheritance, fragile base classes, parallel inheritance hierarchies, temporary fields, large inheritance trees, alternative classes with incompatible interfaces, and type codes that repeatedly reproduce the same branching. Do not impose object orientation on functional, data-oriented, or idiomatic Go/Rust designs.

## Refactoring map

| Observable problem | Candidate change | Guardrail |
| --- | --- | --- |
| Mixed-purpose function | Extract Function | Extract a nameable concept, not arbitrary lines |
| Unrelated class responsibilities | Extract Class/Module | Keep cohesive state and invariants together |
| Repeated behavior | Consolidate or extract | Confirm semantics and change cadence match |
| Excessive parameters/data clump | Parameter Object or API redesign | Avoid a bag-of-fields object |
| Deep nesting | Guard Clauses | Preserve cleanup and transactional behavior |
| Complex conditional | Decompose Conditional | Prefer explicit domain predicates |
| Feature envy | Move behavior | Move toward the data owner without creating cycles |
| Primitive obsession | Value Object/domain type | Use only when invariants or behavior justify it |
| Repeated type branching | State/Strategy/polymorphism | Keep a simple switch when variants are small and stable |
| Message chain | Facade/Hide Delegate | Do not conceal useful domain traversal |
| Incorrect inheritance | Composition/delegation | Preserve substitutability and lifecycle |
| Magic value | Named constant/enum/type | Avoid naming incidental one-off values |
| Dead code | Delete | Confirm reflection, configuration, and external consumers |
| Shotgun surgery | Move responsibility | Minimize public contract churn |

## Pattern selection

Use Strategy, Factory Method, Adapter, Facade, Decorator, State, Observer, Command, or Builder only when each removes an observed recurring problem. Use Abstract Factory, Chain of Responsibility, Composite, Proxy, Bridge, Template Method, or Iterator when architecture and variation demand them. Require especially strong justification for Visitor, Memento, Flyweight, Prototype, and Mediator.

Before recommending Singleton, check whether the composition root or dependency-injection container can own and inject the instance. Global access and hidden state reduce testability.

## Validation

Refactor incrementally. Run characterization or specification tests before and after each meaningful step. Review public behavior, concurrency, persistence, resource cleanup, error mapping, and performance-sensitive paths. Inspect the final diff for accidental rewrites and unrelated formatting.

