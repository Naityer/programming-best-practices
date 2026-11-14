# Informe de auditoría de `programming-best-practices`

Fecha: 2026-11-05 · Rama: `claude/aud-programming-best-practices-5a7e37` · Perfil: `standard`, alcance `repository`, solo checks sin efectos sobre el proyecto (sin `--allow-project-writes`, `--allow-network` ni `--allow-generated-code`).
Plan de referencia: [PLAN.md](PLAN.md). Resúmenes por proyecto (`verdict.json`, libro de decisiones, métricas) en la carpeta de notas compartida, subcarpeta `pbp/`; los informes completos (`report.json/md/sarif`, varios MB) quedaron en un directorio temporal fuera de los repos y no contienen secretos (Gitleaks se ejecuta con `--redact`).

## 1. Resumen

- La herramienta funciona de extremo a extremo, pero **las primeras pruebas reales descubrieron seis fallos que la dejaban inservible o poco fiable** (§4). Todos están corregidos con tests en esta rama.
- Cubre bien algoritmos (Python/JS/TS por reglas estructurales) y seguridad básica; **no cubría SRP, tamaño, complejidad ni errores tragados** (criterios C1, C5–C7 del plan). Se añadió `analyze_structure.py` para ello.
- Los patrones de diseño solo se analizan en Python: en finance-manager, atlas y atlas-dev (TypeScript) el frontend «no está operativo» (94, 446 y 439 ficheros sin analizar).
- La precisión real de los hallazgos de algoritmos es baja (6 de 8 revisados se descartaron). La revisión semántica es imprescindible.
- Hallazgo ajeno a la herramienta pero grave: **atlas versiona una clave privada** (§3.3).

## 2. Auditoría de la herramienta

**Tests:** `python -m unittest discover -s tests` → inicialmente 301 tests, **1 error** (`test_build_stats.test_matches_golden_outputs`: el fixture `tests/fixtures/stats-history/.quality-audit/` estaba excluido por `.gitignore`, así que en cualquier clon limpio el test fallaba). Tras corregirlo y añadir tests: **318 tests, todos en verde** (17 nuevos). Duración ≈ 80–165 s.

**Evals:**

| Eval | Resultado | Lectura |
|---|---|---|
| `evals/algorithms/cases.json` (`evaluate_algorithms.py`) | 8/8 verdaderos positivos, 0 FP, 0 FN; precisión y recall 1.0 | Corpus propio y pequeño; **no predice la precisión en código real** (§3) |
| `measure_algorithm_functionality.py --skip-tests` / `measure_design_pattern_functionality.py --skip-tests` | índice 4.0 / 10.0, `suite_passed: false` | Con `--skip-tests` el índice no es válido; no se interpreta. No ejecutado en modo completo |
| `evals/cases.json` (6 casos de comportamiento del agente) | **No ejecutado**: no hay runner; son prompts con expectativas en texto | Sin verificar |
| `verify_release.py` / `verify_design_patterns_release.py` | **No ejecutados**: exigen el repositorio hermano `audit_code`, que no existe en este equipo | Sin verificar |

**Cobertura de los criterios del plan:**

| Criterio | Antes | Ahora |
|---|---|---|
| C1 SRP | No | Parcial (señales de tamaño; la decisión es semántica) |
| C2 Algoritmos/complejidad | Sí (algoritmos); complejidad ciclomática no | Sí |
| C3 Patrones | Solo Python | Solo Python (sin cambio) |
| C4 Duplicación | No | No |
| C5 Acoplamiento | No | Parcial (fan-out de imports) |
| C6 Tamaño | No | Sí |
| C7 Errores | Solo reglas sueltas de Ruff/Semgrep | Sí (+ `catch` vacío en JS/TS) |
| C8 Tests | Planificado | Planificado, **no ejecutado en las pruebas reales** (requiere escribir en el proyecto) |
| C9 Seguridad | Sí (Gitleaks, Semgrep) | Sí; OSV omitido (necesita red) |

## 3. Pruebas reales

