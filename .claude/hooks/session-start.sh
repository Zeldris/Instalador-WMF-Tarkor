#!/bin/bash
# Traído de Tarkor (QA-10) y adaptado al instalador: deja listo el entorno de pruebas al empezar una sesión en la
# nube, que es lo que se pierde en cada reinicio del contenedor: las dependencias de sistema de Tauri (WebKitGTK,
# su driver y xvfb para las e2e, mingw para comprobar el núcleo para Windows), las de npm del asistente y las crates
# de Cargo. Idempotente: lo que ya está, no se toca. El Ollama falso de las e2e (`app/e2e/ollama-falso.mjs`) no se
# levanta aquí: lo lanza quien corre las e2e (cabecera de `app/e2e/asistente.e2e.mjs`).
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

raiz="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$raiz"

# Sistema: lo mismo que instala la CI (`.github/workflows/comprobar.yml`) más el driver y xvfb de las e2e.
paquetes=(libwebkit2gtk-4.1-dev libgtk-3-dev librsvg2-dev libayatana-appindicator3-dev libxdo-dev libssl-dev
  gcc-mingw-w64-x86-64 webkit2gtk-driver xvfb)
faltan=()
for p in "${paquetes[@]}"; do
  dpkg -s "$p" >/dev/null 2>&1 || faltan+=("$p")
done
if [ ${#faltan[@]} -gt 0 ]; then
  echo "Instalando ${#faltan[@]} paquetes de sistema (${faltan[*]})…"
  (apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${faltan[@]}") >/tmp/session-start-apt.log 2>&1 \
    || echo "AVISO: no se pudieron instalar (log en /tmp/session-start-apt.log); sin ellos no compila src-tauri ni corren las e2e."
fi

# npm del asistente (aprovecha la caché del contenedor).
(cd app && npm install --no-audit --no-fund --loglevel=error) \
  || echo "AVISO: npm install falló (¿red?); sin él no corren tsc ni vitest."

# Crates y el objetivo de Windows del núcleo (la CI comprueba que compila para Windows).
(cd app && cargo fetch -q) || echo "AVISO: cargo fetch falló (¿red?); se reintentará al compilar."
if command -v rustup >/dev/null && ! rustup target list --installed 2>/dev/null | grep -q x86_64-pc-windows-gnu; then
  rustup target add x86_64-pc-windows-gnu >/dev/null 2>&1 || true
fi

# El gancho de antes de subir (tests de lo que cambia y la bitácora de cada commit).
git -C "$raiz" config core.hooksPath .githooks
command -v tauri-driver >/dev/null || echo "Para las e2e falta tauri-driver: cargo install tauri-driver --locked"
echo "Entorno listo: dependencias de Tauri, npm del asistente y crates de Cargo."
