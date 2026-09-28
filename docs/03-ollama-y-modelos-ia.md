# Ollama y los modelos de IA

**Estado: propuesta elegida (2026-09-28), a validar en la prueba de concepto.** Camino elegido:
**Ollama gestionado por la propia app como un segundo sidecar** (opción D). Las alternativas
descartadas se dejan abajo para no volver a discutirlas.

## El problema

Hoy, en desarrollo, Ollama es un requisito previo que el desarrollador instala y gestiona a mano
(`iniciar-tarkor.sh` lo lanza con `OLLAMA_IGPU_ENABLE=1 OLLAMA_FLASH_ATTENTION=1
OLLAMA_KV_CACHE_TYPE=q8_0 ollama serve`):

| Uso | Modelo | Cómo se obtiene hoy | Tamaño aprox. |
|---|---|---|---|
| Narrador | `tarkor-narrador` (`FROM qwen2.5:7b`) | `ollama pull qwen2.5:7b` + `ollama create tarkor-narrador -f Modelfile` | 4,7 GB |
| Cronista (clasificación de acciones) | `qwen2.5:1.5b-instruct` | `ollama pull` | 1 GB |
| Sugerencias ("Sugerir") | `qwen3.5:4b` | `ollama pull` | 3,4 GB |
| Embeddings (RAG de lore y hechos de partida) | `nomic-embed-text` | `ollama pull` | 0,3 GB |

Unos 9 GB de descarga en total y un paso de construcción propio para el narrador. Un jugador final
no puede hacer esto a mano.

## Por qué no es opcional

El narrador es el corazón del juego: sin modelo no hay ni una narración. Y `nomic-embed-text`
también hace falta **durante la partida**, no solo para indexar el lore: `worldFacts.ts` genera
embeddings de los hechos de la partida (`SessionFact`) y cada búsqueda de lore convierte la
consulta en embedding. Tiene que estar siempre presente, y en la misma versión con la que se
indexó el lore empaquetado.

## Decisión: Ollama como sidecar gestionado por la app (D)

La app de Tauri arranca y para su **propia instancia de Ollama**, igual que hace con el backend:

- **Binario:** se usa la release oficial de Ollama (licencia MIT, se puede redistribuir). Versión
  **fijada en el catálogo** (hoy la 0.34.3) con la suma SHA256 de cada paquete copiada de su
  `sha256sum.txt`. Actualizar Ollama es cambiar versión, URL y sumas en `catalogo.json`.
- **Se descarga en el primer arranque, no va dentro del instalador.** El paquete oficial pesa
  ~1,4 GB tanto en Windows (`ollama-windows-amd64.zip`) como en Linux
  (`ollama-linux-amd64.tar.zst`) e incluye ya soporte NVIDIA y Vulkan (Vulkan cubre también AMD e
  Intel). El paquete extra de ROCm para AMD (0,25-1 GB) no se descarga por defecto; si en la fase
  0.8 rinde claramente mejor que Vulkan en alguna gráfica, se añadiría solo para ella. Así el
  instalador se queda en unos cientos de MB.
- **Implementado y probado (2026-09-28):** `app/nucleo/src/motor.rs` descarga (reanudable),
  verifica la suma, extrae y arranca el motor. Probado aquí con el paquete real de Linux: 1.361 MB
  en 58 s, arranque en 0,3 s, todos los ajustes de `12` aplicados según el registro de Ollama.
- **Aislado de cualquier otro Ollama:** puerto libre elegido al arrancar (no el 11434 por defecto)
  y carpeta de modelos propia dentro de los datos de la app (`OLLAMA_MODELS`). Si el jugador ya
  tiene Ollama para otras cosas, no se tocan ni se mezclan.
- **Sin root ni instalación en el sistema:** imprescindible en la Steam Deck (sistema de solo
  lectura) y coherente con instalar sin permisos de administrador en Windows.
- **Ajustes de rendimiento calculados para cada equipo y perfil** (caché de contexto cuantizada,
  Vulkan, una sola petición a la vez, reserva de VRAM...): ver
  [`12-catalogo-y-rendimiento.md`](12-catalogo-y-rendimiento.md).
- **Descarga de modelos** con la API de Ollama (`POST /api/pull`, que da progreso), mostrando una
  barra por modelo en el asistente. Se puede pausar y reanudar.

### Sin `ollama create`: el narrador es el modelo base + prompt por petición

Hoy `tarkor-narrador` es `qwen2.5:7b` + un bloque `SYSTEM` + `temperature 0.7` + `num_ctx 8192`.
La API de Ollama acepta `system` y `options` en cada petición, así que:

- Se descarga solo `qwen2.5:7b` (o el narrador del perfil).
- El backend manda el texto del `SYSTEM` y los parámetros en cada petición del narrador.
- El texto del `SYSTEM` se incrusta en el backend en tiempo de build (hoy
  `modelfileSystemPrompt.ts` ya lo extrae del `Modelfile`, pero leyendo el fichero en tiempo de
  ejecución — ver [`10-proteccion-del-codigo-y-build.md`](10-proteccion-del-codigo-y-build.md)).

Ventajas: desaparece el paso de construcción, cambiar el prompt en una actualización es solo
cambiar el backend, y el prompt no queda en un `Modelfile` legible en disco.

Cambio necesario en el juego: que el narrador acepte un modo "modelo base + system por petición"
controlado por variable de entorno, sin romper el modo actual con `tarkor-narrador` en desarrollo.

## Alternativas descartadas

- **A. Instalar el Ollama oficial en el sistema del jugador.** Pide permisos de administrador, deja
  un servicio que arranca con el sistema (contrario a `08`) y choca con instalaciones previas.
- **B. Ollama como requisito manual.** Contradice el objetivo de "abrir y jugar".
- **E. Sin Ollama, cargando modelos GGUF directamente desde el backend (`node-llama-cpp`).** Menos
  piezas, pero obliga a reescribir `lib/ollama.ts`, `ollamaQueue.ts` y el formato JSON forzado que
  hoy da Ollama, y a empaquetar binarios nativos de llama.cpp por plataforma dentro del backend. Se
  guarda como plan de reserva si Ollama da problemas serios en la prueba de concepto.
- **C. Modelos más pequeños** ya no es una alternativa aparte: quedan integrados como perfiles
  **Mínimo** y **Ligero** del catálogo (ver [`12`](12-catalogo-y-rendimiento.md)).

## Qué falta validar (fase 0)

- Arrancar el Ollama portable como sidecar en Windows y en la Steam Deck, sin instalar nada.
- Medir la velocidad real de `qwen2.5:7b` en la Deck (probablemente en CPU: el soporte de Ollama
  para la gráfica de la Deck es limitado).
- Comprobar que el narrador con `system` + `options` por petición da el mismo resultado que
  `tarkor-narrador`.
- Tamaños reales de cada variante de descarga de Ollama y de cada modelo.
