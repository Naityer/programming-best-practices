# Plan de auditoría de `programming-best-practices`

Qué debe comprobar la skill en un proyecto, cómo se mide cada criterio, qué parte cubre hoy la herramienta y cómo se integra con vigilante, Karajan y Atlas dev. Las decisiones de arquitectura de los demás se respetan: aquí solo se *consumen* sus contratos, no se modifican.

## 1. Principios (heredados de la skill y del ecosistema)

- **Solo lectura por defecto.** El plan se escribe fuera del repo auditado; `run_audit.py` no ejecuta nada que escriba en el proyecto sin `--allow-project-writes` (caché, build, tests), ni usa red sin `--allow-network`.
- **Evidencia antes que opinión.** Herramienta > especificación > LLM. Una herramienta que no corrió (`skipped`, `unavailable`, `timed_out`) es evidencia incompleta, nunca un «pasa».
- **Sin puntuación universal ni umbrales inventados.** Los umbrales de tamaño/complejidad son *disparadores de revisión* configurables, de severidad baja/media; no son un veredicto.
- **Revisión semántica obligatoria** antes de actuar: cada hallazgo muestreado se *confirma* o *descarta* con motivo (`--semantic-review`). El libro de decisiones (`review-ledger.json`) alimenta las estadísticas de falsos positivos.
- **Ninguna acción de arreglo sin aprobación**: la auditoría informa; arreglar es otra tarea (borrador en Atlas dev, aprobada por una persona).

## 2. Criterios

| # | Criterio | Qué se busca | Cómo se mide | Cobertura hoy |
|---|---|---|---|---|
| C1 | Responsabilidad única (SRP) | Clases/módulos con varias razones de cambio | `analyze_structure`: `many-methods`, `file-size`, `function-length`; contraste semántico (¿mezcla persistencia, red y presentación?) | **Parcial** (señal por tamaño; la decisión es semántica) |
| C2 | Algoritmos y complejidad | Búsquedas lineales repetidas, ordenar para tomar el extremo, concatenación en bucle, joins anidados | `analyze_algorithms` (catálogo + reglas `pbp.algorithm.*`); complejidad ciclomática (`analyze_structure`) | **Sí** en Python/JS/TS por reglas estructurales; precisión real baja (ver INFORME) |
| C3 | Patrones de diseño | Oportunidades (Strategy, Template Method…) y patrones mal implementados | `analyze_design_patterns` | **Solo Python**; el frontend TypeScript/JavaScript «no está operativo» |
| C4 | Duplicación | Código copiado entre módulos | — (`tooling-matrix.md` cita PMD CPD «o equivalente configurado», pero `plan_audit` no planifica ningún check de duplicación) | **No** |
| C5 | Acoplamiento | Fan-out de imports, dependencias circulares | `fan-out` (imports distintos) | **Parcial** (sin ciclos ni fan-in) |
| C6 | Tamaño de módulos | Ficheros/funciones/parámetros/anidamiento excesivos | `analyze_structure` (`file-size`, `function-length`, `parameters`, `nesting`) | **Sí** (Python completo; JS/TS solo a nivel de fichero) |
| C7 | Manejo de errores | Excepciones tragadas, `catch` vacío, captura demasiado amplia | `analyze_structure` (`swallowed-exception`) + Semgrep (`pbp.python.generic-exception-swallowed`) + Ruff (`BLE001`, `S110`, `S112`) | **Sí** (heurístico; exige leer el motivo) |
| C8 | Tests | Existencia, ejecución, cobertura, mutación | `python.tests`, `js.test`, `*.coverage`, `*.mutation` (requieren `--allow-project-writes`) | **Planificado, no ejecutado en las pruebas reales** (ver INFORME) |
| C9 | Seguridad básica | Secretos, dependencias vulnerables | Gitleaks, Semgrep, OSV (red) | **Sí**, pero profundiza `aegis-secops`; aquí solo se registra |

Los criterios C4 y la parte de ciclos de C5 son huecos conocidos (véase «Mejoras» en el INFORME).

