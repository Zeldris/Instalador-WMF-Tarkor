# Pendiente

Lo que queda abierto; la bitácora solo apunta aquí. Se añade y se quita en este archivo.

## Pendiente

- Pendientes leves de la revisión de `INS-48` (no vuelven a revisarse en su PR): `bloqueado` no descuenta lo
  ya descargado en Ajustes; no se impide mover la carpeta con una descarga en marcha (el asistente hoy no lo
  permite); `Estado::ia()` lee `config.json` en cada llamada; el aviso de restos del origen solo va a stderr;
  con poco disco el paso 3 dice «equipo insuficiente».
- Pendientes leves de la revisión de `INS-43` (lo demás lo cerró `INS-68`): los arreglos de `reintentar_motor` y
  `estado_motor` no tienen test (los cubre el E2E del trozo 3); sin test: desmontar antes de que `listen` resuelva,
  Borrar desactivado mientras borra, Volver desactivado durante el cambio. Leves de la revisión de la rama contra
  `origin/main`: `anonimizar` no mira los nombres cortos 8.3 de Windows; 200 líneas de `leer_final` pueden dejar
  fuera el «out of memory»; «Pausar» sale también en fases que no se pueden cancelar. De la revisión de sus
  arreglos: `borrar_modelo` va por la espera de lectura de 10 s (un borrado lento en Windows saldría como error); el
  cambio de `masLigero` a `evaluacion.perfiles` en `App.tsx` no tiene un test que falle sin él. De la revisión de la
  fase 2: `task_start` de `recuperar.py` usa la hora del commit de la base y no la de la fusión (con un `main` quieto
  cuenta compactaciones de antes de la tarea); `sin-find-forzado.py` no ve un `.find(` partido en varias líneas ni
  `.findLast(...)!`, da falsos positivos con `.find(x)!==y`, excluye cualquier archivo de `app/src` que empiece por
  «test» y usa `list[str]` (Python 3.9+); `tools/qa/e2e.sh` no corre la variante `E2E_ESPERA_ERROR_RED=1` y compila
  en cada ejecución.
- Pendientes leves de la revisión de `INS-49` (no vuelven a revisarse en su PR): con un `.completo` vacío (lo
  instalado antes de `INS-49`) el primer Reparar vuelve a bajar el motor aunque esté sano; el porcentaje al reponer
  un modelo es el de cada capa y vuelve a 0 %; `escribir_sumas` relee todo el motor tras extraerlo en vez de sumar
  al extraer.
- Pendientes leves de la revisión del trozo A de `INS-42`: sin test de Atrás o desmontar durante la espera, ni de
  `aErrorIa` con el objeto de Tauri.
- Pendientes leves de la revisión del trozo B de `INS-42`: `calentar` no manda las `options` del juego
  (`num_thread`), que podrían recargar el modelo en el primer turno; al abrir con el motor ya caído, `Juego` puede
  arrancarlo a la vez que «Reintentar» de la pantalla del motor detenido; el test «calienta una sola vez» usa
  `rerender` y no prueba el `[]` del efecto.
- Pendientes leves de la revisión del trozo C de `INS-42`: la comprobación del E2E de `rendimiento` con «Esperando
  conexión» es tautológica.
- Pendientes leves de la fase 1 antes de `main` (`INS-42`; no vuelven a revisarse en su PR): el test de dos
  arranques copia la forma de `asegurar` en vez de llamarlo (el tipo lo cubre: sin turno no se llama a
  `arrancar_con_turno`); `coger` reserva memoria para la guarda.
- Pendientes leves de la revisión de `FLU-5` (no vuelven a revisarse en su PR): el commit de formato `a27489f` no
  actualizó la bitácora (se hizo en los siguientes). La versión de Rust la fija `FLU-6` (2026-10-26); el CI de
  GitHub con ella está sin probar hasta que vuelva la cuota.
- Pendientes leves de la revisión de `FLU-6` (no vuelven a revisarse en su PR): `Swatinem/rust-cache` saca la
  clave de `rustc -vV` en la raíz, donde manda el stable del runner y no la versión fijada (caché desperdiciada,
  nunca un fallo); el job de Windows baja también rustfmt, clippy y el destino de Windows, que no usa; el test de
  la versión de Rust no entiende un `channel` que no sea número (`nightly-…`); `scout-updates` no lee `rust-toolchain.toml`, así que nadie avisa
  cuando la 1.94.1 se queda vieja.
