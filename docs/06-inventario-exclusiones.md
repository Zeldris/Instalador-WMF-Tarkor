# Inventario de exclusiones

**Estado: investigación hecha, dudas de la sección D resueltas (2026-09-28); cambios de código
sin implementar.** Resultado de una auditoría real
del repo `World-Maker-Fantasy` (2026-09-16) para identificar con precisión qué excluir del
instalador y qué deshabilitar en la UI. Cita las rutas de archivo reales tal como estaban en ese
momento — pueden haberse movido para cuando se implemente esto de verdad, conviene reverificar.

**Reverificación rápida 2026-09-28** (commit `ace5cd8`): las rutas del frontend (`DetailModal.tsx`,
`CharacterSelect.tsx`) siguen igual; `POST /world/:slug/image-prompt` sigue en `world.ts` (ahora
~línea 789); la documentación del juego se ha reorganizado en subcarpetas
(`docs/arquitectura/15-instalacion.md`, `docs/arquitectura/20-instalador-distribuible.md`,
`docs/ia/fine-tuning-ia-local.md`); la carpeta `tools/playwright-e2e/` ya no existe en el repo. Se
añaden dos puntos nuevos (sección E).

## A. Excluir del instalador con certeza

### A1. Generación de prompts de imagen

Tiene dos caras — datos/backend y un botón real en la UI del jugador, hay que tocar las dos:

- **Backend**: `POST /world/:slug/image-prompt` (`backend/src/routes/world.ts`, ~líneas 775-840).
  Si no hay prompt guardado o se pide `regenerate`, llama a `generateImagePrompt()`
  (`backend/src/services/imagePromptGenerator.ts`) → `completeWithFallback()`
  (`backend/src/lib/aiProviders/orchestrator.ts`) → rotación de 6 proveedores cloud
  (Cerebras→Mistral→SambaNova→Cloudflare→Gemini→Groq→Ollama local como último recurso).
  **Importante:** `GET /world/:slug/enciclopedia` (~línea 520 del mismo archivo) SÍ es parte del
  juego real — solo LEE los `ImagePrompt` ya guardados, nunca llama a proveedores cloud. No tocar
  ese GET.
- **Frontend**: `frontend/src/components/ImagePromptDisplay.tsx` (componente `ImagePromptSlot`,
  ~líneas 175-233), montado 4 veces dentro de `frontend/src/components/DetailModal.tsx` (el modal
  de detalle de cualquier entrada de la Enciclopedia, ~líneas 633/643/657/681). Muestra un botón
  "Generar"/"Regenerar" que llama a `requestImagePrompt()` (`frontend/src/lib/api.ts`, ~línea
  2123), que pega al POST de arriba.
- **Acción para el instalador**: quitar/ocultar `ImagePromptSlot` de `DetailModal.tsx` (dejar solo
  `MediaSlot`, que muestra la imagen ya empaquetada), y eliminar o desactivar la ruta POST en
  backend. Sin esto, el jugador vería botones "Generar" que fallarían con error 502 al no haber
  claves configuradas, en vez de simplemente no existir.
- **Scripts de npm** (solo curación de contenido, nunca se ejecutan jugando): `seed-image-prompts`,
  `export-image-prompts`, `audit-images` (`backend/src/scripts/{seedImagePrompts,
  exportImagePrompts,auditImages}.ts`).

### A2. Pipeline de fine-tuning / distillation / DPO

Genera datasets de entrenamiento y compara modelos — nada de esto lo usa el jugador ni corre durante
una partida normal:

- Scripts npm: `generate-distillation-dataset`, `split-distillation-dataset`,
  `compare-narrador-models`, `export-dpo-dataset`, `generate-dpo-dataset`
  (`backend/src/scripts/`).
- Script suelto en la raíz del repo: `generar-dataset-dpo.sh` (no lo invoca `iniciar-tarkor.sh`).
- Documentación de referencia: `docs/ia/fine-tuning-ia-local.md` — fuera de alcance del instalador
  por completo.
