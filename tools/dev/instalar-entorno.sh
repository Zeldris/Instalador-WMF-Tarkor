#!/bin/bash
# Deja listo el entorno de pruebas del instalador (antes `.claude/hooks/session-start.sh`, QA-10 de Tarkor; desde el
# piloto FLU-2 es el `install` de `.claude/gw.json`, que el gancho de inicio de Galivelop-workflow corre en la nube).
# Instala lo que se pierde en cada reinicio del contenedor: las dependencias de sistema de Tauri (WebKitGTK, su driver
# y xvfb para las e2e, mingw para comprobar el núcleo para Windows), las de npm del asistente y las crates de Cargo.
# Idempotente: lo que ya está, no se toca. El Ollama falso de las e2e (`app/e2e/ollama-falso.mjs`) lo lanza quien
# corre las e2e (cabecera de `app/e2e/asistente.e2e.mjs`).
# Uso: bash tools/dev/instalar-entorno.sh   (los paquetes de sistema, solo con apt y como root)
set -uo pipefail
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"

paquetes=(libwebkit2gtk-4.1-dev libgtk-3-dev librsvg2-dev libayatana-appindicator3-dev libxdo-dev libssl-dev
  gcc-mingw-w64-x86-64 webkit2gtk-driver xvfb)
if command -v apt-get >/dev/null && command -v dpkg >/dev/null && [ "$(id -u)" = 0 ]; then
  faltan=()
  for p in "${paquetes[@]}"; do
    dpkg -s "$p" >/dev/null 2>&1 || faltan+=("$p")
  done
  if [ ${#faltan[@]} -gt 0 ]; then
    log="$(mktemp)"
    echo "Instalando ${#faltan[@]} paquetes de sistema (${faltan[*]})…"
    (apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${faltan[@]}") >"$log" 2>&1 \
      || echo "AVISO: no se pudieron instalar (log en $log); sin ellos no compila src-tauri ni corren las e2e."
  fi
else
  echo "Paquetes de sistema: instálalos a mano si faltan (${paquetes[*]})."
fi

(cd app && npm install --no-audit --no-fund --loglevel=error) \
  || echo "AVISO: npm install falló (¿red?); sin él no corren tsc ni vitest."
(cd app && cargo fetch -q) || echo "AVISO: cargo fetch falló (¿red?); se reintentará al compilar."
if command -v rustup >/dev/null && ! rustup target list --installed 2>/dev/null | grep -q x86_64-pc-windows-gnu; then
  rustup target add x86_64-pc-windows-gnu >/dev/null 2>&1 || true
fi
# El check pasa `cargo fmt --check` y clippy (FLU-5); un rustup con el perfil mínimo no los trae.
command -v rustup >/dev/null && { rustup component add rustfmt clippy >/dev/null 2>&1 || true; }
git config blame.ignoreRevsFile .git-blame-ignore-revs
command -v tauri-driver >/dev/null || echo "Para las e2e falta tauri-driver: cargo install tauri-driver --locked"
echo "Entorno listo: dependencias de Tauri, npm del asistente y crates de Cargo."
