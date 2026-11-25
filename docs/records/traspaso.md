# Bitácora de traspaso

**Para qué:** que cualquier sesión de Claude, de cualquier cuenta, sepa exactamente por dónde va el
trabajo del instalador y pueda seguir. Reglas en [`CLAUDE.md`](../../CLAUDE.md). **Se actualiza en
cada commit.**

---

## Estado actual

| | |
|---|---|
| **Actualizado** | 2026-11-25 |
| **Ramas de trabajo** | Cada sesión, su rama con su fila «Tarea en curso» (`QA-136` de Tarkor): `claude/installer-docs-review-09e7vs` (rehecha desde `main` el 2026-10-26). Las skills, ganchos y `settings.json` de `.claude/` van versionados con `git add` normal; a `main` se pasa **por pull request**. |
| **Último commit en `main`** | Fusión del PR #16 (2026-11-12, `5d3fcf3`): `INS-44`, `INS-45` e `INS-57` (borrar datos al desinstalar en Windows y Linux, hoja de estilos), con la confirmación de la usuaria y el CI de GitHub en verde. |
| **Hito** | Fase 0 del [plan](../05-plan-de-trabajo.md): faltan `INS-7` y `INS-8` (necesitan la Steam Deck o un Windows). La fase 2 (SQLite) no está en el juego: su PR #1 se cerró sin fusionar y se rehace en `INS-60`. |
| **Tarea en curso · `claude/installer-docs-review-09e7vs`** | INS-68 en curso: hechos A (c9d7a15), B (5d086d9), C1 (a1930c9, 16fc6e1), C2 (84612a6) y el arreglo de PDEATHSIG (0d33ae7). Revisión de bloque hecha: 0 graves, 3 leves a pending.md; de los 3 medios, el backoff de esperaRed.ts arreglado y subido; faltan vigilancia/cierre con cerrando y cambiar_perfil (en arreglo, Rust) con Findings: 3. Luego la línea de uso en GiB (en Rust) y tachar los puntos 4–9, 18, 19 y 22. Presupuesto de compactaciones: 2. |
| **Tarea en curso · `claude/gw-update-0.8.0`** | Al fusionarse, rama terminada: no queda nada pendiente en ella. |
| **Tarea en curso · `claude/flu-13-ledger-ci`** | Rama abandonada sin fusionar: `FLU-13` la cerró `FLU-15` (v0.8.2 del flujo). |
| **Tarea en curso · `claude/gw-update-0.8.1`** | Al fusionarse, rama terminada: no queda nada pendiente en ella. |
| **Tarea en curso · `claude/gw-update-0.8.2`** | Al fusionarse, rama terminada: no queda nada pendiente en ella. |
| **Tests** | 2026-11-12: núcleo `cargo test -p tarkor-nucleo` 149 y el check del proyecto en verde. Asistente `vitest` y E2E con el Ollama falso: último verde el 2026-10-25 (`vitest` 27 entonces). |

## Dónde está todo (para saber qué sigue)

1. **Esta bitácora**: qué se está haciendo ahora y el paso inmediato.
2. **[Plan de implementación](../05-plan-de-trabajo.md)**: fases 0 a 5 con su casilla y su `INS-n`.
3. **Los documentos de diseño** (`docs/01`…`docs/13`, índice en el [README](../../README.md)).
4. **El asistente y el núcleo**: [`app/README.md`](../../app/README.md) (cómo se compila, se prueba
   y se mide un motor real).
5. **El flujo de trabajo**: [skills y modelos](../runbooks/skills-y-modelos.md) y la guía de
   revisión [`REVIEW.md`](../../REVIEW.md).

## Siguiente paso y los que vienen (en orden)

**En `main`** (2026-11-16): PR #20 (INS-63…INS-67) fusionado con el CI en verde, con la confirmación de la usuaria.

**Para revisar en local** (2026-11-15, decisión de la usuaria: en la nube solo lo que no toca otros repos): `INS-60`, `INS-61`, `INS-62`, `INS-35`, `INS-36` e `INS-37` necesitan el repo del juego; `INS-56` espera a `UX-40` del juego; `INS-7` e `INS-8`, la Steam Deck o un Windows. En la nube se sigue con la `0.4` («Solidez»: `INS-64`, `INS-63`, `INS-65`) y lo del instalador de la `0.5` (`INS-66`, `INS-67`).