Resumen (`verdict.json`; las cifras incluyen las métricas estructurales y la revisión semántica):

| Proyecto | outcome | blocker | high | medium | low | Herramientas con resultado | No ejecutadas (motivo) |
|---|---|---|---|---|---|---|---|
| karajan | incomplete | 0 | 7 | 116 | 1192 | ruff, algoritmos, patrones, gitleaks, semgrep | build/tests/compile (efectos), lint/typecheck JS (sin script), OSV (red) |
| finance-manager | incomplete | 0 | 0 | 0 | 54 | algoritmos, patrones, gitleaks, semgrep | build/tests/typecheck (efectos), cpp.* (sin CMake), OSV |
| atlas | **fail** | **1** | 0 | 16 | 214 | algoritmos, patrones (parcial), gitleaks, semgrep | build/lint/typecheck/tests (efectos), OSV |
| atlas-dev | incomplete | 0 | 0 | 2 | 174 | algoritmos, patrones (parcial), gitleaks, semgrep | build/typecheck/tests (efectos), cpp.*, OSV |

`incomplete` es el resultado honesto: ninguna prueba ni build corrió. Ningún proyecto «pasa».

**No modificación de los proyectos.** Comprobado con `find -newermt` y `git status` en los cuatro: ningún fichero nuevo, salvo una excepción — la **primera ejecución sobre karajan escribió ficheros en su `.ruff_cache/`** (ignorado por git, regenerable) porque el plan lanzaba `ruff` con caché activada y clasificado como «sin efectos». Corregido (`--no-cache`); lo escrito sigue ahí y puede borrarse. Lo que muestra `git status` en esos repos (`data/` sin versionar en atlas-dev, `*.backup-shm/-wal` en atlas, `data/modo.json` en karajan) no se atribuye a esta auditoría: karajan ya lo tenía al empezar; los ficheros `-shm/-wal` son de SQLite en uso por esos proyectos (no verificado su origen exacto).

### 3.1 karajan (Python + dashboard JS)

Se cumple (con lo que midió la herramienta): sin secretos detectados y un único patrón de diseño sugerido con evidencia (Template Method en `app/database.py:968`); el detector es conservador, así que no equivale a «el diseño es bueno».
Mejorable (confirmado tras leer el código):

- **SRP — `TaskStore`** (`app/database.py:62`, 43 métodos, 1468 líneas): migraciones de esquema, runs, artefactos, outbox, métricas, FTS, revisiones y decisiones en una clase. `ResourceStore` (`app/resources/resource_library.py:52`, 46 métodos) igual.
- **Complejidad — `run_subtask`** (`app/execution/delegation.py:294`): complejidad ciclomática 62, 268 líneas. También `compute_observability` (`app/execution/monitoring.py:80`, 45).
- **Tamaño del dashboard**: `dashboard/static/src/modules/monitor.js` (3093 líneas, ≥6 sub-vistas), `inspiration.js` (2489), `decision.js` (2119).
- **Errores**: `app/handoff/store.py:101` descarta una excepción sin registrarla; `app/database.py:1355` hace `except Exception: continue` y una fila corrupta desaparece sin aviso. (48 casos candidatos en total; muchos son de mejor esfuerzo — revisar uno a uno.)
- **Aridad**: `record_run` con 14 parámetros en `app/database.py:687` y duplicado en `app/platform/persistence/postgres/tasks.py:229`.
- Descartados: `curated_resources.py:6` (287 líneas, es un literal de datos), `production_setup.py:30` y `github_resources.py:214` (algoritmos sobre listas de <20 elementos), `handoff/store.py:50` (descarte documentado y justificado).

### 3.2 finance-manager (React/TypeScript + servidor Node)

Se cumple: algoritmos sin hallazgos de impacto, sin secretos, 0 hallazgos graves.
Mejorable:

