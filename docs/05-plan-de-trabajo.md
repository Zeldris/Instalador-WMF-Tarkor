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
fase que toque), que nombran los commits y la [bitácora](registros/traspaso.md);
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
- [ ] **INS-7** Narrador con `system` + `options` por petición sobre `qwen2.5:7b`: comparar con
  `tarkor-narrador` (ver [`03`](03-ollama-y-modelos-ia.md)).
- [ ] **INS-8** Prueba en la Steam Deck y en un Windows limpio: tiempos de descarga, memoria real
  de cada perfil, tokens por segundo, Vulkan frente a ROCm en la Deck, calidad de narración de
  Mínimo y Ligero. Ajustar el catálogo con lo medido.

## Fase 1 — Decisiones pendientes

Se pueden resolver en paralelo a la fase 0. Ver la tabla del [README](../README.md).

- [ ] **INS-11** Firma de código en Windows.
- [ ] **INS-12** Licencia del juego (propuesta: todos los derechos reservados) y de este repo.
- [x] **INS-13** Perfiles pequeños: se ofrecen Mínimo y Ligero con modelos Apache 2.0, avisando del
  resultado (calidad a confirmar en `INS-8`).
- [x] **INS-14** (2026-10-25) Perfiles por encima del máximo seguro: se pueden elegir con aviso y
  confirmación en la tarjeta, sin interruptor (ver `09` y `11`). Implementado el mismo día en el
  asistente y en Ajustes (`Tarjetas`, `pideConfirmar`/`bloqueado` en `app/src/tipos.ts`).
- [ ] **INS-15** Confirmar licencias de modelos e imágenes.

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

- [ ] **INS-31** Frontend: URL del backend en tiempo de ejecución (`api.ts`).
- [ ] **INS-32** Frontend: fuentes Cinzel e Inter en local.
- [ ] **INS-33** Frontend: quitar `ImagePromptSlot`; deshabilitar "Crear desde cero" como "en
  construcción"; revisar el texto de `ComingSoon.tsx`.
- [ ] **INS-34** Backend: build sin rutas ni servicios de curación (ruta de image-prompt, orquestador
  cloud, `LiveTeacherCapture`, scripts).
- [ ] **INS-35** Backend: `SYSTEM` del narrador incrustado en build; narrador con modelo base +
  `system` por petición detrás de variable de entorno; leer `TARKOR_NUM_THREAD`,
  `TARKOR_NUM_BATCH`, `TARKOR_NUM_CTX_NARRADOR` y `TARKOR_MODELOS_SIN_PENSAR` (ver `12`).
- [ ] **INS-36** Backend: CORS restringido y escucha solo en `127.0.0.1` en modo empaquetado; rutas de
  imágenes y datos por variable de entorno.
- [ ] **INS-37** Menú del juego: enlace a Ajustes → Rendimiento de la IA.

## Fase 4 — Empaquetado completo y CI

Ver [`04`](04-empaquetado-tauri.md) y [`10`](10-proteccion-del-codigo-y-build.md).

- [ ] **INS-41** Integrar el build del juego (frontend + backend en bytecode + plantilla) en la app de
  Tauri. Pendiente: pantalla del motor detenido: variante "El motor del juego se ha detenido" (docs/11), cuando
  `MotorDetenido` diga qué proceso es.
- [ ] **INS-42** Asistente real de punta a punta: descargas y comprobaciones de verdad; calentar el
  narrador al arrancar. Incluye la autopausa al perder la red con reanudación sola y la velocidad
  de la narración de prueba (ronda de diseño del 2026-10-25). Si calentar el narrador o una narración fallan por
  falta de memoria (`serve` sigue vivo y la pantalla del motor detenido no sale), ofrecer el perfil más ligero
  (hallazgo de la revisión de `INS-43`).
