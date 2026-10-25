# orchestrate-dealer — notas del proyecto

Las lee la skill `orchestrate-dealer` antes de repartir. Salen de `opt-tokens` (2026-10-25, `INS-43`): de 25,7M de
entrada de la tarea, 17,2M fueron de subagentes, con 52k de arranque cada uno.

## Arreglos de la revisión de un trozo

- Los hallazgos de la revisión de un trozo vuelven **al subagente que lo implementó**, con `SendMessage` a su id,
  no a uno nuevo: ya tiene el código en contexto y no paga el arranque ni vuelve a descubrir lo que hizo. Las cuatro
  rondas de arreglos de `INS-43`, cada una con un subagente nuevo, costaron ~1,5M cada una.
- Uno nuevo solo si el implementador acabó por un tope (de llamadas o de uso) o si su contexto pasa de ~150k.
- El diff del arreglo pasa la revisión corta igual que el trozo (el implementador puede defender su diseño: esa
  revisión es el contrapeso).

## Encargo del revisor

- Lleva el **rango del diff** (`git diff <a> <b>`), los archivos del contrato que mirar (el documento de `docs/`,
  los llamadores) y qué buscar sobre todo, y pide **unas 12 llamadas como mucho**, leyendo por tramos (`grep -n` y
  `sed -n`), nunca archivos de más de ~300 líneas enteros. Los revisores de `INS-43` hicieron 17-21 llamadas a
  ~95k; el de los arreglos de la fase 1, con ese encargo, 7.
- La revisión completa de la rama (fase 1 de `AGENTS.md`) no se acota: es el contrapeso de las cortas.

## Arreglos de un patrón

- Al encargo de un arreglo se añade: «Si el fallo es de un patrón (una forma de escribir que falla en más sitios),
  busca con `grep` sus otras apariciones y arréglalas, o lístalas en MISSING». En `INS-43` el arreglo del `!` de
  `nuevo` en Ajustes dejó el de `actual`, dos líneas más arriba, y otros tres en Descarga, Perfil y Listo (retro de
  `INS-43`).
