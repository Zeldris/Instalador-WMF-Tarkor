# Plan de trabajo

**Estado: orden sugerido, no calendarizado.** Nada de esto tiene fecha ni está decidido que se vaya
a abordar ya — queda aquí como checklist de referencia para cuando se decida ponerse con esto de
verdad. Basado en el orden ya sugerido en la investigación original
(`docs/20-instalador-distribuible.md` del repo del juego), ampliado con lo que salió en la sesión
del 2026-09-16.

Cada punto enlaza al documento que lo detalla. Marcar como hecho a medida que se avance.

## Fase 1 — Decisiones que faltan antes de escribir código

Sin esto resuelto, no tiene sentido empezar a tocar el repo del juego:

- [ ] **Ollama**: decidir entre gestionarlo desde el instalador o dejarlo como requisito manual —
  ver [`03-ollama-y-modelos-ia.md`](03-ollama-y-modelos-ia.md).
- [ ] **Legal**: elegir licencia del código y del contenido narrativo, confirmar términos de
  redistribución de Ollama/Qwen/nomic-embed-text — ver
  [`08-legal-y-privacidad.md`](08-legal-y-privacidad.md).
- [ ] **Flujo de instalación**: decidir carpeta de instalación, si se firma el código desde ya,
  dónde vive la carpeta de datos del usuario por plataforma — ver
  [`07-flujo-de-instalacion.md`](07-flujo-de-instalacion.md).
- [ ] Resolver las 5 dudas abiertas de [`06-inventario-exclusiones.md`](06-inventario-exclusiones.md)
  (sección D) sobre qué tan a fondo se recorta el backend.

## Fase 2 — Migración de base de datos (sobre el repo del juego)

Se puede validar contra el propio Postgres de desarrollo, no depende de tener SQLite funcionando
todavía — ver [`02-migracion-postgres-a-sqlite.md`](02-migracion-postgres-a-sqlite.md):

1. [ ] Sustituir las dos queries `<=>` (`retrieval.ts`, `worldFacts.ts`) por similitud coseno en
   JS, guardando el embedding como JSON en vez de `vector(768)`.
2. [ ] Sustituir el `FOR UPDATE` de `progression.ts` por un mutex en memoria por `saveId`.
3. [ ] Convertir los campos de array nativo del schema a `String` con JSON serializado (migración
   de schema + arreglar cada sitio que lee/escribe esos campos).
4. [ ] Decidir si se mantienen dos `schema.prisma` o uno con `datasource` parametrizado, y aplicar
   esa decisión.

## Fase 3 — Recorte de funcionalidad para el instalador

Sobre el repo del juego, sin tocar todavía el empaquetado en sí — ver
[`06-inventario-exclusiones.md`](06-inventario-exclusiones.md):

1. [ ] Backend: excluir del build los scripts de curación de contenido, fine-tuning/DPO, y
   `LiveTeacherCapture` (o dejarlos fuera de la build empaquetada sin tocar el repo de desarrollo).
2. [ ] Backend: decidir y aplicar qué hacer con `POST /world/:slug/image-prompt` (quitar del todo
   vs. dejar inerte).
3. [ ] Frontend: quitar `ImagePromptSlot` de `DetailModal.tsx`.
4. [ ] Frontend: deshabilitar la pestaña "Crear desde cero" en `CharacterSelect.tsx`, marcada "en
   construcción".
5. [ ] Frontend: revisar el texto de `ComingSoon.tsx` (multijugador) si se quiere un wording
   distinto al actual.
6. [ ] Confirmar que el catálogo/imágenes/lore que se empaquetan están completos y ya curados —
   nada de generación pendiente en el paquete final.

## Fase 4 — Empaquetado

Ver [`04-empaquetado-tauri.md`](04-empaquetado-tauri.md):

1. [ ] Elegir y probar el mecanismo de empaquetado del backend Node como sidecar.
2. [ ] Confirmar que Prisma Client con SQLite empaqueta limpio en las plataformas de destino.
3. [ ] Montar el envoltorio Tauri completo: sidecar + frontend compilado + primer arranque creando
   el `.sqlite` local si no existe.
4. [ ] Implementar el flujo de instalación (consentimiento + validación post-instalación) descrito
   en [`07-flujo-de-instalacion.md`](07-flujo-de-instalacion.md).
5. [ ] Resolver Ollama según lo decidido en la Fase 1.

## Fase 5 — Prueba real

- [ ] Probar el instalador real en la propia Steam Deck (o la máquina que se use) antes de dar el
  trabajo por terminado — mismo criterio que el resto del proyecto: "probar en vivo, no solo que
  compile".
- [ ] Probar también en una máquina "limpia" (sin Ollama/Node/nada preinstalado) para validar la
  experiencia real de un jugador nuevo, no solo la de una máquina de desarrollo.
- [ ] Validar el flujo completo de desinstalación (¿qué se borra, qué se conserva?).

---

Nada de esto está calendarizado ni decidido — queda aquí documentado para retomarlo cuando se
decida seguir adelante.
