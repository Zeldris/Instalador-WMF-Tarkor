# Instalador de Tarkor (World-Maker-Fantasy)

Repositorio para empaquetar **Tarkor** como una aplicación de escritorio instalable — un único
`.exe`/`.dmg`/`.AppImage` que cualquiera pueda descargar y abrir, sin clonar el repositorio del
juego, sin instalar Node/Postgres/podman a mano, y sin depender de un dominio público ni de abrir
un navegador apuntando a una URL.

Este repositorio será público (para que cualquiera pueda descargar el instalador), a diferencia del
repositorio del juego en sí (`World-Maker-Fantasy`), que sigue siendo privado. Aquí no vive el
código del juego — vive la documentación de arquitectura y, más adelante, el código específico del
empaquetado (configuración de Tauri, scripts de build, migraciones a SQLite, etc.).

## Estado actual

**Solo documentación todavía — no se ha escrito ningún código de empaquetado.** Este repositorio
existe para dejar la arquitectura completamente pensada y por escrito antes de ponerse a
implementarla, así no se pierde el contexto de las decisiones entre sesiones.

## Cómo se relaciona con el repositorio del juego

`World-Maker-Fantasy` (repo privado, separado) es donde vive el juego real: backend Fastify,
frontend Vite/React, catálogo del mundo, etc. Ese repositorio ya tenía una investigación inicial de
viabilidad para este instalador — `docs/20-instalador-distribuible.md` — escrita el 2026-08-20, que
es el punto de partida de todo lo que hay aquí. Ese documento no se borra ni se mueve del repo del
juego; este repositorio lo desarrolla y lo amplía en documentos separados por tema.

No confundir tampoco con `docs/15-instalacion.md` del repo del juego, que es la guía para instalar
el **entorno de desarrollo** (clonar, `npm install`, Postgres vía podman) — eso sigue siendo válido
para quien quiera tocar código. Este repositorio habla de un **paquete terminado** para alguien que
solo quiere jugar.

## Índice de documentos

- [`docs/01-arquitectura-general.md`](docs/01-arquitectura-general.md) — visión de conjunto: Tauri,
  el backend como sidecar, cómo encajan las piezas.
- [`docs/02-migracion-postgres-a-sqlite.md`](docs/02-migracion-postgres-a-sqlite.md) — el obstáculo
  real identificado (pgvector, un `FOR UPDATE`, columnas de array nativo) y cómo resolverlo.
- [`docs/03-ollama-y-modelos-ia.md`](docs/03-ollama-y-modelos-ia.md) — qué hacer con Ollama y sus 4
  modelos en un instalador para un usuario que no es desarrollador. **Sin resolver todavía.**
- [`docs/04-empaquetado-tauri.md`](docs/04-empaquetado-tauri.md) — Tauri en sí: el sidecar de
  Node, build por plataforma, firma de código, tamaño del instalador. **Sin resolver todavía.**
- [`docs/05-plan-de-trabajo.md`](docs/05-plan-de-trabajo.md) — orden de trabajo sugerido cuando se
  decida implementar esto de verdad, como checklist.
- [`docs/06-inventario-exclusiones.md`](docs/06-inventario-exclusiones.md) — qué se excluye del
  instalador (herramientas de desarrollo/curación de contenido) y qué se deshabilita en la UI pero
  se deja visible como "en construcción" (multijugador, creación libre de personaje).
- [`docs/07-flujo-de-instalacion.md`](docs/07-flujo-de-instalacion.md) — el proceso de instalación
  en sí: qué se le explica al usuario antes de instalar, validación post-instalación, y una
  checklist de lo que un instalador bien construido suele cuidar. **Sin resolver todavía.**
- [`docs/08-legal-y-privacidad.md`](docs/08-legal-y-privacidad.md) — licencia del proyecto (gratis
  para todos), avisos legales, qué datos toca el instalador/el juego y qué se le comunica al
  usuario al respecto. **Sin resolver todavía.**

Cada documento indica en su cabecera si su contenido ya está **decidido** (una alternativa elegida,
lista para implementar) o sigue **abierto** (hay que decidir o investigar más antes de escribir
código).