- `backend/src/services/liveTeacherCapture.ts` + tabla `LiveTeacherCapture`: activado por
  `LIVE_TEACHER_CAPTURE_ENABLED`. Cuando está activo, ~1 de cada 3 turnos narrados manda EN
  SEGUNDO PLANO la misma pregunta a un proveedor cloud para comparar con la respuesta local, solo
  para acumular pares de entrenamiento. No afecta lo que ve el jugador, pero si hubiera una clave
  puesta consumiría cuota cloud sin que el jugador lo supiera — no debe activarse en el instalador.

### A3. Scripts de curación de contenido / seed del mundo

- `reindex-lore` (`backend/src/scripts/reindex-lore.ts`): indexa `docs/rpgtarkor/*.md` en
  embeddings RAG, necesita Ollama arriba (`nomic-embed-text`). Solo hace falta al crear la base de
  datos por primera vez o cuando cambia el lore fuente — no es algo que el jugador dispare. La base
  de datos distribuida en el instalador debería venir YA con los `LoreChunk` pre-indexados.
- `seed-catalog` (`backend/src/scripts/seed-catalog.ts`): a diferencia de `reindex-lore`, este SÍ
  se ejecuta hoy en cada arranque normal (`iniciar-tarkor.sh` lo corre siempre — rápido, sin red,
  sin IA, solo upserts a Postgres desde `worldCatalog.ts`). Es más "sincronizar datos del juego" que
  "herramienta de desarrollo" pura — ver duda abierta en la sección D sobre si mantenerlo en el
  instalador.
- Scripts de debug manual por terminal, sin ruta HTTP ni consumo desde frontend, no forman parte de
  ningún flujo de arranque: `test-turn.ts`, `test-retrieval.ts`, `test-worldtick.ts`,
  `auditSave.ts` (comando "revisar partida", vuelca el estado de una partida por terminal),
  `migrate-arcano-a-magia-2026-09-01.sql` (migración de datos puntual de una sesión de desarrollo
  concreta, no parte del ciclo estándar de migraciones de Prisma).

### A4. Herramienta de test E2E

`tools/playwright-e2e/` — herramienta de Claude para jugar/probar el juego de forma automatizada,
ya sabido que no debe ir en el instalador. Confirmado que no hay dependencia cruzada del
backend/frontend hacia esa carpeta. (2026-09-28: la carpeta ya no está en el repo; si vuelve, mismo
criterio.) Tampoco van la carpeta `debug/` ni los `Modelfile` alternativos de `modelfiles/` y
`backend/Modelfile.*` (pruebas de otros modelos).

### A5. Variables de entorno de las 6 APIs cloud

Alimentan exclusivamente A1 y A2 — ver detalle completo en la sección C.

## B. Deshabilitar en la UI, mantener visible como "en construcción"

### B1. Multijugador — ya está en ese estado hoy, casi sin cambios que hacer

Búsqueda completa en `backend/src` de "multijugador"/"multiplayer"/"sala"/"room": cero resultados,
no existe ningún endpoint ni lógica de servidor para multijugador. Es puramente frontend:

- `frontend/src/pages/Home.tsx` (~líneas 50-64): botón "Multijugador" navega a `/multijugador`.
- `frontend/src/App.tsx` (~línea 18): ruta `/multijugador` → componente `ComingSoon`.
- `frontend/src/pages/ComingSoon.tsx`: pantalla "Multijugador — próximamente", texto actual
  "todavía está en diseño... el MVP se centra primero en pulir el modo en solitario".

No hace falta ningún cambio de fondo para el instalador — ya cumple el criterio pedido. Único
ajuste posible: revisar el texto de `ComingSoon.tsx` para que diga literalmente "en construcción
para futuras versiones" si se quiere ese wording exacto.

### B2. Creación de personaje libre — sí requiere cambio real

A diferencia de multijugador, aquí hay una funcionalidad completa y funcional, no un placeholder:

- `frontend/src/pages/CharacterSelect.tsx`: dos pestañas, `tab === 'pregen'` y `tab === 'custom'`
  (esta última con un formulario completo — nombre, arquetipo, motivación, reparto de 68 puntos
  entre 7 atributos con sliders — que termina en `confirmCustom()`).
