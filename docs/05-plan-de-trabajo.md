# Plan de implementación

**Estado: en marcha desde el 2026-09-28.** Sustituye al checklist anterior. Ordenado por riesgo: lo
que puede tumbar el plan (empaquetar el backend, Ollama portable, velocidad en la Deck) se prueba
primero, antes de invertir en la migración de la base de datos.

Dónde se trabaja cada fase:

- **Este repo (público):** envoltorio Tauri, asistente de primer arranque, gestión de sidecars.
- **Repo del juego (privado):** migración a SQLite, recorte de funcionalidad, cambios pequeños para
  el modo empaquetado, CI de build.

Marcar cada punto al terminarlo. Cada tarea tiene su identificador `INS-<fase><n>` (la fase 0 va
sin el 0: `INS-1` es la antigua 0.1, y por eso no admite más de nueve tareas: lo nuevo entra en la
fase que toque), que nombran los commits y la [bitácora](records/traspaso.md);
las del flujo de trabajo llevan `FLU-n` y van en su [sección](#flujo-de-trabajo).

## Dónde lo dejamos (2026-09-28)

**Hecho y en `main` de este repo:** fases `INS-1`…`INS-6` (asistente, detección de equipo, catálogo de
perfiles, motor de IA real, backend compilado a bytecode), con pruebas de punta a punta.

**A medias — fase 2 en el repo del juego**, rama `claude/instalador-empaquetado`,
[PR #1](https://github.com/Zeldris/World-Maker-Fantasy/pull/1), **sin fusionar**:

- Código hecho: el backend funciona sobre Postgres y sobre SQLite. En local, la batería completa
  pasa igual en los dos (2710/2711; el fallo es un test ya intermitente en `main`).
- CI nuevo (Postgres+pgvector y SQLite). Primera ejecución: SQLite 2710/2711; Postgres falló al
  crear la extensión (`prisma db execute` sin `--schema`), ya corregido en el último commit.
  **Falta ver ese CI en verde.**
- Pendiente antes de fusionar:
  1. Dos tests de `routes/turn.integration.test.ts` fallan a veces con la batería completa, en
     Postgres y en SQLite: "OrdenProduccion … racion-carne-ahumada" y "P3.2 … retoma solo el
     viaje" (sondea 15 s a que termine un viaje reanudado). Pasan siempre al correr el fichero
     solo. Buscar la causa (orden entre ficheros o tiempos), no reintentarlos.
  2. `lib/prisma.test.ts`: endurecer el test para que la transacción "tardía" coincida con otra
     abierta (con el test actual, la versión anterior del arreglo también pasaría).
- Nota para el día a día del juego: tras cambiar `schema.prisma` hay que correr
  `npm run schema:sqlite` (un test y el CI lo exigen).

**Siguiente:** cerrar lo de arriba y fusionar; después fase 3 (modo empaquetado del juego) y
fase 4 (backend dentro de la app y CI de releases). `INS-7`, `INS-8` y la fase 5 necesitan probar en la
Steam Deck o en Windows: `cargo run --release -p tarkor-nucleo --example motor equilibrado`
(ver `app/README.md`).

## Fase 0 — Esqueleto y prueba de concepto

Objetivo: demostrar que el patrón completo funciona en Windows y en la Steam Deck.

- [x] **INS-1** Proyecto Tauri v2 en `app/` con el asistente (React + Vite + TypeScript) usando los
  tokens visuales del juego. Pantallas según [`11`](11-diseno-del-frontal.md).
- [x] **INS-2** Detección de equipo en Rust (`sysinfo`, gráfica por plataforma) y cálculo de perfiles
  de [`09`](09-deteccion-de-equipo-y-perfiles.md), con tests unitarios.
- [x] **INS-3** `config.json` en la carpeta de datos: al abrir, asistente si no está completado.
- [x] **INS-3b** Catálogo de modelos y perfiles en JSON (con perfil Mínimo para que cualquiera pueda
  probar) y ajustes de rendimiento de Ollama calculados por equipo (ver
  [`12`](12-catalogo-y-rendimiento.md)).
- [x] **INS-4** Gestor de sidecars en Rust: puerto libre, arrancar y parar procesos, esperar al
  health-check, un reinicio automático, parada garantizada al cerrar.
- [x] **INS-5** Ollama portable: descarga de la versión fijada (SHA256), arranque aislado
  (`OLLAMA_HOST`, `OLLAMA_MODELS`), descarga de modelos con progreso vía `/api/pull`.
- [x] **INS-6** Prueba de empaquetado del backend compilado a bytecode (camino A de
  [`10`](10-proteccion-del-codigo-y-build.md)): funciona con el backend real contra Postgres
  (lecturas, crear partida, `FOR UPDATE`). Herramienta en `herramientas/empaquetar-backend.mjs`.
  Pendiente para después de la fase 2: repetirla sobre SQLite y probar Prisma sin motor nativo
  (`queryCompiler` + adaptador SQLite).
- [ ] **INS-7** Narrador con `system` + `options` por petición sobre `llama3.1:8b`: comparar con
  `tarkor-narrador-llama31` (ver [`03`](03-ollama-y-modelos-ia.md)). Decidido con la usuaria el
  2026-11-11: el narrador de Equilibrado y Máximo es `llama3.1:8b`, el mismo que el juego, en lugar de
  `qwen2.5:7b` (catálogo, `03`, `09`, `12`; Máximo ya no cabe en la Deck, ver `09`).
- [ ] **INS-8** Prueba en la Steam Deck y en un Windows limpio: tiempos de descarga, memoria real
  de cada perfil, tokens por segundo, Vulkan frente a ROCm en la Deck, calidad de narración de
  Mínimo y Ligero. Ajustar el catálogo con lo medido.

## Fase 1 — Decisiones pendientes

Se pueden resolver en paralelo a la fase 0. Ver la tabla del [README](../README.md).

- [ ] **INS-11** Firma de código en Windows.
- [ ] **INS-12** Licencia del juego (propuesta: todos los derechos reservados) y de este repo. Hecha la del
  repo (2026-11-05): MIT, con `LICENSE` en la raíz y `license` en `package.json` y los `Cargo.toml` (ver `08`).
  Falta la del juego.
- [x] **INS-13** Perfiles pequeños: se ofrecen Mínimo y Ligero con modelos Apache 2.0, avisando del
  resultado (calidad a confirmar en `INS-8`).
- [x] **INS-14** (2026-10-25) Perfiles por encima del máximo seguro: se pueden elegir con aviso y
  confirmación en la tarjeta, sin interruptor (ver `09` y `11`). Implementado el mismo día en el
  asistente y en Ajustes (`Tarjetas`, `pideConfirmar`/`bloqueado` en `app/src/tipos.ts`).
- [ ] **INS-15** Confirmar licencias de modelos e imágenes. Revisada la de `llama3.1:8b` (2026-11-11, ver
  `08`). Hecha la pantalla del instalador (2026-11-11): «Licencias y avisos» desde el paso 2 y Ajustes, con
  «Built with Llama», el aviso de Meta, la política de uso (copiar enlace) y los textos completos de Llama 3.1,
  MIT (Ollama) y Apache 2.0 en `app/src/licencias/` (`pantallaLicencias.tsx`, ver `11`). Falta: la misma
  pantalla en el juego, las licencias de las imágenes y comprobar las de los modelos al publicar.

## Fase 2 — Migración a SQLite (repo del juego) — código hecho, PR #1 sin fusionar

Ver [`02`](02-migracion-postgres-a-sqlite.md). Sin romper el modo de desarrollo con Postgres.

- [x] **INS-21** Proveedor de base de datos por variable de entorno y generación de
  `schema.sqlite.prisma` en el build, con test de sincronía.
- [x] **INS-22** Embeddings en JSON + similitud coseno en JS (`retrieval.ts`, `worldFacts.ts`).
- [x] **INS-23** `lockRowForUpdate()` con mutex en memoria cuando el proveedor es SQLite.
- [x] **INS-24** Los 16 campos de lista a `Json` (sin capa de conversión: un `Json` con un array se
  lee y escribe igual); los `push` reescritos con `anadirNpcRetirado`.
- [x] **INS-25** `mode: 'insensitive'` y `skipDuplicates`.
- [x] **INS-26** Batería de tests del backend pasando contra SQLite.
- [x] **INS-27** Script de build de la base de datos plantilla (migrada + catálogo + lore indexado).

## Fase 3 — Modo empaquetado del juego (repo del juego)

Ver [`06`](06-inventario-exclusiones.md).

- [x] **INS-31** (2026-10-26) Frontend: URL del backend en tiempo de ejecución (`api.ts`). Hecho en el repo del
  juego, rama `claude/ins-31-url-backend` ([PR #78](https://github.com/Zeldris/World-Maker-Fantasy/pull/78)),
  **en `main` del juego** (`b76c66b2`, sin PR y con CI local por la cuota agotada, `QA-215`; retro `QA-259`…`QA-261`
  aplicada allí): `apiBaseUrl()` con el contrato
  `window.__TARKOR__.apiUrl` de [`04`](04-empaquetado-tauri.md); todas las URLs de `api.ts` pasan por ella; 8 tests.
- [x] **INS-32** (2026-10-26) Frontend: fuentes Cinzel e Inter en local. Ya estaba hecho en `main` del juego por
  su tarea `BAS-1` (`4a150259`, 2026-10-25): `frontend/src/assets/fonts/fonts.css` con Cinzel e Inter variables
  (latin y latin-ext, de `@fontsource-variable` 5.3.0) y sus `LICENSE-*.txt` (OFL, ver `08`); en `frontend` no
  queda ninguna petición a Google Fonts. Sin cambios en el juego.
- [x] **INS-33** (2026-10-27) Frontend: quitar `ImagePromptSlot`; deshabilitar "Crear desde cero" como "en
  construcción"; revisar el texto de `ComingSoon.tsx`. Decidido por la usuaria (2026-10-26): en el juego
  empaquetado (`window.__TARKOR__` presente) desaparece todo lo de admin: el enlace de `Home.tsx`, las rutas
  `/admin/*` y `ImagePromptSlot` en cualquier sitio (ya estaba tras el modo desarrollador, `CFG-33` del juego); en
  desarrollo sigue igual. «Crear desde cero» deshabilitada y el texto de `ComingSoon.tsx` («en construcción para
  futuras versiones») cambian en todas partes. **En `main` del juego** (`aae4a755`, sin PR, CI local, `QA-215`;
  retro aprobada por la usuaria, `QA-262`…`QA-265`): `esEmpaquetado()` en `frontend/src/lib/empaquetado.ts`, que
  comparte la lectura de `window.__TARKOR__` con `apiBaseUrl()`; 9 tests nuevos que fallan sin el arreglo; `tsc`,
  `oxlint` y vitest (798) en verde. El juego no tiene E2E de frontend.
- [x] **INS-34** (2026-10-27) Backend: build sin rutas ni servicios de curación (ruta de image-prompt, orquestador
  cloud, `LiveTeacherCapture`, scripts). **En `main` del juego** (`c7f0e5f9`, sin PR, CI local, `QA-215`; retro
  aprobada por la usuaria, `QA-266`): esbuild sustituye `process.env.TARKOR_EMPAQUETADO` por `"1"` (`define`) y la
  ruta `POST /world/:slug/image-prompt` y la captura en vivo se cargan con `import()` dinámico en la rama que queda
  muerta (plegarla exige `minify` o `minifySyntax`); `empaquetado.test.ts` y `world.test.ts` fallan sin el arreglo.
  Aquí, `herramientas/empaquetar-backend.mjs` lleva el `define` y se para si el `metafile` trae `lib/aiProviders/`,
  `imagePromptGenerator`, `liveTeacherCapture` o scripts de curación (pasa con la rama, para con el `main` anterior).
  CI local: 3958 tests de backend y 798 de frontend; el test de navegador de `tools/qa`, que allí se saltó por la
  descarga de Chromium, pasado desde aquí (382 tests de `tools/qa`).
- [ ] **INS-35** Backend: `SYSTEM` del narrador incrustado en build; narrador con modelo base +
  `system` por petición detrás de variable de entorno; leer `TARKOR_NUM_THREAD`,
  `TARKOR_NUM_BATCH` y `TARKOR_NUM_CTX_NARRADOR` (ver `12`). Encargo: issue [#93](https://github.com/Zeldris/World-Maker-Fantasy/issues/93) del juego (2026-11-11), con
  `INS-36`; el modo base va detrás de `TARKOR_NARRADOR_BASE=1`. `TARKOR_MODELOS_SIN_PENSAR` sobra: el juego ya
  manda `think: false` en todas las peticiones.
- [ ] **INS-36** Backend: CORS restringido y escucha solo en `127.0.0.1` en modo empaquetado; rutas de
  imágenes y datos por variable de entorno (`TARKOR_IMAGENES_DIR`) y versión fijada en el build. Encargo: el issue
  [#93](https://github.com/Zeldris/World-Maker-Fantasy/issues/93) del juego, con `INS-35` (2026-11-11).
- [ ] **INS-37** Menú del juego: enlace a Ajustes → Rendimiento de la IA. Contrato fijado (2026-11-04, `04`):
  «Rendimiento de la IA» en el menú solo si `window.__TARKOR__.abrirAjustes` es una función, y la llama al pulsarlo.
  Falta: hacerlo en el juego (encargo a una sesión del juego) e inyectar la función en `INS-41`.

## Fase 4 — Empaquetado completo y CI

Ver [`04`](04-empaquetado-tauri.md) y [`10`](10-proteccion-del-codigo-y-build.md).

- [ ] **INS-41** Integrar el build del juego (frontend + backend en bytecode + plantilla) en la app de
  Tauri. Pendiente: pantalla del motor detenido: variante "El motor del juego se ha detenido" (docs/11), cuando
  `MotorDetenido` diga qué proceso es.
- [x] **INS-42** (2026-10-26) Asistente real de punta a punta: descargas y comprobaciones de verdad; calentar el
  narrador al arrancar. Incluye la autopausa al perder la red con reanudación sola y la velocidad
  de la narración de prueba (ronda de diseño del 2026-10-25). Si calentar el narrador o una narración fallan por
  falta de memoria (`serve` sigue vivo y la pantalla del motor detenido no sale), ofrecer el perfil más ligero
  (hallazgo de la revisión de `INS-43`).
  Hecho del trozo A (2026-10-26, autopausa): el núcleo clasifica los errores de Ollama
  (`Error::es_de_red`, `sin_memoria`; `motor::Error::es_de_red`), Tauri devuelve `ErrorIa {mensaje, red, sinMemoria}` en
  `instalar_motor` y `descargar_modelos`, y la Descarga espera con «Esperando conexión» y reintenta sola a los 5, 10,
  20, 40 y 60 s (con «Pausar» y «Reintentar ahora»); E2E con `FALSO_CORTES_PULL`.
  Hecho del trozo B (2026-10-26): comando `calentar_narrador` (Tauri) y `calentarNarrador` en la
  `Api`; al entrar en el juego se arranca el motor si no corre y se calienta el narrador («Preparando el narrador…» /
  «El narrador está listo»), con el aviso y «Cambiar a un perfil más ligero» si falta memoria y una línea discreta en
  otro error; la Comprobación sugiere un perfil más ligero bajo 3 palabras/s (`PALABRAS_LENTAS`); tests de vitest y
  E2E (`asistente`, `rendimiento`). Revisión del trozo B: el umbral de lento se mide sin redondear (y una medida de 0 no
  sugiere nada) y `asegurar_motor` arranca el motor solo si no corre bajo un candado común con `arrancar_motor`, para que
  dos arranques a la vez no se pisen.
  Hecho del trozo C (2026-10-26): la misma autopausa al cambiar de perfil en Ajustes y en Reparar. `cambiar_perfil` y
  `reparar` devuelven `ErrorIa` (el corte llega con `red: true`), el gancho común `useEsperaRed` (`app/src/esperaRed.ts`:
  escalera de esperas, cuenta atrás, «Reintentar ahora» y limpieza al desmontar) lo usan la Descarga, Ajustes y Reparar,
  y «Pausar» cancela también la espera; tests de vitest, y el E2E `rendimiento` corta el primer pull del cambio de perfil
  (`FALSO_CORTES_PULL`). Con el trozo C, `INS-42` queda cerrada.
- [x] **INS-43** (2026-10-25) Ajustes → Rendimiento de la IA (con uso de la gráfica vía `/api/ps`) y pantalla de
  motor detenido. Decidido el 2026-10-25 (ver `11`): frase de dónde corre la IA y memoria real; cambiar de perfil
  descarga, reinicia el motor y ofrece borrar lo que sobra; "Copiar informe" con "Ver detalles"; un hilo de Rust
  vigila el motor y avisa con un evento. Hecho: núcleo (`ollama::resumen_uso`, `sobrantes`, `informe.rs` con
  `anonimizar`, marca de arranque en el registro y `sin_memoria` desde ella), comandos `uso_ia`, `cambiar_perfil`,
  `modelos_sobrantes`, `borrar_modelos`, `informe`, `motor_detenido` y `reintentar_motor`, hilo de vigilancia con
  el evento `motor-detenido`; frontal: línea de uso cada 5 s, cambio de perfil con progreso y pausa, borrar
  sobrantes, `CopiarInforme` y la pantalla del motor detenido (Reintentar, "Cambiar a un perfil más ligero");
  tests de vitest y E2E `app/e2e/rendimiento.e2e.mjs`. Pendiente de `INS-8`: en Windows, la vigilancia y el
  reinicio del motor, el informe con rutas de Windows (`anonimizar`) y la línea de uso con una gráfica real.
- [x] **INS-44** NSIS: castellano, instalación por usuario, desinstalador con las dos casillas. Decidido el
  2026-11-11 (ver `04`): plantilla NSIS propia (`app/src-tauri/windows/installer.nsi`), copia de la de Tauri
  2.12.0 con la casilla de Tauri cambiada por las dos de `07`; los ganchos (`installerHooks`) no pueden añadir
  una casilla a la página de confirmación. Lo borra `tarkor.exe --desinstalar [--partidas] [--ia]`, llamado antes
  de quitar los archivos (lee `carpetaIa` de `config.json`); el tamaño de la casilla, de
  `tarkor.exe --info-desinstalar <ini>`. Pasos: (a) núcleo y opciones del ejecutable; (b) plantilla y test
  que para si cambia la versión de `@tauri-apps/cli`; (c) CI de Windows que construye el `.exe`, instala en
  silencio, siembra datos y desinstala con `/BORRARPARTIDAS` y `/BORRARIA`.
  La plantilla instala en `%LOCALAPPDATA%\Programs\Tarkor` (`07`; la de Tauri usaría `%LOCALAPPDATA%\Tarkor`,
  que es de la IA y los registros). Hecho el 2026-11-11: (a), (b) y (c), el job `instalador-windows` de
  `app.yml` con `tools/qa/desinstalar-windows.ps1`, en verde a la primera (el `.exe` queda como artefacto). Pendiente de `INS-8`: verlo en pantalla (casillas, tamaño).
- [x] **INS-45** AppImage (+ `.deb` opcional) compilado en Ubuntu 22.04. Incluye «Borrar datos del juego» en
  Ajustes (Linux, `07`), con el mismo borrado del núcleo que el desinstalador de `INS-44`; el CI de Linux
  construye el `.AppImage` y el `.deb`. Diseño del diálogo decidido el 2026-11-11 (ver `07`): dos casillas, «Borrar»
  desactivado sin ninguna, para el motor, borra y cierra.
  Hecho el 2026-11-11: el job `paquetes-linux` de `app.yml` construye el `.AppImage` y el `.deb` en Ubuntu 22.04 y
  comprueba que los dos arrancan (en verde a la primera; los dos quedan como artefacto); órdenes `plataforma`,
  `info_borrado`, `borrar_datos` y `cerrar_app`, y el diálogo `BorrarDatos` en Ajustes con vitest y el paso 7 de
  `rendimiento.e2e.mjs`. Pendiente de `INS-8`: probar el `.AppImage` en la Steam Deck y en un escritorio limpio.
- [ ] **INS-46** Workflow de GitHub Actions en el repo privado que publica releases con `SHA256SUMS`
  en este repo.
- [ ] **INS-47** Pantalla "Licencias de terceros" generada en el build.
- [ ] **INS-56** La marca de Tarkor en el asistente (de `UX-40` del juego, decidido con la usuaria el
  2026-11-11): tokens `gold-*`, `stone-*`, `night-*` y `crystal-deep` en `app/src/estilos.css`; «TARKOR» del riel en
  `.title-gold` (Cinzel 900), filo de oro en el paso activo y el riel, `.gold-hairline`, `h1` en Cinzel 700; el azul
  (`accent-*`) solo para estados. **Fondo de madera**, como dentro del juego. Espera a que la rama
  `claude/marca-interfaz` del juego (`docs/producto/diseno-interfaz-marca.md`) llegue a su `main`. Aparte, cuando
  existan las imágenes (fila E14 de ese documento): iconos de la app en `app/src-tauri/icons/`.
- [x] **INS-48** (2026-10-25) Carpeta del motor y los modelos elegible antes de descargar y movible desde Ajustes
  (`OLLAMA_MODELS`); espacio necesario frente a libre en cada tarjeta, con la descarga bloqueada si no
  cabe (ver `07` y `11`). Hecho: `carpetaIa` en `config.json`, `nucleo/src/carpetas.rs`
  (`espacio_libre_mb`, `mover_carpeta`: renombra o copia y borra), `perfiles::evaluar` con el disco
  de la carpeta aparte, comando `cambiar_carpeta_ia` (`<elegida>/Tarkor IA`, para y rearranca el
  motor) y selector nativo (`tauri-plugin-dialog` 2). Pendiente de `INS-8`: mover a la tarjeta SD de
  la Deck y entre discos en Windows (el test de copia fallida solo corre en Unix).
- [x] **INS-49** (2026-10-25) "Reparar": volver a comprobar la suma del motor y pedir de nuevo los modelos, desde
  Ajustes y desde la comprobación final. Hecho: `motor::instalar` guarda la suma de cada archivo en `.completo`
  y `motor::reparar` las comprueba y reinstala si falla alguna; `nucleo/src/modelos.rs` suma las capas de cada
  manifiesto de Ollama y borra las dañadas; comando `reparar` (para el motor, repara, borra capas, rearranca y
  pide los modelos del perfil) y componente `Reparar` en Ajustes y en las filas «Motor de IA» y «Modelos» de la
  comprobación. Pendiente de `INS-8`: reparar en Windows (archivos bloqueados por el motor) y en la Deck.

## Fase 5 — Prueba real

- [ ] **INS-51** En la Steam Deck (modo escritorio y como juego ajeno a Steam).
- [ ] **INS-52** En un Windows 10 y un Windows 11 limpios, sin Node ni Ollama.
- [ ] **INS-53** En un equipo de 8 GB: el perfil Ligero debe ser jugable.
- [ ] **INS-54** Actualizar de una versión a otra sin perder partidas.
- [ ] **INS-55** Desinstalar conservando y sin conservar partidas.

## Flujo de trabajo

Cómo trabaja Claude en este repo: [`AGENTS.md`](../AGENTS.md), la [bitácora](records/traspaso.md), los
ganchos, `.claude/gw/scripts`, `tools/qa` y las skills ([runbook](runbooks/skills-y-modelos.md)).

- [x] **FLU-1** (2026-10-21) Traer de Tarkor su flujo de trabajo y sus skills, adaptados al instalador: `CLAUDE.md`,
  [`REVIEW.md`](../REVIEW.md), bitácora, ganchos de sesión y de antes de subir, `tools/qa` con sus
  tests (job `qa` de la CI) y las skills de `.claude/skills/` con sus notas para el instalador.
  Hecho, con `/code-review` (dos rondas), `/opt-tokens` y la
  [retro](records/retro-2026-10-21-flujo.md), cuyas cuatro propuestas se aplicaron.
- [ ] 🚧 **FLU-2** (2026-10-22) Piloto de [Galivelop-workflow](https://github.com/Zeldris/galivelop-workflow) v0.2.0:
  sus scripts (`.claude/gw/scripts/`), skills, ganchos, `AGENTS.md` con `CLAUDE.md` que lo importa, y una sola CI
  (Linux, Windows y `qa` con el pre-commit de la rama base). Lo propio del instalador queda en `.claude/gw.json`,
  `.claude/gw/*.md`, `tools/qa/{en-app,tests-app}.sh`, `tools/dev/instalar-entorno.sh` y `tools/banco/`. Hecho:
  aplicado con el check en verde, la prueba del paso 6 de `aplicar.md` y `doctor.py` sin FAIL; revisión de código
  y [retro](records/retro-2026-10-22-piloto-galivelop.md). Falta: la CI de GitHub en verde (agotada; mientras,
  `FLU-3`) y el [registro del piloto](records/piloto-galivelop-workflow.md) cerrado.
- [x] **FLU-3** (2026-10-22) `ci-local.py` (retro del piloto; hoy en `.claude/gw/scripts/`): con la CI de GitHub agotada, corre en local
  los pasos de los jobs de Ubuntu del CI (los lee del workflow, no los copia) y, con `--apuntar`, deja
  fecha, commit y resultado en [`ci-local.md`](records/ci-local.md). El job de Windows sale como «sin cubrir».
- [x] **FLU-4** (2026-10-25) `/gw-update` a Galivelop-workflow v0.3.0: scripts, esquema, skills y ganchos al día;
  el CI conserva sus jobs (el cambio de `ciInstall` no le toca) y `REVIEW.md` gana dos reglas de la plantilla.
- [x] **FLU-5** (2026-10-26, retro de `INS-42`) `cargo fmt` del workspace en commits aparte (`a27489f` y `9b0035c`, a
  120 columnas y `use_small_heuristics = "Max"` en `app/rustfmt.toml`, el estilo del resto del repo) y `cargo fmt --all --check` en `check` de
  `.claude/gw.json` y en el CI (con `rustfmt` y `clippy` declarados en el toolchain). Los commits de formato van
  en `.git-blame-ignore-revs`, que `tools/dev/instalar-entorno.sh` activa.
- [x] **FLU-6** (2026-10-26, retro de `FLU-5`) `app/rust-toolchain.toml` fija Rust 1.94.1 (con `rustfmt`, `clippy` y
  el destino de Windows) para que local, el pre-push y el CI formateen y avisen igual; el CI y
  `tools/dev/instalar-entorno.sh` lo instalan con `rustup toolchain install` desde `app/`. Subir de versión es un
  commit a mano (con el `rust-version` de `[workspace.package]` en `app/Cargo.toml`, que heredan los miembros y
  compara `tools/qa/tests/test_version_rust.py`).
  **Pendiente:** el CI de GitHub con la versión fijada no ha corrido (sin cuota); lo comprueba la próxima subida con
  cuota, en la pestaña Actions, y el job de Windows con `INS-8`.
- [x] **FLU-7** (2026-11-04) `/gw-update` a Galivelop-workflow v0.5.0, con las rutas en inglés (`docs/records/`,
  `reviewed.txt`), `commitNext` y commits sin firmas del agente (`agentSignatures: false`). El CI se parte en
  `check.yml` (del flujo: el `check` de `.claude/gw.json`) y `app.yml` (del instalador: `npm test`, el build,
  `cargo test` en Linux y Windows y la compilación para Windows); el job `qa` y los tests de los scripts de las skills
  salen del CI del proyecto (los prueba el repo del flujo). `tools/qa` deja `ci-local.py` y sus tests, que ya trae el
  flujo; `instalar-entorno.sh` instala con `sudo -n` si no es root. `REVIEW.md` etiqueta cada regla con
  `(check: …)` o `(criterio)`. **Pendiente:** el CI de GitHub sigue sin cuota; `app.yml` no ha corrido allí.
- [x] **FLU-8** (2026-11-11) `/gw-update` a Galivelop-workflow v0.5.1 (parche): scripts, skills, ganchos y
  `check.yml` al día; `worktree.baseRef: "head"` en `settings.json`. `REVIEW.md` gana la regla de `## Tests` (un doble
  pide también una prueba de humo contra el real) y el docstring de `test_herramientas_con_test.py` usa los nombres
  nuevos de los scripts. Retro antes de `main` (P1 a P3, `docs/records/retro-2026-11-11-flu8.md`); fusionado en
  `main` por el PR #13 (2026-11-11), con la confirmación de la usuaria y el CI en verde.
