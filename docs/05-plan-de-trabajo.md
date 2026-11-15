# Plan de trabajo: roadmap por versiones

Este documento es el roadmap del instalador: una sección por versión, con su tabla de tareas. Lo lee
`.claude/gw/scripts/roadmap.py` (`show`, `list`, `done`), que entiende `` ## `X.Y` «Nombre» `` y las tablas
`| Id | Tarea | Estado |`. Decidido con la usuaria el 2026-11-15 (propuesta en
[`versiones.md`](records/auditoria-2026-11-15/versiones.md); las diez propuestas de la auditoría, en su
[README](records/auditoria-2026-11-15/README.md)).

Reglas:

- Cada tarea lleva un id (`INS-n` del instalador, `FLU-n` del flujo de trabajo) y está en una versión, o en
  «Después, sin versión». Un id sale en una sola fila de todo el archivo. Las tareas se nombran en commits y en la
  [bitácora](records/traspaso.md).
- Solo la última menor publicada recibe parches; lo nuevo va a la siguiente menor libre.
- PR por tanda a `main`, sin ramas `version/`. Cada PR rellena `[Unreleased]` de `CHANGELOG.md` y, al cerrar la
  versión, se pone el tag `vX.Y.Z`.
- Estado: `pendiente`, `en curso` o `hecho (AAAA-MM-DD; nota)`.

Dónde se trabaja: este repo (público) lleva el envoltorio Tauri, el asistente y los sidecars; el repo del juego
(privado), la migración a SQLite, el recorte de funcionalidad y el modo empaquetado.

## `0.1` «Asistente»

Lo ya fusionado en `main` (fases 0, 1 y 4 hechas, con pruebas de punta a punta). Tag retroactivo `v0.1.0` sobre `9fce3d1`.

