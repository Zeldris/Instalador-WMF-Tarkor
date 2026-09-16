# Arquitectura general

**Estado: decidido en líneas generales.** Las piezas concretas de cada apartado se detallan en los
documentos siguientes (02 a 04).

## El problema de partida

Tarkor hoy son tres piezas separadas que hay que arrancar a mano: backend Fastify (Node), frontend
Vite/React servido aparte, y Postgres en un contenedor podman. Además, hay funcionalidad completa
del repo del juego que existe solo para que Álvaro (el desarrollador) cure contenido — generación de
prompts de imagen vía proveedores de IA en la nube, un pipeline de fine-tuning, scripts de siembra
de catálogo — que un jugador final nunca necesita ver ni ejecutar.

Un instalador de escritorio tiene que resolver ambos problemas a la vez: que todo arranque solo,
como una app, **y** que solo contenga lo que un jugador necesita para jugar una partida.

## Qué es el instalador, en una frase

Una aplicación de escritorio (un único `.exe`/`.dmg`/`.AppImage` según la plataforma) que contiene
una versión **recortada y ya curada** de Tarkor: el motor de juego completo, el catálogo de mundo ya
sembrado, las imágenes ya generadas, y nada de las herramientas de desarrollo/curación que hoy viven
en el mismo repo.

## Las tres capas

### 1. Envoltorio: Tauri

Tauri usa el webview del sistema operativo en vez de empaquetar un navegador entero (a diferencia de
Electron), así que el instalador resultante pesa bastante menos. Ver
[`04-empaquetado-tauri.md`](04-empaquetado-tauri.md) para el detalle.

- El **frontend** ya compilado (build de Vite) se carga directamente en el webview — no hace falta
  servirlo aparte ni abrir un navegador.
- El **backend Node** corre como proceso "sidecar" — un binario que Tauri arranca y para junto con
  la propia app, hablando por `localhost` con el frontend exactamente igual que en desarrollo. El
  frontend no necesita ningún cambio de arquitectura para esto: ya habla con el backend vía
  `VITE_API_URL` (fallback a `http://localhost:3001`), solo cambia quién arranca ese proceso.

### 2. Base de datos: SQLite local al paquete

Nada de contenedor ni de servicio externo que instalar aparte. La base de datos vive como un
fichero `.sqlite` dentro de la carpeta de datos de la app, creado en el primer arranque. Ver
[`02-migracion-postgres-a-sqlite.md`](02-migracion-postgres-a-sqlite.md) para los tres puntos
concretos de fricción con Postgres y cómo resolverlos.

### 3. Modelo de IA: Ollama local

El narrador y el resto de modelos siguen corriendo en Ollama, en la propia máquina del jugador —
igual que hoy en desarrollo, no se sustituye por ningún servicio en la nube (eso sería justo lo
contrario del objetivo: nada de depender de un dominio público, y tampoco de pagar inferencia en la
nube por cada jugador). Lo que cambia es que el JUGADOR no es un desarrollador — no se le puede
pedir que instale Ollama a mano y haga `ollama pull` de 4 modelos distintos por línea de comandos.
Ver [`03-ollama-y-modelos-ia.md`](03-ollama-y-modelos-ia.md) — **sin resolver todavía**, es el hueco
más grande del plan actual.

## Qué NO va en el instalador

Decisión explícita de Álvaro (2026-09-16): el instalador es una versión recortada del juego, no un
clon 1:1 del repo de desarrollo. Concretamente:

- **Generación de prompts de imagen** (proveedores de IA en la nube — Cerebras/Mistral/SambaNova/
  Cloudflare/Gemini/Groq) — herramienta de curación de contenido para Álvaro, no algo que el jugador
  necesite. Las imágenes ya generadas se empaquetan tal cual, listas; el jugador nunca regenera nada.
- **Multijugador** — la opción aparece en la UI pero deshabilitada, marcada como "en construcción
  para futuras versiones". No funcional en el instalador.
- **Creación de personaje libre ("Crear desde cero")** — mismo criterio: visible pero deshabilitada,
  "en construcción". Solo queda disponible "En solitario" con los personajes pregenerados existentes.
- Cualquier otra herramienta de desarrollo/debug/captura de datos que no forme parte de la
  experiencia de juego real — ver el inventario completo en
  [`06-inventario-exclusiones.md`](06-inventario-exclusiones.md).

## Lo que NO cambia

El motor de juego en sí (backend Fastify, lógica de turnos, combate, Enciclopedia, todo lo que ya
funciona) no se reescribe. El instalador es un envoltorio + una migración de base de datos + una
poda de funcionalidad de desarrollo, no una reimplementación.
