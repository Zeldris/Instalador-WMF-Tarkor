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
| **Último commit en `main`** | Fusión del PR #6 (2026-10-25, `14f55ce`): `INS-14`, `INS-48` y `FLU-4`. La CI de GitHub no arrancó (pago); `ci-local` en verde sobre `7276a43`, Windows sin cubrir. |
| **Hito** | Fase 0 del [plan](../05-plan-de-trabajo.md): faltan `INS-7` y `INS-8` (necesitan la Steam Deck o un Windows). La fase 2 está hecha en el repo del juego, a falta de fusionar su PR #1. |
| **Tarea en curso · `claude/installer-docs-review-09e7vs`** | ✅ 2026-10-25: PR #6 fusionado en `main` con la confirmación de la usuaria; la rama se rehace desde `main`. Siguiente: `/clear` y después `INS-49` («Reparar») o la fase 3 del plan. |
| **Tests** | 2026-10-25: núcleo `cargo test -p tarkor-nucleo` 70, asistente `vitest` 10, `tsc -b` 0, clippy 0 avisos, `cargo check` del núcleo para Windows (mingw) en verde. |

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
4. `INS-7`, `INS-8` y la fase 5, cuando la usuaria pueda probar en la Steam Deck o en Windows.

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

- ~~`INS-48` · Carpeta de la IA elegible y movible~~ (2026-10-25): espacio necesario frente a libre en cada
  tarjeta, «Cambiar carpeta» en el paso 4 y «Mover a otra carpeta» en Ajustes.
- ~~`INS-14` · Perfiles por encima del máximo seguro~~ (2026-10-25): se pueden elegir con aviso y confirmación
  en la tarjeta, sin interruptor; implementado el mismo día.
- ~~`FLU-4` · Galivelop-workflow v0.3.0~~ (2026-10-25): `/gw-update` de scripts, skills y ganchos; `comprobar.yml`
  se queda el local; dos reglas nuevas en `REVIEW.md`.
- ~~`FLU-3` · CI en local~~ (2026-10-22): `tools/qa/ci-local.py` corre los jobs de Ubuntu de `comprobar.yml` y
  apunta el resultado en [`ci-local.md`](ci-local.md) mientras la CI de GitHub está agotada.
- ~~`FLU-1` · flujo de trabajo y skills de Tarkor~~ (2026-10-21): `CLAUDE.md`, `REVIEW.md`, bitácora,
  ganchos de sesión, pre-push y de antes de `main`, `tools/qa` con sus tests (job `qa` de la CI) y las
  skills con notas para el instalador; [retro](retro-2026-10-21-flujo.md) aplicada.
- ~~`INS-1`…`INS-6`, `INS-3b`, `INS-13`, `INS-21`…`INS-27` · renumeradas~~ (2026-10-21): las tareas
  ya hechas del plan llevan ahora su identificador `INS-n` (antes 0.1, 2.1…), para que la bitácora y
  el pre-push las sigan.