- `src/pages/Personal.tsx` (1755 líneas) agrupa **cinco páginas** exportadas (`MovimientosPage` :73, `PresupuestosPage` :692, `SuscripcionesPage` :856, `DeudasPage` :1130, `ObjetivosPage` :1554): una página por fichero. También `src/pages/Banking.tsx` (911) y `Plan.tsx` (641).
- Los 51 hallazgos de algoritmos restantes son de baja confianza: `src/atlas/capital.tsx:142` es una **suma numérica clasificada como concatenación** (falso positivo); `src/domain/csv.ts:98` y `src/domain/debt.ts:147` operan sobre decenas de elementos (impacto nulo).
- `server/banking.mjs:14` (`catch{}` tras `chmodSync`) es descarte intencionado de mejor esfuerzo → descartado.
- Patrones de diseño: **no analizados** (TypeScript sin frontend).

### 3.3 atlas (monorrepo NestJS/React)

Se cumple: 0 hallazgos de Semgrep.
Mejorable:

- **Seguridad (ajeno a buenas prácticas, a escalar):** `instances/dev/.atlas/addon-token/rsa.private.pem` está **versionado** (commit `119d9da`) y sin `.gitignore`. Blocker confirmado. Recomendación: sacarlo de git, rotar la clave y generarla al arrancar la instancia.
- **SRP/tamaño**: `apps/server/src/core/document-change/document-change.service.ts` (1559 líneas), `apps/web/src/features/databases/components/thread-view.tsx` (1474), `modules/notion/src/server/lib/notion-mirror.ts` (1471).
- **Algoritmos**: `modules/knowledge-graph/src/server/knowledge-graph.service.ts:318` — `mappings.find` dentro de filas×campos×opciones al construir el grafo (crece multiplicativamente); indexar en un `Map`.
- **Errores**: 16 `catch` vacíos candidatos (p. ej. `apps/server/src/core/addons/subscriptions-store.ts:37`), sin revisar uno a uno.
- Patrones: no analizados (446 ficheros TypeScript sin frontend).

### 3.4 atlas-dev

Se cumple: el fan-out de `server/src/server.ts` (78 imports, 39 rutas) es el de una raíz de composición; sin hallazgos graves ni secretos reales.
Mejorable:

- Partir el registro de rutas de `server/src/server.ts` (704 líneas) por dominio; `server/src/flujos/registro.ts` (964) en un módulo por flujo; `web/src/features/agentes/compositor.tsx` (734).
- `server/src/espacios/mapa-proyectos.ts:163`: filtrado de `nodos` dentro del bucle de repos, O(R×N) (impacto bajo hoy).
- Falsos positivos descartados: 25 «generic-api-key» de Gitleaks en `data/.vite-preview-…/uso-tokens.json` (caché de uso de tokens: sus claves son rutas/UUID de sesión). Pero `data/` **no está en `.gitignore`** y contiene bundles generados: conviene ignorarlo.
- Patrones: no analizados (439 ficheros TypeScript).

## 4. Qué funcionó y qué no

Funcionó: el plan es determinista y legible; las barreras de permisos hacen que `run_audit` omita y declare lo que escribiría; el informe distingue `skipped/unavailable/timed_out` de «pasa»; la exclusión de dependencias/generados evitó miles de falsos hallazgos; Gitleaks con `--redact` no filtra secretos al informe; la revisión semántica con libro de decisiones deja trazabilidad.

Fallos encontrados en las pruebas reales y **corregidos** (con tests en `tests/test_audit_regressions.py`):

1. **El plan apuntaba a reglas de Semgrep inexistentes** (`pipeline/rules/semgrep.yml` en vez de `scripts/rules/semgrep.yml`): Semgrep fallaba (exit 7) en todos los proyectos y las reglas propias no se aplicaban nunca.
2. **`build_report` abortaba con `duplicate id`** al coincidir dos diagnósticos de Ruff en la misma línea (la huella ignoraba la columna): el informe de karajan no se generaba. Ahora Ruff usa la columna y `build_report` numera las colisiones restantes.
3. **Ruff escribía su caché en el proyecto auditado** pese a estar planificado como «sin efectos». Ahora `--no-cache`.
4. **Los analizadores recorrían `node_modules`, `.venv` y los worktrees de agentes antes de filtrar** (`Path.rglob("*")`): `design-patterns` agotó los 300 s en karajan, y el informe luego descartaba como «generado» lo que había leído. Nuevo `analysis_core/files.py` (poda al bajar + respeta `.gitignore`): karajan pasó de timeout (8 min en total) a ≈ 8 s en patrones.
5. **Ruff `SIM*`/`SLF*` se clasificaban como seguridad/alta** (`startswith("S")`): inflaba los «graves» de vigilante. Ahora solo `S<n>` (bandit).
6. **`dist-atlas/`, `.vite-*` no se consideraban generados** al normalizar; un bundle de 4000 líneas dominaba los hallazgos de atlas-dev.
7. **El fixture del test de estadísticas estaba ignorado por git** (error del propio `unittest`).

