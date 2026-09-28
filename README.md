# Instalador de Tarkor (World-Maker-Fantasy)

Repositorio para empaquetar **Tarkor** como una aplicación de escritorio instalable: un `.exe`
(Windows) o un `.AppImage` (Linux) que cualquiera pueda descargar y abrir, sin clonar el repositorio
del juego, sin instalar Node, Postgres ni Ollama a mano, y sin depender de ningún servidor.

Este repositorio es público (para publicar los instaladores), a diferencia del repositorio del
juego (`World-Maker-Fantasy`), que sigue siendo privado. Aquí no vive el código del juego: vive la
documentación, el diseño y el envoltorio de escritorio (Tauri, asistente de primer arranque,
gestión de procesos). La build final se hace desde el repo privado (ver
[`docs/10`](docs/10-proteccion-del-codigo-y-build.md)).

## Estado actual

- Documentación y diseño completos para la v1 (Windows + Linux).
- Prototipo navegable del asistente: [`diseno/prototipo-asistente.html`](diseno/prototipo-asistente.html).
- Implementación: **fase 0 en marcha** (ver [`docs/05-plan-de-trabajo.md`](docs/05-plan-de-trabajo.md)).

## Decisiones

| Tema | Decisión | Estado | Documento |
|---|---|---|---|
| Plataformas v1 | Windows y Linux (x86_64). macOS fuera | Decidido | [04](docs/04-empaquetado-tauri.md) |
| Envoltorio | Tauri v2 | Decidido | [01](docs/01-arquitectura-general.md) |
| Base de datos | SQLite local, base de datos plantilla ya sembrada | Decidido | [02](docs/02-migracion-postgres-a-sqlite.md) |
| Motor de IA | Ollama propio de la app como sidecar, descargado en el primer arranque | Propuesta, se valida en fase 0 | [03](docs/03-ollama-y-modelos-ia.md) |
| Narrador | Modelo base + `system` por petición (sin `ollama create`) | Propuesta, se valida en fase 0 | [03](docs/03-ollama-y-modelos-ia.md) |
| Hardware | Análisis del equipo con permiso + perfiles Ligero / Equilibrado / Máximo | Decidido | [09](docs/09-deteccion-de-equipo-y-perfiles.md) |
| Protección del código | Backend a bytecode, frontend minificado, sin *source maps* | Decidido, técnica exacta en fase 0 | [10](docs/10-proteccion-del-codigo-y-build.md) |
| Dónde se compila | CI en el repo privado; releases en este repo | Decidido | [10](docs/10-proteccion-del-codigo-y-build.md) |
| Instalación | NSIS por usuario sin admin (Windows); AppImage (Linux) | Decidido | [07](docs/07-flujo-de-instalacion.md) |
| Consentimiento y validación | En el asistente de primer arranque | Decidido | [07](docs/07-flujo-de-instalacion.md), [11](docs/11-diseno-del-frontal.md) |
| Firma en Windows | Azure Trusted Signing / certificado / sin firma en v1 | **Abierto** | [04](docs/04-empaquetado-tauri.md) |
| Licencia del juego | Todos los derechos reservados, uso personal gratuito | **Propuesta, confirmar** | [08](docs/08-legal-y-privacidad.md) |
| Licencia de este repo | MIT o todos los derechos reservados | **Abierto** | [08](docs/08-legal-y-privacidad.md) |
| Perfil Ligero | Narrador pequeño: calidad y licencia por probar | **Abierto** | [09](docs/09-deteccion-de-equipo-y-perfiles.md) |
| Por encima del máximo seguro | Bloqueado con opción "mostrar no recomendados" | **Propuesta, confirmar** | [09](docs/09-deteccion-de-equipo-y-perfiles.md) |

## Documentos

- [`01-arquitectura-general.md`](docs/01-arquitectura-general.md) — visión de conjunto.
- [`02-migracion-postgres-a-sqlite.md`](docs/02-migracion-postgres-a-sqlite.md) — puntos de
  fricción con Postgres (reverificados contra el código actual) y base de datos plantilla.
- [`03-ollama-y-modelos-ia.md`](docs/03-ollama-y-modelos-ia.md) — Ollama como sidecar y modelos.
- [`04-empaquetado-tauri.md`](docs/04-empaquetado-tauri.md) — procesos, puertos, plataformas,
  firma, tamaño.
- [`05-plan-de-trabajo.md`](docs/05-plan-de-trabajo.md) — plan de implementación por fases.
- [`06-inventario-exclusiones.md`](docs/06-inventario-exclusiones.md) — qué se quita del
  instalador y qué se deshabilita.
- [`07-flujo-de-instalacion.md`](docs/07-flujo-de-instalacion.md) — instalador, asistente,
  validación, carpetas, desinstalación.
- [`08-legal-y-privacidad.md`](docs/08-legal-y-privacidad.md) — licencias y datos.
- [`09-deteccion-de-equipo-y-perfiles.md`](docs/09-deteccion-de-equipo-y-perfiles.md) — análisis
  del equipo y perfiles de IA.
- [`10-proteccion-del-codigo-y-build.md`](docs/10-proteccion-del-codigo-y-build.md) — protección
  del código y pipeline de build.
- [`11-diseno-del-frontal.md`](docs/11-diseno-del-frontal.md) — pantallas del asistente, ajustes y
  errores.

## Relación con el repositorio del juego

`World-Maker-Fantasy` es donde vive el juego: backend Fastify, frontend Vite/React, catálogo del
mundo. Su `docs/arquitectura/20-instalador-distribuible.md` (2026-08-20) es el punto de partida de
todo esto. No confundir con `docs/arquitectura/15-instalacion.md` del juego, que explica cómo montar
el **entorno de desarrollo**; este repositorio habla de un **paquete terminado** para quien solo
quiere jugar.