- Solo 1 personaje pregenerado está habilitado hoy: `PLAYABLE_CHARACTER_IDS = new
  Set(['char-gorhorn'])` — el resto de `pregeneratedCharacters` en `frontend/src/data/mock.ts`
  existen en el código pero están ocultos por una decisión ya tomada antes de esta sesión ("por
  ahora que solo salga Gorhorn").
- **Backend**: `POST /saves` (`backend/src/routes/saves/creation.ts`) es genérico — no distingue
  "pregenerado" vs. "custom" salvo por el campo opcional `pregeneratedCharacterId`, toma
  directamente `characterName`/`characterArchetype`/`characterOrigin`/`characterMotivation`/
  `attributes` del body sea cual sea su origen. No hace falta tocar el backend para esto.
- **Acción para el instalador**: en `CharacterSelect.tsx`, deshabilitar/ocultar la pestaña `custom`
  (marcada "en construcción", mismo criterio que multijugador) y forzar `tab` siempre a `'pregen'`.

## C. Variables de entorno

**Hacen falta para jugar, se mantienen en el instalador:**

- `DATABASE_URL` / `DIRECT_URL` (o su equivalente SQLite tras la migración de
  [`02-migracion-postgres-a-sqlite.md`](02-migracion-postgres-a-sqlite.md))
- `PORT`
- `OLLAMA_BASE_URL`, `OLLAMA_MODEL_NARRADOR`, `OLLAMA_MODEL_CRONISTA`, `OLLAMA_MODEL_SUGERENCIAS`,
  `OLLAMA_MODEL_EMBEDDINGS`, `OLLAMA_KEEP_ALIVE`
- `PACING_MIN_MS`, `PACING_MAX_MS`, `WORLD_TICK_INTERVAL_MINUTES`, `TRANSIT_MAX_REAL_MINUTES`,
  `TRAVEL_SEGUNDOS_PRIMER_TRAMO`, `TRAVEL_SEGUNDOS_POR_TRAMO_EXTRA`, `TRAVEL_SEGUNDOS_MAXIMOS`,
  `TRAVEL_INTERRUPTION_PROBABILITY_PER_SEGMENT`, `STATIONARY_INTERRUPTION_PROBABILITY_PER_CHUNK`
  — todas gobiernan ritmo/mecánica de juego real, nada que ver con IA cloud.
- `VITE_API_URL` (frontend, opcional, cae a `localhost:3001` si no está)

**Se quitan del instalador** (solo alimentan A1/A2, ya opcionales hoy — el código cae solo a Ollama
si faltan, `env.ts` las lee con `?? ''`):

- `CEREBRAS_API_KEY`, `CEREBRAS_MODEL`
- `MISTRAL_API_KEY`, `MISTRAL_MODEL`
- `SAMBANOVA_API_KEY`, `SAMBANOVA_MODEL`
- `CLOUDFLARE_API_KEY`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_MODEL`
- `GEMINI_API_KEY`, `GEMINI_MODEL`
- `GROQ_API_KEY`, `GROQ_MODEL`
- `LIVE_TEACHER_CAPTURE_ENABLED`, `LIVE_TEACHER_CAPTURE_SAMPLE_RATE`

## D. Dudas para decidir explícitamente antes de implementar

1. **¿Quitar la ruta `POST /world/:slug/image-prompt` del backend del todo, o solo ocultar el botón
   en frontend?** Si solo se oculta el botón pero la ruta sigue viva, un jugador curioso podría
   llamarla a mano y recibiría un 502 (sin claves configuradas) — no es grave, pero conviene decidir
   si el build del instalador compila el backend sin esa ruta, o si basta con el frontend recortado.
   **Resuelto (2026-09-28):** se quita del build. El orquestador de proveedores cloud tampoco va en
   el instalador, así que la ruta no tendría nada que llamar; además, menos código dentro del
   binario.
2. **`seed-catalog` en cada arranque**: ¿el instalador lo sigue corriendo en cada arranque (permite
   actualizaciones de contenido futuras sin reinstalar), o el instalador trae los datos ya sembrados
   de una vez y se elimina ese paso visible? **Resuelto (2026-09-28):** las dos cosas — el
   instalador trae una base de datos plantilla ya sembrada y se sigue ejecutando `seed-catalog` en
   cada arranque para llevar contenido nuevo a las partidas existentes. Ver `02`, "Primer
   arranque".
3. **`reindex-lore`**: confirmar que el plan es distribuir la base de datos con los `LoreChunk` ya
   pre-indexados (export/import de esa tabla), en vez de pedir que el instalador del jugador corra
   este proceso. **Resuelto (2026-09-28):** sí, el lore va ya indexado en la base de datos
   plantilla. Ojo: esto NO evita descargar `nomic-embed-text` — el juego lo sigue necesitando en
   partida (hechos de sesión y consultas de lore), ver `03`.
4. **`iniciar-tarkor.sh`/`.bat` como base del instalador**: hoy asumen una ruta de NVM fija (propia
   del entorno de desarrollo actual) y detectan terminal gráfica para abrir ventanas — comodidades
   de desarrollo, no un mecanismo de arranque pensado para un instalador empaquetado de verdad. El
   instalador necesita su propio mecanismo de arranque (ver
   [`04-empaquetado-tauri.md`](04-empaquetado-tauri.md)), no reutilizar estos scripts tal cual.
   **Resuelto:** Tauri arranca y para los dos sidecars; los scripts no se incluyen.
5. **Un solo `schema.prisma` o dos**: si el instalador reutiliza el mismo schema que desarrollo
   (recomendable, evita bifurcar el modelo de datos), las tablas `ImagePrompt`/`LiveTeacherCapture`
   quedarán presentes pero sin uso en el instalador — no hace falta quitarlas del schema, solo
   confirmar que se prefiere mantener un solo schema compartido. **Resuelto:** un solo schema
   fuente; el de SQLite se genera en el build (ver `02`).

## E. Puntos nuevos (2026-09-28)

1. **Fuentes sin conexión.** `frontend/src/index.css` carga Cinzel desde Google Fonts
   (`@import url('https://fonts.googleapis.com/…')`). Una app de escritorio no puede depender de
   eso (sin red se vería con Georgia, y además es una petición a un tercero que contradice `08`).
   Acción: empaquetar Cinzel e Inter en local (p. ej. `@fontsource/cinzel`, `@fontsource/inter`)
   en la build del instalador.
2. **`Modelfile` leído en tiempo de ejecución.** `backend/src/lib/modelfileSystemPrompt.ts` lee
   `../../Modelfile` del disco. En el binario hay que incrustar el texto en el build (ver `03` y
   `10`). Además, en el instalador el narrador pasa a ser el modelo base + `system` por petición
   (ver `03`).

## Resumen de rutas para cuando se implemente

- Backend dev-only a excluir del build: `backend/src/scripts/{seedImagePrompts,
  exportImagePrompts,auditImages,generate-distillation-dataset,split-distillation-dataset,
  compare-narrador-models,export-dpo-dataset,generate-dpo-dataset,test-turn,test-retrieval,
  test-worldtick,auditSave}.ts`
- Backend ruta a excluir/desactivar: `backend/src/routes/world.ts` (`POST
  /world/:slug/image-prompt`)
- Backend orquestador cloud a excluir: `backend/src/lib/aiProviders/orchestrator.ts` + clientes
  individuales de la misma carpeta
- Frontend a modificar: `frontend/src/components/ImagePromptDisplay.tsx` (quitar
  `ImagePromptSlot`), `frontend/src/components/DetailModal.tsx` (dejar de montarlo),
  `frontend/src/pages/CharacterSelect.tsx` (deshabilitar tab `custom`)
- Frontend ya conforme, no tocar: `frontend/src/pages/Home.tsx`, `frontend/src/pages/
  ComingSoon.tsx`, `frontend/src/App.tsx`
- Scripts en la raíz del repo a excluir: `generar-dataset-dpo.sh`
- Documentación de referencia a no incluir/reescribir: `docs/ia/fine-tuning-ia-local.md` (fuera de
  alcance por completo), `docs/arquitectura/15-instalacion.md` (si se reutiliza como base, quitar la
  sección de las 6 API keys y `LIVE_TEACHER_CAPTURE_*`)
- Frontend a modificar también: `frontend/src/index.css` (fuentes locales),
  `frontend/src/lib/api.ts` (URL del backend en tiempo de ejecución, ver `04`)