1. `INS-60`: rehacer la fase 2 (SQLite) sobre el `main` actual del juego; el PR #1 se cerró sin fusionar
   (detalle en el [plan](../05-plan-de-trabajo.md)).
2. Fase 3 (modo empaquetado del juego, `INS-31`…`INS-37`) y fase 4 (`INS-41`…`INS-47`, e `INS-56`: la marca de Tarkor en el asistente cuando el juego fusione `UX-40`; `INS-58`: colocar las imágenes de [`13`](../13-hoja-de-estilos-e-imagenes.md) cuando el generador las entregue).
3. `INS-7`, `INS-8` y la fase 5, cuando la usuaria pueda probar en la Steam Deck o en Windows.

## Pendiente

Lo pendiente está en [`docs/records/pending.md`](pending.md); se añade y se quita allí.

## Decisiones de la usuaria que bloquean algo

- Firma de código en Windows (`INS-11`) y licencias (`INS-12`, `INS-15`).

## Comandos para comprobar el estado

```bash
cd app && npm test && npx tsc -b                       # asistente (vitest + tipos)
cd app && cargo test -p tarkor-nucleo                  # núcleo (detección, perfiles, catálogo, motor)
cd app && cargo clippy --workspace --all-targets -- -D warnings
python3 -m unittest discover -s tools/qa/tests         # herramientas del proyecto
python3 .claude/gw/scripts/md-links.py                 # enlaces de los .md
python3 .claude/gw/scripts/doctor.py                   # el flujo (Galivelop-workflow) bien montado
# Entorno (dependencias de WebKit, mingw, npm, cargo): lo deja listo el gancho de inicio de sesión
#   (`install` de .claude/gw.json); a mano, tras un reinicio del contenedor: bash tools/dev/instalar-entorno.sh
# Pruebas de punta a punta del asistente (tauri-driver + xvfb): ver app/README.md.
```

## Hecho (5 últimas)

Dos líneas cada una como mucho; el detalle está en el commit y la más antigua sale cuando hay más de 5.

- ~~`INS-47` · Licencias de terceros generadas en el build~~ (2026-11-12, en la rama): cargo-about + npm, sección en
  la página de licencias y `THIRD-PARTY-NOTICES.txt` para `INS-46`.
- ~~`INS-59` · Borrar solo la IA vuelve al asistente~~ (2026-11-12, en la rama): `desinstalar::borrar` deja `config.json`
  en «Elige perfil» sin modelos; pendiente de `INS-8`.
- ~~`INS-57` · Hoja de estilos del instalador y peticiones de imágenes~~ (2026-11-11, PR #16):
  [`13`](../13-hoja-de-estilos-e-imagenes.md); sus cuatro dudas, resueltas por la usuaria (§6); colocarlas es `INS-58`.
- ~~`INS-45` · AppImage, `.deb` y «Borrar datos del juego»~~ (2026-11-11, PR #16): CI de Linux construye y arranca
  los paquetes; diálogo en Ajustes (solo Linux) que para el motor, borra y cierra; pendiente de `INS-8` en la Deck.
- ~~`INS-44` · Instalador NSIS con las dos casillas~~ (2026-11-11, PR #16): plantilla propia, `tarkor.exe --desinstalar`
  y CI de Windows que instala y desinstala; pendiente de `INS-8` verlo en pantalla.

1. 2026-11-11 — Encargo de `INS-35` e `INS-36` lanzado en el juego (issue #93): `TARKOR_NARRADOR_BASE`, `TARKOR_NUM_THREAD`/`NUM_BATCH`/`NUM_CTX_NARRADOR`, escucha en 127.0.0.1, CORS de Tauri, `TARKOR_IMAGENES_DIR` y versión en build; `TARKOR_MODELOS_SIN_PENSAR` fuera porque el juego ya manda `think: false`.
2. 2026-11-11 — 2026-11-11: `FLU-8` (flujo v0.5.1) fusionado en `main` por el PR #13, con la confirmación de la usuaria y el CI en verde; retro con P1 a P3 aplicadas; los 14 hallazgos del flujo, en el punto 16.
3. 2026-11-11 — 2026-11-05: PR #12 fusionado (INS-12, licencia MIT del repo; falta la del juego). La CI de GitHub vuelve a arrancar: ya no hace falta ci-local. INS-37: contrato fijado en 04 (window.__TARKOR__.abrirAjustes()).
