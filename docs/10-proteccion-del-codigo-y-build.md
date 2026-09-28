# Protección del código y pipeline de build

**Estado: decidido el enfoque (2026-09-28); técnica exacta del backend a validar en la prueba de
concepto.** Petición explícita de Álvaro: el código del juego tiene que ir protegido dentro del
binario. No hace falta que sea imposible de extraer — que se pueda sacar algo con esfuerzo es
aceptable — pero en general no debe quedar a la vista.

## Objetivo realista

Ninguna técnica hace el código imposible de extraer en un programa que corre en la máquina de otra
persona. El objetivo es que **extraer algo útil cueste un esfuerzo considerable**, y que la
protección legal (licencia, ver [`08-legal-y-privacidad.md`](08-legal-y-privacidad.md)) cubra el
resto.

## Qué se protege y cómo

| Pieza | Nivel | Técnica |
|---|---|---|
| **Backend** (motor del juego: turnos, combate, mundo) | Alto — es donde está el valor | 1. `esbuild` junta todo en un único fichero, minificado, sin comentarios ni *source maps*. 2. Se compila a **bytecode de V8** (sin código fuente dentro). 3. Ofuscación ligera opcional en módulos clave que no estén en el camino caliente de cada turno. |
| **Frontend** (React) | Medio — siempre extraíble, lo ejecuta el webview | Build de Vite minificado, sin *source maps*. Tauri lo incrusta comprimido dentro del ejecutable (más difícil de sacar que el `.asar` de Electron). La lógica sensible ya vive en el backend. |
| **Envoltorio Rust (Tauri)** | Muy alto | Código nativo compilado, `strip` de símbolos en release. |
| **Prompts del narrador** | Bajo — punto débil asumido | Lo que se envía a Ollama se puede ver (`localhost`). Se dificulta incrustando el texto del `SYSTEM` en el backend compilado y enviándolo en cada petición, en vez de dejar un `Modelfile` legible en disco (ver [`03-ollama-y-modelos-ia.md`](03-ollama-y-modelos-ia.md)). |
| **Base de datos** (catálogo, lore) e **imágenes** | Bajo | Ficheros de datos legibles. Cifrar SQLite (SQLCipher) obligaría a meter la clave en el binario: solo disuade y complica el empaquetado. **No se hace en la v1.** |

## Resultado de la prueba de concepto (fase 0.6, 2026-09-28)

**El camino A funciona con el backend real del juego.** Herramienta:
[`herramientas/empaquetar-backend.mjs`](../herramientas/empaquetar-backend.mjs) (vive en este repo
porque no contiene código del juego: lo transforma desde una ruta local).

Probado con una copia del backend del commit `ace5cd8`, Node 22.22.2, Prisma 6.19.3 y una base
de datos Postgres con pgvector, migraciones del juego aplicadas y catálogo sembrado (99 PNJ, 64
lugares, 67 fragmentos de lore):

| Prueba desde el bytecode | Resultado |
|---|---|
| Arranque (Fastify, rutas, worker del mundo) | Correcto |
| `GET /health` | 200 |
| `GET /world/helek-sirik/enciclopedia` (808 KB) y `/locations` | 200 |
| `POST /saves` (crear partida: transacción con varias tablas) y `GET /saves/:id` | 200 |
| `POST /saves/:id/attribute-points` (bloqueo `FOR UPDATE` con SQL crudo) | Respuesta de negocio correcta |
| Errores 500 en el registro | Ninguno |

**Tamaño:** 151 MB: runtime de Node 119 MB + `servidor.jsc` 5,2 MB + cliente de Prisma recortado
(sin los motores de otras bases de datos, ~70 MB menos). Con Prisma sin motor nativo se
reduciría algo más.

**Qué queda protegido y qué no** (comprobado buscando dentro de `servidor.jsc`):

- No hay código fuente. Los nombres de funciones del motor no aparecen (p. ej.
  `lockRowForUpdate`): el minificado los renombra antes de compilar.
- Los **textos literales sí se leen** (descripciones de objetos, mensajes, trozos de prompts):
  cualquier técnica los deja, porque el programa los necesita tal cual.
- El `Modelfile` hoy viaja como fichero aparte (el backend lo lee del disco): su prompt se lee
  entero. Se resuelve incrustándolo (fase 3.5).

**Adaptaciones que hace la herramienta** y que conviene llevar al juego en la fase 3 para no
depender de ellas:

- `server.ts` usa `await` de primer nivel, que no existe en CommonJS: la herramienta envuelve el
  arranque en una función asíncrona. Mejor: que el juego exporte una función `main()`.
- `import.meta.dirname` (3 sitios) se sustituye por una ruta relativa a
  `TARKOR_BACKEND_RAIZ`. Mejor: rutas de imágenes y datos por variable de entorno.
- El backend escucha en `0.0.0.0`: en el instalador tiene que ser `127.0.0.1` (fase 3.6).

## Backend a bytecode: dos caminos

