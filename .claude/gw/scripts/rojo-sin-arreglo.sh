#!/usr/bin/env bash
# galivelop-workflow v0.3.0
# Checks that a new test FAILS without the fix it covers (a test that passes either way proves nothing).
# With the fix still uncommitted: it stashes the fix files, runs the test command (it must fail), restores them and
# runs it again (it must pass).
#   bash rojo-sin-arreglo.sh [--fails-with REGEX] "<test command>" <fix-file>...
#   e.g.  bash rojo-sin-arreglo.sh "npx vitest run src/a.test.ts -t 'name'" src/a.ts
#   --fails-with REGEX  the failing run must also print REGEX (guards against failing for another reason, such as a
#                       typo in the test name or a missing import).
#   --ran-one REGEX     the run WITH the fix must print exactly one line matching REGEX, where REGEX is what your test
#                       runner prints once per test that ran (e.g. '^ok ' for TAP, '^PASSED|PASSED$' for pytest -v,
#                       '^test .* \.\.\. ok$' for cargo). Zero lines = the filter matched nothing; two or more = it ran
#                       more than the new test. It reads output, so it works with any runner that prints one line per test.
# Make the command run exactly the new test (by its exact name): a filter that matches nothing may "pass" without
# running it. Every fix file must have uncommitted changes (a new, untracked file counts).
# Bash 3.2 compatible. Root from this script's path, never from $CLAUDE_PROJECT_DIR or the current directory.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
pattern=""
one=""
usage="usage: bash $0 [--fails-with REGEX] [--ran-one REGEX] \"<test command>\" <fix-file>..."
while [ "${1:-}" = "--fails-with" ] || [ "${1:-}" = "--ran-one" ]; do
  [ $# -ge 2 ] || { echo "rojo-sin-arreglo: $1 needs a regex; $usage" >&2; exit 2; }
  if [ "$1" = "--fails-with" ]; then pattern="$2"; else one="$2"; fi
  shift 2
done
if [ $# -lt 2 ]; then
  echo "rojo-sin-arreglo: $usage" >&2; exit 2
fi
cmd="$1"; shift
for re in "$pattern" "$one"; do  # an invalid regex would make grep print nothing and the check pass: refuse it now
  [ -n "$re" ] || continue
  printf '\n' | grep -Eq -- "$re" 2>/dev/null
  [ $? -ne 2 ] || { echo "rojo-sin-arreglo: /$re/ is not a valid extended regex (grep -E); fix it and rerun: $usage" >&2; exit 2; }
done
root="$(git -C "$here" rev-parse --show-toplevel 2>/dev/null)" || {
  echo "rojo-sin-arreglo: $here is not inside a git repository; reinstall the workflow: /gw-update" >&2; exit 2; }
cd "$root" || exit 2
for f in "$@"; do
  [ -n "$(git status --porcelain -- "$f")" ] || {
    echo "rojo-sin-arreglo: $f has no uncommitted changes (is it the fix file? the fix must not be committed yet); check: git status -- $f" >&2; exit 2; }
done
out="$(mktemp -d "${TMPDIR:-/tmp}/gw-rojo.XXXXXX")" || { echo "rojo-sin-arreglo: cannot create a temp dir; free space and retry" >&2; exit 2; }
stashes_before="$(git stash list | grep -c .)"
git stash push --quiet --include-untracked -- "$@" || { rm -rf "$out"; echo "rojo-sin-arreglo: cannot stash the fix files; check: git status" >&2; exit 2; }
if [ "$(git stash list | grep -c .)" -le "$stashes_before" ]; then
  rm -rf "$out"; echo "rojo-sin-arreglo: nothing was stashed; check the fix files: git status -- $*" >&2; exit 2
fi
restored=""
restore() {
  [ -z "$restored" ] || return 0
  restored=1
  git stash pop --quiet || { echo "rojo-sin-arreglo: could not restore the fix files; they are in the stash: git stash list; git stash pop" >&2; return 1; }
}
trap 'restore; rm -rf "$out"' EXIT
bash -c "$cmd" > "$out/without.log" 2>&1 < /dev/null
without=$?
restore || exit 2
bash -c "$cmd" > "$out/with.log" 2>&1 < /dev/null
with=$?

echo "rojo-sin-arreglo: without the fix: exit $without; with the fix: exit $with"
if [ "$with" -ne 0 ]; then
  tail -n 20 "$out/with.log" >&2
  echo "rojo-sin-arreglo: the test does not pass with the fix (or the command is wrong); run it: $cmd" >&2; exit 1
fi
if [ "$without" -eq 0 ]; then
  echo "rojo-sin-arreglo: the test also passes WITHOUT the fix, so it does not cover it; make it fail first, then rerun: bash $0 \"$cmd\" $*" >&2; exit 1
fi
if [ -n "$pattern" ] && ! grep -Eq -- "$pattern" "$out/without.log"; then
  tail -n 20 "$out/without.log" >&2
  echo "rojo-sin-arreglo: it fails without the fix but not with /$pattern/, maybe for another reason; check the output above and rerun" >&2; exit 1
fi
if [ -n "$one" ]; then
  ran="$(grep -Ec -- "$one" "$out/with.log")"
  case "$ran" in '' | *[!0-9]*) echo "rojo-sin-arreglo: cannot count the lines matching /$one/; check the regex and rerun: $usage" >&2; exit 2 ;; esac
  if [ "$ran" -ne 1 ]; then
    tail -n 20 "$out/with.log" >&2
    echo "rojo-sin-arreglo: $ran lines match /$one/ in the run with the fix, expected exactly 1 (the new test); narrow the command's test filter so it runs only that test, then rerun" >&2; exit 1
  fi
fi
echo "rojo-sin-arreglo: OK, the test fails without the fix and passes with it"
exit 0
