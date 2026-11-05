# Retro del 2026-11-05: licencia MIT (`INS-12`) antes de `main`

**Estado:** presentada a la usuaria el 2026-11-05: aprobadas P1 a P5. Todas son del flujo y quedan propuestas en
«For Galivelop-workflow»; en este repo, P3 y P4 ya están aplicadas a mano (`8edd0a2`).

Lo revisado: la tarea de la licencia MIT (`e6d33d8`) y la fase 1 sobre todo el diff de la rama contra `origin/main`
(`FLU-7`, `INS-35` a `INS-37` e `INS-12`: 152 archivos, +14,6k líneas). La revisión dio 12 hallazgos. Siete se
arreglaron en `8edd0a2`; los leves, al punto 15 de la bitácora.

## Lo medido (`gw-opt-tokens`, la última hora)

- Sesión principal: 27 llamadas, sin compactar, contexto medio 97k (suelo 74k, techo 119k), 2,6M de entrada.
- `/code-review`: un subagente con el modelo grande, 22 llamadas y 2,3M de entrada, **el 47 % del total** (4,9M). Para
  un cambio de 25 líneas, casi todo fue revisar `FLU-7`, que llevaba en la rama desde el 2026-11-04 sin ir a `main`.
- Lo que más arrastró en la principal: la lectura de las licencias de los otros dos repos (52k) y las secciones de `08`
  y del plan (44k). La bitácora se rehízo una vez porque la fila pasó de 600 caracteres: la escribí con un reemplazo
  de Python en vez de con `handoff.py set-row`, que ya está apuntado en las notas de `gw-opt-tokens`.

## Propuestas

**P1 (tokens, general).** Un `/gw-update` va a `main` en su propio PR nada más terminarlo, antes de la siguiente tarea.
Así su revisión se hace una vez y sobre lo suyo, y no se suma al primer cambio pequeño que venga detrás. Qué cambia: el
último paso de la skill `gw-update` («abre el PR a la rama protegida antes de seguir»). Coste: una línea. Riesgo para
la calidad: ninguno; la revisión es la misma, pero llega antes. Ahorro: aquí habría sido ~2M.

**P2 (revisión, general).** Los archivos copiados del flujo (`.claude/gw/scripts/`, `.claude/skills/gw-*`, los ganchos)
ya se revisan en Galivelop-workflow. El `/code-review` del proyecto revisaría solo lo que difiere de la versión
publicada del flujo, más la configuración propia (`gw.json`, los workflows, `AGENTS.md`). Qué cambia: una lista
`vendored` en `gw.json` que lea la revisión. Riesgo: una edición local de un archivo copiado se colaría sin revisar.
Contrapeso: la revisión compara cada uno de esos archivos con la versión publicada y revisa entero el que difiera.

**P3 (comprobación automática, general).** Al partir el CI en `FLU-7`, los tests de los scripts de las skills dejaron
de correr sin que nada avisara. Solo lo vio la revisión. `doctor.py` (y el final de `gw-update`) avisaría de cualquier
carpeta con `test_*.py` que no cubra ninguna orden de `check`. Riesgo: ninguno. Aquí ya está arreglado (`8edd0a2`).

**P4 (comprobación automática, general).** Quedaron nombres viejos de la migración (`orchestrate-dealer`, `opt-ai.md`,
`tools/qa/ci-local.py`) porque `staleRefs` no los tenía. `gw-update` añadiría a `staleRefs` las rutas y los nombres que
renombra su propia migración. Riesgo: ninguno. Aquí ya se añadieron a mano (`8edd0a2`).

**P5 (plantilla del CI, general).** En el `check.yml` del flujo, `setup-node` mira `package.json` solo en la raíz (aquí
está en `app/`) y no hay `rust-cache`. Además, ni `check.yml` ni `app.yml` corren en `main`. Se propone al flujo una
clave de directorios de Node y Rust y la caché de Rust; lo de `main` queda como pregunta de diseño. Riesgo: ninguno.

## For Galivelop-workflow

- P1: último paso de `gw-update`, el PR a la rama protegida antes de seguir con otra tarea.
- P2: lista `vendored` en `gw.json` para que `/code-review` revise solo lo que difiere de la versión publicada.
- P3: `doctor.py` avisa de carpetas con `test_*.py` que ninguna orden de `check` cubre.
- P4: `gw-update` añade a `staleRefs` lo que renombra su migración.
- P5: `check.yml` con directorios de Node y Rust configurables y `Swatinem/rust-cache`; decidir si corre en `main`.
- `review-before-main.sh` no reconoce las líneas de `ci-local.md` del formato anterior (`· en verde`).
- El paso del CI que corre el `pre-commit` de la rama base sobre el PR marcó como secreto el comentario de
  `PATHCODE` en `.githooks/pre-commit` (un par ruta-código entre comillas): el gancho anterior a v0.5.0 no descarta ese
  par. Aquí se le añadió `gw-allow-secret` (2026-11-05, con permiso de la usuaria); el flujo debería traer el
  comentario ya marcado, o sin un ejemplo que parezca un secreto, para que el primer PR de cada proyecto que se
  actualice no salga en rojo.
