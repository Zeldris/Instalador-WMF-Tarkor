# Retro del 2026-10-21: flujo de trabajo traído de Tarkor (`FLU-1`)

**Estado:** aprobadas las cuatro propuestas (usuaria, 2026-10-21); aplicadas en la rama.

Lo revisado: los commits de `FLU-1` en `claude/installer-docs-review-09e7vs` (`ec5016c`…`5e640dd`), el
`/code-review` del diff contra `main` y `/opt-tokens` de la sesión.

## Lo medido (`/opt-tokens`)

- 432 llamadas, 4 compactaciones, contexto medio 378k. El primer tramo llegó a 786k de techo (446k de
  media); los cuatro siguientes, entre 125k y 173k. El tope de 200k de `.claude/settings.json` entró
  con `FLU-1`: la próxima sesión dirá si los tramos se quedan por debajo.
- Lo que más arrastró: documentos de `docs/` leídos enteros (`05-plan-de-trabajo.md` 19 veces,
  `README.md` 10) y 9 capturas.
- Todo en el modelo grande; un solo subagente. La copia y adaptación de las skills era mecánica y no
  pasó por `orchestrate-dealer`.

## Lo que encontró el `/code-review`

Siete de once hallazgos eran de las herramientas traídas, no del instalador: el `pre-push` perdía la
entrada de git, el gancho de `main` comparaba con el checkout y no cubría la fusión automática,
`fusionar.sh` no probaba el catálogo, `enlaces-md.py` no aceptaba anclas con mayúsculas, y la
renumeración a `INS-n` dejó «fase 3.5» en dos documentos. Todos arreglados en la rama.

## Propuestas

1. **Test del gancho de `main`** (comprobación automática). `revision-antes-de-main.sh` solo se probó
   a mano; un `tools/qa/tests/test_revision_main.py` con las entradas probadas (otra base, sin marca,
   marca igual a la rama en GitHub, `update_pull_request` sin base) lo vigila. Coste: un archivo de
   test. Riesgo: ninguno.
2. **Comprobar que no quedan ids viejos del plan** (comprobación automática). Un test en
   `tools/qa/tests` que falle si `docs/` o el `README` citan «fase N.M»: la renumeración a `INS-n` lo
   dejó pasar y solo lo vio la revisión. Coste: un test. Riesgo: ninguno.
3. **Los ganchos de Claude y `settings.json` piden permiso** (información). En modo automático, editar
   `.claude/hooks/` o `.claude/settings.json` lo bloquea el clasificador. Una línea en el runbook
   (`skills-y-modelos.md`, paso 3): pedir permiso a la usuaria antes de tocarlos, en vez de descubrirlo
   al fallar. Coste: una línea. Riesgo: ninguno.
4. **Leer documentos por trozos** (gasto, `opt-tokens/proyecto.md`). Apuntar en los gastos conocidos
   que el plan y el `README` se leen con `grep -n` y `sed -n` del tramo, no enteros: fueron lo que más
   arrastró. Riesgo para la calidad: perder contexto de otra sección; contrapeso, leer entero al
   cambiar la estructura del documento.

## Revisión de lo aplicado

El `/code-review` de los commits de la retro encontró doce cosas. Arregladas: el matcher del gancho de
`main` cogía también `update_pull_request_branch` (ahora anclado, y el gancho solo trata como fusión las
dos herramientas de fusión), `head` como `dueño:rama`, el error de `origin` se muestra, el test de ids
viejos no distinguía mayúsculas ni números de dos cifras, saltaba la bitácora y `.claude/`, y partía
rutas con espacios; y los tests del gancho cubren ahora cambiar la base, fusionar, la fusión automática
y el matcher. Quedan como están: la fusión automática no revisa los commits que lleguen después de
activarla (lo cubriría una protección de rama en GitHub), reabrir un PR sin cambiar la base, los
estados de commit fuera de `check-runs` y que el aviso de permiso de los ganchos sea solo texto.
