# Formato de `propuestas.md`

Registro acumulativo de todo lo que `scout-updates` ha propuesto. **Nada se borra**: es lo que evita reproponer lo
establecido o lo ya rechazado.

```markdown
# Propuestas · <proyecto>

Registro acumulativo de `scout-updates`. Nada se borra.

| Id | Fecha | Componente | Propuesta | Fuente (consulta) | Estado |
|---|---|---|---|---|---|
| P-001 | 2026-10-20 | narrador | `modelo-a` → `modelo-b` (Probar, probable) | <url> (2026-10-20) | propuesta |
```

- **Id**: `P-` y número correlativo; el siguiente al mayor que haya.
- **Propuesta**: actual → propuesto, con el anillo y la fuerza de la tarjeta.
- **Estados**:
  - `propuesta`: en el informe, sin decidir.
  - `aceptada`: la usuaria la aprueba; se añade la tarea que la aplica (p. ej. `aceptada → QA-180`).
  - `aplicada`: la tarea está cerrada.
  - `rechazada: <motivo>`: el motivo es obligatorio; es lo que se comprueba para reabrirla.
  - `superada por P-n`: otra la sustituye; la vieja se queda, no se reescribe.
- **Reabrir** una rechazada: solo si su motivo ya no se cumple. Se añade una fila nueva que la cita
  (`reabre P-002: el presupuesto ya no es 20 €/mes`), y la vieja pasa a `superada por P-n`.
- **No repetir**: antes de proponer, busca el componente y el candidato en la tabla. Si ya está vivo (`propuesta`,
  `aceptada`) solo se actualiza si hay evidencia nueva, en la misma fila (fuente y fecha nuevas).