Limitaciones que **siguen**:

- Frontend de patrones inoperativo en TypeScript/JavaScript; sin duplicación (C4); sin ciclos de dependencias.
- Sin `--allow-project-writes` no hay tests, cobertura ni build: auditar C8 exige copia desechable o autorización explícita.
- Con repo sucio el alcance por defecto es `changed-files` y los analizadores se limitan a esos ficheros (en karajan, dos JSON de datos): hay que pasar `--scope repository`.
- Un check por fichero cambiado para Gitleaks (`universal.gitleaks.0001…0038`) genera planes de cientos de líneas.
- Algoritmos: precisión baja en código real. De 8 hallazgos de algoritmos revisados, 6 se descartaron (n diminuto, suma numérica clasificada como concatenación) y 2 se confirmaron con impacto bajo-medio. La regla `repeated-concatenation` no distingue tipos.
- `B008` (llamada en valor por defecto) marca el idioma `Depends()` de FastAPI: 33 «medium» en karajan sin revisar.
- La heurística de «salida generada» de `analyze_structure` puede omitir código denso escrito a mano (se afinó, pero sigue siendo heurística).

## 5. Mejoras realizadas (todas con tests)

| Commit | Mejora |
|---|---|
| fixture stats-history | Versiona el fixture ignorado; `test_matches_golden_outputs` vuelve a pasar en un clon limpio |
| semgrep/ruff/ids | Corrige ruta de reglas, `--no-cache`, ids únicos |
| analysis_core/files.py | Enumeración con poda y `.gitignore` |
| analyze_structure.py | Nuevo analizador de solo lectura (SRP/tamaño/complejidad/errores) + check `universal.structure` + parser; omite salida generada |
| export_verdict.py | `verdict.json`: contrato compacto y sin ambigüedad para vigilante (cuenta `blocker` como grave, declara herramientas requeridas incompletas y si hubo revisión semántica) |
| normalize | `dist-*`/`.vite*` generados; `SIM*`/`SLF*` ya no son seguridad |

### Mejoras priorizadas pendientes

1. **P1** Frontend de patrones para TypeScript/JavaScript (o declarar claramente en el informe que no se analizó: ya sale como limitación, pero no en `verdict.json`).
2. **P1** Tipos en `repeated-concatenation` / `repeated-linear-membership`: exigir evidencia de colección grande o tipo `string/array` para bajar los falsos positivos.
3. **P2** Check de duplicación (PMD CPD/jscpd) en el plan, y ciclos de dependencias.
4. **P2** Un solo check de Gitleaks con lista de rutas en vez de uno por fichero cambiado; `--scope repository` por defecto en perfil `standard`.
5. **P2** Modo «copia desechable»: ejecutar tests y cobertura en un clon temporal para auditar C8 sin tocar el proyecto.
6. **P3** Silenciar `B008` si el proyecto usa FastAPI; agrupar `swallowed-exception` por fichero.

## 6. Lo no verificado

- Tests, build, cobertura y mutación de los cuatro proyectos (no se autorizaron escrituras).
- OSV (dependencias vulnerables, requiere red).
- Que los ~170 candidatos estructurales de karajan y los centenares de hallazgos de baja prioridad sean reales: solo se revisó una muestra (22 decisiones en total; los libros están en `pbp/*/review-ledger.json`).
- `evals/cases.json` (comportamiento del agente), `verify_release.py` (necesita `audit_code`) y la instalación de la skill (`tools/install_skill.py`, solo en seco).
- Que vigilante detecte los informes: no se ejecutó; la lectura del contrato se hizo sobre su código fuente.