- Pendientes leves de `INS-31` (en `main` del juego): con `VITE_API_URL=""` la base queda vacía (igual que antes);
  el aviso de `useReconnectionPolling.ts` no dice qué URL probó (útil para `INS-41`). El comentario de los tests y
  `15-instalacion.md` ya se arreglaron allí.
- Leves de `INS-33` en el juego, para la próxima sesión que toque esos archivos: el formulario de «Crear desde cero»
  queda sin alcanzar, a propósito; en `docs/mapa-agente.md`, «Crear desde cero» se atribuye a `Home.tsx` (es
  `CharacterSelect.tsx`, cuyo test falta en la lista); y `import/first` (`QA-263`) no caza un `import` tras un
  comentario, el caso que la motivó (comprobado con oxlint: solo salta con código delante).
- Leves de `INS-34` en el juego, sin tarea todavía: el test del bundle va en ESM con `packages: 'external'` (el
  empaquetador del instalador lo cubre con su `metafile`); `esbuild` fijado en el backend puede separarse del que use
  el instalador; en el build empaquetado siguen `GET`/`PUT /world/:slug/image-prompt[/usado]` (solo la tabla local),
  las variables cloud de `env.ts` y el aviso de arranque de `LIVE_TEACHER_CAPTURE_ENABLED` (ya no captura nada).
- Leves de la revisión de la rama contra `origin/main` (2026-11-05, `INS-12` y `FLU-7`; no vuelven a revisarse en su
  PR), casi todas de la plantilla de Galivelop-workflow, para avisar allí: `check.yml` y `app.yml` no corren en
  `main` (`branches-ignore`); el `setup-node` de `check.yml` mira `package.json` en la raíz y no `app/`, así que
  `tsc` va con el Node del runner, y no hay `rust-cache`; `instalar-entorno.sh` solo avisa si falla (el paso
  Install del CI sale en verde), usa `npm install` y no `npm ci`, e instala xvfb y webkit2gtk-driver que el check no
  usa; `review-before-main.sh` no reconoce las líneas de `ci-local.md` del formato viejo (`· en verde`). El commit
  `9002d38` (`FLU-7`) va a nombre de Claude, de antes de la regla «todo a nombre de Zeldris»; no se reescribe.
- Hallazgos de la revisión de `FLU-8` contra `origin/main` (2026-11-11), todos en scripts del flujo, que aquí no se
  editan (`REVIEW.md`): para proponer en Galivelop-workflow con `gw-harvest`. En `check-green.sh`, el mismo pid que
  vuelve a tomar el candado no actualiza su sha ni su log (un push de varias refs avisa con los de la primera); un
  `check.lock.steal` sin `pid` (muerto entre `mkdir` y escribirlo) bloquea hasta borrarlo a mano (el mensaje dice
  qué borrar); `proc_start`/`proc_is` dan por muerto un proceso de otro usuario y `before-stop.py` lo da por vivo;
  `before-stop.py` compara el sha corto (con `-dirty`) de `check.sh` con HEAD. `merge-branch.sh` ya no valida
  `check` y `checkWrapper` antes de fusionar (con la configuración rota, fusiona y luego falla). En el `pre-push`,
  tras esperar el candado no se vuelve a mirar la caché de verdes; con el mismo árbol en una ref protegida y en una
  rama, la rama no se comprueba ni se apunta en verde; `lock_wait` no es `local`. Los `check-<sha>.log` de
  `.git/gw` no se borran nunca. `check.sh` sin `--quiet` pasa la salida por `tee` (sin TTY, sin colores).
  `private-check.py`: `amend_advice` propone `git rebase -i` sobre refs que pueden ser un tag o `HEAD`, y
  `git add -A`, y no usa `cfg`. `pre-commit`: `md_prose_dropped` lanza `sed` y `grep` por línea, y `PROSE_ASSIGN`
  deja pasar un secreto de una palabra en mayúscula entre comillas en un `.md`.
