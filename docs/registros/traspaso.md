# Bitácora de traspaso

**Para qué:** que cualquier sesión de Claude, de cualquier cuenta, sepa exactamente por dónde va el
trabajo del instalador y pueda seguir. Reglas en [`CLAUDE.md`](../../CLAUDE.md). **Se actualiza en
cada commit.**

---

## Estado actual

| | |
|---|---|
| **Actualizado** | 2026-10-25 |
| **Ramas de trabajo** | Cada sesión, su rama con su fila «Tarea en curso» (`QA-136` de Tarkor): `claude/installer-docs-review-09e7vs` (rehecha desde `main` el 2026-10-25). Las skills, ganchos y `settings.json` de `.claude/` van versionados con `git add` normal; a `main` se pasa **por pull request**. |
| **Último commit en `main`** | Fusión del PR #7 (2026-10-25, `8566d48`): `INS-49`, con la confirmación de la usuaria. La CI de GitHub no arrancó (pago); `ci-local` en verde sobre `04a37c6`, Windows sin cubrir. |
| **Hito** | Fase 0 del [plan](../05-plan-de-trabajo.md): faltan `INS-7` y `INS-8` (necesitan la Steam Deck o un Windows). La fase 2 está hecha en el repo del juego, a falta de fusionar su PR #1. |
| **Tarea en curso · `claude/installer-docs-review-09e7vs`** | 2026-10-25: `INS-43` cerrada (Rust, frontal y E2E `app/e2e/rendimiento.e2e.mjs`). Fase 1 (code-review) con los medios arreglados (motor, esperas, perfiles inexistentes, avisos y controles); E2E en verde tras los arreglos. Fase 2 hecha: opt-tokens y la [retro](retro-2026-10-25-ins43.md), aprobada entera (`perfilDe()` y check contra `.find(...)!`, `tools/qa/e2e.sh`). Presupuesto: 1 compactación (la tarea lleva 2). Siguiente: fase 3 (revisión de los commits de la fase 2, `revisado.sh`, PR). |
| **Tests** | 2026-10-25: núcleo `cargo test -p tarkor-nucleo` 104, asistente `vitest` 27, `tsc -b` 0, clippy 0 avisos, `cargo check` del núcleo para Windows (mingw) en verde; E2E del asistente con el Ollama falso en verde. |

## Dónde está todo (para saber qué sigue)

1. **Esta bitácora**: qué se está haciendo ahora y el paso inmediato.
2. **[Plan de implementación](../05-plan-de-trabajo.md)**: fases 0 a 5 con su casilla y su `INS-n`.
3. **Los documentos de diseño** (`docs/01`…`docs/12`, índice en el [README](../../README.md)).
4. **El asistente y el núcleo**: [`app/README.md`](../../app/README.md) (cómo se compila, se prueba
   y se mide un motor real).
5. **El flujo de trabajo**: [skills y modelos](../runbooks/skills-y-modelos.md) y la guía de
   revisión [`REVIEW.md`](../../REVIEW.md).

## Siguiente paso y los que vienen (en orden)

