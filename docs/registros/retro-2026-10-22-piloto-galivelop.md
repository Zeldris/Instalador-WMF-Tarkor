# Retro del 2026-10-22: piloto de Galivelop-workflow (`FLU-2`)

**Estado:** presentadas a la usuaria (2026-10-22); aprobadas el `/clear` tras el PR y `tools/qa/ci-local.py`
(`FLU-3`, aplicado en la rama); rechazadas las demás.

Lo revisado: los commits de `FLU-2` en `claude/piloto-galivelop-workflow` (`8c0b422`…), la revisión de código del
diff contra `main` (13 hallazgos, [registro del piloto](piloto-galivelop-workflow.md#comprobaciones)) y
`opt-tokens` de la sesión.

## Lo medido (`opt-tokens`)

- Desde `97440ec`: 110 llamadas, contexto medio 118k (tramos de 104k a 123k, techo 144k), 4 compactaciones en el
  periodo y 8 en la sesión, que lleva `FLU-1` y `FLU-2` seguidas.
- Lo que más arrastró: un `tail -c 20000` de la salida cruda de un subagente (77k) y el runbook
  `skills-y-modelos.md`, leído 9 veces (80k).
- La revisión de código, en un subagente con el modelo grande: 21 llamadas y 2,3M de entrada. Se deja así: encontró
  fallos reales del flujo (roces 15-18).

## Propuestas

| Propuesta | Decisión |
| --- | --- |
| `/clear` tras este PR: la sesión relee unos 118k en cada llamada y la bitácora basta para retomar | Aprobada |
| No leer la salida cruda de un subagente, solo su informe (nota en `.claude/gw/opt-tokens.md`) | Rechazada |
| El runbook de skills, por tramos (en «Documentos largos» de `.claude/gw/opt-tokens.md`) | Rechazada |
| `tools/qa/ci-local.py`: corre lo de `comprobar.yml` en local y lo apunta con fecha y commit (CI agotada) | Aprobada: `FLU-3` |
| `REVIEW.md`: los scripts del flujo se revisan y prueban en Galivelop-workflow | Rechazada |
| Runbook: la prueba del paso 6, en una rama de usar y tirar y siempre con los ganchos (se usó `--no-verify` una vez) | Rechazada |
| Roce 19 al flujo: la plantilla de `AGENTS.md` copia el check en vez de apuntar a `.claude/gw.json` | Rechazada |