## 7. Peticiones a otras herramientas

- **vigilante** (`src/comprobaciones/auditoria.mjs`):
  - Pasa `--profile quick` al planificador; los perfiles válidos son `fast|standard|deep`, así que el modo `planificar` **siempre fallaría** (no ejecutado; deducido del código y de `plan_audit.py --help`).
  - Solo cuenta `critical|high`: un hallazgo `blocker` (el nivel más grave del informe) no se contaría. Mejor leer `verdict.json` (`graves`, `incomplete_required`, `semantic_review.done`).
  - Solo busca `.quality-audit/` **dentro** del repo, y la skill pide escribir fuera (el plan debe ir fuera): acordar una ruta de informes configurable.
  - Si `semantic_review.done` es falso, tratar los recuentos como provisionales.
- **atlas** (propietario del repo): sacar `instances/dev/.atlas/addon-token/rsa.private.pem` de git y rotar la clave; revisar los 16 `catch` vacíos candidatos.
- **atlas-dev**: añadir `data/` a `.gitignore`; si Atlas dev abre incidencias desde estos hallazgos, usar el id estable `PBP-…` y agrupar por fichero/causa (una incidencia, una tarea en borrador).
- **karajan**: enlazar los hallazgos `pbp.pattern.*` con su biblioteca de patrones (`refactoring-guru` curada en `app/curated_resources.py`) y valorar `programming-best-practices` como modificador de observación en el laboratorio; el corpus `evals/algorithms` sirve de banco de pruebas. Revisar `TaskStore`/`run_subtask` como candidatos de refactor.
- **aegis-secops**: ¿asume la validación de los blockers de Gitleaks (clave privada en atlas) y la política de `data/` sin ignorar?
- **ruff (karajan)**: borrar `.ruff_cache/` si se desea volver al estado previo a la auditoría (contiene ficheros escritos por la primera ejecución).

## 8. Ampliación: huecos cubiertos y pruebas en entorno controlado

**Entorno controlado.** Nuevo `scripts/run_in_copy.py`: copia los ficheros que git ve (+ `node_modules`/`.venv` con `--copy-deps`) a un directorio temporal fuera del proyecto, le crea su propio git y ejecuta plan → build/tests/typecheck/herramientas → informe → `verdict.json` allí. El original solo se lee (test: la lista de ficheros del original no cambia). Límites: no aísla recursos externos al repo (puertos, bases de datos fuera de la carpeta); los monorrepos pnpm con enlaces simbólicos no se copian bien; y copia lo que git ve, de modo que en atlas (carpetas `uploads/`, `backups/` sin ignorar) la copia pesó **52 GB** — conviene un límite de tamaño o una lista de exclusión (pendiente).

| Proyecto (copia) | Build | Typecheck | Tests | Otros |
|---|---|---|---|---|
| finance-manager | pasa | pasa | **pasan** | OSV (con red): **8 avisos** en dependencias de desarrollo (2 altos: vite GHSA-587h-7wmj-h5pm, source-map-js GHSA-68fv-2mgg-jv7q); Gitleaks limpio |
| karajan | pasa (JS) | no hay script | JS pasa; Python **557 ok / 2 fallan / 3 omitidos** (12 min) | `compile` pasa. Fallos: `tests/ui/test_dashboard_smoke.py::test_every_view_mounts_without_console_errors` (timeout de Playwright al hacer clic: real o de entorno, sin determinar) y `tests/agent_tools/test_agent_tools_workspace.py::test_self_workspace_protects_the_harness_from_the_agent` (necesita `data/active_config.json`, fichero local no versionado: **artefacto de la copia**) |
| atlas-dev | pasa | pasa | **545 ok / 7 fallan / 4 omitidos** en 5 ficheros (`src/flujos/flujos.test.ts` 2, `rutas.test.ts` 1, `versiones.test.ts` 3, `tareas.test.ts` 1) | estos tests ejercitan flujos git; la primera copia no tenía `.git`. Ahora la copia lleva su propio git, **pero esta ejecución es anterior a ese cambio** y no se repitió: no se sabe cuántos fallos son del entorno |
| atlas | **falla** (turbo/`@atlas/kernel`: `Cannot find module 'node:path'`, falta `@types/node`) | falla (mismo motivo) | falla en 5 s | Lint con hallazgos; Semgrep y patrones sin novedades. **Inconclusivo**: el monorrepo pnpm no se reproduce en la copia (los enlaces de `node_modules` no sobreviven al copiado), así que los fallos son del entorno, no del proyecto |

