# Detección de equipo y perfiles de IA

**Estado: decidido el enfoque (2026-09-28); tres detalles abiertos al final.** Petición explícita
de Álvaro: pedir permiso al jugador para revisar su equipo, mostrarle el máximo **seguro** según
su hardware y dejarle elegir cuánta RAM/esfuerzo quiere dedicar al juego — con posibilidad de
cambiarlo más tarde desde Ajustes.

Este documento sustituye a un "requisitos mínimos" cerrado: en vez de fijar un único equipo
mínimo, el juego se adapta al equipo que haya dentro de unos límites.

## Por qué hace falta

El narrador es un modelo de lenguaje corriendo en local. Hoy, en desarrollo, los 4 modelos
(`03-ollama-y-modelos-ia.md`) pueden ocupar juntos unos 10-11 GB de memoria si están cargados a
la vez. Un portátil con 8 GB de RAM no puede con eso; un PC con una gráfica de 12 GB va sobrado.
Configurar lo mismo para todos obliga a elegir entre excluir equipos modestos o desaprovechar los
buenos.

## Flujo

1. **Permiso.** Pantalla propia del asistente de primer arranque (ver
   [`11-diseno-del-frontal.md`](11-diseno-del-frontal.md), pantalla 3). Explica qué se consulta y
   que nada sale del equipo. Dos botones: "Analizar mi equipo" y "Prefiero elegir a mano".
2. **Detección** (si acepta). La hace el lado Rust de Tauri, en local, en menos de un segundo.
3. **Recomendación.** Se calcula el máximo seguro y se propone un perfil.
4. **Elección.** El jugador elige perfil (y, opcionalmente, el uso de CPU).
5. **Descarga** solo de los modelos que necesita ese perfil.
6. **Prueba rápida** opcional para confirmar la velocidad real.
7. **Cambiarlo después** desde Ajustes → Rendimiento de la IA, repitiendo la detección.

Si el jugador elige "a mano", se le muestran los mismos perfiles sin marcar ningún máximo, con
**Ligero** preseleccionado y el aviso de que un perfil demasiado alto puede dejar el equipo lento o
cerrar el juego.

## Qué se detecta

| Dato | Para qué | Cómo (Rust) |
|---|---|---|
| RAM total y libre | Techo principal de los perfiles | crate `sysinfo` |
| Núcleos e hilos de CPU, modelo | Uso de CPU recomendado (`num_thread`) | `sysinfo` |
| GPU: fabricante, modelo, VRAM | Si se puede descargar trabajo a la gráfica | Windows: DXGI (`IDXGIAdapter::GetDesc` → `DedicatedVideoMemory`). Linux: `/sys/class/drm/card*/device/mem_info_vram_total` (AMD), `nvidia-smi` si existe (NVIDIA) |
| Memoria compartida (gráfica integrada) | La Steam Deck y los portátiles con iGPU comparten RAM con la gráfica | Se detecta por ausencia de VRAM dedicada o GPU integrada conocida (p. ej. Van Gogh/Aerith de la Deck) |
| Espacio libre en el disco de datos | Que quepan los modelos del perfil | `sysinfo` (discos) sobre la carpeta de datos |
| Sistema operativo y versión | Soporte / diagnóstico | `sysinfo` |

Nada de esto se guarda salvo en el propio `config.json` local de la app, y nunca se envía a ningún
sitio (ver [`08-legal-y-privacidad.md`](08-legal-y-privacidad.md)).

**Cuando la detección de GPU falla o no es fiable** (frecuente con gráficas AMD e integradas), se
asume "sin GPU" y se calcula todo solo con RAM — tirar a la baja es el comportamiento seguro.

## Qué significa "RAM o esfuerzo" en la práctica

Ollama no tiene un ajuste de "usa como mucho X GB". Lo que el jugador elige como perfil se traduce
por dentro a una combinación de:

| Palanca | Qué cambia | Impacto |
|---|---|---|
| Tamaño del modelo del narrador | 7B (actual) o uno más pequeño | Memoria y calidad de narración |
| Modelo de "Sugerir" | Propio (`qwen3.5:4b`) o reutiliza el del cronista | Memoria, calidad de sugerencias |
| Modelos cargados a la vez (`OLLAMA_MAX_LOADED_MODELS`) | 1, 2 o todos | Memoria pico vs. tiempo de espera al cambiar de modelo |
| Tiempo que un modelo sigue cargado sin usarse (`OLLAMA_KEEP_ALIVE`) | 0 s, 5 min... | Memoria en reposo vs. velocidad del siguiente turno |
| Capas en la GPU (`num_gpu`) | 0, parcial o todas | Velocidad; consume VRAM |
| Hilos de CPU (`num_thread`) | Mitad de los núcleos, o todos menos uno | Velocidad vs. que el resto del equipo siga fluido |

**Lo que NO se toca:** `num_ctx` del narrador se queda en 8192. El propio `backend/Modelfile` del
juego documenta que con 4096 la generación se desestabilizó (JSON corrupto, texto en otro idioma).
Bajar el contexto no es un ajuste válido para ahorrar memoria.

## Perfiles propuestos

Cifras aproximadas a validar en la prueba de concepto (fase 0 del plan). La memoria es el pico
estimado solo de la IA; el juego en sí (webview + backend) suma ~1 GB aparte.

