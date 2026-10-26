# Bitácora de traspaso

**Para qué:** que cualquier sesión de Claude, de cualquier cuenta, sepa exactamente por dónde va el
trabajo del instalador y pueda seguir. Reglas en [`CLAUDE.md`](../../CLAUDE.md). **Se actualiza en
cada commit.**

---

## Estado actual

| | |
|---|---|
| **Actualizado** | 2026-10-26 |
| **Ramas de trabajo** | Cada sesión, su rama con su fila «Tarea en curso» (`QA-136` de Tarkor): `claude/installer-docs-review-09e7vs` (rehecha desde `main` el 2026-10-26). Las skills, ganchos y `settings.json` de `.claude/` van versionados con `git add` normal; a `main` se pasa **por pull request**. |
| **Último commit en `main`** | Fusión del PR #11 (2026-10-26, `a73f881`): `FLU-6`, con la confirmación de la usuaria. La CI de GitHub no arrancó (sin cuota); `ci-local` en verde sobre `f59202b`, Windows sin cubrir (pendiente de `INS-8`). |
| **Hito** | Fase 0 del [plan](../05-plan-de-trabajo.md): faltan `INS-7` y `INS-8` (necesitan la Steam Deck o un Windows). La fase 2 está hecha en el repo del juego, a falta de fusionar su PR #1. |
| **Tarea en curso · `claude/installer-docs-review-09e7vs`** | 2026-10-26: `INS-31` hecha en el repo del juego (rama `claude/ins-31-url-backend`, [PR #78](https://github.com/Zeldris/World-Maker-Fantasy/pull/78) en borrador). La usuaria dijo «fusiona»: la sesión `session_01EzaeVYQBXa4ivFEerT9eGJ` del juego la deja a un paso de `main` con sus reglas (revisión, retro, CI local; `QA-215` y `QA-238`) y para antes de `revisado.sh`. Siguiente: presentar su retro a la usuaria; con su confirmación, una sesión del juego la sube a `main`. |
| **Tests** | 2026-10-26: núcleo `cargo test -p tarkor-nucleo` 116, `cargo fmt --all --check` en verde, clippy 0 avisos, `tsc -b` 0, `cargo check` del núcleo y la app para Windows (mingw) en verde. Asistente `vitest` 27 y E2E con el Ollama falso: último verde el 2026-10-25. |

## Dónde está todo (para saber qué sigue)

1. **Esta bitácora**: qué se está haciendo ahora y el paso inmediato.
2. **[Plan de implementación](../05-plan-de-trabajo.md)**: fases 0 a 5 con su casilla y su `INS-n`.
3. **Los documentos de diseño** (`docs/01`…`docs/12`, índice en el [README](../../README.md)).
4. **El asistente y el núcleo**: [`app/README.md`](../../app/README.md) (cómo se compila, se prueba
   y se mide un motor real).
5. **El flujo de trabajo**: [skills y modelos](../runbooks/skills-y-modelos.md) y la guía de
   revisión [`REVIEW.md`](../../REVIEW.md).

## Siguiente paso y los que vienen (en orden)

1. Fusionar el PR #1 del repo del juego (fase 2): dos tests intermitentes de
   `routes/turn.integration.test.ts` y endurecer `lib/prisma.test.ts` (detalle en el
   [plan](../05-plan-de-trabajo.md#dónde-lo-dejamos-2026-09-28)).
2. Fase 3 (modo empaquetado del juego, `INS-31`…`INS-37`) y fase 4 (`INS-41`…`INS-47`).
3. Pendientes leves de la revisión de `INS-48` (no vuelven a revisarse en su PR): `bloqueado` no descuenta lo
   ya descargado en Ajustes; no se impide mover la carpeta con una descarga en marcha (el asistente hoy no lo
   permite); `Estado::ia()` lee `config.json` en cada llamada; el aviso de restos del origen solo va a stderr;
   con poco disco el paso 3 dice «equipo insuficiente».
4. Pendientes leves de la revisión de `INS-43`: `cambiar_perfil` pone `cancelar` a false y puede deshacer una pausa de otra descarga; `cambiar_perfil` con el motor caído lo arranca primero con el perfil viejo, y si eso falla no prueba el nuevo; no hay test de la pausa de `cambiar_perfil`; los arreglos de `cambiar_perfil`, `reintentar_motor` y `estado_motor` no tienen test (los cubre el E2E del trozo 3); sin test: desmontar antes de que `listen` resuelva, Borrar desactivado mientras borra, Volver desactivado durante el cambio; la lectura de `motor_detenido()` al montar o al acabar un cambio puede borrar un aviso que llegue mientras tanto (conviene un contador de avisos); sin test de que `CopiarInforme` pida el informe cada vez; «Copiar» oculta el texto desplegado mientras carga. Leves de la revisión de la rama contra `origin/main`: `anonimizar` no mira el límite izquierdo del nombre ni los nombres cortos 8.3 de Windows; `leer_final` pierde una línea cuando el corte cae al principio de una, y 200 líneas pueden dejar fuera el «out of memory»; los sobrantes van en GB decimales y la línea de uso en GiB; `modelos_sobrantes` no mira `ocupado`; «Pausar» sale también en fases que no se pueden cancelar; el cierre de la app (`RunEvent::Exit`) espera al Mutex del motor hasta 30 s. De la revisión de sus arreglos: `borrar_modelo` va por la espera de lectura de 10 s (un borrado lento en Windows saldría como error); el cambio de `masLigero` a `evaluacion.perfiles` en `App.tsx` no tiene un test que falle sin él. De la revisión de la fase 2: `task_start` de `recuperar.py` usa la hora del commit de la base y no la de la fusión (con un `main` quieto cuenta compactaciones de antes de la tarea); `sin-find-forzado.py` no ve un `.find(` partido en varias líneas ni `.findLast(...)!`, da falsos positivos con `.find(x)!==y`, excluye cualquier archivo de `app/src` que empiece por «test» y usa `list[str]` (Python 3.9+); `ejemplo.ts` sigue cayéndose con `perfiles` vacío; `tools/qa/e2e.sh` no corre la variante `E2E_ESPERA_ERROR_RED=1` y compila en cada ejecución. `esperar_http` de `procesos.rs` ya solo lo usan sus tests.
5. Pendientes leves de la revisión de `INS-49` (no vuelven a revisarse en su PR): con un `.completo` vacío (lo
   instalado antes de `INS-49`) el primer Reparar vuelve a bajar el motor aunque esté sano; `alTerminar` de
   Ajustes guarda los modelos del perfil leído al empezar aunque se cambie durante la reparación; el porcentaje
   al reponer un modelo es el de cada capa y vuelve a 0 %; `escribir_sumas` relee todo el motor tras extraerlo
   en vez de sumar al extraer; la lista única de modelos de un perfil está copiada en cuatro sitios (conviene un
   `modelosDe(perfil)` en `catalogo.ts`).
6. Pendientes leves de la revisión del trozo A de `INS-42`: `clasificar` (`ollama.rs`) no reconoce `EOF` ni
   `unexpected EOF` como corte de red; sin test de Atrás o desmontar durante la espera, ni de `aErrorIa` con el objeto de Tauri;
   el máximo de progreso va por modelo, no por capa (una capa nueva más pequeña no cuenta como progreso).
7. Pendientes leves de la revisión del trozo B de `INS-42`: `calentar` no manda las `options` del juego (`num_thread`), que podrían
   recargar el modelo en el primer turno; al abrir con el motor ya caído, `Juego` puede arrancarlo a la vez que
   «Reintentar» de la pantalla del motor detenido; el test «calienta una sola vez» usa `rerender` y no prueba el
   `[]` del efecto; la fila de fallo de la Comprobación ofrece «Probar un perfil más ligero» aunque no haya uno.
   El candado compartido ya no pide test: arrancar
   sin él no compila (`Turno`, retro de `INS-42`).
8. Pendientes leves de la revisión del trozo C de `INS-42`: `cambiar` y `empezar` no reinician la escalera tras
   Pausar y volver a pulsar (queda en 40/60 s); si un reintento de `reparar` falla por red tras reinstalar el motor o
   reponer capas, lo hecho se pierde y dice «Todo estaba en orden»; `maxHecho` nunca se vacía (un modelo borrado y
   vuelto a bajar no cuenta como progreso); la comprobación del E2E de `rendimiento` con «Esperando conexión» es
   tautológica.
9. Pendientes leves de la fase 1 antes de `main` (`INS-42`; no vuelven a revisarse en su PR):
   - cada reintento de `reparar` tras un corte vuelve a parar el motor y a recalcular todos los hashes;
   - que el runner local cierre la conexión («forcibly closed») cuenta como corte de red;
   - mientras el cambio de perfil espera la red, `cambiando` oculta la pantalla del motor detenido;
   - el reintento de Reparar usa un `alTerminar` de un render anterior;
   - sin Range (un 200 desde 0) el progreso no reinicia la escalera de esperas;
   - «Probar un perfil más ligero» de la Comprobación no preselecciona el más ligero;
   - el `map_err(|e| ErrorIa::from(e.to_string()))` se repite en cinco comandos.
   - de la fase 3 (el `Turno`): la vigilancia relanza el motor dentro de `Estado::motor` sin turno, y un
     `asegurar` a la vez lo ve parado y lo reinicia otra vez; la salida (`RunEvent::Exit`) para el motor sin turno, y
     uno que esté arrancando al cerrar queda vivo; un fallo pasajero de `version()` hace que `asegurar` reinicie un
     motor sano (las tres, ya en `main`); el test de dos arranques copia la forma de `asegurar` en vez de llamarlo (el
     tipo lo cubre: sin turno no se llama a `arrancar_con_turno`); `coger` reserva memoria para la guarda.
10. Pendientes leves de la revisión de `FLU-5` (no vuelven a revisarse en su PR): el commit de formato `a27489f` no
    actualizó la bitácora (se hizo en los siguientes). La versión de Rust la fija `FLU-6` (2026-10-26); el CI de
    GitHub con ella está sin probar hasta que vuelva la cuota.
11. Pendientes leves de la revisión de `FLU-6` (no vuelven a revisarse en su PR): `Swatinem/rust-cache` saca la
    clave de `rustc -vV` en la raíz, donde manda el stable del runner y no la versión fijada (caché desperdiciada,
    nunca un fallo); el job de Windows baja también rustfmt, clippy y el destino de Windows, que no usa; el test de
    la versión de Rust no entiende un `channel` que no sea número (`nightly-…`); `scout-updates` no lee `rust-toolchain.toml`, así que nadie avisa
    cuando la 1.94.1 se queda vieja.
12. Pendientes leves de `INS-31` (PR #78 del juego): con `VITE_API_URL=""` la base queda vacía (igual que antes);
    el comentario de `useEntityBanner.test.tsx` aún dice «concatena API_URL»; `docs/arquitectura/15-instalacion.md`
    del juego no menciona `window.__TARKOR__`.
13. `INS-7`, `INS-8` y la fase 5, cuando la usuaria pueda probar en la Steam Deck o en Windows.

## Decisiones de la usuaria que bloquean algo

- **CI de GitHub agotada** (2026-10-22: «recent account payments have failed or your spending limit needs to be
  increased»). La usuaria decide que, hasta que vuelva, se sube de forma manual: antes de ir a `main`,
  `python3 tools/qa/ci-local.py --apuntar` corre en local los jobs de Ubuntu de `comprobar.yml` y lo deja en
  [`ci-local.md`](ci-local.md) con fecha y commit (`FLU-3`). Los tests del núcleo **en Windows** no se pueden correr
  así: quedan pendientes hasta que vuelva la CI. Cuando vuelva, se re-lanza sobre `main`.
- Firma de código en Windows (`INS-11`) y licencias (`INS-12`, `INS-15`).

## Comandos para comprobar el estado

```bash
cd app && npm test && npx tsc -b                       # asistente (vitest + tipos)
cd app && cargo test -p tarkor-nucleo                  # núcleo (detección, perfiles, catálogo, motor)
cd app && cargo clippy --workspace --all-targets -- -D warnings
python3 -m unittest discover -s tools/qa/tests         # herramientas del proyecto
python3 .claude/gw/scripts/enlaces-md.py               # enlaces de los .md
python3 .claude/gw/scripts/doctor.py                   # el flujo (Galivelop-workflow) bien montado
# Entorno (dependencias de WebKit, mingw, npm, cargo): lo deja listo el gancho de inicio de sesión
#   (`install` de .claude/gw.json); a mano, tras un reinicio del contenedor: bash tools/dev/instalar-entorno.sh
# Pruebas de punta a punta del asistente (tauri-driver + xvfb): ver app/README.md.
```

## Hecho (5 últimas)

Dos líneas cada una como mucho; el detalle está en el commit y la más antigua sale cuando hay más de 5.

- ~~`INS-31` · URL del backend en tiempo de ejecución~~ (2026-10-26): `apiBaseUrl()` en el `api.ts` del juego con
  `window.__TARKOR__.apiUrl`; PR #78 del juego en borrador, sin fusionar.
- ~~`FLU-6` · Versión de Rust fijada~~ (2026-10-26): Rust 1.94.1 en `app/rust-toolchain.toml`, con rustfmt, clippy
  y el destino de Windows; el CI y `instalar-entorno.sh` lo instalan de ahí.
- ~~`FLU-5` · `cargo fmt` en el check~~ (2026-10-26): workspace formateado a 120 columnas en commits aparte
  (`a27489f` y `9b0035c`, ignorados por `git blame`) y `cargo fmt --all --check` en el check y en el CI.
- ~~`INS-42` · Asistente real de punta a punta~~ (2026-10-26): autopausa por red con espera creciente en la
  Descarga, Ajustes y Reparar; calentar el narrador al entrar; perfil más ligero si falta memoria o narra lento.
- ~~`INS-43` · Rendimiento de la IA y motor detenido~~ (2026-10-25): dónde corre la IA, cambiar de perfil con
  borrado de sobrantes, «Copiar informe» y pantalla del motor detenido con vigilancia en Rust.
