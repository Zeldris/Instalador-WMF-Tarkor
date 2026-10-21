# Bitácora de traspaso

**Para qué:** que cualquier sesión de Claude, de cualquier cuenta, sepa exactamente por dónde va el
trabajo del instalador y pueda seguir. Reglas en [`CLAUDE.md`](../../CLAUDE.md). **Se actualiza en
cada commit.**

---

## Estado actual

| | |
|---|---|
| **Actualizado** | 2026-10-21 |
| **Ramas de trabajo** | Cada sesión, su rama con su fila «Tarea en curso» (`QA-136` de Tarkor): `claude/installer-docs-review-09e7vs`. Las skills, ganchos y `settings.json` de `.claude/` van versionados con `git add` normal; a `main` se pasa **por pull request**. |
| **Último commit en `main`** | Fusión del PR #2 (2026-09-28, `3418c2d`): fases `INS-1`…`INS-6` del plan con pruebas de punta a punta. |
| **Hito** | Fase 0 del [plan](../05-plan-de-trabajo.md): faltan `INS-7` y `INS-8` (necesitan la Steam Deck o un Windows). La fase 2 está hecha en el repo del juego, a falta de fusionar su PR #1. |
| **Tarea en curso · `claude/installer-docs-review-09e7vs`** | `FLU-1` 🚧 traer de Tarkor su flujo de trabajo (CLAUDE.md, bitácora, ganchos, `tools/qa`, runbook, `REVIEW.md`) y sus skills, adaptados al instalador. Hechas las notas de las skills, el job `qa` de la CI y el `/code-review` (arreglado). Falta: `/opt-tokens` y retro antes del PR a `main`. **Siguiente:** `/opt-tokens` y retro (fase 2 antes del PR). |
| **Tests** | 2026-10-21: núcleo `cargo test -p tarkor-nucleo` 52, asistente `vitest` 5, `tsc -b` 0, clippy 0 avisos; `tools/qa/tests` en verde. |

## Dónde está todo (para saber qué sigue)

1. **Esta bitácora**: qué se está haciendo ahora y el paso inmediato.
2. **[Plan de implementación](../05-plan-de-trabajo.md)**: fases 0 a 5 con su casilla y su `INS-n`.
3. **Los documentos de diseño** (`docs/01`…`docs/12`, índice en el [README](../../README.md)).
4. **El asistente y el núcleo**: [`app/README.md`](../../app/README.md) (cómo se compila, se prueba
   y se mide un motor real).
5. **El flujo de trabajo**: [skills y modelos](../runbooks/skills-y-modelos.md) y la guía de
   revisión [`REVIEW.md`](../../REVIEW.md).

## Siguientes pasos (en orden)

1. Terminar `FLU-1`: notas de las skills, job de CI de `tools/qa`, revisión, `/opt-tokens`, retro y
   PR a `main`.
2. Fusionar el PR #1 del repo del juego (fase 2): dos tests intermitentes de
   `routes/turn.integration.test.ts` y endurecer `lib/prisma.test.ts` (detalle en el
   [plan](../05-plan-de-trabajo.md#dónde-lo-dejamos-2026-09-28)).
3. Fase 3 (modo empaquetado del juego, `INS-31`…`INS-37`) y fase 4 (`INS-41`…`INS-47`).
4. `INS-7`, `INS-8` y la fase 5, cuando la usuaria pueda probar en la Steam Deck o en Windows.

## Decisiones de la usuaria que bloquean algo

- Firma de código en Windows (`INS-11`) y licencias (`INS-12`, `INS-15`).
- Perfiles por encima del máximo seguro: bloqueados o con aviso (`INS-14`; propuesta en el README).

## Comandos para comprobar el estado

```bash
cd app && npm test && npx tsc -b                       # asistente (vitest + tipos)
cd app && cargo test -p tarkor-nucleo                  # núcleo (detección, perfiles, catálogo, motor)
cd app && cargo clippy --workspace --all-targets -- -D warnings
python3 -m unittest discover -s tools/qa/tests         # herramientas del flujo
python3 tools/qa/enlaces-md.py                         # enlaces de los .md
# Entorno (dependencias de WebKit, mingw, npm, cargo, core.hooksPath): lo deja listo el gancho de inicio de
#   sesión; a mano, tras un reinicio del contenedor: CLAUDE_CODE_REMOTE=true .claude/hooks/session-start.sh
# Pruebas de punta a punta del asistente (tauri-driver + xvfb): ver app/README.md.
```

## Hecho recientemente

- ~~`INS-1`…`INS-6`, `INS-3b`, `INS-13`, `INS-21`…`INS-27` · renumeradas~~ (2026-10-21): las tareas
  ya hechas del plan llevan ahora su identificador `INS-n` (antes 0.1, 2.1…), para que la bitácora y
  el pre-push las sigan.