## 3. Flujo operativo

```
plan_audit.py --scope repository  ──►  plan.json   (fuera del repo)
run_audit.py plan.json --execute  ──►  execution/  (solo checks sin efectos)
build_report.py execution.json --fragment … --semantic-review …  ──►  report.{json,md,sarif} [+ review-ledger.json]
export_verdict.py <dir del informe> ──►  verdict.json   (contrato para vigilante)
build_stats.py                    ──►  tendencias entre auditorías
```

Notas de uso aprendidas en las pruebas reales:

1. Con el repo sucio, el alcance por defecto es `changed-files` y los analizadores se centran en esos ficheros (a veces solo JSON). Para una auditoría de buenas prácticas, usar **`--scope repository`**.
2. Sin `--allow-project-writes` se omiten build/tests/compilación: es lo que garantiza «no modifica el proyecto». Auditar tests y cobertura exige una copia o una autorización explícita.
3. Las métricas estructurales se integran como check `universal.structure`; también se pueden pasar como fragmento (`normalize_tool_output.py --tool structure`).

## 4. Integración

### 4.1 vigilante (check `auditoria`)

- Contrato actual de vigilante (`vigilante/src/comprobaciones/auditoria.mjs`): busca `.quality-audit/**/report.json` **dentro del repo** (profundidad ≤ 3), cuenta `findings` críticos/altos/medios y la antigüedad del fichero.
- Contrato nuevo y no ambiguo: `verdict.json` (`export_verdict.py`) con `outcome`, `counts{blocker,high,medium,low}`, `graves` (= blocker + high), estado de herramientas, herramientas requeridas incompletas y si hubo revisión semántica. Vigilante debería leer `verdict.json` en lugar de recontar `report.json` (megabytes) y tratar `incomplete_required` y `semantic_review.done=false` como «sin datos», nunca como «bien».
- Peticiones a vigilante (no se tocan aquí): contar `blocker` como grave; usar `--profile standard` (el modo `planificar` pasa `--profile quick`, que el planificador rechaza); aceptar una ruta de informes fuera del repo.

### 4.2 Karajan

- Biblioteca de patrones: Karajan cura `refactoring-guru` (`app/curated_resources.py`) como referencia de patrones de diseño. Propuesta (no implementada): enlazar cada hallazgo `pbp.pattern.<patrón>.opportunity` a la ficha de ese patrón en la biblioteca de Karajan por nombre de patrón, sin copiar contenido. `references/design-patterns/refactoring-map.json` relaciona *olores → patrones candidatos*, no contiene URLs.
- Laboratorio por componente (`docs/laboratorio/`): `programming-best-practices` encaja como *modificador de observación*; su corpus etiquetado (`evals/algorithms`) y sus métricas de precisión sirven de banco de pruebas. Esta auditoría no modifica el laboratorio; solo propone consumirlo.

### 4.3 Atlas dev: hallazgo → incidencia → tarea en borrador

1. Un hallazgo `confirm` (revisado) con severidad ≥ media se agrupa por fichero/causa.
2. Se abre **una incidencia** por agrupación (no una por línea) con el identificador estable del hallazgo (`PBP-…`, estable entre ejecuciones).
3. Se deja **una tarea en borrador** (nunca ejecutada) con: ficheros, criterio incumplido, evidencia, y la comprobación de aceptación (tests de la zona verdes antes y después).
4. La persona aprueba o descarta; si descarta, la decisión se registra como `dismiss` con motivo para que no reaparezca.

Esto reutiliza el circuito existente de Atlas dev («incidencia + tarea de arreglo en borrador»); no se añade ninguna API.

## 5. Criterios de aceptación de esta auditoría

- Tests de la skill en verde y evals ejecutados (INFORME §2).
- Pipeline completo sobre karajan, finance-manager, atlas y atlas-dev con salida fuera de los proyectos.
- Muestra de hallazgos revisada semánticamente (confirmar/descartar con motivo).
- Mejoras con tests y commits atómicos en la rama de trabajo; nada fusionado en `main`.
