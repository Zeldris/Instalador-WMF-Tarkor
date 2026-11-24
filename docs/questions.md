# Questions

Questions for the user, one entry each; `python3 .claude/gw/scripts/questions.py` reads and rewrites this
file (format: header of scripts/questions.py). Answer by number: `questions.py answer "5. a, 6. ok"`.

## Q-1
- Refs: FLU-12
- Status: answered
- Asked: 2026-11-18
- Question: Revisión de FLU-12, hallazgo medio: .claude/settings.json tiene dos veces el gancho whole-read.py para Read (la entrada vieja "Read" y la nueva "^(Read|Bash)$"), así que avisa de una relectura en la primera lectura. CLAUDE.md pide preguntar antes de tocar settings.json. ¿a) la quito yo, b) la quitas tú?
- Recommendation: a: sí, la quito yo (la plantilla 0.8.0 solo trae la anclada)
- Answer: a
- Answered: 2026-11-18

## Q-2
- Refs: FLU-12
- Status: answered
- Asked: 2026-11-18
- Question: Revisión de FLU-12, hallazgo medio: AGENTS.md dice que el revisor recibe pendingFile de gw.json, pero el proyecto no lo fija (los pendientes siguen en la bitácora). ¿a) fijar pendingFile = docs/records/pending.md y mover allí los pendientes, b) dejarlos en la bitácora y decir en AGENTS.md que, sin pendingFile, se nombra la sección de pendientes de traspaso.md?
- Recommendation: a: mover los pendientes a docs/records/pending.md (handoff.py move-pending); además baja la bitácora, que es ~5,5k tokens de cada arranque
- Answer: a
- Answered: 2026-11-18

## Q-3
- Refs: FLU-15
- Status: answered
- Asked: 2026-11-24
- Question: ¿En qué rama va la subida a 0.9.0? a) la misma claude/gw-update-0.8.2 (FLU-15 pasa a cubrir 0.9.0) b) rama nueva claude/gw-update-0.9.0 tras fusionar la de 0.8.2
- Recommendation: a) seguir en claude/gw-update-0.8.2: aún no ha ido a main, y un solo PR lleva 0.8.2 y 0.9.0 con una sola ronda de las tres fases
- Answer: a
- Answered: 2026-11-24

## Q-4
- Refs: FLU-15
- Status: answered
- Asked: 2026-11-24
- Question: ¿Aplico apply.py --update? Toca .claude/settings.json (gancho PreToolUse para Read|Grep|Glob|Bash, el aviso de whole-read.py) y .githooks/, que CLAUDE.md pide consultar.
- Recommendation: ok: aplicar --update (83 actualizaciones, 11 nuevos, migración de gw.json al bloque languages y el gancho PreToolUse nuevo en .claude/settings.json)
- Answer: ok
- Answered: 2026-11-24

## Q-5
- Refs: FLU-15
- Status: answered
- Asked: 2026-11-24
- Question: 0.9.0 trae la skill gw-seo (para webs). ¿a) se queda o b) se quita?
- Recommendation: b) quitar gw-seo tras el --update y apuntarlo en gw.json si hay clave para excluirlo: el instalador no es una web y su descripción ocupa contexto en cada arranque
- Answer: b
- Answered: 2026-11-24

## Q-6
- Refs: FLU-15
- Status: answered
- Asked: 2026-11-24
- Question: AGENTS.md: ¿tomo los tres cambios de la plantilla?
- Recommendation: ok: tomar los tres cambios de AGENTS.md (paso 5 con merge-main.py, timeout de 90 min para push y check, /clear también tras un «Siguiente»), con «usuaria» en vez de «persona»
- Answer: ok
- Answered: 2026-11-24

## Q-7
- Refs: FLU-15
- Status: answered
- Asked: 2026-11-24
- Question: CLAUDE.md, REVIEW.md y marcas de versión: ¿tomo los cambios?
- Recommendation: ok: en CLAUDE.md, la línea de idioma nueva (Agent language: / languages.docs.primary); en REVIEW.md, visibleLanguages → languages.ui; y la línea de marca a v0.9.0 en REVIEW, GLOSSARY y las tres notas
- Answer: ok
- Answered: 2026-11-24
