#!/bin/bash
# QA-58 (de Tarkor): comprueba que un test nuevo falla sin el
# arreglo que cubre. Aparta los cambios sin commit de los archivos del arreglo, corre ese test por su
# nombre exacto (un -t que no casa con nada «pasa» sin ejecutar el test), exige que falle y lo deja todo
# como estaba. Después corre el test con el arreglo y exige que pase.
#
# Solo vitest (el asistente, en `app`); para el núcleo en Rust, `cargo test <nombre>` a mano con y sin el arreglo.
# Uso (desde la raíz del repo, con el arreglo sin commit):
#   bash tools/qa/rojo-sin-arreglo.sh app <archivo de test> "<nombre exacto del test>" <archivo del arreglo>...
# Ejemplo:
#   bash tools/qa/rojo-sin-arreglo.sh app src/App.test.tsx \
#     "cada perfil explica qué resultado esperar" app/src/pantallas.tsx
set -u
[ $# -ge 4 ] || { sed -n '2,12p' "$0"; exit 2; }
paquete="$1"; test="$2"; nombre="$3"; shift 3
raiz="$(git rev-parse --show-toplevel)"
cd "$raiz" || exit 2
for f in "$@"; do
  # Cambios sin commit, o un archivo nuevo que aún no está en git (también cuenta como arreglo).
  [ -n "$(git status --porcelain -- "$f")" ] || { echo "rojo-sin-arreglo: $f no tiene cambios sin commit (¿es el archivo del arreglo?)"; exit 2; }
done
# -t es una expresión regular sobre «describe > test»: el nombre, escapado y anclado al final, casa solo
# con ese test (sin escapar, «(prueba)» no casaría consigo mismo).
patron="$(printf '%s' "$nombre" | sed -e 's/[][\\.^$*+?(){}|/]/\\&/g')\$"
correr() { (cd "$raiz/$paquete" && npx vitest run "$test" -t "$patron" 2>&1); }
# La línea «Tests»; si el archivo ni carga (p. ej. sin el arreglo falta una exportación), la de «Test Files».
cuenta() { local t; t="$(cat)"; echo "$t" | grep -E "^ *Tests +" | tail -1 | grep . || echo "$t" | grep -E "^ *Test Files +" | tail -1; }

git stash push --quiet --include-untracked -- "$@" || exit 2
trap 'git stash pop --quiet' EXIT
sin="$(correr)"
resumen_sin="$(echo "$sin" | cuenta)"
git stash pop --quiet; trap - EXIT
con="$(correr)"
resumen_con="$(echo "$con" | cuenta)"

echo "Sin el arreglo: $resumen_sin"
echo "Con el arreglo: $resumen_con"
# Exactamente un test ejecutado en cada pasada: si el nombre casa con otros, su resultado se colaría.
ejecutados() { echo "$1" | grep -oE "[0-9]+ (passed|failed)" | awk '{n += $1} END {print n + 0}'; }
for r in "$resumen_sin" "$resumen_con"; do
  [ "$(ejecutados "$r")" = 1 ] || { echo "rojo-sin-arreglo: se ejecutaron $(ejecutados "$r") tests, no 1: revisa el nombre exacto"; exit 1; }
done
if ! echo "$resumen_con" | grep -qE "[1-9][0-9]* passed" || echo "$resumen_con" | grep -q "failed"; then
  echo "rojo-sin-arreglo: con el arreglo no pasa (o no se ejecutó ningún test: revisa el nombre)"; exit 1
fi
if ! echo "$resumen_sin" | grep -q "failed"; then
  echo "rojo-sin-arreglo: sin el arreglo el test también pasa: no cubre el fallo"; exit 1
fi
echo "rojo-sin-arreglo: bien, el test falla sin el arreglo y pasa con él"
