<!-- galivelop-workflow v0.2.0 -->
# Guía de revisión

Lo que el revisor (`/code-review`) comprueba en cada diff del instalador, además de los fallos de
siempre. Lo mecánico ya lo comprueban los tests, el pre-push (`tsc`, clippy) y la CI (Linux y
Windows); aquí está lo que pide criterio. Cuando una retro saque un fallo que se repite, se añade
aquí con su `FLU-n` o `INS-n`.

## Un dato, un sitio

- Un dato que ya vive en un sitio (un archivo de configuración, uno de datos, una constante) no se repite a mano en
  el código, la documentación ni el README; si hay que repetirlo, todas las copias cambian en el mismo commit.
- La configuración del flujo vive solo en `.claude/gw.json` y solo la lee `.claude/gw/scripts/config.py`.

## Ganchos y scripts

- La raíz del repo se saca de la ruta del script (`$(dirname "$0")`) o de `git rev-parse --show-toplevel`, nunca de
  `$CLAUDE_PROJECT_DIR` ni del directorio actual: una sesión puede arrancar fuera del repo.
- Un gancho de subida comprueba **el commit que se sube**, no la carpeta de trabajo.
- Los ganchos **fallan cerrados** cuando les falta un dato (un commit que el clon no tiene, una API que no responde),
  con la orden que lo arregla.
- Los scripts de shell corren en bash 3.2 (macOS): nada de `mapfile` ni arrays asociativos.
- Cada cambio en un gancho o un script lleva su caso en los tests; un caso que espera un fallo comprueba el motivo,
  no solo el código de salida.

## Traído de otro repo: se adapta a los contratos de este

- El código, los scripts o las reglas traídos de otro repositorio se comprueban contra **este** repo, no contra el
  original: formatos, rutas, extensiones de archivo, patrones de nombres, constantes, claves de configuración e
  identificadores de tarea.
- Lo que viene de un proyecto que sube de otra forma (directo a la rama protegida, o por pull request) se adapta a
  cómo sube este a `main`.
- Una tabla o un ejemplo de una guía que lee un script lo lee ese script en un test.

## Idiomas visibles

- Si `.claude/gw.json` declara `visibleLanguages`, todo texto nuevo que vea un usuario existe en cada uno de esos
  idiomas (etiquetas, textos alternativos, títulos de página, mensajes), y una traducción es de verdad, no el mismo
  texto.

## Procesos (el motor de IA y el backend)

- **Nada queda vivo al cerrar.** Todo proceso que arranca la app (`procesos::Proceso::arrancar`) se
  para en todos los caminos de salida: cierre normal, error en el asistente, fallo del health-check y
  pánico. Un proceso hijo que sobrevive deja el puerto y la memoria ocupados y la siguiente apertura
  falla.
- **Linux y Windows a la vez.** Lo que toca procesos, rutas o permisos se escribe para los dos (en
  Windows no hay señales ni `chmod`; en Linux no hay `.exe`) y la CI de Windows lo compila. Un
  `#[cfg]` nuevo tiene su rama para la otra plataforma o dice por qué no la necesita.
- **Puertos.** Se pide un puerto libre (`puerto_libre`) y solo se escucha en `127.0.0.1`, nunca en
  `0.0.0.0`: el motor y el backend no se exponen a la red.
- **Esperas con tope.** Una espera (health-check, descarga, `/api/pull`) tiene límite y se puede
  cancelar; el asistente nunca se queda colgado sin decir qué pasa.

## Descargas e integridad

- **Fijado por SHA256.** Lo que se descarga y se ejecuta (el paquete del motor) lleva su versión y su
  SHA256 en el catálogo y se comprueba antes de descomprimir (`motor::sha256`). Cambiar la versión es
  cambiar los dos.
- **Solo los sitios previstos.** La app solo se conecta a los servidores del catálogo (descargas de
  Ollama y su registro de modelos) y al motor local. Ninguna telemetría ni petición nueva sin pasar
  por [`08`](docs/08-legal-y-privacidad.md).
- **A medias no cuenta.** Una descarga cancelada o fallida no deja un archivo que parezca bueno: se
  escribe aparte y se renombra al terminar.

## Lo que ya está guardado en el equipo de alguien

- **`config.json` y el catálogo son compatibles hacia atrás.** Un campo nuevo lleva
  `#[serde(default)]` (o el `default` del struct) para que un `config.json` o un catálogo sustituido
  de una versión anterior se siga leyendo; renombrar o quitar un campo dice qué pasa con los que ya
  existen y lleva un test que lea el formato viejo.
- **El catálogo se valida al cargar** (`Catalogo::validar`): un perfil o modelo nuevo pasa la
  validación y un catálogo roto en la carpeta de datos cae al incrustado, no tumba la app.
- **Las partidas no se tocan.** Actualizar o desinstalar sin «borrar partidas» no borra nada de la
  carpeta de datos del juego.

## El equipo de la usuaria

- **Permiso antes de mirar.** El análisis del equipo (`equipo::analizar`) solo corre tras aceptar en
  el asistente, y lo que se lee no sale del equipo ([`09`](docs/09-deteccion-de-equipo-y-perfiles.md)).
- **El máximo seguro manda.** Un perfil por encima de lo que cabe (`perfiles::evaluar`) no se ofrece
  como recomendado; los cálculos de memoria, hilos y contexto (`rendimiento::calcular`) dejan margen
  para el sistema y el juego, y un cambio en ellos lleva su test con un equipo pequeño (8 GB, sin
  gráfica dedicada) y la Steam Deck.

## Textos que se leen

- **Todo el texto visible, en `app/src/textos.ts`**, en español y con las comillas « ». Un mensaje
  de error dice qué pasó y qué puede hacer la usuaria, sin trazas ni rutas internas.
- **El asistente y el núcleo dicen lo mismo.** Lo que decide el núcleo (si un perfil cabe, cuánto
  ocupa la descarga) llega por su comando de Tauri; el asistente no lo recalcula con una copia.

## Plan y documentos

- **Tarea cerrada:** su casilla marcada en el [plan](docs/05-plan-de-trabajo.md) con lo hecho y lo que
  queda, la bitácora al día en el mismo commit (`CLAUDE.md`).
- **Una decisión de diseño cambia su documento** (`docs/01`…`docs/12`) y la tabla de decisiones del
  [README](README.md) en el mismo diff.
