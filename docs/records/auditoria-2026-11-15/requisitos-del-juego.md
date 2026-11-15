# Auditoría 2026-11-15: lo que exige el repo del juego

Subagente `sonnet`, solo lectura, juego en `origin/main` b098334e (clon de un commit: sin historial). Lo marcado
**[verificado]** lo comprobó la sesión principal.

## Alta

1. **La fase 2 (SQLite) no está en el juego.** [verificado] El
   [PR #1](https://github.com/Zeldris/World-Maker-Fantasy/pull/1) (`claude/instalador-empaquetado`, INS-21…27) está
   **cerrado sin fusionar desde el 2026-11-03**, con conflictos; el plan (`05`, l. 23-24 y 94) y la bitácora siguen
   diciendo «a falta de fusionar». En `main`: `schema.prisma` solo `postgresql`, sin `schema.sqlite.prisma`, 246
   migraciones (última `20261110120000_aviso_reservas_bajas`). Sin esto el instalador no tiene base de datos.
2. **Código Postgres nuevo desde el PR #1** que la fase 2 no cubría (según el subagente, rutas del backend del juego):
   `hasSome` (`habilidadesRenombradas.ts:66,71`) y jsonb `?|` en SQL crudo (`:79`); `has` (`worldFacts.ts:158`);
   `pg_advisory_xact_lock` (`avanceDiario.ts:98`, `zonePoints.ts:352,418`, `mundoPartida.ts:46`); más `push`
   (`turnResolution.ts:6886`, `moralGrupo.ts:79,84`, `routes/saves/quests.ts:180`), `mode: 'insensitive'`
   (`turnResolution.ts:5937`, `generarMisiones.ts:107`), `skipDuplicates` (`fichaEdificio.ts:96`, `difusion.ts:135`,
   `linajes.ts:78,191`); `$queryRaw/$executeRaw` en 14 archivos. Rehacer la fase 2 sobre `main` actual, con un test
   de humo del backend entero contra SQLite en el CI del juego para que no vuelva a desfasarse.
3. **INS-35/36 abiertas y el juego sigue igual**: `server.ts:55` `cors({ origin: true })`, `server.ts:74` escucha en
   `0.0.0.0`; narrador por defecto `tarkor-narrador-llama31` (`config/env.ts`). Ya en el plan con el issue #93.

## Media

4. **`sync-item-catalog`**: `iniciar-tarkor.sh` y `actualizar-mundo.sh` del juego lo corren tras `seed-catalog`; el
   instalador no lo nombra.
5. **Imágenes: 464 MB** en `backend/uploads` (222 archivos) [verificado con `du`]; `docs/04:117` dice ~270 MB.
   Afecta al espacio previsto y al catálogo. Propuesta: medirlo con un script.
6. **Variables nuevas no inventariadas en `06`**: `FICTION_MINUTES_PER_REAL_MINUTE`, `TRANSIT_MAX_REAL_MINUTES`,
   `WORLD_TICK_INTERVAL_MINUTES`, `OLLAMA_KEEP_ALIVE_CRONISTA`, `IA_REGISTRO`, `IA_CASOS` (estas dos pueden guardar
   prompts en disco: privacidad, desactivadas por defecto).
7. **`.env.example` no coincide con los defectos de `env.ts`** (p. ej. `OLLAMA_KEEP_ALIVE_CRONISTA`): tomar los
   valores de `env.ts`.
8. **`modelfileSystemPrompt.ts:12` lee `../../Modelfile.llama31` del disco**: o va empaquetado en esa ruta o INS-35
   lo incrusta.
9. **`server.ts:62` sirve `../uploads/images` relativo al código**: en la app instalada, parametrizar hacia la carpeta
   de datos.

## Baja

10. CI del juego en Node 22 y Prisma 6.19.3: fijar lo mismo al compilar el sidecar.
11. `lib/ollama.ts:79` `num_thread: 8` fijo: parametrizable para perfiles bajos.
12. Guardas `TARKOR_EMPAQUETADO` (`routes/world.ts:830`, `turnResolution.ts:6991`): test de que esbuild las pliega
    en el build del instalador.

## Bien

Modelos (`llama3.1:8b` vía Modelfile, `qwen2.5:1.5b-instruct`, `qwen3.5:4b`, `nomic-embed-text`) coinciden con
`catalogo.json`; `think: false`; Prisma 6.19.3 y Fastify 5; contrato `window.__TARKOR__.apiUrl`; Ollama 0.34.3.
