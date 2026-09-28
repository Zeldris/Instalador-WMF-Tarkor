# Catálogo de modelos y rendimiento

**Estado: implementado en `app/nucleo` (2026-09-28); cifras a validar en la fase 0.8.** Petición
de Álvaro: sacar el máximo partido de Ollama en cada equipo, ofrecer modelos más pequeños para
que **cualquiera pueda probar el juego** aunque no llegue a los requisitos actuales (avisando de que
el resultado depende del modelo elegido), y que todo sea fácil de configurar y de ir ampliando.

## 1. Catálogo en un fichero, no en el código

Modelos, perfiles y reglas del cálculo viven en
[`app/catalogo/catalogo.json`](../app/catalogo/catalogo.json). Añadir un perfil, cambiar el
narrador de uno, o ajustar una cifra tras medirla es **editar ese JSON**. La app no tiene ningún
perfil escrito en código.

| Qué | Dónde en el JSON |
|---|---|
| Un modelo nuevo | `modelos`: tamaño de descarga, licencia y si "piensa" (Qwen 3.x) |
| Un perfil nuevo o cambiado | `perfiles`, en orden de menos a más memoria |
| Texto de "qué resultado esperar" | `perfiles[].resultado` (se muestra en la tarjeta) |
| Perfil de prueba que no se recomienda | `perfiles[].experimental: true` |
| Reserva para el sistema, márgenes, contexto del narrador | `reglas` |

**Tres niveles, de más fijo a más flexible:**

1. **Incrustado:** el `catalogo.json` del repo se mete en el binario al compilar. Es el que usa
   todo el mundo por defecto.
2. **Externo:** si existe `catalogo.json` en la carpeta de datos del jugador, lo sustituye sin
   recompilar. Sirve para probar cambios en un equipo concreto (p. ej. la Steam Deck) y es la base
   para, en una versión futura, recibir catálogos nuevos sin publicar otra versión de la app.
3. **Validación:** un catálogo externo roto (JSON mal formado, un perfil que usa un modelo que no
   está en la lista, versión desconocida, sin ningún perfil no experimental...) se ignora y se usa
   el incrustado. Nunca deja el juego sin arrancar. La app informa del motivo (`origen_catalogo`).

Los tests del núcleo comprueban el catálogo incrustado en cada build: que esté ordenado, que todos
los perfiles incluyan el modelo de embeddings, y que **todos los modelos tengan licencia Apache
2.0** (un modelo con otra licencia no entra sin revisarlo antes, ver `08`).

## 2. Perfiles: que cualquiera pueda jugar

| Perfil | Narrador | Sugerir | Memoria IA | Descarga | Qué esperar |
|---|---|---|---|---|---|
| **Mínimo** | `qwen2.5:1.5b-instruct` (el mismo que el cronista) | el mismo | ~2 GB | 1,3 GB | Para probar en casi cualquier equipo. Narraciones cortas, simples, a veces equivocadas con el mundo |
| **Ligero** | `qwen3.5:2b` | cronista | ~3,8 GB | 4 GB | Juego completo con narraciones más breves y menos matices |
| **Equilibrado** | `qwen2.5:7b` | cronista | ~7 GB | 6 GB | La experiencia de diseño: el narrador de desarrollo |
| **Máximo** | `qwen2.5:7b` | `qwen3.5:4b` | ~11 GB | 9,4 GB | Sugerencias más ricas y sin esperas entre modelos |
| **Ultra** *(experimental)* | `qwen3.5:9b` | `qwen3.5:4b` | ~14 GB | 11,3 GB | Narrador más grande para gráficas potentes; sin afinar para Tarkor |

Todos incluyen el cronista (`qwen2.5:1.5b-instruct`) y `nomic-embed-text`.

- **Mínimo** reutiliza un único modelo de lenguaje para todo: una sola descarga pequeña y un solo
  modelo en memoria.
- **Ligero** cambia `qwen2.5:3b` (licencia Qwen Research, restrictiva) por `qwen3.5:2b` (Apache
  2.0).
- **Si ningún perfil cabe**, no se bloquea: se recomienda Mínimo, las tarjetas se habilitan y se
  explica que puede ir lento o cerrarse. El objetivo es que todo el mundo pueda probarlo.
- La pantalla de perfil explica que **cada perfil usa modelos de distinto tamaño: cuanto más
  grande, mejor narra**, y cada tarjeta lleva su texto de "qué esperar".
- **Experimental** nunca se recomienda ni cuenta como "máximo seguro", aunque quepa.

**A validar en la fase 0.8:** que los modelos pequeños respetan el JSON estructurado que exige el
narrador (Ollama lo fuerza con gramática, así que la forma debería salir bien; el contenido es lo
que hay que juzgar) y que la narración en castellano es aceptable en Mínimo y Ligero.

