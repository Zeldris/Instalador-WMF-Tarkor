# Plan de implementación

**Estado: en marcha desde el 2026-09-28.** Sustituye al checklist anterior. Ordenado por riesgo: lo
que puede tumbar el plan (empaquetar el backend, Ollama portable, velocidad en la Deck) se prueba
primero, antes de invertir en la migración de la base de datos.

Dónde se trabaja cada fase:

- **Este repo (público):** envoltorio Tauri, asistente de primer arranque, gestión de sidecars.
- **Repo del juego (privado):** migración a SQLite, recorte de funcionalidad, cambios pequeños para
  el modo empaquetado, CI de build.

Marcar cada punto al terminarlo.

## Fase 0 — Esqueleto y prueba de concepto

Objetivo: demostrar que el patrón completo funciona en Windows y en la Steam Deck.

- [ ] **0.1** Proyecto Tauri v2 en `app/` con el asistente (React + Vite + TypeScript) usando los
  tokens visuales del juego. Pantallas según [`11`](11-diseno-del-frontal.md).
- [ ] **0.2** Detección de equipo en Rust (`sysinfo`, gráfica por plataforma) y cálculo de perfiles
  de [`09`](09-deteccion-de-equipo-y-perfiles.md), con tests unitarios.
- [ ] **0.3** `config.json` en la carpeta de datos: al abrir, asistente si no está completado.
- [ ] **0.4** Gestor de sidecars en Rust: puerto libre, arrancar y parar procesos, esperar al
  health-check, un reinicio automático, parada garantizada al cerrar.
- [ ] **0.5** Ollama portable: descarga de la versión fijada (SHA256), arranque aislado
  (`OLLAMA_HOST`, `OLLAMA_MODELS`), descarga de modelos con progreso vía `/api/pull`.
- [ ] **0.6** Prueba de empaquetado del backend: Fastify + Prisma sobre SQLite compilado a
  bytecode (camino A de [`10`](10-proteccion-del-codigo-y-build.md)); probar también Prisma sin
  motor nativo (`queryCompiler` + adaptador SQLite).
- [ ] **0.7** Narrador con `system` + `options` por petición sobre `qwen2.5:7b`: comparar con
  `tarkor-narrador` (ver [`03`](03-ollama-y-modelos-ia.md)).
- [ ] **0.8** Prueba en la Steam Deck y en un Windows limpio: tiempos de descarga, memoria real
  de cada perfil, palabras por segundo. Ajustar las cifras de `09` con lo medido.

## Fase 1 — Decisiones pendientes

Se pueden resolver en paralelo a la fase 0. Ver la tabla del [README](../README.md).

- [ ] Firma de código en Windows.
- [ ] Licencia del juego (propuesta: todos los derechos reservados) y de este repo.
- [ ] Perfil Ligero: narrador y licencia (tras probar calidad en 0.8).
- [ ] Perfiles por encima del máximo seguro: bloqueados o con aviso.
- [ ] Confirmar licencias de modelos e imágenes.

## Fase 2 — Migración a SQLite (repo del juego)

Ver [`02`](02-migracion-postgres-a-sqlite.md). Sin romper el modo de desarrollo con Postgres.

- [ ] **2.1** Proveedor de base de datos por variable de entorno y generación de
  `schema.sqlite.prisma` en el build, con test de sincronía.
- [ ] **2.2** Embeddings en JSON + similitud coseno en JS (`retrieval.ts`, `worldFacts.ts`).
- [ ] **2.3** `lockRowForUpdate()` con mutex en memoria cuando el proveedor es SQLite.
- [ ] **2.4** Los 16 campos de lista a `Json` con capa de conversión en `lib/prisma.ts`; reescribir
  los `push`.
- [ ] **2.5** `mode: 'insensitive'` y `skipDuplicates`.
- [ ] **2.6** Batería de tests del backend pasando contra SQLite.
- [ ] **2.7** Script de build de la base de datos plantilla (migrada + catálogo + lore indexado).

## Fase 3 — Modo empaquetado del juego (repo del juego)

Ver [`06`](06-inventario-exclusiones.md).

- [ ] **3.1** Frontend: URL del backend en tiempo de ejecución (`api.ts`).
- [ ] **3.2** Frontend: fuentes Cinzel e Inter en local.
- [ ] **3.3** Frontend: quitar `ImagePromptSlot`; deshabilitar "Crear desde cero" como "en
  construcción"; revisar el texto de `ComingSoon.tsx`.
- [ ] **3.4** Backend: build sin rutas ni servicios de curación (ruta de image-prompt, orquestador
  cloud, `LiveTeacherCapture`, scripts).
- [ ] **3.5** Backend: `SYSTEM` del narrador incrustado en build; narrador con modelo base +
  `system` por petición detrás de variable de entorno.
- [ ] **3.6** Backend: CORS restringido y escucha solo en `127.0.0.1` en modo empaquetado; rutas de
  imágenes y datos por variable de entorno.
- [ ] **3.7** Menú del juego: enlace a Ajustes → Rendimiento de la IA.

## Fase 4 — Empaquetado completo y CI

Ver [`04`](04-empaquetado-tauri.md) y [`10`](10-proteccion-del-codigo-y-build.md).

- [ ] **4.1** Integrar el build del juego (frontend + backend en bytecode + plantilla) en la app de
  Tauri.
- [ ] **4.2** Asistente real de punta a punta: descargas y comprobaciones de verdad.
- [ ] **4.3** Ajustes → Rendimiento de la IA y pantalla de motor detenido.
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
