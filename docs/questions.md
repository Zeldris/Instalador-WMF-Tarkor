# Questions

Questions for the user, one entry each; `python3 .claude/gw/scripts/questions.py` reads and rewrites this
file (format: header of scripts/questions.py). Answer by number: `questions.py answer "5. a, 6. ok"`.

## Q-1
- Refs: FLU-12
- Status: open
- Asked: 2026-11-18
- Question: Revisión de FLU-12, hallazgo medio: .claude/settings.json tiene dos veces el gancho whole-read.py para Read (la entrada vieja "Read" y la nueva "^(Read|Bash)$"), así que avisa de una relectura en la primera lectura. CLAUDE.md pide preguntar antes de tocar settings.json. ¿a) la quito yo, b) la quitas tú?
- Recommendation: a: sí, la quito yo (la plantilla 0.8.0 solo trae la anclada)

## Q-2
- Refs: FLU-12
- Status: open
- Asked: 2026-11-18
- Question: Revisión de FLU-12, hallazgo medio: AGENTS.md dice que el revisor recibe pendingFile de gw.json, pero el proyecto no lo fija (los pendientes siguen en la bitácora). ¿a) fijar pendingFile = docs/records/pending.md y mover allí los pendientes, b) dejarlos en la bitácora y decir en AGENTS.md que, sin pendingFile, se nombra la sección de pendientes de traspaso.md?
- Recommendation: a: mover los pendientes a docs/records/pending.md (handoff.py move-pending); además baja la bitácora, que es ~5,5k tokens de cada arranque