| Perfil | Narrador | Cronista | Sugerir | Embeddings | Cargados a la vez | Memoria pico IA | Descarga |
|---|---|---|---|---|---|---|---|
| **Ligero** | `qwen2.5:3b` | `qwen2.5:1.5b-instruct` | usa el cronista | `nomic-embed-text` | 1 | ~3,5 GB | ~3,3 GB |
| **Equilibrado** | `qwen2.5:7b` | `qwen2.5:1.5b-instruct` | usa el cronista | `nomic-embed-text` | 2 | ~7 GB | ~6 GB |
| **Máximo** | `qwen2.5:7b` | `qwen2.5:1.5b-instruct` | `qwen3.5:4b` | `nomic-embed-text` | todos | ~10,5 GB | ~9 GB |

- **Máximo** es exactamente la configuración actual de desarrollo.
- `nomic-embed-text` está en **todos** los perfiles: el juego lo necesita mientras se juega, no
  solo para indexar el lore (ver [`02-migracion-postgres-a-sqlite.md`](02-migracion-postgres-a-sqlite.md)).
  Además tiene que ser la misma versión con la que se indexó el lore empaquetado.
- **Ligero** usa un narrador distinto: narrará peor. Hay que probarlo en partida real antes de
  ofrecerlo, y comprobar su licencia (`qwen2.5:3b` no es Apache 2.0 como el 7B — ver `08`).

## Cálculo del máximo seguro

```
reserva_sistema   = max(3 GB, 25 % de la RAM total)
juego             = 1 GB                               (webview + backend + SQLite)
memoria_para_IA   = RAM_total - reserva_sistema - juego
si hay GPU dedicada con VRAM fiable:
    memoria_para_IA += VRAM * 0,9                      (las capas en GPU no ocupan RAM)
máximo_seguro     = el perfil más alto cuya "memoria pico IA" <= memoria_para_IA
```

Además, un perfil deja de estar disponible si no cabe en el disco (descarga + 10 % de margen).

Ejemplos:

| Equipo | memoria_para_IA | Máximo seguro |
|---|---|---|
| Portátil 8 GB, sin GPU | 8 − 3 − 1 = 4 GB | Ligero |
| Steam Deck 16 GB (compartida) | 16 − 4 − 1 = 11 GB | Máximo (justo). Recomendado: Equilibrado |
| PC 16 GB + GPU 8 GB | 16 − 4 − 1 + 7,2 = 18,2 GB | Máximo |
| PC 6 GB | 6 − 3 − 1 = 2 GB | Ninguno → aviso de que el equipo no llega |

**Recomendado vs. máximo:** el perfil preseleccionado es uno por debajo del máximo seguro cuando el
máximo queda con menos de 1,5 GB de margen, para no dejar el equipo al límite.

**Si ningún perfil cabe**, se explica con claridad y se deja continuar con Ligero bajo
responsabilidad del jugador (no se bloquea la instalación: la detección puede equivocarse).

## Uso de CPU

Control secundario, independiente del perfil:

- **Moderado** (por defecto): la mitad de los hilos. El equipo sigue fluido mientras narra.
- **Alto**: todos los hilos menos uno. Narración más rápida; el equipo va más cargado mientras
  narra.

## Prueba rápida

Botón opcional al final de la elección: genera una narración corta de prueba y mide
palabras/segundo. Se muestra como "Tu equipo narra a unas X palabras por segundo (una narración
típica tardará unos Y segundos)". Si sale muy lenta (p. ej. menos de 3 palabras/s), se sugiere
bajar de perfil. Solo se ofrece tras descargar los modelos; no bloquea nada.

## Dónde se guarda

`config.json` en la carpeta de datos de la app (ver
[`07-flujo-de-instalacion.md`](07-flujo-de-instalacion.md)):

```json
{
  "version": 1,
  "permisoAnalisis": true,
  "equipo": { "ramTotalMb": 16000, "gpu": { "nombre": "…", "vramMb": 0, "integrada": true } },
  "perfil": "equilibrado",
  "usoCpu": "moderado",
  "modelosDescargados": ["qwen2.5:7b", "qwen2.5:1.5b-instruct", "nomic-embed-text"],
  "asistenteCompletado": true
}
```

Al arrancar, Tauri lee este fichero y lanza Ollama y el backend con las variables de entorno que
corresponden al perfil (`OLLAMA_MAX_LOADED_MODELS`, `OLLAMA_KEEP_ALIVE`, `OLLAMA_MODEL_*`...).

## Cambiarlo después

Ajustes → Rendimiento de la IA:

- Muestra el perfil actual, la memoria que usa y el espacio que ocupan los modelos.
- "Volver a analizar mi equipo" (útil si se amplía la RAM o se cambia de gráfica).
- Cambiar de perfil: si el nuevo perfil necesita modelos que no están descargados, se avisa del
  tamaño antes de descargar. Si sobran modelos, se ofrece borrarlos para liberar espacio.
- El cambio se aplica reiniciando el motor de IA, sin cerrar la partida.

## Decisiones abiertas

1. **Por encima del máximo seguro:** ¿bloqueado, o permitido con aviso explícito? Propuesta:
   bloqueado por defecto, con un interruptor "Mostrar perfiles no recomendados" que lo permite con
   confirmación.
2. **Perfil Ligero con otro narrador:** ¿se acepta peor narración a cambio de que funcione en
   equipos de 8 GB, o se exige siempre el narrador de 7B? Hay que probarlo en partida real.
3. **Prueba rápida:** propuesta incluida como opcional; confirmar que se quiere.
