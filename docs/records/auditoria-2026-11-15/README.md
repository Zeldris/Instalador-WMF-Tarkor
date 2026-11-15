# Auditorías del 2026-11-15

Tres auditorías de solo lectura con subagentes, sobre la rama `claude/installer-docs-review-09e7vs`. Nada de esto
entra en el plan hasta que la usuaria lo decida.

- [Lo que exige el repo del juego](requisitos-del-juego.md)
- [Marca y estilos del front](marca-y-estilos.md)
- [Deuda técnica](deuda-tecnica.md)

## Propuesta de tareas (pendiente de decidir)

| Prioridad | Propuesta | Origen |
|---|---|---|
| 1 | Rehacer la fase 2 (SQLite) sobre `main` actual del juego: el PR #1 está cerrado sin fusionar, y han aparecido `hasSome`, jsonb `?|`, `pg_advisory_xact_lock` y más. Con test de humo contra SQLite en el CI del juego. Corregir plan y bitácora. | juego 1-2 |
| 2 | INS-35/36 (CORS, `127.0.0.1`, narrador) y rutas empaquetadas: Modelfile y `uploads` | juego 3, 8, 9 |
| 3 | Inventario `06` al día: variables nuevas (`IA_REGISTRO`/`IA_CASOS` desactivadas), defectos de `env.ts`, `sync-item-catalog`, imágenes 464 MB | juego 4-7 |
| 4 | E2E en el CI | deuda 1 |
| 5 | Dependabot + `cargo audit`/`npm audit` | deuda 11 |
| 6 | Ayudante de mutex sin pánico; partir `lib.rs`; errores tragados (`carpetas.rs`, `App.tsx:38`) | deuda 3-7 |
| 7 | Accesibilidad: contraste del botón principal y textos tenues, bordes, `progressbar`, foco del `.seg`, tamaños para la Deck | marca 2, 4-6, 12 |
| 8 | Fuentes: solo `latin`/`latin-ext` en woff2 (~200 KB) | marca, recursos |
| 9 | Con INS-56: oro, tokens de escala, estilos en línea, errores y cargas comunes | marca 1, 7-8 |
| 10 | Decidir firma y actualizador (INS-11) | deuda 2 |
