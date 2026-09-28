# Plan de implementación

**Estado: en marcha desde el 2026-09-28.** Sustituye al checklist anterior. Ordenado por riesgo: lo
que puede tumbar el plan (empaquetar el backend, Ollama portable, velocidad en la Deck) se prueba
primero, antes de invertir en la migración de la base de datos.

Dónde se trabaja cada fase:

- **Este repo (público):** envoltorio Tauri, asistente de primer arranque, gestión de sidecars.
- **Repo del juego (privado):** migración a SQLite, recorte de funcionalidad, cambios pequeños para
  el modo empaquetado, CI de build.

Marcar cada punto al terminarlo.

## Dónde lo dejamos (2026-09-28)

**Hecho y en `main` de este repo:** fases 0.1-0.6 (asistente, detección de equipo, catálogo de
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
fase 4 (backend dentro de la app y CI de releases). Las fases 0.7, 0.8 y 5 necesitan probar en la
Steam Deck o en Windows: `cargo run --release -p tarkor-nucleo --example motor equilibrado`
(ver `app/README.md`).

## Fase 0 — Esqueleto y prueba de concepto

Objetivo: demostrar que el patrón completo funciona en Windows y en la Steam Deck.

- [x] **0.1** Proyecto Tauri v2 en `app/` con el asistente (React + Vite + TypeScript) usando los
  tokens visuales del juego. Pantallas según [`11`](11-diseno-del-frontal.md).
- [x] **0.2** Detección de equipo en Rust (`sysinfo`, gráfica por plataforma) y cálculo de perfiles
  de [`09`](09-deteccion-de-equipo-y-perfiles.md), con tests unitarios.
- [x] **0.3** `config.json` en la carpeta de datos: al abrir, asistente si no está completado.
- [x] **0.3b** Catálogo de modelos y perfiles en JSON (con perfil Mínimo para que cualquiera pueda
  probar) y ajustes de rendimiento de Ollama calculados por equipo (ver
  [`12`](12-catalogo-y-rendimiento.md)).
- [x] **0.4** Gestor de sidecars en Rust: puerto libre, arrancar y parar procesos, esperar al
  health-check, un reinicio automático, parada garantizada al cerrar.
- [x] **0.5** Ollama portable: descarga de la versión fijada (SHA256), arranque aislado
  (`OLLAMA_HOST`, `OLLAMA_MODELS`), descarga de modelos con progreso vía `/api/pull`.
- [x] **0.6** Prueba de empaquetado del backend compilado a bytecode (camino A de
  [`10`](10-proteccion-del-codigo-y-build.md)): funciona con el backend real contra Postgres
  (lecturas, crear partida, `FOR UPDATE`). Herramienta en `herramientas/empaquetar-backend.mjs`.
  Pendiente para después de la fase 2: repetirla sobre SQLite y probar Prisma sin motor nativo
  (`queryCompiler` + adaptador SQLite).
- [ ] **0.7** Narrador con `system` + `options` por petición sobre `qwen2.5:7b`: comparar con
  `tarkor-narrador` (ver [`03`](03-ollama-y-modelos-ia.md)).
- [ ] **0.8** Prueba en la Steam Deck y en un Windows limpio: tiempos de descarga, memoria real
  de cada perfil, tokens por segundo, Vulkan frente a ROCm en la Deck, calidad de narración de
  Mínimo y Ligero. Ajustar el catálogo con lo medido.

## Fase 1 — Decisiones pendientes

Se pueden resolver en paralelo a la fase 0. Ver la tabla del [README](../README.md).

- [ ] Firma de código en Windows.
- [ ] Licencia del juego (propuesta: todos los derechos reservados) y de este repo.
- [x] Perfiles pequeños: se ofrecen Mínimo y Ligero con modelos Apache 2.0, avisando del
  resultado (calidad a confirmar en 0.8).
- [ ] Perfiles por encima del máximo seguro: bloqueados o con aviso.
- [ ] Confirmar licencias de modelos e imágenes.

## Fase 2 — Migración a SQLite (repo del juego) — código hecho, PR #1 sin fusionar

Ver [`02`](02-migracion-postgres-a-sqlite.md). Sin romper el modo de desarrollo con Postgres.

- [x] **2.1** Proveedor de base de datos por variable de entorno y generación de
  `schema.sqlite.prisma` en el build, con test de sincronía.
- [x] **2.2** Embeddings en JSON + similitud coseno en JS (`retrieval.ts`, `worldFacts.ts`).
- [x] **2.3** `lockRowForUpdate()` con mutex en memoria cuando el proveedor es SQLite.
- [x] **2.4** Los 16 campos de lista a `Json` (sin capa de conversión: un `Json` con un array se
  lee y escribe igual); los `push` reescritos con `anadirNpcRetirado`.
- [x] **2.5** `mode: 'insensitive'` y `skipDuplicates`.
- [x] **2.6** Batería de tests del backend pasando contra SQLite.
- [x] **2.7** Script de build de la base de datos plantilla (migrada + catálogo + lore indexado).

## Fase 3 — Modo empaquetado del juego (repo del juego)

Ver [`06`](06-inventario-exclusiones.md).

- [ ] **3.1** Frontend: URL del backend en tiempo de ejecución (`api.ts`).
- [ ] **3.2** Frontend: fuentes Cinzel e Inter en local.
- [ ] **3.3** Frontend: quitar `ImagePromptSlot`; deshabilitar "Crear desde cero" como "en
  construcción"; revisar el texto de `ComingSoon.tsx`.
- [ ] **3.4** Backend: build sin rutas ni servicios de curación (ruta de image-prompt, orquestador
  cloud, `LiveTeacherCapture`, scripts).
- [ ] **3.5** Backend: `SYSTEM` del narrador incrustado en build; narrador con modelo base +
  `system` por petición detrás de variable de entorno; leer `TARKOR_NUM_THREAD`,
  `TARKOR_NUM_BATCH`, `TARKOR_NUM_CTX_NARRADOR` y `TARKOR_MODELOS_SIN_PENSAR` (ver `12`).
- [ ] **3.6** Backend: CORS restringido y escucha solo en `127.0.0.1` en modo empaquetado; rutas de
  imágenes y datos por variable de entorno.
- [ ] **3.7** Menú del juego: enlace a Ajustes → Rendimiento de la IA.

## Fase 4 — Empaquetado completo y CI

Ver [`04`](04-empaquetado-tauri.md) y [`10`](10-proteccion-del-codigo-y-build.md).

- [ ] **4.1** Integrar el build del juego (frontend + backend en bytecode + plantilla) en la app de
  Tauri.
- [ ] **4.2** Asistente real de punta a punta: descargas y comprobaciones de verdad; calentar el
  narrador al arrancar.
- [ ] **4.3** Ajustes → Rendimiento de la IA (con uso de la gráfica vía `/api/ps`) y pantalla de
  motor detenido.
- [ ] **4.4** NSIS: castellano, instalación por usuario, desinstalador con las dos casillas.
- [ ] **4.5** AppImage (+ `.deb` opcional) compilado en Ubuntu 22.04.
- [ ] **4.6** Workflow de GitHub Actions en el repo privado que publica releases con `SHA256SUMS`
  en este repo.
- [ ] **4.7** Pantalla "Licencias de terceros" generada en el build.

## Fase 5 — Prueba real

- [ ] En la Steam Deck (modo escritorio y como juego ajeno a Steam).
- [ ] En un Windows 10 y un Windows 11 limpios, sin Node ni Ollama.
- [ ] En un equipo de 8 GB: el perfil Ligero debe ser jugable.
- [ ] Actualizar de una versión a otra sin perder partidas.
- [ ] Desinstalar conservando y sin conservar partidas.