**Huecos del apartado «sin cubrir o sin verificar», uno a uno**

| Hueco | Estado |
|---|---|
| Tests/build/cobertura | **Cubierto en 3 de 4 proyectos** (arriba). Cobertura (`coverage.py`) sigue `unavailable` en karajan (no instalado); mutación no ejecutada (perfil `deep`) |
| OSV (red) | **Cubierto** en finance-manager (8 avisos); no en los demás |
| Duplicación (C4) | **Cubierto**: `analyze_structure` detecta bloques idénticos (exacto, no semántico) |
| Ciclos de dependencias (C5) | **Cubierto**: ciclos de imports internos (Python y rutas relativas JS/TS) |
| Frontend de patrones TS/JS | **No cubierto**: requiere `tree-sitter-language-pack` (dependencia que no se instaló). Ahora queda declarado en `verdict.json` (`coverage_gaps`, `tools_not_run`) para que ningún consumidor lo lea como «bien» |
| Tests rojos sin rastro | **Cubierto**: un check de tests que falla genera `pbp.tests.failing` (severidad alta); antes no producía ningún hallazgo |
| Precisión de algoritmos | **Mejorada**: sumas numéricas ya no se tratan como concatenación (`+= 1`, y confianza baja si no hay evidencia de secuencia). No se midió de nuevo sobre los cuatro proyectos |
| `B008` de FastAPI | **Cubierto**: `Depends/Query/Body…` baja a `low` |
| Monorrepo sin `package.json` raíz | **Cubierto**: se audita el subpaquete con más scripts (atlas-dev auditaba `desktop`, que no tiene ninguno) |
| `evals/cases.json` | **Parcial**: sin runner; nuevo test que comprueba que cada expectativa está documentada en la skill. No mide el comportamiento del agente |
| `tools/install_skill.py` | **Verificado en seco** (vista previa sin cambios); no se aplicó |
| vigilante consume el informe | **Verificado**: `vigilante check` lee un `report.json` (59 hallazgos, 0 graves) y confirma el fallo del modo `planificar` (`invalid choice: 'quick'`) |
| `verify_release.py` | **No verificable**: necesita el repositorio `audit_code`, que no existe en este equipo |
| Gitleaks un check por fichero | **No cubierto** (cambiaría la semántica del alcance); queda como mejora |
| Revisión semántica ampliada | **No cubierto**: la muestra sigue siendo de 22 decisiones |

**Cola de borradores de Atlas dev.** Todo lo que depende de otro repositorio se dejó como tarea en **borrador** (nada ejecutado) vía `POST /tareas` de Atlas dev (14 tareas: atlas 3, atlas-dev 2, vigilante 3 —bajo la app `skills-package`—, karajan 4, finance-manager 2). No se usó `POST /vigilante/hallazgos` porque cierra solas las incidencias abiertas del mismo repo cuyas claves no aparezcan (había abiertas, p. ej. `atlas:secretos`). Limitación: la API de tareas solo acepta 500 caracteres de `resumen`; el detalle completo (evidencia, arreglo, criterios) está en `pbp/borradores/*.md` de la carpeta de notas y cada borrador lo enlaza.

Nuevo recuento de tests: **328 en verde** (27 nuevos respecto a los 301 iniciales).
