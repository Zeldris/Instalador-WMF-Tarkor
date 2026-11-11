# gw-orchestrate-dealer — notas del proyecto

Las lee la skill `gw-orchestrate-dealer` antes de repartir. Salen de `gw-opt-tokens` (2026-10-25, `INS-43`): de 25,7M de
entrada de la tarea, 17,2M fueron de subagentes, con 52k de arranque cada uno.

## Arreglos de la revisión de un trozo

- Los hallazgos de la revisión de un trozo vuelven **al subagente que lo implementó**, con `SendMessage` a su id,
  no a uno nuevo: ya tiene el código en contexto y no paga el arranque ni vuelve a descubrir lo que hizo. Las cuatro
  rondas de arreglos de `INS-43`, cada una con un subagente nuevo, costaron ~1,5M cada una.
- Uno nuevo solo si el implementador acabó por un tope (de llamadas o de uso) o si su contexto pasa de ~150k.
- El diff del arreglo pasa la revisión corta igual que el trozo (el implementador puede defender su diseño: esa
  revisión es el contrapeso).

## Arreglos de la revisión de la rama (fase 1)

- Con más de tres arreglos, van **todos al mismo subagente** (`sonnet`), también los de un solo archivo cuyo sitio
  dio el revisor: la excepción de la skill («un arreglo de un archivo lo hace la sesión principal») vale con tres
  o menos. El encargo apunta al archivo de hallazgos; la sesión principal lee su diff y pasa la revisión corta.
  En `INS-44`/`INS-45`, cinco arreglos hechos en la sesión principal costaron ~3-4M (opt-tokens del 2026-11-11).

## Encargo del revisor

- Lleva el **rango del diff** (`git diff <a> <b>`), los archivos del contrato que mirar (el documento de `docs/`,
  los llamadores) y qué buscar sobre todo, y pide **unas 12 llamadas como mucho**, leyendo por tramos (`grep -n` y
  `sed -n`), nunca archivos de más de ~300 líneas enteros. Los revisores de `INS-43` hicieron 17-21 llamadas a
  ~95k; el de los arreglos de la fase 1, con ese encargo, 7.
- La revisión completa de la rama (fase 1 de `AGENTS.md`) no se acota: es el contrapeso de las cortas.

## Encargo del implementador

Retro de `INS-42` (los subagentes, el 71 % de la entrada, de 52k al arrancar a ~100k de media):

- **El check, en una llamada:** `python3 .claude/gw/scripts/ci-local.py`, que corre los jobs de Ubuntu del CI y solo imprime
  lo que falla. No listar las órdenes una a una. Tras un fallo, se repite solo esa orden. Los E2E, aparte.
- **Compilar antes del E2E** (opt-tokens de `INS-15`): antes de lanzar un E2E, `cd app && cargo clippy --workspace
  --all-targets -q -- -D warnings`; el E2E, solo con eso en verde. En `INS-15` el E2E (compila la app entera) se
  repitió dos veces por un choque de nombres (E0618) y un comando sin registrar en `invoke_handler`.
- **Los tramos que tocar:** la sesión principal da en el encargo los `grep -n` de las funciones del trozo; el
  subagente lee por tramos (`sed -n`) y busca el nombre con `grep -n` antes de editar, para ver sus llamadores.
- **El trozo que cierra una tarea** pide también su línea en «Hecho» de la bitácora: sin ella el pre-push rechaza
  la subida (trozo C de `INS-42`; `R4` de la retro de `INS-43`, propuesto al flujo).

## Arreglos de un patrón

- Al encargo de un arreglo se añade: «Si el fallo es de un patrón (una forma de escribir que falla en más sitios),
  busca con `grep` sus otras apariciones y arréglalas, o lístalas en MISSING». En `INS-43` el arreglo del `!` de
  `nuevo` en Ajustes dejó el de `actual`, dos líneas más arriba, y otros tres en Descarga, Perfil y Listo (retro de
  `INS-43`).