## 3. Ajustes de rendimiento automáticos

`app/nucleo/src/rendimiento.rs` calcula, en cada arranque, las variables para Ollama y el backend
según el equipo y el perfil. Variables comprobadas contra `envconfig/config.go` de Ollama
(septiembre 2026).

### Para Ollama

| Variable | Valor | Por qué |
|---|---|---|
| `OLLAMA_FLASH_ATTENTION` | `1` | Reduce la memoria del contexto; necesaria para cuantizar la caché |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0`, o `q4_0` si el margen de memoria es justo (< 1 GB) | `q8_0` ocupa la mitad que `f16` casi sin pérdida; `q4_0`, un cuarto con algo de pérdida |
| `OLLAMA_NUM_PARALLEL` | `1` | Un solo jugador; cada petición en paralelo multiplica la memoria del contexto |
| `OLLAMA_MAX_QUEUE` | `16` | No hace falta una cola de 512 peticiones |
| `OLLAMA_MAX_LOADED_MODELS` | del perfil (1, 2 o 4) | Memoria pico frente a esperas al cambiar de modelo |
| `OLLAMA_KEEP_ALIVE` | del perfil (2 min a 15 min) | Memoria en reposo frente a rapidez del siguiente turno |
| `OLLAMA_CONTEXT_LENGTH` | `8192` | Lo que necesita el narrador (con 4096 se desestabilizó) |
| `OLLAMA_VULKAN` | `1` | Aceleración en gráficas AMD e Intel sin CUDA ni ROCm, incluida la Steam Deck |
| `OLLAMA_IGPU_ENABLE` | `1` | Usa gráficas integradas |
| `OLLAMA_GPU_OVERHEAD` | 512 MB, solo con gráfica dedicada | Deja VRAM libre para que el escritorio no se entrecorte |
| `OLLAMA_NO_CLOUD` | `1` | Privacidad (`08`): sin funciones en la nube |
| `OLLAMA_NOPRUNE` | `1` | Conserva descargas a medias para poder reanudarlas |

`OLLAMA_HOST` (puerto libre) y `OLLAMA_MODELS` (carpeta propia) los pone el gestor de sidecars
(fase 0.4-0.5).

### Para el backend del juego

Además de `OLLAMA_MODEL_*` y `OLLAMA_KEEP_ALIVE`, variables nuevas que el backend empaquetado
tiene que leer y pasar en cada petición a Ollama (fase 3.5 del plan):

| Variable | Opción de Ollama | Valor |
|---|---|---|
| `TARKOR_NUM_THREAD` | `num_thread` | Mitad de los hilos (Moderado) o todos menos uno (Alto) |
| `TARKOR_NUM_BATCH` | `num_batch` | 512, o 256 con margen justo |
| `TARKOR_NUM_CTX_NARRADOR` | `num_ctx` | 8192 |
| `TARKOR_MODELOS_SIN_PENSAR` | `think: false` | Modelos Qwen 3.x del perfil: pensar antes de narrar multiplica el tiempo de cada turno |

### Otras mejoras de rendimiento previstas

- **Calentar el narrador:** al terminar de arrancar, una petición vacía carga el narrador en
  memoria mientras el jugador está en el menú, para que el primer turno no tarde de más (fase 4.2).
- **Ver dónde corre la IA:** `GET /api/ps` de Ollama dice qué parte de cada modelo está en la
  gráfica. Se muestra en Ajustes ("La IA usa la gráfica al 100 %") y sirve para diagnosticar
  (fase 4.3).
- **Velocidad real:** la prueba rápida de `09` usa `eval_count / eval_duration` de la respuesta de
  Ollama (tokens por segundo exactos), no un cronómetro.
- **Steam Deck:** probar en la fase 0.8 Vulkan (por defecto) frente a ROCm con
  `HSA_OVERRIDE_GFX_VERSION=10.3.0` y quedarse con el más rápido. Si ROCm gana, la regla se añade
  al cálculo para APUs AMD.
- **Cuantización del modelo:** los tamaños del catálogo corresponden a la cuantización por defecto
  de Ollama (Q4_K_M). Si en la fase 0.8 una variante `q8_0` del narrador narra claramente mejor en
  equipos con gráfica grande, entra como un perfil más del catálogo, sin cambiar código.

## 4. Ampliarlo en el futuro

- **Nuevo perfil o nuevo modelo:** editar `catalogo.json` y pasar `cargo test -p tarkor-nucleo`.
- **Nueva regla de rendimiento:** una función en `rendimiento.rs` con su test.
- **Catálogo remoto (futuro):** descargar un `catalogo.json` firmado desde las releases de este
  repositorio a la carpeta de datos del jugador. La validación y el respaldo al incrustado ya
  existen; faltaría la descarga y la firma.