1. Fusionar el PR #1 del repo del juego (fase 2): dos tests intermitentes de
   `routes/turn.integration.test.ts` y endurecer `lib/prisma.test.ts` (detalle en el
   [plan](../05-plan-de-trabajo.md#dónde-lo-dejamos-2026-09-28)).
2. Fase 3 (modo empaquetado del juego, `INS-31`…`INS-37`) y fase 4 (`INS-41`…`INS-47`).
3. Pendientes leves de la revisión de `INS-48` (no vuelven a revisarse en su PR): `bloqueado` no descuenta lo
   ya descargado en Ajustes; no se impide mover la carpeta con una descarga en marcha (el asistente hoy no lo
   permite); `Estado::ia()` lee `config.json` en cada llamada; el aviso de restos del origen solo va a stderr;
   con poco disco el paso 3 dice «equipo insuficiente».
4. Pendientes leves de la revisión de `INS-43`: `cambiar_perfil` pone `cancelar` a false y puede deshacer una pausa de otra descarga; `cambiar_perfil` con el motor caído lo arranca primero con el perfil viejo, y si eso falla no prueba el nuevo; no hay test de la pausa de `cambiar_perfil`; los arreglos de `cambiar_perfil`, `reintentar_motor` y `estado_motor` no tienen test (los cubre el E2E del trozo 3); sin test: desmontar antes de que `listen` resuelva, Borrar desactivado mientras borra, Volver desactivado durante el cambio; la lectura de `motor_detenido()` al montar o al acabar un cambio puede borrar un aviso que llegue mientras tanto (conviene un contador de avisos); sin test de que `CopiarInforme` pida el informe cada vez; «Copiar» oculta el texto desplegado mientras carga. Leves de la revisión de la rama contra `origin/main`: `anonimizar` no mira el límite izquierdo del nombre ni los nombres cortos 8.3 de Windows; `leer_final` pierde una línea cuando el corte cae al principio de una, y 200 líneas pueden dejar fuera el «out of memory»; los sobrantes van en GB decimales y la línea de uso en GiB; `modelos_sobrantes` no mira `ocupado`; «Pausar» sale también en fases que no se pueden cancelar; el cierre de la app (`RunEvent::Exit`) espera al Mutex del motor hasta 30 s. De la revisión de sus arreglos: `borrar_modelo` va por la espera de lectura de 10 s (un borrado lento en Windows saldría como error); el cambio de `masLigero` a `evaluacion.perfiles` en `App.tsx` no tiene un test que falle sin él. De la revisión de la fase 2: `task_start` de `recuperar.py` usa la hora del commit de la base y no la de la fusión (con un `main` quieto cuenta compactaciones de antes de la tarea); `sin-find-forzado.py` no ve un `.find(` partido en varias líneas ni `.findLast(...)!`, da falsos positivos con `.find(x)!==y`, excluye cualquier archivo de `app/src` que empiece por «test» y usa `list[str]` (Python 3.9+); `ejemplo.ts` sigue cayéndose con `perfiles` vacío; `tools/qa/e2e.sh` no corre la variante `E2E_ESPERA_ERROR_RED=1` y compila en cada ejecución.
5. Pendientes leves de la revisión de `INS-49` (no vuelven a revisarse en su PR): con un `.completo` vacío (lo
   instalado antes de `INS-49`) el primer Reparar vuelve a bajar el motor aunque esté sano; `alTerminar` de
   Ajustes guarda los modelos del perfil leído al empezar aunque se cambie durante la reparación; el porcentaje
   al reponer un modelo es el de cada capa y vuelve a 0 %; `escribir_sumas` relee todo el motor tras extraerlo
   en vez de sumar al extraer; la lista única de modelos de un perfil está copiada en cuatro sitios (conviene un
   `modelosDe(perfil)` en `catalogo.ts`).
6. `INS-7`, `INS-8` y la fase 5, cuando la usuaria pueda probar en la Steam Deck o en Windows.

## Decisiones de la usuaria que bloquean algo

- **CI de GitHub agotada** (2026-10-22: «recent account payments have failed or your spending limit needs to be
  increased»). La usuaria decide que, hasta que vuelva, se sube de forma manual: antes de ir a `main`,
  `python3 tools/qa/ci-local.py --apuntar` corre en local los jobs de Ubuntu de `comprobar.yml` y lo deja en
  [`ci-local.md`](ci-local.md) con fecha y commit (`FLU-3`). Los tests del núcleo **en Windows** no se pueden correr
  así: quedan pendientes hasta que vuelva la CI. Cuando vuelva, se re-lanza sobre `main`.
- Firma de código en Windows (`INS-11`) y licencias (`INS-12`, `INS-15`).

## Comandos para comprobar el estado

```bash
cd app && npm test && npx tsc -b                       # asistente (vitest + tipos)
cd app && cargo test -p tarkor-nucleo                  # núcleo (detección, perfiles, catálogo, motor)
cd app && cargo clippy --workspace --all-targets -- -D warnings
python3 -m unittest discover -s tools/qa/tests         # herramientas del proyecto
python3 .claude/gw/scripts/enlaces-md.py               # enlaces de los .md
python3 .claude/gw/scripts/doctor.py                   # el flujo (Galivelop-workflow) bien montado
# Entorno (dependencias de WebKit, mingw, npm, cargo): lo deja listo el gancho de inicio de sesión
#   (`install` de .claude/gw.json); a mano, tras un reinicio del contenedor: bash tools/dev/instalar-entorno.sh
# Pruebas de punta a punta del asistente (tauri-driver + xvfb): ver app/README.md.
```

## Hecho (5 últimas)

Dos líneas cada una como mucho; el detalle está en el commit y la más antigua sale cuando hay más de 5.

- ~~`INS-43` · Rendimiento de la IA y motor detenido~~ (2026-10-25): dónde corre la IA, cambiar de perfil con
  borrado de sobrantes, «Copiar informe» y pantalla del motor detenido con vigilancia en Rust.
- ~~`INS-49` · Reparar~~ (2026-10-25): suma de cada archivo del motor y de cada capa de los modelos; reinstala o
  vuelve a pedir solo lo dañado, desde Ajustes y desde la comprobación.
- ~~`INS-48` · Carpeta de la IA elegible y movible~~ (2026-10-25): espacio necesario frente a libre en cada
  tarjeta, «Cambiar carpeta» en el paso 4 y «Mover a otra carpeta» en Ajustes.
- ~~`INS-14` · Perfiles por encima del máximo seguro~~ (2026-10-25): se pueden elegir con aviso y confirmación
  en la tarjeta, sin interruptor; implementado el mismo día.
- ~~`FLU-4` · Galivelop-workflow v0.3.0~~ (2026-10-25): `/gw-update` de scripts, skills y ganchos; `comprobar.yml`
  se queda el local; dos reglas nuevas en `REVIEW.md`.
