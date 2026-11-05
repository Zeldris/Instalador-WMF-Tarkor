<!-- galivelop-workflow v0.5.0 -->
# Guía de revisión

Lo que el revisor (`/code-review`) comprueba en cada diff del instalador, además de los fallos de
siempre. Lo mecánico ya lo comprueban los tests, el pre-push (`tsc`, clippy) y la CI (Linux y
Windows); aquí está lo que pide criterio. Cada regla acaba en `(check: …)`, con lo que la hace cumplir, o en
`(criterio)` si no hay check; una regla mecánica marcada `(criterio)` pide su check. Cuando una retro saque un fallo
que se repite, se añade aquí con su `FLU-n` o `INS-n`.

## Cómo se informa

- Antes de dar un hallazgo, intenta refutarlo: busca el código, el test o el gancho que ya lo cubre. Solo se informa
  de lo que sobrevive, con la ruta y la línea. (criterio)
- Los hallazgos se escriben también en un archivo fuera del árbol (el scratchpad, o
  `"$(git rev-parse --git-dir)/review.md"`), no solo en la conversación: una compactación o un relevo se los lleva, y
  de ese archivo salen los encargos de los arreglos y los leves que se apuntan en la bitácora. (criterio)
- Un dato que caduca (una versión, un precio, una cuota, un límite de un servicio externo) escrito en el diff lleva su
  fecha y su fuente; si no, es un hallazgo. (criterio)
- La revisión acaba con un veredicto, uno de tres: `SHIP` (nada que arreglar), `SHIP WITH FIXES` (hay arreglos, ninguno
  bloquea) o `DO NOT SHIP` (algo grave o que rompe). (criterio)

## Un dato, un sitio

- Un dato que ya vive en un sitio (un archivo de configuración, uno de datos, una constante) no se repite a mano en
  el código, la documentación ni el README; si hay que repetirlo, todas las copias cambian en el mismo commit.
  (criterio)
- La configuración del flujo vive solo en `.claude/gw.json` y solo la lee `.claude/gw/scripts/config.py`. (criterio)

## Ganchos y scripts

- La raíz del repo se saca de la ruta del script (`$(dirname "$0")`) o de `git rev-parse --show-toplevel`, nunca de
  `$CLAUDE_PROJECT_DIR` ni del directorio actual: una sesión puede arrancar fuera del repo. (criterio)
- Un gancho de subida comprueba **el commit que se sube**, no la carpeta de trabajo. (criterio)
- Los ganchos **fallan cerrados** cuando les falta un dato (un commit que el clon no tiene, una API que no responde),
  con la orden que lo arregla. Excepción razonada: las claves de rutas (`log`, `reviewMark`, `recordsDir`,
  `proposalsDir`, `ciLocalLog`) son opcionales con defecto en inglés, así que una ausente no es un dato que falte.
  (criterio)
- Los scripts de shell corren en bash 3.2 (macOS): nada de `mapfile` ni arrays asociativos. (criterio)
- Una carpeta con nombre fijo en un directorio compartido (`$TMPDIR`, `/tmp`) es por usuario, se crea con permisos 700
  y se rechaza si ya existe como symlink o de otro usuario; los archivos sueltos, con `mktemp`. (criterio)
- Cada cambio en un gancho o un script lleva su caso en los tests; un caso que espera un fallo comprueba el motivo,
  no solo el código de salida. Vale para los scripts propios del proyecto. (criterio)
- Los scripts de `.claude/gw/scripts/` se prueban en el repo del flujo y no se editan aquí: un cambio va al flujo
  como propuesta, con `gw-harvest` (check: `config-guard.py` pregunta antes de editarlos). (criterio)
- Un gancho que pregunta o bloquea se revisa **probando cómo saltárselo**: envoltorios con opciones que llevan valor
  (`sudo -u X`, `sudo -uX`, `env -u X`, `nice -n 5`, `timeout 5`, `xargs -I{}`), el destino de los copiadores (`cp`,
  `install`, `rsync`, `dd of=`, `-t DIR`), una carpeta antecesora de la protegida y una ruta relativa o con `..`; y
  los falsos positivos habituales (leer o copiar **desde** la carpeta, `git restore --staged`). Cada forma, su caso.
  (criterio)
- `pkill -f <patrón>` (y `pgrep -f`) casa también con la orden que lo lanza cuando el patrón va en ella
  (`bash -c "… pkill -f servidor"`), y la mata: un pidfile, `pgrep -x` o un patrón que no se case a sí mismo
  (`[s]ervidor`). (criterio)
- Un runbook o encargo que sigue una tarea programada (una sesión sin persona delante) se revisa como código, aunque
  case con `content`: lo que dice se ejecuta tal cual. (criterio)

## Traído de otro repo: se adapta a los contratos de este

- El código, los scripts o las reglas traídos de otro repositorio se comprueban contra **este** repo, no contra el
  original: formatos, rutas, extensiones de archivo, patrones de nombres, constantes, claves de configuración e
  identificadores de tarea. (criterio)
- Lo que viene de un proyecto que sube de otra forma (directo a la rama protegida, o por pull request) se adapta a
  cómo sube este a `main`. (criterio)
- Una tabla o un ejemplo de una guía que lee un script lo lee ese script en un test. (criterio)

## Idiomas visibles

- Si `.claude/gw.json` declara `visibleLanguages`, todo texto nuevo que vea un usuario existe en cada uno de esos
  idiomas (etiquetas, textos alternativos, títulos de página, mensajes), y una traducción es de verdad, no el mismo
  texto. (criterio)

