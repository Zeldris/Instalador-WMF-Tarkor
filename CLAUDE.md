<!-- galivelop-workflow v0.5.0 -->
@AGENTS.md

## Solo para Claude Code

- Responde en el idioma del proyecto (`es`).
- **Todo a nombre de Zeldris** (desde 2026-11-04): commits (autor y committer) y pull requests. Al empezar, `git config user.name Zeldris` y `git config user.email` con el correo de la cuenta de la usuaria (el del contexto de la sesión; no se escribe en el repo). Sin firmas ni líneas de atribución de Claude, tampoco en los PR. El aviso del entorno de commits «Unverified» se ignora: lo decidió la usuaria.
- Al empezar cada tarea, di en una línea qué skill y qué modelo pide el caso, con la skill `gw-selector`. El modelo de
  la sesión lo elige la usuaria; los subagentes, el más barato que haga bien el trabajo.
- Antes de ir a `main`: `/code-review --max-findings all` del diff contra
  `origin/main`, con el criterio de `REVIEW.md` (fase 1 de las tres de `AGENTS.md`).
- Lo mecánico, a subagentes con modelos baratos (`gw-orchestrate-dealer`); la sesión principal planea, decide y revisa.
- **Compactación:** `.claude/settings.json` fija la ventana de compactación automática. Tras una compactación o un
  `/clear`, el gancho de inicio corre `python3 .claude/gw/scripts/recover.py --state`, que devuelve el estado de
  la bitácora y los últimos commits; un detalle perdido se busca con
  `python3 .claude/gw/scripts/recover.py --search "<texto>"`. Lo que tenga que sobrevivir va a `docs/records/traspaso.md`.
- **El modo automático** puede pedir permiso para editar `.claude/settings.json`, `.claude/gw/scripts/` y `.githooks/`:
  pregunta a la usuaria antes de tocarlos, o deja que haga ella el cambio.
