# Auditoría 2026-11-15: deuda técnica

Subagente `sonnet`, solo lectura, sobre `bdb36af`. Sin verificar todavía en la sesión principal; las rutas con línea
son las que comprobó el subagente. No repite los pendientes leves de `traspaso.md`.

## Alta

1. **E2E fuera del CI.** `.github/workflows/app.yml` no corre `app/e2e` (tauri-driver + xvfb, `tools/qa/e2e.sh`).
   `cambiar_perfil`, `reintentar_motor` y `estado_motor` solo los cubre el E2E. Propuesta: job `e2e` en `app.yml`,
   incluida la variante `E2E_ESPERA_ERROR_RED=1`. Esfuerzo M.
2. **Sin firma ni actualizador** (INS-11 abierta; `tauri.conf.json` sin `updater`, `pubkey` ni `signCommand`).
   SmartScreen avisará en Windows; no hay forma de actualizar salvo reinstalar. Propuesta: decidirlo y dejarlo escrito
   en `docs/` y el plan. Esfuerzo L.
3. **`Mutex.lock().unwrap()` en caminos de usuario** (`app/src-tauri/src/lib.rs:147,154,155,163,164,385,722,760,761,774,777,786,800,1057`).
   Un pánico con el candado cogido envenena el mutex y tumba en cascada los comandos y el cierre. En release
   `panic = "abort"` lo limita, pero no en dev/tests. Propuesta: ayudante `bloquear()` con
   `unwrap_or_else(PoisonError::into_inner)`. Esfuerzo S.

## Media

4. **`lib.rs` con 1131 líneas**: ciclo del motor, 30 comandos, vigilancia, desinstalación por CLI (l. 969) y tests.
   Propuesta: partir en `motor_ciclo.rs`, `comandos_*.rs`, `vigilancia.rs`; así se pueden testear los comandos. M.
5. **Módulos grandes del núcleo**: `nucleo/src/ollama.rs` (705), `motor.rs` (673), `desinstalar.rs` (642). Separar
   cliente HTTP, parseo de progreso y reintentos. M.
6. **Errores tragados con efecto**: `nucleo/src/carpetas.rs:181,183` (`let _ = fs::remove_dir_all`) puede dejar
   restos grandes sin aviso. Los `let _ = canal.send/app.emit` de `lib.rs` son aceptables (comentarlos). S.
7. **Silenciados en el frontal**: `src/App.tsx:38` (`.catch(() => {})` al suscribirse a `motor-detenido`: si falla, no
   se avisa de la caída del motor), `src/pantallas.tsx:280` (`modelosSobrantes().catch(() => [])`),
   `src/pantallaLicencias.tsx:22`, `src/componentes.tsx:385,393`. S.
8. **Tipos a mano entre frontal y Rust** (`src/api.ts:85-115`, `tipos.ts`): renombrar en Rust no rompe el build TS.
   Propuesta: `ts-rs`/`specta` o un test que compare `src/ejemplo.ts` con la serialización de Rust. M.
9. **`App.test.tsx` de 991 líneas**; partirlo por pantalla. `ejemplo.ts` sigue cayéndose con `perfiles` vacío. M.
10. **CSP y capacidades**: `connect-src http://127.0.0.1:*` abre cualquier puerto local; `style-src 'unsafe-inline'`
    sin justificar; `core:default` quizá más de lo necesario. S.
11. **Sin auditoría de dependencias** (ni Dependabot, ni `cargo audit`, ni `npm audit`) en un instalador que descarga
    y descomprime de la red (`tar`, `ruzstd`, `zip`, `ureq`). S.

## Baja

12. Parches npm pendientes (`@tauri-apps/*` 2.12.0→2.12.4, `vite` 8.3.1→8.3.8, `vitest` 5.0.2→5.1.0, `react` 19.3.1…);
    `jsdom` 30.1.1 con `latest` 29.1.1 (tag raro); `typescript ~6.0.2` frente a 7.0.2, pin que parece deliberado.
13. `cargo tree -d` no comprobado; proponerlo en el CI como aviso.
14. `app/README.md:16` cita `src/simulacion.ts`, que ya no existe; su tabla lista 6 de 12 módulos del núcleo y no
    menciona los E2E.
15. `esperar_http` (`procesos.rs`) solo lo usan sus tests: borrar o `#[cfg(test)]`.
16. `tools/`: pendientes ya anotados (`instalar-entorno.sh`, `sin-find-forzado.py`, `e2e.sh` compila siempre).
17. CI: instalación de dependencias y `cargo-about` repetida en tres jobs; `windows-latest` sin fijar.
18. `expect` restantes aceptables (`lib.rs:1047`, `catalogo.rs:137-138`, tests).

## Cobertura

Hueco principal: los comandos y la vigilancia de `src-tauri/src/lib.rs`. Sin tests propios de `api.ts`,
`esperaRed.ts`, `formato.ts` (confirmar con cobertura). Falta un barrido de tests que esperan fallo sin comprobar el
motivo (`grep -n 'is_err()'`).

## Top 5 según el subagente

1. E2E en el CI. 2. Ayudante de mutex y partir `lib.rs`. 3. Dependabot + `cargo audit`/`npm audit`.
4. Errores tragados de `carpetas.rs` y `App.tsx:38`. 5. Decidir firma y actualizador (INS-11).
