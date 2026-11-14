<!-- galivelop-workflow v0.6.0 -->
# Glosario

Vocabulario de Instalador-WMF-Tarkor. Primero van los términos del flujo; el proyecto añade debajo los de su dominio y los
mantiene al día (skill `domain-modeling`). El flujo nunca sobrescribe este archivo una vez creado.

## Términos del flujo

- **Bitácora**: `docs/records/traspaso.md`, el estado del trabajo para la siguiente sesión: rama, tarea en curso, siguiente paso,
  check.
- **Relevo**: una sesión que se acaba y otra que sigue desde la bitácora, sin preguntar por dónde iba.
- **Punto estable**: un estado con el check en verde, con commit y subido.
- **Check**: las órdenes del proyecto que tienen que pasar en cada commit que se sube: las de `check` en
  [`.claude/gw.json`](.claude/gw.json), que es el único sitio donde se listan.
- **Commit `WIP:`**: un commit subido con algo a medias o en rojo; la bitácora dice qué falla y por qué.
- **Rama protegida**: `main`, lo publicado; solo recibe trabajo revisado, con confirmación de la
  usuaria.
- **Marca de revisión**: `docs/records/reviewed.txt`, el archivo versionado con el sha del último commit revisado; los ganchos
  aceptan código hasta él.
- **Contenido frente a código**: el contenido (lo que casa con `content` de `.claude/gw.json`) no necesita revisión
  de código; todo lo demás es código.
- **Encargo a un subagente**: lo que recibe un subagente: objetivo, rutas, restricciones, el check que debe pasar y
  qué tiene que devolver.
- **Retro**: la retrospectiva de la sesión antes de ir a la rama protegida; sus propuestas se presentan a la usuaria y
  lo que confirme se aplica en la rama.
- **Propuesta (`.gw-new`)**: un archivo del flujo que la actualización no pudo aplicar sin perder cambios locales;
  se fusiona a mano y luego se borra.

## Términos del proyecto

- **Asistente**: la app de escritorio que guía la instalación pantalla a pantalla (`app/src`, React).
- **Núcleo**: la lógica en Rust sin interfaz (`app/nucleo`, crate `tarkor-nucleo`): catálogo, perfiles, descargas,
  procesos y `config.json`.
- **Catálogo**: `app/catalogo/catalogo.json`, los perfiles y modelos que se ofrecen, con la versión y el SHA256 del
  motor; se valida al cargar ([`12`](docs/12-catalogo-y-rendimiento.md)).
- **Perfil**: un nivel de equipo del catálogo (qué modelos y qué motor le tocan); la Steam Deck es el mínimo.
- **Máximo seguro**: el perfil más alto que el equipo aguanta según su memoria y su gráfica
  ([`09`](docs/09-deteccion-de-equipo-y-perfiles.md#cálculo-del-máximo-seguro)).
- **Motor**: el programa que corre los modelos de IA en local (Ollama), descargado y fijado por SHA256.
- **Carpeta de datos**: donde la app guarda `config.json`, el motor y los modelos ([`07`](docs/07-flujo-de-instalacion.md)).
