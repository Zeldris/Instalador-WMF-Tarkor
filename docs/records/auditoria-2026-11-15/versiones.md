# Propuesta: trabajar por versiones (2026-11-15)

**Confirmada por la usuaria el 2026-11-15** (ver «Decisiones» al final). Pedido: «a partir de ahora todo versionado, gestionado por release como
galivelop-workflow y galivelop-image-generator»; rehacer la fase 2 y meter las 10 propuestas del
[README](README.md) en el plan.

## Cómo lo hacen los dos repos (resumen de un subagente, solo lectura)

- **Workflow:** `docs/roadmap.md` con una sección por versión (`` ## `0.6` «Medir» ``) y una tabla
  `| Id | Tarea | Estado |` (última celda `pendiente` / `en curso` / `hecho (fecha; nota)`), más
  `## Después, sin versión`. `roadmapFiles` en `.claude/gw.json` lo conecta con `roadmap.py show/list/done`;
  `plan`/`refsSources` validan los `Refs:`. Rama `version/X.Y.0` por menor (`releaseCheckBranches`), tag `vX.Y.Z`,
  `CHANGELOG.md` Keep a Changelog, `release.yml` disparado por el tag, retro y `handoff.py archive` al cerrar.
  Reglas: solo la última menor publicada recibe parches; lo nuevo va a la siguiente menor libre.
- **image-generator:** sin roadmap; versión en un solo archivo, `CHANGELOG` con `[Unreleased]` que llena cada PR,
  `releases.py bump/notes/verify-tag` y `release.yml` por tag. Sin ramas de versión.
- `roadmap: true` no activa nada (clave reservada); lo que cuenta es `roadmapFiles`.

## Propuesta para el instalador

Mezcla de los dos: roadmap con tablas del workflow (`roadmap.py`) y versión única + `CHANGELOG` + `release.yml` por
tag del generador. La versión vive en `app/src-tauri/tauri.conf.json`; un script la copia a `package.json` y
`Cargo.toml`. `docs/05-plan-de-trabajo.md` pasa a ser el roadmap (secciones por versión, tablas, ids `INS-n`); las
casillas hechas se quedan como historial de la `0.1`.

| Versión | Nombre | Tareas |
|---|---|---|
| `0.1.0` | «Asistente» | Lo ya fusionado en `main` (fases 0, 1, 4 hechas). Tag retroactivo sobre `9fce3d1`. |
| `0.2` | «Versiones» | **FLU-10** roadmap, `roadmapFiles`, versión única, `CHANGELOG`, `release.yml` por tag (sin binarios todavía). Corregir plan y bitácora sobre el PR #1. |
| `0.3` | «Base de datos» | **INS-60** rehacer la fase 2 (SQLite) sobre `main` del juego, con test de humo en su CI (prop. 1). **INS-61** INS-35/36 + rutas empaquetadas: Modelfile y `uploads` (prop. 2). **INS-62** inventario `06` al día (prop. 3). INS-35, INS-36, INS-37. |
| `0.4` | «Solidez» | **INS-63** E2E en el CI (prop. 4). **INS-64** Dependabot + `cargo audit`/`npm audit` (prop. 5). **INS-65** mutex sin pánico, partir `lib.rs`, errores tragados (prop. 6). |
| `0.5` | «Marca» | INS-56 (absorbe la prop. 9: oro, tokens, estilos en línea, errores/cargas comunes). **INS-66** accesibilidad (prop. 7). **INS-67** fuentes `latin`/`latin-ext` woff2 (prop. 8). INS-58. |
| `0.6` | «Publicar» | INS-11 con la prop. 10 (firma y actualizador). INS-41, INS-46 (release con instaladores y `SHA256SUMS`), INS-12, INS-15. |
| `1.0` | «Prueba real» | INS-7, INS-8, INS-51…55. |

Ids: INS-60…67 nuevos (el último usado es INS-59); FLU-10 nuevo. La prop. 9 entra en INS-56 y la 10 en INS-11, sin id
propio, para no duplicar.

## Decisiones que hacen falta

1. ¿Vale el reparto y los nombres de versión?
2. ¿Ramas `version/0.X.0` con PR por tarea hacia ella (workflow) o PR por tanda a `main` y versión al cerrar
   (generador)? Propuesta: la del generador, más simple para un solo frente.
3. Tocar `.claude/gw.json` (`roadmapFiles`, `plan`, `refsSources`): es configuración del flujo.

**Respuestas (2026-11-15):** 1) el reparto y los nombres valen tal cual; 2) PR por tanda a `main`, con
`CHANGELOG` `[Unreleased]` y tag al cerrar la versión (como el generador), sin ramas `version/`; 3) se puede tocar
`.claude/gw.json` (`roadmapFiles`, `plan`, `refsSources`).
