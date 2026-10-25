<!-- galivelop-workflow v0.3.0 -->
@AGENTS.md

## Solo para Claude Code

- Responde en el idioma del proyecto (`es`).
- Al empezar cada tarea, di en una línea qué skill y qué modelo pide el caso, con la skill `selector`. El modelo de
  la sesión lo elige la usuaria; los subagentes, el más barato que haga bien el trabajo.
- Antes de ir a `main`: `/code-review --max-findings all` del diff contra
  `origin/main`, con el criterio de `REVIEW.md` (fase 1 de las tres de `AGENTS.md`).
- Lo mecánico, a subagentes con modelos baratos (`orchestrate-dealer`); la sesión principal planea, decide y revisa.
- **Compactación:** `.claude/settings.json` fija la ventana de compactación automática. Tras una compactación o un
  `/clear`, el gancho de inicio corre `python3 .claude/gw/scripts/recuperar.py --estado`, que devuelve el estado de
  la bitácora y los últimos commits; un detalle perdido se busca con
  `python3 .claude/gw/scripts/recuperar.py --buscar "<texto>"`. Lo que tenga que sobrevivir va a `docs/registros/traspaso.md`.
- **El modo automático** puede pedir permiso para editar `.claude/settings.json`, `.claude/gw/scripts/` y `.githooks/`:
  pregunta a la usuaria antes de tocarlos, o deja que haga ella el cambio.
