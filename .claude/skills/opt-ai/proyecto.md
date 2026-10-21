# `opt-ai` en el instalador

Lo propio de este proyecto para la skill. En otro proyecto, este archivo se reescribe. El juego tiene el suyo
(registro JSONL, RAG, benchmark de turno); aquí lo que se mide es el **motor y los perfiles que instala el
asistente**.

## Perfiles y modelos

Fuente de verdad: `app/catalogo/catalogo.json` (perfiles `minimo`, `ligero`, `equilibrado`, `maximo` y `ultra`, sus
modelos de narrador, cronista, sugerencias y embeddings, `memoriaGb`, `maxModelosCargados` y `keepAlive`) y la
versión del motor (`motor.version`, hoy Ollama 0.34.3). Léelo en cada pasada; aquí no se copian los nombres de
modelo. Diseño: [`docs/12-catalogo-y-rendimiento.md`](../../../docs/12-catalogo-y-rendimiento.md) y
[`docs/09-deteccion-de-equipo-y-perfiles.md`](../../../docs/09-deteccion-de-equipo-y-perfiles.md).

## Ajustes que ya se calculan

`app/nucleo/src/rendimiento.rs` (`rendimiento::calcular`) da por perfil y equipo las variables del motor
(`OLLAMA_FLASH_ATTENTION`, `OLLAMA_KV_CACHE_TYPE` en `q8_0`, o `q4_0` si el margen de memoria es justo,
`OLLAMA_NUM_PARALLEL` a 1, `OLLAMA_MAX_LOADED_MODELS`, `OLLAMA_KEEP_ALIVE`, `OLLAMA_CONTEXT_LENGTH`, Vulkan) y las
del backend (modelos del perfil, `TARKOR_NUM_THREAD` según el uso de CPU que elige la usuaria, `TARKOR_NUM_BATCH`,
`TARKOR_NUM_CTX_NARRADOR`). Una propuesta del paso 3 cambia esta función o el catálogo, con su test (equipo de 8 GB sin
gráfica dedicada y la Steam Deck, `REVIEW.md`).

## Cómo se mide

- **Sin registro JSONL**: el paso 0 usa la salida de `cargo run -p tarkor-nucleo --example motor [perfil]` (en
  `app/`), que instala el motor en la carpeta de datos (o en `TARKOR_DATOS`), lo arranca con los ajustes del perfil
  para ese equipo, descarga sus modelos y hace la narración de prueba con sus tiempos. Una pasada por perfil y
  equipo; se guarda la salida para comparar antes y después.
- **Dónde**: la Steam Deck (siempre, es el mínimo), un Windows limpio y el equipo de la usuaria (`INS-8`). En el
  contenedor de la nube no hay GPU ni memoria para medir nada útil.
- **El paso 2 (RAG) no aplica**: la recuperación vive en el backend del juego y se mide con su `opt-ai`.

## Tiempos aceptables

Se fijan con la primera medición en la Deck (`INS-8`). Hasta entonces, el paso 4 no marca ningún perfil como
«demasiado lento» por su cuenta: informa de las cifras y propone el umbral a la usuaria.

## Lo que ya hay (no proponerlo otra vez)

Se apunta aquí cada ajuste aprobado.

- Flash attention, caché KV cuantizada según el margen, un solo turno a la vez, modelos cargados según el perfil
  y Vulkan para gráficas sin CUDA (`rendimiento::calcular`, `INS-3b`).
- Hilos de la IA según el uso de CPU elegido (`rendimiento::hilos_para_ia`).