- [x] **INS-43** (2026-10-25) Ajustes → Rendimiento de la IA (con uso de la gráfica vía `/api/ps`) y pantalla de
  motor detenido. Decidido el 2026-10-25 (ver `11`): frase de dónde corre la IA y memoria real; cambiar de perfil
  descarga, reinicia el motor y ofrece borrar lo que sobra; "Copiar informe" con "Ver detalles"; un hilo de Rust
  vigila el motor y avisa con un evento. Hecho: núcleo (`ollama::resumen_uso`, `sobrantes`, `informe.rs` con
  `anonimizar`, marca de arranque en el registro y `sin_memoria` desde ella), comandos `uso_ia`, `cambiar_perfil`,
  `modelos_sobrantes`, `borrar_modelos`, `informe`, `motor_detenido` y `reintentar_motor`, hilo de vigilancia con
  el evento `motor-detenido`; frontal: línea de uso cada 5 s, cambio de perfil con progreso y pausa, borrar
  sobrantes, `CopiarInforme` y la pantalla del motor detenido (Reintentar, "Cambiar a un perfil más ligero");
  tests de vitest y E2E `app/e2e/rendimiento.e2e.mjs`.
- [ ] **INS-44** NSIS: castellano, instalación por usuario, desinstalador con las dos casillas.
- [ ] **INS-45** AppImage (+ `.deb` opcional) compilado en Ubuntu 22.04.
- [ ] **INS-46** Workflow de GitHub Actions en el repo privado que publica releases con `SHA256SUMS`
  en este repo.
- [ ] **INS-47** Pantalla "Licencias de terceros" generada en el build.
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

Cómo trabaja Claude en este repo: [`AGENTS.md`](../AGENTS.md), la [bitácora](registros/traspaso.md), los
ganchos, `.claude/gw/scripts`, `tools/qa` y las skills ([runbook](runbooks/skills-y-modelos.md)).

- [x] **FLU-1** (2026-10-21) Traer de Tarkor su flujo de trabajo y sus skills, adaptados al instalador: `CLAUDE.md`,
  [`REVIEW.md`](../REVIEW.md), bitácora, ganchos de sesión y de antes de subir, `tools/qa` con sus
  tests (job `qa` de la CI) y las skills de `.claude/skills/` con sus notas para el instalador.
  Hecho, con `/code-review` (dos rondas), `/opt-tokens` y la
  [retro](registros/retro-2026-10-21-flujo.md), cuyas cuatro propuestas se aplicaron.
- [ ] 🚧 **FLU-2** (2026-10-22) Piloto de [Galivelop-workflow](https://github.com/Zeldris/galivelop-workflow) v0.2.0:
  sus scripts (`.claude/gw/scripts/`), skills, ganchos, `AGENTS.md` con `CLAUDE.md` que lo importa, y una sola CI
  (Linux, Windows y `qa` con el pre-commit de la rama base). Lo propio del instalador queda en `.claude/gw.json`,
  `.claude/gw/*.md`, `tools/qa/{en-app,tests-app}.sh`, `tools/dev/instalar-entorno.sh` y `tools/banco/`. Hecho:
  aplicado con el check en verde, la prueba del paso 6 de `aplicar.md` y `doctor.py` sin FAIL; revisión de código
  y [retro](registros/retro-2026-10-22-piloto-galivelop.md). Falta: la CI de GitHub en verde (agotada; mientras,
  `FLU-3`) y el [registro del piloto](registros/piloto-galivelop-workflow.md) cerrado.
- [x] **FLU-3** (2026-10-22) `tools/qa/ci-local.py` (retro del piloto): con la CI de GitHub agotada, corre en local
  los pasos de los jobs de Ubuntu de `comprobar.yml` (los lee del workflow, no los copia) y, con `--apuntar`, deja
  fecha, commit y resultado en [`ci-local.md`](registros/ci-local.md). El job de Windows sale como «sin cubrir».
- [x] **FLU-4** (2026-10-25) `/gw-update` a Galivelop-workflow v0.3.0: scripts, esquema, skills y ganchos al día;
  `comprobar.yml` conserva sus jobs (el cambio de `ciInstall` no le toca) y `REVIEW.md` gana dos reglas de la plantilla.
