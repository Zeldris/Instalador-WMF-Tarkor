<!-- galivelop-workflow v0.2.0 -->
# opt-ai — notas del proyecto

Las lee primero la skill `opt-ai`; aquí vive todo lo propio de los modelos de IA local de este proyecto. El flujo
las crea una vez; desde entonces son del proyecto. Vienen de `.claude/skills/opt-ai/proyecto.md` (`FLU-1`, del repo
del juego), pasadas aquí con el piloto de Galivelop-workflow (`FLU-2`).

**En el instalador** no hay registro JSONL ni RAG: lo que se mide es el **motor y los perfiles que instala el
asistente**. Las medidas salen del ejemplo `motor` del núcleo y de la prueba en equipos reales (`INS-8`). La skill
**solo propone** (usuaria, 2026-10-20): no cambia configuración, catálogo ni modelos; lo aprobado entra como tarea
del [plan](../../docs/05-plan-de-trabajo.md) con su `INS-n` o `FLU-n`. Sin web ni motores remotos; la búsqueda de
novedades es de `scout-updates`. Todo en español.

## Motores y modelos

Fuente de verdad: `app/catalogo/catalogo.json` (perfiles `minimo`, `ligero`, `equilibrado`, `maximo` y `ultra`, sus
modelos de narrador, cronista, sugerencias y embeddings, `memoriaGb`, `maxModelosCargados` y `keepAlive`) y la
versión del motor (`motor.version`, Ollama). Léelo en cada pasada; aquí no se copian los nombres de modelo. Diseño:
[`docs/12-catalogo-y-rendimiento.md`](../../docs/12-catalogo-y-rendimiento.md) y
[`docs/09-deteccion-de-equipo-y-perfiles.md`](../../docs/09-deteccion-de-equipo-y-perfiles.md).

`app/nucleo/src/rendimiento.rs` (`rendimiento::calcular`) da por perfil y equipo las variables del motor
(`OLLAMA_FLASH_ATTENTION`, `OLLAMA_KV_CACHE_TYPE` en `q8_0`, o `q4_0` si el margen de memoria es justo,
`OLLAMA_NUM_PARALLEL` a 1, `OLLAMA_MAX_LOADED_MODELS`, `OLLAMA_KEEP_ALIVE`, `OLLAMA_CONTEXT_LENGTH`, Vulkan) y las
del backend (modelos del perfil, `TARKOR_NUM_THREAD` según el uso de CPU que elige la usuaria, `TARKOR_NUM_BATCH`,
`TARKOR_NUM_CTX_NARRADOR`). Una propuesta cambia esta función o el catálogo, con su test (equipo de 8 GB sin
gráfica dedicada y la Steam Deck, `REVIEW.md`).

## Tareas

Las del juego (narrador, cronista, sugerencias, embeddings); el instalador solo hace la narración de prueba del
ejemplo `motor`. El RAG no aplica aquí: vive en el backend del juego y se mide con su `opt-ai`.

## Perfiles de máquina

Los cinco del catálogo. El mínimo es la **Steam Deck** y se mide siempre. Dónde: la Deck, un Windows limpio y el
equipo de la usuaria (`INS-8`); en el contenedor de la nube no hay GPU ni memoria para medir nada útil.

## Ajustes

Sin registro JSONL todavía: el bloque queda sin `log` y `medir.py` no aplica hasta que el instalador escriba uno.

```opt-ai
exclude_tasks: warmup
cold_ms: 100
```

## Banco de pruebas

`cargo run -p tarkor-nucleo --example motor [perfil]` (en `app/`): instala el motor en la carpeta de datos (o en
`TARKOR_DATOS`), lo arranca con los ajustes del perfil para ese equipo, descarga sus modelos y hace la narración de
prueba con sus tiempos. Una pasada por perfil y equipo; se guarda la salida para comparar antes y después. Descarga
varios GB: nunca en la sesión principal ni sin necesidad.

## Casos de calidad

No aplica en el instalador (sin RAG).

## Tiempos aceptables

Se fijan con la primera medición en la Deck (`INS-8`). Hasta entonces, ningún perfil se marca como «demasiado
lento» por su cuenta: se informa de las cifras y se propone el umbral a la usuaria.

## Ya en marcha

- Flash attention, caché KV cuantizada según el margen, un solo turno a la vez, modelos cargados según el perfil
  y Vulkan para gráficas sin CUDA (`rendimiento::calcular`, `INS-3b`).
- Hilos de la IA según el uso de CPU elegido (`rendimiento::hilos_para_ia`).
