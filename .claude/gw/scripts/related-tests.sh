#!/usr/bin/env bash
# galivelop-workflow v0.5.0
# The tests of what changes, in the push. Called by .githooks/pre-push as:
#   related-tests.sh <changed-files-file> [<checkout-dir>]
# (one repo-relative path per line; git's ref lines on stdin are ignored). <checkout-dir> is where the pushed commit
# is checked out (default: the project root, i.e. its HEAD); the commands run there, and relatedTests is read from
# that commit's .claude/gw.json:
#   fast  commands that run on every push; one whose text has {files} runs only if some changed file exists in it
#   slow  commands that run only when some changed file exists in the commit or some file was deleted (e.g.
#         foo.ts -> foo.integration.test.ts)
# An entry is a string or {"command", "paths"?, "cwd"?}: `paths` (regex) limits it to the changed files that match,
# `cwd` is the folder it runs in ({files} relative to it); `checkWrapper` prefixes every command. config.py
# (`related`) decides which commands apply and builds each line; this script runs them.
# {files} is replaced by the changed files that exist in the commit (git cat-file, not the disk), each shell-quoted;
# nonexistent paths are never passed. Deleted files are decided PER ENTRY: if an entry's scope (`paths`/`cwd`) matches
# an existing changed file it behaves as always; if it matches none but matches a deleted file, an entry whose command
# uses {files} is skipped (a note on stdout) and one without {files} runs. Fast ones go first; the first failure stops
# the run (exit 1). A no-op when relatedTests is absent or empty. Fails closed on an invalid config.
# Bash 3.2 compatible. Root from this script's path, never from $CLAUDE_PROJECT_DIR or the current directory.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
if [ "$#" -lt 1 ]; then echo "related-tests: usage: related-tests.sh <changed-files-file> [<checkout-dir>]" >&2; exit 2; fi
list="$1"
# Git exports GIT_DIR (and friends) to hooks, also in a linked worktree; with GIT_DIR set `rev-parse --show-toplevel`
# answers $here, not the repo root.
root="$(unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE; git -C "$here" rev-parse --show-toplevel 2>/dev/null)" || {
  echo "related-tests: $here is not inside a git repository; reinstall the workflow: /gw-update" >&2; exit 2; }
dir="${2:-$root}"
sha="$(git -C "$dir" rev-parse -q --verify 'HEAD^{commit}' 2>/dev/null)" || {
  echo "related-tests: $dir has no checked-out commit; push again from the project: git push" >&2; exit 1; }
cd "$dir" || exit 2
config="$here/config.py"
python3 "$config" --root "$root" --rev "$sha" validate > /dev/null || {
  echo "related-tests: the config is invalid; fix it: python3 $config --root $root --rev ${sha:0:7} validate" >&2; exit 1; }
existing=""
deleted=""
if [ -f "$list" ]; then
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    if git cat-file -e "$sha:$f" 2>/dev/null; then existing="$existing$f"$'\n'; else deleted="$deleted$f"$'\n'; fi
  done < "$list"
fi
delfile="$(mktemp "${TMPDIR:-/tmp}/gw-related-deleted.XXXXXX")" || { echo "related-tests: cannot create a temp file; check \$TMPDIR" >&2; exit 2; }
trap 'rm -f "$delfile"' EXIT
printf '%s' "$deleted" > "$delfile"

run() {  # run <kind>: every command config.py says applies, one NUL-terminated line each
  local kind="$1" full cmds
  cmds="$(printf '%s' "$existing" | python3 "$config" --root "$root" --rev "$sha" related --kind "$kind" --deleted-file "$delfile" 2>&4 | tr '\0' '\001')" || {
    echo "related-tests: cannot work out the $kind commands; fix the config: python3 $config --root $root --rev ${sha:0:7} validate" >&2; exit 1; }
  while IFS= read -r -d $'\001' full; do
    echo "pre-push: related tests ($kind): $full"
    bash -c "$full" < /dev/null || {
      echo "related-tests: failed ($kind): $full; fix it and run it again: $full" >&2; exit 1; }
  done <<<"$cmds"
}
exec 4>&1  # config.py notes (skipped entries) go to stdout
run fast
run slow
exit 0
