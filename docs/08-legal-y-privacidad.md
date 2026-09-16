# Legal y privacidad

**Estado: ABIERTO.** Petición explícita de Álvaro (2026-09-16): Tarkor será gratuito para todos,
pero quiere que el instalador sea escrupulosamente legal — explicar todo con claridad, no dejar
nada en letra pequeña ilegible. Este documento recoge qué hay que resolver, sin decidir el texto
legal en sí (eso necesita redactarse con cuidado, probablemente con más investigación o asesoría
específica cuando se llegue a este punto).

## Por qué esto importa más de lo habitual en un proyecto personal

Aunque el proyecto sea gratuito y no busque monetización, distribuir un instalador público a
desconocidos cambia las obligaciones reales frente a tenerlo solo en una máquina de desarrollo:

- El instalador va a tocar el disco del usuario (instala archivos, puede crear una carpeta de
  datos con partidas guardadas).
- Si el instalador gestiona la instalación de Ollama (ver
  [`03-ollama-y-modelos-ia.md`](03-ollama-y-modelos-ia.md)), está trayendo software de terceros.
- El propio motor del juego usa modelos de IA (Qwen 2.5/3.5) que tienen sus propias licencias.
- El repo del instalador será público — cualquiera puede leer el código de empaquetado, aunque el
  repo del juego en sí siga privado.

## Lo que hay que resolver

### 1. Licencia del propio proyecto Tarkor

Sin decidir todavía qué licencia usar para el instalador/el juego distribuido. Preguntas a
resolver:
- ¿El código del instalador (este repo, que será público) lleva una licencia open source estándar
  (MIT, Apache 2.0, GPL...), o es "código visible pero no licenciado para reuso" (ver la propia
  narrativa del juego, con contenido original que Álvaro puede querer proteger)?
- El contenido narrativo del juego (lore, personajes, mundo de Berig/Helek Sirik) es propiedad de
  Álvaro — ¿se distribuye bajo qué términos junto con el instalador? Probablemente distinto de la
  licencia del código en sí.
- Las imágenes generadas para la Enciclopedia (empaquetadas ya hechas, ver
  [`06-inventario-exclusiones.md`](06-inventario-exclusiones.md)) — de qué proveedor de IA salieron
  originalmente y qué términos de uso/redistribución tiene ese proveedor para imágenes generadas.

### 2. Licencias de terceros que el instalador trae consigo

Cualquier pieza de software de terceros que el instalador empaquete o instale necesita que se
respeten sus propios términos y, normalmente, que se le dé crédito visible al usuario:

- **Ollama** (si el instalador lo gestiona) — licencia propia, revisar qué exige al redistribuir.
- **Qwen 2.5 / Qwen 3.5** (modelos base usados por el narrador/cronista/sugerencias) — licencia de
  Alibaba/Qwen, revisar términos de uso y redistribución de los pesos del modelo.
- **nomic-embed-text** (modelo de embeddings) — licencia propia también.
- **Tauri** y cualquier dependencia de Node/npm empaquetada — la mayoría son MIT/Apache 2.0 y no
  suelen exigir mucho, pero conviene generar un aviso de "licencias de terceros" que liste todo,
  práctica estándar en instaladores serios.

### 3. Qué datos toca el juego y qué se le comunica al jugador

Punto fuerte de Tarkor de cara a esto: es local-first, no hay servidor remoto ni cuenta de usuario.
Pero aun así conviene decirlo explícitamente, no asumir que el jugador lo da por hecho:

- Las partidas guardadas viven en la máquina del jugador (SQLite local, ver
  [`02-migracion-postgres-a-sqlite.md`](02-migracion-postgres-a-sqlite.md)) — nunca se suben a
  ningún sitio.
- El motor de narración corre localmente vía Ollama — ningún texto de la partida (acciones del
  jugador, narración generada) sale de la máquina, salvo que el jugador decida algo distinto en el
  futuro (no aplica hoy, ni con el pipeline de fine-tuning ni con las APIs cloud, que quedan fuera
  del instalador por completo — ver `06-inventario-exclusiones.md`).
- Si el instalador descarga algo en el primer arranque (Ollama, modelos de IA), eso sí implica
  tráfico de red — hay que decirlo con claridad en el flujo de consentimiento (ver
  [`07-flujo-de-instalacion.md`](07-flujo-de-instalacion.md)).
- Sin telemetría oculta, sin analítica de uso enviada a ningún sitio, salvo que se decida
  explícitamente lo contrario en el futuro (y en ese caso, opt-in claro, nunca activado por
  defecto sin avisar).

### 4. Aviso de responsabilidad / "as-is"

Práctica estándar en software gratuito distribuido públicamente: un aviso claro de que el software
se ofrece tal cual, sin garantías, y de que Álvaro no es responsable de daños derivados de su uso
(pérdida de datos, mal funcionamiento, etc.) — redactar cuando se llegue a este punto, no inventar
texto legal ahora sin revisión.

### 5. Menores de edad / clasificación de contenido

Tarkor es un RPG de fantasía con violencia (combate, muerte permanente) — sin decidir todavía si
hace falta algún tipo de aviso de edad/contenido recomendado, o si basta con una nota simple en la
página de descarga.

## Qué falta antes de poder escribir el texto legal real

- Decidir la licencia del código (punto 1).
- Confirmar los términos exactos de Ollama/Qwen/nomic-embed-text para redistribución (punto 2) —
  esto puede condicionar si el instalador puede embeber Ollama directamente o solo enlazarlo (ver
  también `03-ollama-y-modelos-ia.md`, opción A).
- Escribir el texto real de consentimiento/privacidad una vez estén claras las piezas anteriores —
  no antes, para no tener que reescribirlo si cambia alguna decisión de arquitectura.
