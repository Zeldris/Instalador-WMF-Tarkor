#!/bin/bash
# Deja listo el entorno de pruebas del instalador (antes `.claude/hooks/session-start.sh`, QA-10 de Tarkor; desde el
# piloto FLU-2 es el `install` de `.claude/gw.json`, que el gancho de inicio de Galivelop-workflow corre en la nube).
# Instala lo que se pierde en cada reinicio del contenedor: las dependencias de sistema de Tauri (WebKitGTK, su driver
# y xvfb para las e2e, mingw para comprobar el núcleo para Windows), las de npm del asistente y las crates de Cargo.
# Idempotente: lo que ya está, no se toca. El Ollama falso de las e2e (`app/e2e/ollama-falso.mjs`) lo lanza quien
# corre las e2e (cabecera de `app/e2e/asistente.e2e.mjs`).
# Uso: bash tools/dev/instalar-entorno.sh   (los paquetes de sistema, solo con apt y como root o con sudo sin contraseña)
set -uo pipefail
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"

paquetes=(libwebkit2gtk-4.1-dev libgtk-3-dev librsvg2-dev libayatana-appindicator3-dev libxdo-dev libssl-dev
  gcc-mingw-w64-x86-64 webkit2gtk-driver xvfb)
# Como root, apt-get directo; si no, con un sudo que no pida contraseña (el runner de GitHub Actions, donde lo corre
# el `check` de .github/workflows/check.yml).
como_root=()
[ "$(id -u)" = 0 ] || { sudo -n true 2>/dev/null && como_root=(sudo -n); }
if command -v apt-get >/dev/null && command -v dpkg >/dev/null && { [ "$(id -u)" = 0 ] || [ ${#como_root[@]} -gt 0 ]; }; then
  faltan=()
  for p in "${paquetes[@]}"; do
    dpkg -s "$p" >/dev/null 2>&1 || faltan+=("$p")
  done
  if [ ${#faltan[@]} -gt 0 ]; then
    log="$(mktemp)"
    echo "Instalando ${#faltan[@]} paquetes de sistema (${faltan[*]})…"
    ("${como_root[@]}" apt-get update -qq && "${como_root[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${faltan[@]}") >"$log" 2>&1 \
      || echo "AVISO: no se pudieron instalar (log en $log); sin ellos no compila src-tauri ni corren las e2e."
  fi
else
  echo "Paquetes de sistema: instálalos a mano si faltan (${paquetes[*]})."
fi

(cd app && npm install --no-audit --no-fund --loglevel=error) \
  || echo "AVISO: npm install falló (¿red?); sin él no corren tsc ni vitest."
# La versión de Rust, con rustfmt, clippy y el destino de Windows, la fija app/rust-toolchain.toml (FLU-6); se instala
# antes de `cargo fetch`, que si no la bajaría él y un fallo saldría como de red. `rustup toolchain install` sin
# argumentos pide rustup 1.28; uno anterior la instala con `rustup show`, que sale con 0 aunque no instale nada, y
# `rustup show active-toolchain` falla si sigue faltando.
if command -v rustup >/dev/null; then
  log="$(mktemp)"
  (cd app && { rustup toolchain install --no-self-update || { rustup show && rustup show active-toolchain; }; }) >"$log" 2>&1 \
    || echo "AVISO: no se pudo instalar el Rust de app/rust-toolchain.toml (log en $log)."
else
  echo "AVISO: sin rustup no se usa el Rust de app/rust-toolchain.toml; fmt y clippy pueden no coincidir con el CI."
fi
(cd app && cargo fetch -q) || echo "AVISO: cargo fetch falló (¿red?); se reintentará al compilar."
git config blame.ignoreRevsFile .git-blame-ignore-revs
command -v tauri-driver >/dev/null || echo "Para las e2e falta tauri-driver: cargo install tauri-driver --locked"
# INS-47: las licencias de terceros las saca cargo-about en cada `npm run build`. La versión se fija en un solo sitio,
# app/herramientas/licencias-terceros.mjs (VERSION_CARGO_ABOUT); se reinstala si la instalada es otra. Primero se baja el
# binario precompilado de la release (segundos); si falla, se compila con `cargo install`.
ver_about="$(sed -n "s/^export const VERSION_CARGO_ABOUT = '\([^']*\)'.*/\1/p" app/herramientas/licencias-terceros.mjs)"
if [ -z "$ver_about" ]; then
  echo "AVISO: no se pudo leer VERSION_CARGO_ABOUT de app/herramientas/licencias-terceros.mjs; cargo-about sin comprobar."
elif [ "$(cargo-about --version 2>/dev/null)" != "cargo-about $ver_about" ]; then
  log="$(mktemp)"
  echo "Instalando cargo-about $ver_about (log en $log)…"
  url="https://github.com/EmbarkStudios/cargo-about/releases/download/$ver_about/cargo-about-$ver_about-x86_64-unknown-linux-musl.tar.gz"
  destino="${CARGO_HOME:-$HOME/.cargo}/bin"
  tmp_about="$(mktemp -d)"
  { [ "$(uname -s)-$(uname -m)" = "Linux-x86_64" ] && mkdir -p "$destino" \
      && curl -sSfL "$url" | tar -xz -C "$tmp_about" --strip-components=1 \
      && install -m 755 "$tmp_about/cargo-about" "$destino/cargo-about"; } >>"$log" 2>&1 \
    || cargo install cargo-about --locked --features cli --version "$ver_about" >>"$log" 2>&1 \
    || echo "AVISO: falta cargo-about $ver_about y no se pudo instalar (log en $log); el build lo necesita: cargo install cargo-about --locked --features cli --version $ver_about"
  rm -rf "$tmp_about"
fi
echo "Entorno listo: dependencias de Tauri, npm del asistente y crates de Cargo."