Se elige uno en la prueba de concepto (fase 0 de [`05-plan-de-trabajo.md`](05-plan-de-trabajo.md)):

**A. Node SEA + bytecode (preferido).**
- Se incluye el runtime oficial de Node 22 como ejecutable del sidecar.
- El bundle de `esbuild` se compila a bytecode V8 con `bytenode` (fichero `.jsc`) y un cargador
  mínimo lo ejecuta.
- Ventajas: runtime oficial, máxima compatibilidad con Fastify/undici/Prisma.
- Riesgos: el bytecode va atado a la versión exacta de Node — el build y el runtime empaquetado
  deben ser la misma versión (se fija en la CI). Algunas librerías que usan
  `Function.prototype.toString` fallan con bytecode — hay que probarlo.

**B. Bun `--compile --bytecode`.**
- Un único ejecutable con el bytecode dentro, sin cargador aparte.
- Riesgo: compatibilidad de Bun con Prisma y con algunos módulos de Node. Solo se elige si A falla.

**Plan de reserva** si el bytecode no es viable con Prisma: `javascript-obfuscator` sobre el bundle
(protección algo menor, algo más lento). Medir el coste en un turno real antes de aceptarlo.

**Descartado:** `pkg` (proyecto archivado) y `nexe` (sin mantenimiento activo).

## Prisma en el binario

- El cliente de Prisma se genera para SQLite con `binaryTargets` de las dos plataformas
  (`windows`, `debian-openssl-3.0.x`/`rhel-openssl-3.0.x` según la base de Linux elegida).
- El motor de consultas nativo (`query_engine`) viaja junto al sidecar y se le indica la ruta con
  `PRISMA_QUERY_ENGINE_LIBRARY`.
- Alternativa preferida si funciona: el juego ya usa Prisma 6.19.3, que tiene un modo sin motor
  nativo en Rust (`previewFeatures = ["queryCompiler", "driverAdapters"]` con el adaptador de
  SQLite). Elimina el binario nativo de Prisma y simplifica mucho el empaquetado. Se prueba en la
  fase 0 junto con el bytecode.

## Rutas que se rompen al empaquetar

Todo lo que el backend lee del disco con rutas relativas a su propio código deja de funcionar en un
binario. Detectado hasta ahora:

- `backend/src/lib/modelfileSystemPrompt.ts` lee `../../Modelfile` en tiempo de ejecución → hay
  que incrustar el texto en tiempo de build.
- `backend/uploads/images` (imágenes de la Enciclopedia, ~268 MB) → se sirve desde los recursos de
  Tauri, ruta pasada por variable de entorno.

Hay que auditar el resto de `readFileSync`/`import.meta.dirname` antes de la fase 4.

## Dónde se hace la build: repo privado

El código fuente no debe pasar nunca por este repositorio público ni por sus logs.

```
World-Maker-Fantasy (privado)                     Instalador-WMF-Tarkor (público)
┌───────────────────────────────┐                 ┌──────────────────────────────┐
│ GitHub Actions                │                 │ Documentación                │
│  ├─ runner windows-latest     │                 │ Código del envoltorio Tauri  │
│  │   build frontend + backend │   checkout      │ (app/: asistente, sidecars)  │
│  │   bytecode + tauri build   │ ◄────────────── │                              │
│  └─ runner ubuntu-22.04       │                 │                              │
│      mismo proceso            │                 │ Releases: .exe, .AppImage,   │
│                               │ ──────────────► │ .deb + SHA256SUMS            │
│  (token con permiso SOLO de   │  publica        │                              │
│   releases en el repo público)│  release        │                              │
└───────────────────────────────┘                 └──────────────────────────────┘
```

- La CI vive en el **repo privado**: hace checkout del juego y del envoltorio público (lectura
  pública, sin token), compila y publica solo los instaladores como *release* del repo público.
- El token guardado en el repo privado solo necesita permiso de *contents: write* sobre el repo
  público (para crear releases). Un *fine-grained token* limitado a ese repo.
- Cada plataforma se compila en su propio runner: Tauri no compila de un sistema a otro, y el
  bytecode de V8 se genera por plataforma.
- **Linux sobre `ubuntu-22.04`**: una glibc más antigua hace que el AppImage funcione también en
  distros de hace un par de años.
- En los logs de la CI no se imprime código ni variables sensibles; los artefactos intermedios
  (bundle sin compilar) no se suben como artefactos de la ejecución.

## Integridad de lo publicado

- Cada release incluye `SHA256SUMS` con la suma de cada instalador.
- Windows: firma de código pendiente de decidir (ver [`04-empaquetado-tauri.md`](04-empaquetado-tauri.md)).
- Ollama y los modelos que se descargan en el primer arranque se verifican contra sumas fijadas en
  el propio binario (ver `03`).

## Qué falta

- Probar en la fase 0 el camino A (Node + bytecode) con el backend real y Prisma sobre SQLite.
- Auditar las rutas de disco del backend.
- Crear el token limitado y el workflow en el repo privado (fase 4).