## Procesos (el motor de IA y el backend)

- **Nada queda vivo al cerrar.** Todo proceso que arranca la app (`procesos::Proceso::arrancar`) se
  para en todos los caminos de salida: cierre normal, error en el asistente, fallo del health-check y
  pánico. Un proceso hijo que sobrevive deja el puerto y la memoria ocupados y la siguiente apertura
  falla. (criterio)
- **Linux y Windows a la vez.** Lo que toca procesos, rutas o permisos se escribe para los dos (en
  Windows no hay señales ni `chmod`; en Linux no hay `.exe`) y la CI de Windows lo compila. Un
  `#[cfg]` nuevo tiene su rama para la otra plataforma o dice por qué no la necesita.
  (check: el job `windows` de `.github/workflows/app.yml` prueba el núcleo y el de Linux compila la app para
  `x86_64-pc-windows-gnu`)
- **Rutas comparadas con lo que da el sistema.** En Windows `canonicalize` devuelve `\\?\C:\…` y `sysinfo` da
  los puntos de montaje sin ese prefijo: una ruta que se compara, se busca en una lista o se guarda pasa antes por
  la misma forma (`carpetas::sin_verbatim`). (criterio)
- **Disco que falla a medias.** Copiar, mover o guardar puede fallar en mitad: lo que queda es el estado de antes o
  el nuevo entero (la copia parcial se borra, la carpeta vuelve si no se pudo guardar la config), y los enlaces
  simbólicos se copian como enlaces, no siguiéndolos. (criterio)
- **Puertos.** Se pide un puerto libre (`puerto_libre`) y solo se escucha en `127.0.0.1`, nunca en
  `0.0.0.0`: el motor y el backend no se exponen a la red. (criterio)
- **Esperas con tope.** Una espera (health-check, descarga, `/api/pull`) tiene límite y se puede
  cancelar; el asistente nunca se queda colgado sin decir qué pasa. (criterio)
- **Una invariante nueva, en todos sus sitios.** Si el diff añade una regla que otros sitios deben cumplir (un
  candado, una clase de error), busca con `grep` esos sitios aunque no estén en el diff. En `INS-42` el candado de
  arranque llegó a `arrancar_motor` y `asegurar_motor`, pero no a Reparar, mover la carpeta, reintentar ni cambiar
  de perfil (retro de `INS-42`). Si se puede, que lo imponga el tipo (`Turno` en `lib.rs`). (criterio)

## Descargas e integridad

- **Fijado por SHA256.** Lo que se descarga y se ejecuta (el paquete del motor) lleva su versión y su
  SHA256 en el catálogo y se comprueba antes de descomprimir (`motor::sha256`). Cambiar la versión es
  cambiar los dos. (criterio)
- **Solo los sitios previstos.** La app solo se conecta a los servidores del catálogo (descargas de
  Ollama y su registro de modelos) y al motor local. Ninguna telemetría ni petición nueva sin pasar
  por [`08`](docs/08-legal-y-privacidad.md). (criterio)
- **A medias no cuenta.** Una descarga cancelada o fallida no deja un archivo que parezca bueno: se
  escribe aparte y se renombra al terminar. (criterio)

## Lo que ya está guardado en el equipo de alguien

- **`config.json` y el catálogo son compatibles hacia atrás.** Un campo nuevo lleva
  `#[serde(default)]` (o el `default` del struct) para que un `config.json` o un catálogo sustituido
  de una versión anterior se siga leyendo; renombrar o quitar un campo dice qué pasa con los que ya
  existen y lleva un test que lea el formato viejo. (criterio)
- **El catálogo se valida al cargar** (`Catalogo::validar`): un perfil o modelo nuevo pasa la
  validación y un catálogo roto en la carpeta de datos cae al incrustado, no tumba la app. (criterio)
- **Las partidas no se tocan.** Actualizar o desinstalar sin «borrar partidas» no borra nada de la
  carpeta de datos del juego. (criterio)

## El equipo de la usuaria

- **Permiso antes de mirar.** El análisis del equipo (`equipo::analizar`) solo corre tras aceptar en
  el asistente, y lo que se lee no sale del equipo ([`09`](docs/09-deteccion-de-equipo-y-perfiles.md)). (criterio)
- **El máximo seguro manda.** Un perfil por encima de lo que cabe (`perfiles::evaluar`) no se ofrece
  como recomendado; los cálculos de memoria, hilos y contexto (`rendimiento::calcular`) dejan margen
  para el sistema y el juego, y un cambio en ellos lleva su test con un equipo pequeño (8 GB, sin
  gráfica dedicada) y la Steam Deck. (criterio)

## Textos que se leen

- **Todo el texto visible, en `app/src/textos.ts`**, en español y con las comillas « ». Un mensaje
  de error dice qué pasó y qué puede hacer la usuaria, sin trazas ni rutas internas. (criterio)
- **El asistente y el núcleo dicen lo mismo.** Lo que decide el núcleo (si un perfil cabe, cuánto
  ocupa la descarga) llega por su comando de Tauri; el asistente no lo recalcula con una copia. (criterio)

## Plan y documentos

- **Tarea cerrada:** su casilla marcada en el [plan](docs/05-plan-de-trabajo.md) con lo hecho y lo que
  queda, la bitácora al día en el mismo commit (`CLAUDE.md`).
  (check: `handoff.py closed --staged` en `.githooks/pre-commit` exige la bitácora; lo demás, criterio)
- **Una decisión de diseño cambia su documento** (`docs/01`…`docs/12`) y la tabla de decisiones del
  [README](README.md) en el mismo diff. (criterio)
