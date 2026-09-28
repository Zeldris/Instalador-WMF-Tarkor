# Migración de Postgres a SQLite

**Estado: decidido — queda por implementar.** Amplía
`docs/arquitectura/20-instalador-distribuible.md` del repo `World-Maker-Fantasy` (2026-08-20).
**Reverificado contra el código real el 2026-09-28** (commit `ace5cd8`): la dependencia de Postgres
sigue siendo acotada, pero el código ha cambiado desde la auditoría original y han aparecido
algunos puntos más pequeños. Las cifras de abajo son las actuales.

## Por qué SQLite y no Postgres embebido

Se consideró llevar un Postgres portable dentro del instalador, pero se descartó: complica el
empaquetado por plataforma y sigue haciendo falta compilar y distribuir la extensión `pgvector`.
La migración a SQLite es acotada, así que no compensa.

## Los puntos de fricción

### 1. pgvector (el más importante)

`LoreChunk.embedding` y `SessionFact.embedding` son `Unsupported("vector(768)")`. Se usan con SQL
crudo en:

- `backend/src/services/retrieval.ts` — RAG de lore, `ORDER BY embedding <=> …::vector`.
- `backend/src/services/worldFacts.ts` — escribe (`$executeRaw`) y busca (`$queryRaw`) hechos de
  partida por similitud.
- `backend/src/scripts/reindex-lore.ts` — indexado (herramienta de desarrollo, ver `06`).

Tarkor es de un solo jugador y local: estas tablas tienen cientos de filas por partida, no
millones.

**Solución:** guardar el embedding como JSON (768 números) y calcular la similitud coseno en JS al
leer las filas candidatas. A esta escala el coste es insignificante.

**Importante:** el modelo de embeddings (`nomic-embed-text`) sigue haciendo falta mientras se juega
(los `SessionFact` se generan en partida y cada búsqueda necesita el embedding de la consulta). Ver
[`03-ollama-y-modelos-ia.md`](03-ollama-y-modelos-ia.md).

### 2. `SELECT ... FOR UPDATE`

Ya no es un único uso: desde la auditoría del 2026-09-01 hay un helper genérico,
`lockRowForUpdate()` en `backend/src/routes/saves/shared.ts`, que bloquea filas de `Save` o
`CombatParticipant`. Se llama unas 25 veces desde 6 ficheros: `progression.ts`, `session.ts`,
`cazar.ts`, `companeros.ts`, `combatGroups.ts` y `aprenderOficio.ts`. Evita condiciones de carrera
reales (doble clic, dos peticiones casi simultáneas).

**Solución:** que el helper esté centralizado lo hace **más fácil**: basta con cambiar
`lockRowForUpdate()`. En SQLite:

- Cada llamada toma un mutex en memoria por `tabla:id` (un `Map` de colas de promesas) que se
  libera al terminar la transacción.
- Y el resto de la función relee las columnas sin `FOR UPDATE` (SQLite no lo admite).

Un solo proceso local y SQLite con escrituras serializadas: el mutex por fila cubre el mismo caso
que el candado original.

**Decisión:** el helper elige la implementación según el proveedor de base de datos activo
(variable de entorno), para no cambiar el comportamiento de la versión de desarrollo con Postgres.

### 3. Listas nativas (`String[]` y listas de enum)

Prisma no admite listas escalares en SQLite. Lista exacta actual (16 campos):

- `String[]`: `Save.unlockedRecipeKeys`, `Save.activeCombatAbilityNames`,
  `Save.npcsRetiredForever`, `Location.aliases`, `CombatEncounter.ordenIniciativa`,
  `LoreChunk.tags`, `Quest.rewardItems`, `Quest.rewardRecipeKeys`, `SkillBar.abilityNames`,
  `Npc.aliases`, `NpcState.lootedItemNames`, `ItemCatalog.herramientaParaOficio`,
  `ItemCatalog.aliases`.
- Listas de enum: `SavedAction.effects` (`AbilityEffect[]`), `Npc.interactionTypes`
  (`NpcInteractionType[]`), `Npc.medio` (`MedioMovimiento[]`).

Operaciones de lista que hay que reescribir además de lecturas y escrituras normales:
`npcsRetiredForever: { push: … }` en `turnResolution.ts` y `routes/saves/quests.ts`.

**Solución:** convertir cada campo a `Json` (Prisma admite `Json` en SQLite desde la 6.2) y
adaptar cada sitio que lo lee o escribe. Para no repartir `JSON.parse` por todo el código, se usa
una capa de conversión en `lib/prisma.ts` (extensión de Prisma Client con `result`/`query`) que
presenta los campos como arrays tipados.

### 4. Puntos menores encontrados en la reverificación

| Uso | Dónde | Problema en SQLite | Solución |
|---|---|---|---|
| `mode: 'insensitive'` | `services/turnResolution.ts` (1 uso) | No existe en SQLite | Comparar en JS o guardar el nombre normalizado en minúsculas |
| `createMany({ skipDuplicates: true })` | `routes/saves/detail.ts` (1 uso) | No soportado en SQLite | Recorrer con `upsert`, o `createMany` dentro de un `try` que ignore duplicados |
| Enums de Prisma | Todo el schema (32 enums) | Admitidos en SQLite desde Prisma 6.2 | Nada: el juego ya usa Prisma 6.19.3 (según `package-lock.json`) |
| `$queryRaw\`SELECT 1\`` | `routes/health.ts` | Ninguno | No tocar |

## Lo que NO hay que tocar

El resto del schema y de las consultas de Prisma Client (`findMany`/`update`/transacciones
normales, columnas `Json`, relaciones, índices) funciona igual en SQLite.

## Un schema, con proveedor elegido en el build

Prisma no permite cambiar `provider` del `datasource` por variable de entorno. Decisión:

- Un único `schema.prisma` fuente (el de desarrollo, Postgres).
- Un paso de build del instalador genera `schema.sqlite.prisma` a partir de él: cambia el
  `provider` a `sqlite` y sustituye `Unsupported("vector(768)")` y las listas por `Json`.
- Un test compara los dos para que no se desincronicen.
- Las migraciones de SQLite se generan aparte (`prisma migrate diff`) en la carpeta
  `prisma/migrations-sqlite/`.

Esto mantiene un solo modelo de datos (sin bifurcarlo) y deja la versión de desarrollo intacta.

## Primer arranque: base de datos plantilla

En vez de crear la base de datos vacía y sembrarla en la máquina del jugador:

- El build genera una **base de datos plantilla** `tarkor-plantilla.sqlite` ya migrada, con el
  catálogo del mundo sembrado y los `LoreChunk` ya indexados con `nomic-embed-text`.
- En el primer arranque se **copia** a la carpeta de datos del jugador. Sin red, sin IA, en un
  segundo.
- En cada arranque posterior:
  1. se aplican las migraciones pendientes (actualizaciones de versión);
  2. se ejecuta `seed-catalog` (upserts rápidos, sin red ni IA — lo que ya hace
     `iniciar-tarkor.sh` hoy), que lleva al jugador el contenido nuevo de cada versión sin tocar
     sus partidas;
  3. si el lore cambió en la versión nueva, se reemplazan las filas de `LoreChunk` por las de la
     plantilla (ya indexadas).

Antes de migrar, se hace una copia de seguridad del `.sqlite` del jugador (`tarkor.sqlite.bak`).

## Qué falta

- Implementar los puntos 1-4 en el repo del juego (fase 2 de
  [`05-plan-de-trabajo.md`](05-plan-de-trabajo.md)).
- Pasar la batería de tests del backend (`vitest`) contra SQLite.