- Leves de la fase 1 antes de `main` (`INS-15`, `INS-7`, 2026-11-11; no vuelven a revisarse en su PR): no hay
  migración de `qwen2.5:7b` a `llama3.1:8b` para quien ya completó el asistente (hoy no hay versión publicada;
  hará falta antes de cambiar un modelo tras `INS-46`); el motor sale solo como «Ollama · MIT», sin los avisos de
  llama.cpp/ggml ni de los runtimes de GPU.
- Leves de la fase 1 antes de `main` (`INS-44`, `INS-45`, 2026-11-11; no vuelven a revisarse en su PR): si la
  carpeta de la IA es un enlace simbólico o una junction solo se quita el enlace y el tamaño sale 0;
  `--info-desinstalar` usa `Config::cargar`, que aparta un `config.json` corrupto; el «desinstalar antes de
  instalar» de una reinstalación corre el desinstalador sin `/UPDATE` (enseña las casillas y borra los registros);
  en Linux no se borran las carpetas de WebKit de `io.github.zeldris.tarkor`; una instalación previa en
  `%LOCALAPPDATA%\Tarkor` se queda ahí al actualizar; `ia_borrable` se fía del nombre `Tarkor IA`. Pendiente de
  `INS-8` (Windows real): el aviso del desinstalador cuando el borrado falla (nuevo, solo compilado en el CI), el
  borrado con archivos bloqueados (no hay reintento) y el caso de la junction.
- Pendientes leves de la revisión de `INS-59` (no vuelven a revisarse en su PR): `PASO_ELEGIR_PERFIL` (4) de
  `desinstalar.rs` copia la numeración de pasos de `App.tsx` sin test que los ate; la regla general iría al
  arrancar (asistente completado pero sin motor ni modelos → asistente), que cubriría también la IA borrada a mano;
  `borrarDatos` de `ejemplo.ts` no imita el cambio, así que ni vitest ni el E2E prueban «borrar la IA y reabrir».
- Para proponer en Galivelop-workflow (`FLU-9`, 2026-11-14): en la 0.6.0, `skills/gw-opt-tokens/scripts/test_measure.py`
  copia `scripts/config.py` y `schema/gw.schema.json` con la estructura del repo del flujo y en un proyecto falla
  (5 errores, `FileNotFoundError`); aquí lleva un parche local (`workflow_file()` mira también `.claude/gw/`, como
  hace `measure.py`). El aviso de `apply.py` sobre `docs/propuestas` en `docs/13:14` es un falso positivo: es una
  ruta del repo GVIG, no de este. La mayoría de los hallazgos de la revisión de `FLU-8` llegaron arreglados en la 0.5.2. En la 0.8.0 el fallo sigue y el parche se rehízo; leve de la revisión de `FLU-12` (no vuelve a revisarse en su PR): repite en tres sitios (líneas 389, 459 y 483) el respaldo raíz/`gw` en lugar de un solo helper.
- Pendientes leves de la revisión de bloque `INS-63`…`INS-67` (2026-11-15; no vuelven a revisarse en su PR): el
  job e2e de `app.yml` llama dos veces a `tools/qa/e2e.sh` y repite vite y cargo-about para la variante del error
  de red (convendría reutilizar el binario).
- Pendientes leves de la revisión de bloque de `INS-68` (2026-11-25; no vuelven a revisarse en su PR):
  `ReparacionHecha` se queda en `Estado::reparacion` hasta el siguiente `reparar` y un Reparar manual posterior
  con la misma carpeta y modelos se salta parar, reinstalar y volver a sumar (`comandos_ia.rs` ~299; conviene un
  `reintento` desde el frontal o borrarlo al cancelar); `bytes.remove(0)` de `informe.rs` ~65 entra en pánico si
  el registro encoge entre `metadata()` y la lectura (`if desde > 0 && !bytes.is_empty()`); `sigue_en_marcha`
  (`estado.rs` ~227) hace 3 `version()` con el turno de arranque cogido y contra un motor colgado espera el
  tiempo de recepción entero en cada uno (cliente de espera corta, o reintentar solo errores de conexión); sin
  verificar: con Ajustes oculto y montado (esperando red), «Ir a Ajustes» del aviso no cambia el perfil porque
  `perfilInicial` solo se lee al montar (`App.tsx` ~69; una `key` o un efecto).
