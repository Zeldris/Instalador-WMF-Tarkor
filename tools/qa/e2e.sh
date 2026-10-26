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

for h in node npx nc xvfb-run tauri-driver WebKitWebDriver; do
  command -v "$h" >/dev/null 2>&1 || fallo "falta '$h' (sudo apt install webkit2gtk-driver xvfb netcat-openbsd; cargo install tauri-driver --locked)"
done

# Igual que en-app.sh: en un worktree, Cargo reutiliza el app/target del checkout principal.
# Ruta absoluta: la relativa (`.git`) se resolvería contra la carpeta desde la que se llama.
principal="$(cd "$(git -C "$raiz" rev-parse --path-format=absolute --git-common-dir)/.." && pwd)"
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

libre() { ! nc -z 127.0.0.1 "$1" 2>/dev/null; }
# Un tauri-driver o un Ollama falso que siguen vivos (de un Ctrl-C) atenderían la prueba con otro HOME y otros datos.
ocupado() { fallo "el puerto $1 está ocupado (¿un tauri-driver u ollama-falso.mjs de otra ejecución? pkill -f 'tauri-driver|ollama-falso')"; }
limpiar() { pkill -f "tauri-driver --port $puerto" 2>/dev/null; pkill -f "ollama-falso.mjs $puerto_falso" 2>/dev/null; pkill -x WebKitWebDriver 2>/dev/null; }
trap 'limpiar; exit 130' INT TERM

fallidas=0
for prueba in "${pruebas[@]}"; do
  libre "$puerto" || ocupado "$puerto"
  libre "$puerto_falso" || ocupado "$puerto_falso"
  nombre="$(basename "$prueba" .e2e.mjs)"
  log="$carpeta/$nombre.log"
  casa="$carpeta/$nombre/lucianita"
  mkdir -p "$casa" "$carpeta/$nombre/datos" "$carpeta/$nombre/capturas"
  (
    export HOME="$casa" TARKOR_DATOS="$carpeta/$nombre/datos" WEBDRIVER_URL="http://127.0.0.1:$puerto"
    unset TARKOR_OLLAMA_URL
    export E2E_RAIZ="$raiz" E2E_PRUEBA="$prueba" E2E_BINARIO="$binario" E2E_CAPTURAS="$carpeta/$nombre/capturas"
    export E2E_PUERTO="$puerto" E2E_PUERTO_FALSO="$puerto_falso" E2E_FALSO=""
    if [ "$nombre" = "asistente" ]; then
      export TARKOR_OLLAMA_URL="http://127.0.0.1:$puerto_falso" E2E_FALSO=1
      # La primera descarga de un modelo se corta como sin internet: el asistente espera y reintenta solo (INS-42).
      export FALSO_CORTES_PULL="${FALSO_CORTES_PULL:-1}"
    fi
    cd "$raiz/app"
    # Las rutas van por el entorno (no dentro de la orden) para que un espacio o una comilla no la rompan, y se espera
    # a que cada servicio escuche en vez de un tiempo fijo.
    exec xvfb-run -a bash -c '
      escucha() { for _ in $(seq 100); do nc -z 127.0.0.1 "$1" 2>/dev/null && return 0; sleep 0.1; done; echo "e2e: nadie escucha en $1" >&2; return 1; }
      F=; if [ -n "$E2E_FALSO" ]; then node "$E2E_RAIZ/app/e2e/ollama-falso.mjs" "$E2E_PUERTO_FALSO" & F=$!; fi
      tauri-driver --port "$E2E_PUERTO" & D=$!
      trap '"'"'kill $D $F 2>/dev/null'"'"' EXIT
      escucha "$E2E_PUERTO" || exit 1
      if [ -n "$F" ]; then escucha "$E2E_PUERTO_FALSO" || exit 1; fi
      node "$E2E_PRUEBA" "$E2E_BINARIO" "$E2E_CAPTURAS"'
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
