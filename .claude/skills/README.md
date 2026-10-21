# Skills del proyecto

Skills que Claude Code carga en el instalador (local y en las sesiones en la nube). Vienen del repo
del juego (2026-10-21, `FLU-1`), donde se armaron; las notas «En este repositorio» y los `proyecto.md`
están reescritos para el instalador. Cuándo usar cada una:
[`docs/runbooks/skills-y-modelos.md`](../../docs/runbooks/skills-y-modelos.md).

| Skill | Origen |
|---|---|
| `selector`, `orchestrate-dealer`, `opt-tokens` | propias del juego (2026-10-04, `QA-121`, 2026-10-19) |
| `opt-ai` | propia del juego (2026-10-20) |
| `scout-updates` | propia del juego (2026-10-20, `QA-176`) |
| `grilling`, `grill-with-docs`, `domain-modeling`, `diagnosing-bugs`, `codebase-design`, `improve-codebase-architecture`, `retro`, `writing-for-agents`, `pr`, `prototype` | [mattpocock/skills](https://github.com/mattpocock/skills), commit `24fe0ef` (`pr` y `prototype`: `6fd9479`, 2026-10-06), licencia MIT ([`LICENSE-mattpocock-skills`](LICENSE-mattpocock-skills)) |
| `research`, `to-questionnaire` | [mattpocock/skills](https://github.com/mattpocock/skills), commit `5beb35b` (2026-10-20), licencia MIT ([`LICENSE-mattpocock-skills`](LICENSE-mattpocock-skills)) |

Las copiadas se dejan tal cual (en inglés) salvo la nota «En este repositorio» al principio de las
que la necesitan. Para actualizarlas: comparar con el commit nuevo del repositorio original y
conservar esas notas.

Al traer una versión nueva de una skill propia desde el repo del juego: copiar todo salvo su nota «En
este repositorio» y su `proyecto.md`, que son de aquí.
