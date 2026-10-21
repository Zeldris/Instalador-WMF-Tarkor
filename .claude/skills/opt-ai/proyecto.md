# `opt-ai` en Tarkor

Lo propio de este proyecto para la skill. En otro proyecto, este archivo se reescribe.

## Tareas y modelos

Fuente de verdad: `backend/src/config/env.ts` (variables `OLLAMA_MODEL_*`, `OLLAMA_KEEP_ALIVE`); léela en cada
pasada, aquí no se copian los nombres de modelo. Tareas (`app.task`, las que emite el código): `narrar` (narrador), `narrar_respaldo` (3.er intento del
combate, modelo del Cronista), `clasificar`, `sugerir` (modelo propio), `dialogo_npc`, `combate`, `modo_dinamico`,
`resumen`, `prompts_imagen`, `embedding` y `rag` (recuperación). `calentar` es el calentamiento al arrancar el
servidor: no es juego y `medir.py` lo excluye (`--con-calentar` lo muestra). Motor: Ollama (columna de `motores.md`).

## Registro y perfiles

- Se activa con `IA_REGISTRO=<archivo.jsonl>`; sin la variable no se escribe nada. Una tanda, un archivo (el
  anterior se guarda para `--anterior`).
- `IA_PERFIL`: `deck` (**mínimo del juego, siempre se mide**), `cpu` (PC sin GPU), `gpu8`, `gpu12`. Sin variable,
  `desconocido` (y `medir.py` avisa).
- Formato: `docs/ia/opt-ai-registro.md`.

## Benchmark y RAG

- Benchmark de turno (antes/después de cada propuesta): `bash tools/qa/bench-ia.sh <etiqueta> --anterior <etiqueta>`
  (`QA-173`): restaura el escenario `ia-gorhorn-dia42`, reindexa, juega 8 turnos de `npm run benchmark-turno` con
  `IA_PERFIL=deck`, muestrea RAM y `ollama ps` y pasa `medir.py`. En segundo plano (~10 min).
- Reindexar el lore: `npm run reindex-lore`. Recuperación: `backend/src/services/retrieval.ts`.
- Evaluación del RAG: `npm run rag-eval` sobre el juego fijo `backend/ia/rag-casos.jsonl` (recall@k y MRR; el
  caso rojo del paso 2 sale de aquí).

## Dónde están las incoherencias

`docs/registros/pruebas-*-hallazgos.md` (hoy `pruebas-0.3-hallazgos.md` y los de las rondas siguientes): las P de IA
son las que inventan, contradicen el lore o se equivocan de nombre. Cada una pasa a caso de `rag-casos.jsonl`
con `origen` = su P.

## Tiempos aceptables

Se fijan con la primera medición en la Deck. Hasta entonces, el paso 4 no marca ninguna tarea como «demasiado
lenta» por su cuenta: informa de las cifras y propone el umbral a la usuaria.

## Lo que ya hay (no proponerlo otra vez)

Se apunta aquí cada herramienta o ajuste aprobado.

- **Prefijo fijo primero** en los prompts del narrador: lo que no cambia va delante y Ollama reaprovecha unos 2.600
  tokens de caché por turno.
- **`arrancar-juego.sh` con `IA_PERFIL`** (`QA-141`): `IA_REGISTRO` absoluto, GPU en `deck` y `rag-eval` antes de jugar.
- Registro por turno (`QA-162`): `app.turno`, `app.intento`, rechazos de guard (`app.evento: rechazo`) y `num_ctx`
  efectivo de `/api/ps`; `medir.py` saca la tabla TURNOS.
- `keep_alive` 1h en `resumen` y en el calentamiento (`QA-161`); captura remota apagada en las tandas (`QA-160`).
