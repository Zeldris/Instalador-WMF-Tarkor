<!-- galivelop-workflow v0.6.0 -->
# gw-scout-updates — notas del proyecto

Las lee primero la skill `gw-scout-updates`: qué vigilar y qué no. El flujo las crea una vez; desde entonces son del
proyecto. Solo la lanza la usuaria (gasta muchos tokens); todo en español, y lo aprobado entra como tarea del
[plan](../../docs/05-plan-de-trabajo.md) con su `INS-n` o `FLU-n`.

## Vale la pena seguir

- **Ollama** (`motor.version` de `app/catalogo/catalogo.json`): el motor que instala el asistente; una versión
  nueva cambia variables de entorno y soporte de gráficas (`rendimiento.rs`).
- **Modelos del catálogo** (narrador, cronista, sugerencias, embeddings por perfil): candidatos que quepan en la
  Steam Deck (perfil mínimo) y escriban bien en español.
- **Tauri v2** y sus plugins (`app/src-tauri/Cargo.toml`, `app/package.json`): empaquetado en Windows y Linux,
  actualizaciones y firma.
- **Acciones de CI** de `.github/workflows/check.yml` y `app.yml` y la imagen `ubuntu-22.04` (webkit2gtk 4.1).

## Ignorados

<!-- Fijados a propósito, con el motivo. -->

## Fuentes preferidas

Las de [`references/sources.md`](../skills/gw-scout-updates/references/sources.md) de la skill; además, las notas de
versión de Ollama (GitHub releases) y de Tauri (tauri.app/release). Ninguna fuente fiable dice cómo escribe un
modelo en español narrativo: eso lo decide el banco de calidad, `tools/banco/` (`banco-calidad.md`).

## Presupuesto

<!-- Límites de una pasada (tiempo, tokens, número de propuestas). -->
