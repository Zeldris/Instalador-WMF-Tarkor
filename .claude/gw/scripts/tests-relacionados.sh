#!/usr/bin/env bash
# galivelop-workflow v0.3.0
# The tests of what changes, in the push. Called by .githooks/pre-push as:
#   tests-relacionados.sh <changed-files-file> [<checkout-dir>]
# (one repo-relative path per line; git's ref lines on stdin are ignored). <checkout-dir> is where the pushed commit
# is checked out (default: the project root, i.e. its HEAD); the commands run there, and relatedTests is read from
# that commit's .claude/gw.json:
#   fast  commands that run on every push; one whose text has {files} runs only if some changed file exists in it
#   slow  commands that run only when some changed file exists in the commit (e.g. foo.ts -> foo.integration.test.ts)
# An entry is a string or {"command", "paths"?, "cwd"?}: `paths` (regex) limits it to the changed files that match,
# `cwd` is the folder it runs in ({files} relative to it); `checkWrapper` prefixes every command. config.py
# (`related`) decides which commands apply and builds each line; this script runs them.
# {files} is replaced by the changed files that exist in the commit (git cat-file, not the disk), each shell-quoted. Fast ones go first; the first failure stops
# the run (exit 1). A no-op when relatedTests is absent or empty. Fails closed on an invalid config.
# Bash 3.2 compatible. Root from this script's path, never from $CLAUDE_PROJECT_DIR or the current directory.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
if [ "$#" -lt 1 ]; then echo "tests-relacionados: usage: tests-relacionados.sh <changed-files-file> [<checkout-dir>]" >&2; exit 2; fi
list="$1"
root="$(git -C "$here" rev-parse --show-toplevel 2>/dev/null)" || {
  echo "tests-relacionados: $here is not inside a git repository; reinstall the workflow: /gw-update" >&2; exit 2; }
dir="${2:-$root}"
sha="$(git -C "$dir" rev-parse -q --verify 'HEAD^{commit}' 2>/dev/null)" || {
  echo "tests-relacionados: $dir has no checked-out commit; push again from the project: git push" >&2; exit 1; }
cd "$dir" || exit 2
config="$here/config.py"
python3 "$config" --root "$root" --rev "$sha" validate > /dev/null || {
  echo "tests-relacionados: the config is invalid; fix it: python3 $config --root $root --rev ${sha:0:7} validate" >&2; exit 1; }
existing=""
if [ -f "$list" ]; then
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    git cat-file -e "$sha:$f" 2>/dev/null || continue
    existing="$existing$f"$'\n'
  done < "$list"
fi

run() {  # run <kind>: every command config.py says applies, one NUL-terminated line each
  local kind="$1" full cmds
  cmds="$(printf '%s' "$existing" | python3 "$config" --root "$root" --rev "$sha" related --kind "$kind" | tr '\0' '\001')" || {
    echo "tests-relacionados: cannot work out the $kind commands; fix the config: python3 $config --root $root --rev ${sha:0:7} validate" >&2; exit 1; }
  while IFS= read -r -d $'\001' full; do
    echo "pre-push: related tests ($kind): $full"
    bash -c "$full" < /dev/null || {
      echo "tests-relacionados: failed ($kind): $full; fix it and run it again: $full" >&2; exit 1; }
  done <<<"$cmds"
}
run fast
run slow
exit 0
