# Piloto de Galivelop-workflow v0.2.0 en el instalador (`FLU-2`)

**Fecha:** 2026-10-22 · **Rama:** `claude/piloto-galivelop-workflow` · **Pedido por:** la usuaria, a propuesta de
la sesión que mantiene [Galivelop-workflow](https://github.com/Zeldris/galivelop-workflow).

Se aplicó el flujo siguiendo su `docs/es/aplicar.md` sobre `main` (`97440ec`), que ya traía el flujo de Tarkor
(`FLU-1`). Este registro apunta qué se hizo, qué decidió la usuaria y cada roce encontrado.

## Qué se hizo

- `.claude/gw.json`: `pushToProtected: pr`, `protectedBranch: main`, `language: es`; el check, como el pre-push de
  antes (`tsc`, clippy, enlaces y los tests de `tools/qa` y `tools/banco`); `relatedTests.fast` con
  `tools/qa/tests-app.sh` (`vitest related` del asistente y `cargo test -p tarkor-nucleo` si cambia el núcleo);
  marca de revisión en `docs/registros/revisado.txt` con retro obligatoria; `designReferences`, `taskId`
  (`INS|FLU`), el plan, `staleRefs` con las rutas viejas y un caso de `selector`.
- Scripts del flujo en `.claude/gw/scripts/`: sustituyen a los de `tools/qa` (bitácora, enlaces, fusionar, ramas del
  pre-push, recuperar, revisado, rojo-sin-arreglo) y al gancho de `.claude/hooks/`. Son un superconjunto de los
  viejos: se comprobó antes de borrarlos.
- `.githooks/pre-push` y `pre-commit`, `.claude/settings.json` y las skills: las del flujo. Las notas del proyecto
  pasaron a `.claude/gw/{opt-ai,opt-tokens,scout-updates}.md` y, las de las demás skills, a la sección
  [Notas del proyecto por skill](../runbooks/skills-y-modelos.md#notas-del-proyecto-por-skill) del runbook.
- `AGENTS.md` con las reglas del proyecto; `CLAUDE.md` lo importa. `REVIEW.md` suma las reglas de la plantilla;
  `GLOSSARY.md`, los términos del instalador.
- `tools/banco/` (el banco de calidad de modelos) sale de la skill `scout-updates`, que el flujo trae sin él.
- Nuevos del proyecto: `tools/qa/en-app.sh`, `tools/qa/tests-app.sh` y `tools/dev/instalar-entorno.sh` (el
  `install` del flujo, antes el gancho de inicio de sesión).
- CI: una sola, `comprobar.yml`, con los jobs de Linux y Windows de antes y el job `qa` adaptado, más el pre-commit
  de la rama base sobre el pull request. La plantilla del flujo se descartó: no tiene Rust ni Windows.

## Decisiones de la usuaria

Todas las recomendadas: check como el pre-push; marca en `docs/registros/revisado.txt`; skills del flujo con las
notas aparte; referencias de diseño (Steam, itch.io, Heroic, LM Studio, instalador de Ollama); banco a
`tools/banco/`; `CLAUDE.md` del flujo con las reglas en `AGENTS.md`; pre-push del flujo; CI propia adaptada.

## Para Galivelop-workflow

Roces, en orden de lo que costaron:

1. **El check en el worktree del pre-push no encuentra `app/node_modules` ni el `target` de Cargo.** El worktree
   temporal solo enlaza los `node_modules` de la raíz; en un proyecto con la app en una subcarpeta, `tsc` falla y
   Cargo compila desde cero. Aquí lo arregla `tools/qa/en-app.sh`. Propuesta: una clave `worktreeLinks` (rutas a
   enlazar del checkout principal) o enlazar todo `node_modules` que esté en el índice de `.gitignore`.
2. **`relatedTests` no filtra rutas.** `{files}` lleva todos los archivos cambiados con su ruta completa; cada
   proyecto tiene que escribir un script que filtre y quite el prefijo (`tools/qa/tests-app.sh`). Propuesta: un
   `paths` (regex) y un `cwd` por orden.
3. **La plantilla de CI solo vale para un proyecto de una plataforma y sin Rust.** El instalador necesita Windows y
   `cargo`; se quedó la CI propia y solo se copió el paso del pre-commit de la base. Propuesta: documentar ese paso
   como pieza suelta para CI existentes, en `aplicar.md`.
4. **`doctor.py` pide «Siguiente paso» en singular.** La bitácora tenía «Siguientes pasos» y daba FAIL; se cambió el
   título. Propuesta: aceptar el plural en `NEXT_STEP`.
5. **El `.gitignore` del proyecto ignoraba `.claude/gw*`** (`.claude/*` con excepciones): solo se ve al aplicar.
   `doctor.py` lo detecta (`ignored`), pero `aplicar.md` podría decirlo antes del paso de copiar.
6. **`opt-tokens/scripts/medir.py` viene sin test**, y el test del proyecto que exige test a cada herramienta lo
   paró. Queda como excepción; propuesta: traer su test como el de `opt-ai`.
7. **Las notas por skill del proyecto solo existen para tres skills** (`.claude/gw/{opt-ai,opt-tokens,scout-updates}.md`).
   Las de las demás (`pr`, `retro`, `grilling`…) fueron a un runbook; propuesta: que toda skill lea
   `.claude/gw/<skill>.md` si existe.
8. **Las plantillas dicen «el usuario»** sin opción: hubo que cambiarlo a mano en `AGENTS.md`, `CLAUDE.md` y
   `GLOSSARY.md`. Propuesta: una clave de configuración con el tratamiento.
9. **`staleRefs` revisa también los registros históricos** (`docs/registros/retro-*.md`): solo se salta la bitácora.
   Las rutas viejas tuvieron que escribirse con cuidado para no chocar con lo que cuentan las retros. Propuesta: una
   lista `staleRefsSkip`.
10. **El banco y las evals de `scout-updates` no vienen con el flujo.** Se movieron a `tools/banco/`; vale, pero
    `aplicar.md` no dice qué hacer con los archivos de una skill que el flujo sustituye.
11. **`install` solo corre cuando cambian los lockfiles** (o en un contenedor nuevo): un paquete de sistema que falta
    no se reinstala hasta entonces. Se apuntó en `tools/dev/instalar-entorno.sh` cómo correrlo a mano.
12. **Los ganchos viejos de `settings.json` hubo que quitarlos a mano**, y la CLI de `recuperar.py` cambió
    (`--estado`, `--buscar`, `--sesion`): las referencias del proyecto se buscaron con `git grep`.
13. **Leer el repo del flujo pidió `add_repo`** en la nube, y su respuesta sugiere registrarlo como raíz, lo que
    cargaría su `CLAUDE.md`; aquí no se registró. `aplicar.md` podría avisarlo.

## Estado

**Estado:** en curso. Falta la CI de la rama, la prueba del paso 6 y el informe a la usuaria.