| Id | Tarea | Estado |
|---|---|---|
| INS-1 | Proyecto Tauri v2 en `app/` con el asistente (React + Vite + TypeScript) y los tokens visuales del juego ([`11`](11-diseno-del-frontal.md)) | hecho (2026-09-28, aprox.; fase 0) |
| INS-2 | Detección de equipo en Rust (`sysinfo`) y cálculo de perfiles de [`09`](09-deteccion-de-equipo-y-perfiles.md), con tests | hecho (2026-09-28, aprox.; fase 0) |
| INS-3 | `config.json` en la carpeta de datos: al abrir, asistente si no está completado | hecho (2026-09-28, aprox.; fase 0) |
| INS-3b | Catálogo de modelos y perfiles en JSON (con perfil Mínimo) y ajustes de Ollama por equipo ([`12`](12-catalogo-y-rendimiento.md)) | hecho (2026-09-28; fase 0) |
| INS-4 | Gestor de sidecars en Rust: puerto libre, arranque y parada, health-check, un reinicio automático | hecho (2026-09-28, aprox.; fase 0) |
| INS-5 | Ollama portable: descarga fijada con SHA256, arranque aislado, modelos con progreso vía `/api/pull` | hecho (2026-09-28, aprox.; fase 0) |
| INS-6 | Prueba de empaquetado del backend a bytecode con Postgres (`herramientas/empaquetar-backend.mjs`); repetirla sobre SQLite y probar Prisma sin motor nativo queda para tras `INS-60` | hecho (2026-09-28, aprox.; fase 0, con la repetición sobre SQLite pendiente) |
| INS-13 | Perfiles pequeños: se ofrecen Mínimo y Ligero con modelos Apache 2.0, avisando del resultado (calidad a confirmar en `INS-8`) | hecho (2026-09-28, aprox.; fase 1) |
| INS-14 | Perfiles por encima del máximo seguro: elegibles con aviso y confirmación en la tarjeta (`09`, `11`) | hecho (2026-10-25; en el asistente y en Ajustes) |
| INS-21 | Proveedor de base de datos por variable de entorno y `schema.sqlite.prisma` en el build, con test de sincronía | descartado (hecho el 2026-09-28, aprox., en el PR #1 del repo del juego, que se cerró sin fusionar; se rehace en `INS-60`) |
| INS-22 | Embeddings en JSON y similitud coseno en JS | descartado (PR #1 del juego cerrado sin fusionar; se rehace en `INS-60`) |
| INS-23 | `lockRowForUpdate()` con mutex en memoria para SQLite | descartado (PR #1 del juego cerrado sin fusionar; se rehace en `INS-60`) |
| INS-24 | Los 16 campos de lista a `Json`; `push` reescritos con `anadirNpcRetirado` | descartado (PR #1 del juego cerrado sin fusionar; se rehace en `INS-60`) |
| INS-25 | `mode: 'insensitive'` y `skipDuplicates` | descartado (PR #1 del juego cerrado sin fusionar; se rehace en `INS-60`) |
| INS-26 | Batería de tests del backend pasando contra SQLite | descartado (PR #1 del juego cerrado sin fusionar; se rehace en `INS-60`) |
| INS-27 | Script de build de la base de datos plantilla (migrada, catálogo, lore indexado) | descartado (PR #1 del juego cerrado sin fusionar; se rehace en `INS-60`) |
| INS-31 | Frontend: URL del backend en tiempo de ejecución (`apiBaseUrl()`, contrato `window.__TARKOR__.apiUrl` de [`04`](04-empaquetado-tauri.md)) | hecho (2026-10-26; en `main` del juego, `b76c66b2`, 8 tests) |
| INS-32 | Frontend: fuentes Cinzel e Inter en local | hecho (2026-10-26; ya en `main` del juego por `BAS-1`, `4a150259`; sin cambios allí) |
| INS-33 | Frontend: sin `ImagePromptSlot` ni admin en el juego empaquetado; «Crear desde cero» deshabilitada | hecho (2026-10-27; en `main` del juego, `aae4a755`, `esEmpaquetado()`, 9 tests) |
| INS-34 | Backend: build sin rutas ni servicios de curación (esbuild `define`, `import()` dinámico) | hecho (2026-10-27; en `main` del juego, `c7f0e5f9`; `empaquetar-backend.mjs` vigila el `metafile`) |
| INS-42 | Asistente real de punta a punta: descargas y comprobaciones reales, calentar el narrador, autopausa por red (trozos A, B y C) | hecho (2026-10-26; autopausa con `useEsperaRed`, `calentar_narrador`, ofrece perfil más ligero sin memoria) |
| INS-43 | Ajustes → Rendimiento de la IA (uso vía `/api/ps`) y pantalla de motor detenido | hecho (2026-10-25; núcleo, comandos, hilo de vigilancia, E2E `rendimiento`; Windows pendiente de `INS-8`) |
| INS-44 | NSIS: castellano, instalación por usuario, desinstalador con las dos casillas | hecho (2026-11-11; plantilla `installer.nsi`, `--desinstalar`, job `instalador-windows`; verlo en pantalla pendiente de `INS-8`) |
| INS-45 | AppImage y `.deb` en Ubuntu 22.04, con «Borrar datos del juego» en Ajustes | hecho (2026-11-11; job `paquetes-linux`, diálogo `BorrarDatos`; Deck y escritorio limpio pendientes de `INS-8`) |
| INS-47 | Pantalla «Licencias de terceros» generada en el build (`cargo-about` y npm) | hecho (2026-11-12; `licencias-terceros.mjs`, `THIRD-PARTY-NOTICES.txt`, 24 licencias y 368 paquetes) |
| INS-48 | Carpeta del motor y los modelos elegible y movible (`OLLAMA_MODELS`), con espacio frente a libre | hecho (2026-10-25; `carpetaIa`, `cambiar_carpeta_ia`; SD de la Deck y Windows pendientes de `INS-8`) |
| INS-49 | «Reparar»: comprobar la suma del motor y pedir de nuevo los modelos | hecho (2026-10-25; `motor::reparar`, `modelos.rs`; Windows y Deck pendientes de `INS-8`) |
| INS-57 | Hoja de estilos del instalador con sus peticiones de imágenes ([`13`](13-hoja-de-estilos-e-imagenes.md)) | hecho (2026-11-11; cuatro dudas resueltas por la usuaria, §6) |
| INS-59 | Tras borrar solo la IA, al volver a abrir empieza el asistente (`desinstalar::borrar` reescribe `config.json`) | hecho (2026-11-12; cinco tests; Windows y Linux pendientes de `INS-8`) |
| FLU-1 | Traer de Tarkor su flujo de trabajo y sus skills, adaptados al instalador | hecho (2026-10-21; con `/code-review` y [retro](records/retro-2026-10-21-flujo.md)) |
| FLU-3 | `ci-local.py`: corre en local los pasos de los jobs de Ubuntu del CI | hecho (2026-10-22; con `--apuntar` deja el resultado en [`ci-local.md`](records/ci-local.md)) |
| FLU-4 | `/gw-update` a Galivelop-workflow v0.3.0 | hecho (2026-10-25; el CI conserva sus jobs) |
| FLU-5 | `cargo fmt` del workspace en commits aparte y `cargo fmt --all --check` en `check` y CI | hecho (2026-10-26; `app/rustfmt.toml`, `.git-blame-ignore-revs`) |
| FLU-6 | `app/rust-toolchain.toml` fija Rust 1.94.1 | hecho (2026-10-26; el CI con la versión fijada no ha corrido por falta de cuota; Windows con `INS-8`) |
| FLU-7 | `/gw-update` a Galivelop-workflow v0.5.0 (rutas en inglés, `commitNext`, sin firmas; CI en `check.yml` y `app.yml`) | hecho (2026-11-04; `app.yml` sin correr en GitHub por falta de cuota) |
| FLU-8 | `/gw-update` a Galivelop-workflow v0.5.1 | hecho (2026-11-11; fusionado por el PR #13, retro `retro-2026-11-11-flu8.md`) |

## `0.2` «Versiones»

Cierra con el plan como roadmap, una sola versión en la app, `CHANGELOG.md` y `release.yml` por tag (sin binarios todavía).

| Id | Tarea | Estado |
|---|---|---|
| FLU-10 | Roadmap por versiones (este documento), `roadmapFiles` en `.claude/gw.json`, versión única en `app/src-tauri/tauri.conf.json` copiada por script a `package.json` y `Cargo.toml`, `CHANGELOG.md` Keep a Changelog y `release.yml` por tag sin binarios | hecho (2026-11-15; roadmap por versiones, versión única, CHANGELOG y release.yml; tag v0.1.0 sobre 9fce3d1) |
| FLU-11 | Corregir plan y bitácora sobre el PR #1 del juego: está cerrado sin fusionar, no «a medias» | hecho (2026-11-15; `INS-21`…`INS-27` pasan a descartados, la bitácora y [`02`](02-migracion-postgres-a-sqlite.md) apuntan a `INS-60`) |

## `0.3` «Base de datos»

Cierra con la fase 2 (SQLite) rehecha sobre el `main` actual del juego, las tareas de modo empaquetado del juego
hechas y el inventario [`06`](06-inventario-exclusiones.md) al día.

| Id | Tarea | Estado |
|---|---|---|
| INS-60 | Rehacer la fase 2 (SQLite) sobre `main` actual del juego: el PR #1 está cerrado sin fusionar y han aparecido `hasSome`, jsonb con operador de existencia, `pg_advisory_xact_lock` y más; con test de humo contra SQLite en el CI del juego (prop. 1) | pendiente |
| INS-61 | `INS-35`/`INS-36` más rutas empaquetadas: Modelfile y `uploads` (prop. 2) | pendiente |
| INS-62 | Inventario `06` al día: variables nuevas (`IA_REGISTRO`/`IA_CASOS` desactivadas), defectos de `env.ts`, `sync-item-catalog`, imágenes de 464 MB (prop. 3) | pendiente |
| INS-35 | Backend: `SYSTEM` del narrador incrustado en build; narrador con modelo base más `system` por petición tras `TARKOR_NARRADOR_BASE=1`; leer `TARKOR_NUM_THREAD`, `TARKOR_NUM_BATCH` y `TARKOR_NUM_CTX_NARRADOR` (`12`). Encargo: [issue #93](https://github.com/Zeldris/World-Maker-Fantasy/issues/93) del juego (2026-11-11). `TARKOR_MODELOS_SIN_PENSAR` sobra: el juego ya manda `think: false` | pendiente |
| INS-36 | Backend: CORS restringido y escucha solo en `127.0.0.1` en modo empaquetado; `TARKOR_IMAGENES_DIR` y versión fijada en el build. Encargo: el mismo issue #93 (2026-11-11) | pendiente |
| INS-37 | Menú del juego: «Rendimiento de la IA» solo si `window.__TARKOR__.abrirAjustes` es una función (contrato de `04`, 2026-11-04). Falta hacerlo en el juego e inyectar la función en `INS-41` | pendiente |

## `0.4` «Solidez»

Cierra con el E2E en el CI, dependencias vigiladas y el código del núcleo sin pánicos ni errores tragados.

| Id | Tarea | Estado |
|---|---|---|
| INS-63 | E2E (`app/e2e`) en el CI (prop. 4) | pendiente |
| INS-64 | Dependabot más `cargo audit` y `npm audit` (prop. 5) | hecho (2026-11-15; dependabot.yml (npm, cargo, acciones), job auditoria con cargo audit y npm audit; 12 avisos de RustSec arreglados, zip 9 y ruzstd 0.9; la extracción de zip 9 en Windows, por ver en el CI y en INS-8) |
| INS-65 | Ayudante de mutex sin pánico, partir `lib.rs` y no tragar errores (`carpetas.rs`, `App.tsx:38`) (prop. 6) | hecho (2026-11-15; lib.rs (1131 líneas) partido en 7 módulos sin cambiar comandos ni eventos; trait Bloquear sustituye los 15 lock().unwrap(); carpetas.rs avisa de los restos si falla la limpieza; los catch silenciados del frontal registran el fallo) |

## `0.5` «Marca»

Cierra con la marca de Tarkor en el asistente, accesible y con fuentes ligeras, y las imágenes colocadas.

| Id | Tarea | Estado |
|---|---|---|
| INS-56 | La marca de Tarkor en el asistente (de `UX-40` del juego): tokens `gold-*`, `stone-*`, `night-*` y `crystal-deep` en `estilos.css`, «TARKOR» en `.title-gold`, filo de oro, `h1` en Cinzel 700, azul solo para estados, fondo de madera. Espera a que `claude/marca-interfaz` del juego llegue a su `main`; iconos en `app/src-tauri/icons/` cuando existan las imágenes (E14). Absorbe la prop. 9: oro, tokens de escala, estilos en línea, errores y cargas comunes | pendiente |
| INS-66 | Accesibilidad: contraste del botón principal y textos tenues, bordes, `progressbar`, foco del `.seg`, tamaños para la Deck (prop. 7) | hecho (2026-11-15; contraste ≥4,5:1 con tokens (botón principal 7,4:1, textos tenues wood-300), bordes wood-400, progressbar en descargas y medidor, foco del .seg, letra 12 px y objetivos de 36 px; los leves 7, 8, 10 y 11 de la auditoría siguen en marca-y-estilos.md) |
| INS-67 | Fuentes: solo `latin` y `latin-ext` en woff2 (~200 KB) (prop. 8) | hecho (2026-11-15; app/src/fuentes.css con 12 @font-face woff2 latin y latin-ext; de 54 archivos a 12 (260 KB); test_fuentes.py) |
| INS-58 | Colocar las imágenes de [`13`](13-hoja-de-estilos-e-imagenes.md) cuando el generador las entregue (iconos, imágenes del NSIS, portada, hierro del riel, 1 MB como mucho). Antes, dos pasos de la usuaria (`13` §6): la sesión en GVIG (encargo sin rama, pendiente) y copiar la entrega a `entrega/`. Verlas en Windows al 100 % y 150 % y en la Deck queda con `INS-8`, `INS-51` e `INS-52` | pendiente |

## `0.6` «Publicar»

Cierra con el release publicado: instaladores y `SHA256SUMS`, firma y actualizador decididos, licencias confirmadas.

| Id | Tarea | Estado |
|---|---|---|
| INS-11 | Firma de código en Windows. Incluye la prop. 10: decidir firma y actualizador | pendiente |
| INS-41 | Integrar el build del juego (frontend, backend en bytecode, plantilla) en la app de Tauri. Pendiente: variante «El motor del juego se ha detenido» (`11`) cuando `MotorDetenido` diga qué proceso es | pendiente |
| INS-46 | Workflow de GitHub Actions que publica releases con instaladores y `SHA256SUMS` (`release.yml` pasa a llevar binarios) | pendiente |
| INS-12 | Licencia del juego (propuesta: todos los derechos reservados) y de este repo. Hecha la del repo (2026-11-05): MIT, `LICENSE` y `license` en `package.json` y `Cargo.toml` (`08`). Falta la del juego | pendiente |
| INS-15 | Confirmar licencias de modelos e imágenes. Revisada la de `llama3.1:8b` (2026-11-11, `08`); hecha la pantalla «Licencias y avisos» del instalador (2026-11-11, `11`). Falta: la misma pantalla en el juego, las licencias de las imágenes y comprobar las de los modelos al publicar | pendiente |

## `1.0` «Prueba real»

Cierra con todo probado en una Steam Deck y en Windows limpios (lo que depende del equipo de la usuaria).

| Id | Tarea | Estado |
|---|---|---|
| INS-7 | Narrador con `system` y `options` por petición sobre `llama3.1:8b`, comparado con `tarkor-narrador-llama31` ([`03`](03-ollama-y-modelos-ia.md)). Decidido el 2026-11-11: el narrador de Equilibrado y Máximo es `llama3.1:8b` en lugar de `qwen2.5:7b` (catálogo, `03`, `09`, `12`) | pendiente |
| INS-8 | Prueba en la Steam Deck y en un Windows limpio: descargas, memoria real por perfil, tokens por segundo, Vulkan frente a ROCm, calidad de Mínimo y Ligero; ajustar el catálogo. Comando: `cargo run --release -p tarkor-nucleo --example motor equilibrado` (`app/README.md`) | pendiente |
| INS-51 | En la Steam Deck (modo escritorio y como juego ajeno a Steam), con sus imágenes de biblioteca (bloque D de `13`): dónde las lee Steam y si el instalador puede copiarlas | pendiente |
| INS-52 | En un Windows 10 y un Windows 11 limpios, sin Node ni Ollama | pendiente |
| INS-53 | En un equipo de 8 GB: el perfil Ligero debe ser jugable | pendiente |
| INS-54 | Actualizar de una versión a otra sin perder partidas | pendiente |
| INS-55 | Desinstalar conservando y sin conservar partidas | pendiente |

## Después, sin versión

Tareas del flujo de trabajo ([`AGENTS.md`](../AGENTS.md), [bitácora](records/traspaso.md), [runbook](runbooks/skills-y-modelos.md)) que no cierran ninguna versión del instalador.

| Id | Tarea | Estado |
|---|---|---|
| FLU-2 | Piloto de [Galivelop-workflow](https://github.com/Zeldris/galivelop-workflow) v0.2.0 (scripts, skills, ganchos, `AGENTS.md`, una sola CI). Hecho: aplicado con el check en verde, `doctor.py` sin FAIL, revisión y [retro](records/retro-2026-10-22-piloto-galivelop.md). Falta: la CI de GitHub en verde (sin cuota; mientras, `FLU-3`) y el [registro del piloto](records/piloto-galivelop-workflow.md) cerrado | en curso |
| FLU-9 | `/gw-update` a Galivelop-workflow v0.6.0 (pasando por la 0.5.2): scripts, skills, ganchos, `check.yml`, agente `gw-worker`, ganchos `PreToolUse` de Read y `Stop`; `AGENTS.md` fusionado a mano; `REVIEW.md` con dos reglas nuevas. Parche local en `test_measure.py` (la 0.6.1 lo sobrescribe). Falta: CI en verde y las tres fases antes de `main` | en curso |

## Notas

- **Pendiente de máquina concreta:** `INS-7`, `INS-8` y la `1.0` necesitan la Steam Deck o un Windows limpio.
  Lo marcado «pendiente de `INS-8`» en las filas de `0.1` (Windows, Deck, escritorio limpio) se comprueba allí.
- **Juego:** tras cambiar `schema.prisma` hay que correr `npm run schema:sqlite` (un test y el CI lo exigen).
- **CI de GitHub:** sin cuota desde octubre; `app.yml` y el CI con Rust 1.94.1 no han corrido allí (`FLU-6`, `FLU-7`).
  Mientras, `ci-local.py` (`FLU-3`) y el check en local.
