# Legal y privacidad

**Estado: privacidad decidida (2026-09-28); licencia propuesta; texto legal definitivo pendiente
de redactar y revisar.**
Petición de Álvaro (2026-09-16): Tarkor será gratuito para todos, y el instalador debe ser
escrupulosamente legal y explicarlo todo con claridad, sin letra pequeña ilegible.

Nada de este documento es asesoramiento legal: el texto final debe revisarlo alguien con
conocimiento del tema antes de publicar la v1.

## Por qué importa

Distribuir un instalador público a desconocidos implica: tocar su disco, traer software de terceros
(Ollama), usar modelos de IA con licencias propias, y publicar un repositorio con código de
empaquetado.

## 1. Licencia del proyecto

**Propuesta (pendiente de confirmar por Álvaro): todos los derechos reservados**, para el juego y
su contenido, con permiso gratuito de uso personal. Es lo que encaja con proteger el código dentro del binario
([`10-proteccion-del-codigo-y-build.md`](10-proteccion-del-codigo-y-build.md)): la protección
técnica sube el listón y la licencia da el derecho a reclamar.

- **El juego distribuido** (binario, contenido narrativo, lore, personajes, mundo de Helek Sirik,
  imágenes): licencia propia de uso personal gratuito. Se permite descargar, instalar y jugar. No
  se permite redistribuir modificado, extraer ni reutilizar el código o el contenido, ni venderlo.
- **Este repositorio público** (documentación y código del envoltorio): **abierto, a decidir.**
  Opciones: también todos los derechos reservados (código visible pero no reutilizable), o una
  licencia abierta (MIT) solo para el envoltorio, que no contiene nada del juego.
- **Imágenes de la Enciclopedia:** hay que confirmar con qué proveedor se generó cada una y que sus
  términos permiten redistribuirlas en un producto gratuito.

## 2. Licencias de terceros

| Pieza | Licencia | Qué exige |
|---|---|---|
| Ollama | MIT | Incluir el aviso de copyright y la licencia |
| `qwen2.5:7b`, `qwen2.5:1.5b-instruct` | Apache 2.0 | Incluir la licencia y los avisos |
| `qwen2.5:3b` (perfil Ligero, `09`) | **Qwen Research License** — no es Apache 2.0 | Revisar antes de usarlo: puede no permitir este uso. Si no lo permite, buscar otro narrador ligero |
| `qwen3.5:4b` | Verificar | — |
| `nomic-embed-text` | Apache 2.0 | Incluir la licencia |
| Tauri, dependencias de Rust y npm | Mayoritariamente MIT / Apache 2.0 | Aviso de licencias de terceros generado en el build (`cargo-about` y `license-checker`) |
| Fuentes Cinzel e Inter | SIL Open Font License | Incluir la licencia al empaquetarlas |

Las licencias de los modelos hay que **comprobarlas en la fuente oficial** en el momento de
publicar: cambian entre versiones.

El juego incluye una pantalla "Licencias de terceros" (Ajustes → Acerca de) con todo lo anterior.

Los modelos y Ollama no van dentro del instalador: se descargan de sus fuentes oficiales en el
primer arranque, con el consentimiento del jugador (ver `03` y `07`).

## 3. Datos y privacidad

Tarkor es local: no hay servidor, ni cuenta, ni telemetría. Aun así se dice explícitamente:

- **Partidas:** en la máquina del jugador (SQLite local). Nunca se suben a ningún sitio.
- **Narración:** la IA corre en local. Ningún texto de la partida sale del equipo. Las APIs en la
  nube y el pipeline de entrenamiento quedan fuera del instalador (ver `06`).
- **Análisis del equipo** (`09`): solo con permiso. Se leen RAM, CPU, gráfica, espacio en disco y
  sistema operativo, se usan para recomendar un perfil y se guardan solo en el `config.json` local.
  Nunca se envían.
- **Tráfico de red:** solo las descargas del primer arranque (Ollama y modelos, desde sus fuentes
  oficiales) y las que el jugador pida al cambiar de perfil. Nada más.
- **Sin telemetría** ni analítica. Si algún día se añade, será opcional y desactivada por defecto.
- **Registros de errores:** se guardan en local y solo salen del equipo si el jugador copia el
  informe y lo envía él mismo.

## 4. Aviso "tal cual"

El software se ofrece sin garantías y sin responsabilidad por daños derivados de su uso. Se
redacta con el texto legal definitivo.

## 5. Contenido y edad

RPG de fantasía con violencia (combate, muerte permanente). Propuesta: una nota de contenido
("Contiene violencia de fantasía; recomendado para mayores de 16 años") en la página de descarga y
en la bienvenida del asistente. Sin sistema de verificación de edad.

## Qué falta

- Confirmar la licencia del juego (propuesta: todos los derechos reservados).
- Decidir la licencia de este repositorio público.
- Confirmar las licencias de los modelos (en especial el narrador del perfil Ligero) y de las
  imágenes.
- Redactar el texto legal definitivo y revisarlo.
