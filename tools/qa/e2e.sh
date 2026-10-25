#!/bin/bash
# Corre los E2E del asistente (app/e2e/*.e2e.mjs) en una orden (INS-43, retro R5). Hace lo que describe
# app/README.md, «Prueba de punta a punta (Linux)»; si ese texto y este script difieren, manda el script.
#   1. Compila el binario con `npx tauri build --no-bundle` y usa ese (target/release/tarkor), nunca el instalado
#      (/usr/bin/tarkor puede ser de otra versión).
#   2. Por cada prueba: HOME con nombre de usuario de 4+ letras (rendimiento.e2e.mjs lo exige), TARKOR_DATOS nuevo,
#      un tauri-driver propio en el puerto 4444 (el que esperan las pruebas) y todo bajo xvfb-run.
#   3. asistente.e2e.mjs va con el Ollama falso externo (TARKOR_OLLAMA_URL, puerto 11499); el resto, con el motor
#      propio de la app y TARKOR_OLLAMA_URL sin poner.
#   4. Imprime una línea por prueba (y el final del log si falla). Log y capturas, en la carpeta que imprime.
# Uso: bash tools/qa/e2e.sh [archivo.e2e.mjs]...   (sin argumentos, todas las de app/e2e). Sale con 1 si alguna falla.
# Necesita webkit2gtk-driver, xvfb y tauri-driver (cargo install tauri-driver --locked); ver app/README.md.
set -uo pipefail
raiz="$(cd "$(dirname "$0")/../.." && pwd)"
puerto=4444
puerto_falso=11499

fallo() { echo "e2e: $*" >&2; exit 2; }

# Las pruebas, antes de compilar nada: una ruta mala falla en el acto.
pruebas=()
if [ "$#" -eq 0 ]; then
  for f in "$raiz"/app/e2e/*.e2e.mjs; do [ -f "$f" ] && pruebas+=("$f"); done
else
  for a in "$@"; do
    [ -f "$a" ] || fallo "no existe la prueba '$a' (uso: bash tools/qa/e2e.sh [archivo.e2e.mjs]...)"
    case "$a" in *.e2e.mjs) ;; *) fallo "'$a' no es una prueba (*.e2e.mjs)" ;; esac
    pruebas+=("$(cd "$(dirname "$a")" && pwd)/$(basename "$a")")
  done
fi
[ "${#pruebas[@]}" -gt 0 ] || fallo "no hay pruebas en app/e2e"

for h in node npx xvfb-run tauri-driver WebKitWebDriver; do
  command -v "$h" >/dev/null 2>&1 || fallo "falta '$h' (sudo apt install webkit2gtk-driver xvfb; cargo install tauri-driver --locked)"
done

# Igual que en-app.sh: en un worktree, Cargo reutiliza el app/target del checkout principal.
principal="$(cd "$(git -C "$raiz" rev-parse --git-common-dir)/.." && pwd)"
if [ "$raiz" != "$principal" ]; then export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$principal/app/target}"; fi
binario="${CARGO_TARGET_DIR:-$raiz/app/target}/release/tarkor"

carpeta="$(mktemp -d "${TMPDIR:-/tmp}/tarkor-e2e.XXXXXX")"
echo "e2e: carpeta de la ejecución: $carpeta"
echo "e2e: compilando (npx tauri build --no-bundle)…"
if ! (cd "$raiz/app" && npx tauri build --no-bundle) >"$carpeta/compilar.log" 2>&1; then
  tail -n 30 "$carpeta/compilar.log"
  fallo "no compila; log completo en $carpeta/compilar.log"
fi
[ -x "$binario" ] || fallo "tras compilar no existe $binario"
echo "e2e: binario: $binario"

fallidas=0
for prueba in "${pruebas[@]}"; do
  nombre="$(basename "$prueba" .e2e.mjs)"
  log="$carpeta/$nombre.log"
  casa="$carpeta/$nombre/lucianita"
  mkdir -p "$casa" "$carpeta/$nombre/datos" "$carpeta/$nombre/capturas"
  (
    export HOME="$casa" TARKOR_DATOS="$carpeta/$nombre/datos" WEBDRIVER_URL="http://127.0.0.1:$puerto"
    unset TARKOR_OLLAMA_URL
    falso=""
    if [ "$nombre" = "asistente" ]; then
      export TARKOR_OLLAMA_URL="http://127.0.0.1:$puerto_falso"
      falso="node $raiz/app/e2e/ollama-falso.mjs $puerto_falso & F=\$!;"
    fi
    cd "$raiz/app"
    exec xvfb-run -a sh -c "$falso tauri-driver --port $puerto & D=\$!; trap 'kill \$D \$F 2>/dev/null' EXIT; sleep 2; node '$prueba' '$binario' '$carpeta/$nombre/capturas'"
  ) >"$log" 2>&1
  if [ $? -eq 0 ]; then
    echo "PASA   $nombre"
  else
    echo "FALLA  $nombre (final del log):"
    tail -n 25 "$log" | sed 's/^/    /'
    fallidas=$((fallidas + 1))
  fi
done

echo "e2e: logs y capturas en $carpeta"
[ "$fallidas" -eq 0 ] || { echo "e2e: $fallidas prueba(s) en rojo" >&2; exit 1; }
echo "e2e: todo en verde"
