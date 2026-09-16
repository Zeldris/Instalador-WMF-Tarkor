# Migración de Postgres a SQLite

**Estado: decidido — investigación de viabilidad ya hecha, queda por implementar.** Origen: este
documento amplía `docs/20-instalador-distribuible.md` del repo `World-Maker-Fantasy`
(2026-08-20), donde se auditó el `schema.prisma` completo y el código real
(`grep` de `$queryRaw`/`$executeRaw` en `backend/src`) para ver cuánto del motor depende de verdad
de Postgres en vez de SQL genérico. La conclusión de esa auditoría: la dependencia es superficial —
tres puntos concretos, nada más.

## Por qué SQLite y no Postgres embebido

Se consideró bundlear un binario portable de Postgres dentro del instalador (evitaría tocar el
schema y las dos queries de vector), pero se descartó: complica el empaquetado por plataforma y no
resuelve el problema de raíz, porque seguiría haciendo falta compilar/distribuir la extensión
pgvector junto al binario, que no siempre trae extensiones de terceros de serie. La migración a
SQLite es acotada (los tres puntos de abajo), así que no compensa la complejidad extra.

## Los tres puntos de fricción

### 1. pgvector (el más importante)

`LoreChunk.embedding` y `SessionFact.embedding` son `Unsupported("vector(768)")` en el schema — la
extensión `pgvector`, habilitada a mano (`CREATE EXTENSION vector`), no gestionada por Prisma. Se
usa en exactamente dos sitios con SQL crudo:

- `backend/src/services/retrieval.ts` (~líneas 31-36) — RAG de lore: `ORDER BY embedding <=>
  ${queryLiteral}::vector`.
- `backend/src/services/worldFacts.ts` (~líneas 104-143) — recuperación de `SessionFact` por
  relevancia, mismo operador `<=>` (distancia coseno).

SQLite no tiene pgvector. Pero Tarkor es un juego de un solo jugador, local: las tablas con
embeddings son pequeñas POR PARTIDA (cientos de filas, no millones) — no hace falta una extensión de
base de datos para esto.

**Solución:** guardar el embedding como JSON (array de 768 floats) y calcular la similitud coseno en
memoria, en JS, al leer las filas candidatas. A esa escala el coste es insignificante; se pierde el
índice `ivfflat`/`hnsw` de pgvector, pero nunca llegó a hacer falta un índice para este volumen de
datos.

### 2. Un `SELECT ... FOR UPDATE`

`backend/src/routes/saves/progression.ts` (~línea 46) usa `FOR UPDATE` para bloquear la fila de
`Save` mientras se resuelve una subida de atributo — arregla un bug real (doble clic/doble pestaña
duplicando el gasto de un punto de ascenso). `FOR UPDATE` es sintaxis estándar SQL que SQLite no
soporta igual (bloquea la base de datos entera, no por fila).

**Solución:** en un instalador de escritorio de un solo proceso local, el problema que este candado
resolvía deja de existir de la misma forma — ya no hay dos pestañas de navegador hablando con un
servidor compartido por red, solo un proceso local. Se sustituye por un mutex en memoria (un `Map`
de locks por `saveId`, o una cola de promesas) — más simple que el original, no un downgrade.

Nota: si el mismo motor sigue sirviendo también la versión web/de desarrollo con Postgres, hay que
decidir si este cambio se hace condicional al motor de base de datos activo, o si el mutex en
memoria sustituye al `FOR UPDATE` en los dos casos (más simple de mantener, un solo camino de
código) — ver [`05-plan-de-trabajo.md`](05-plan-de-trabajo.md).

### 3. Columnas de array nativo

Varios campos `String[]`/`AbilityEffect[]` en el schema (`World.factions`, `Location.aliases`,
`Save.unlockedRecipeKeys`, `LoreChunk.tags`, `SavedAction.effects`, `Quest.rewardItems`,
`Quest.rewardRecipeKeys`, `Npc.aliases`, `Building.lootedItemNames`,
`CraftingRecipe.herramientaParaOficio`, `HarvestYield.aliases`, y algún otro — correr
`grep -n '\[\]$' prisma/schema.prisma` en el repo del juego para la lista exacta y actualizada al
momento de implementar esto, puede haber cambiado). Prisma no soporta listas escalares nativas
contra SQLite.

**Solución:** convertir cada uno a un campo `String` con JSON serializado a mano — mismo patrón que
ya usan varios campos `Json` del propio schema, no es una técnica nueva en este código. Implica una
migración de schema + arreglar cada sitio que lee/escribe esos campos.

## Lo que NO hay que tocar

El resto del schema es SQL estándar sin nada específico de Postgres: todas las columnas `Json`
(bonificadores, atributos, agenda del mundo...), todos los enums, todas las relaciones e índices
normales, y el resto de queries de Prisma Client (`findMany`/`update`/transacciones normales) —
funciona igual contra SQLite sin cambios.

## ¿Un schema o dos?

Pendiente de decidir cuando se implemente: si se mantienen dos `schema.prisma` (uno para desarrollo
con Postgres, otro para la build empaquetada con SQLite) o uno solo con el `datasource`
parametrizado por variable de entorno. Ver [`05-plan-de-trabajo.md`](05-plan-de-trabajo.md), paso 4.

## Primer arranque del instalador

El `.sqlite` local se crea en el primer arranque de la app — equivalente a correr
`prisma migrate deploy` empaquetado dentro del propio binario/sidecar, sin que el jugador tenga que
ejecutar nada a mano. El catálogo del mundo (NPCs, ubicaciones, objetos, fauna/flora, imágenes ya
generadas) tiene que venir pre-sembrado dentro del paquete, no generado en el primer arranque del
jugador — ver [`06-inventario-exclusiones.md`](06-inventario-exclusiones.md) sobre por qué los
scripts de siembra (`seed-catalog`, `reindex-lore`, `seed-image-prompts`) son herramientas de
desarrollo que no deben ejecutarse en la máquina del jugador.
