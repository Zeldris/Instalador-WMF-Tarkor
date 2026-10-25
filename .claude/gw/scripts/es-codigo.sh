#!/usr/bin/env bash
# galivelop-workflow v0.3.0
# Lists the files that are code among those changed between two commits: everything that matches none of the
# config's `content` regexes (Python syntax, on repo-relative paths). The review mark file itself is never code; the
# workflow's own policy and guards always are, whatever `content` says (.claude/gw.json, .claude/settings.json,
# .claude/gw/ and .githooks/): otherwise a commit could widen `content` and pass its own code as content.
# Only code needs /code-review (plan §5.3). Used by .githooks/pre-push and the PR hook.
#   bash es-codigo.sh [--rev REV] A B   # A empty = from the empty tree (a brand-new branch)
#   bash es-codigo.sh [--rev REV] --explicar PATH...   # says, for each path, code or content and why (REV: HEAD)
# The config (`content`, `reviewMark`) is read as commit REV has it (default B, the commit being checked), never
# from the working tree: an uncommitted edit cannot turn the pushed code into content.
# Exit 0 with the list (possibly empty) on stdout; exit 2 if the config or a commit is missing (fail closed).
# Bash 3.2 compatible.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(git -C "$here" rev-parse --show-toplevel 2>/dev/null)" || {
  echo "es-codigo: $here is not inside a git repository; reinstall the workflow: /gw-update" >&2; exit 2; }
cd "$root" || exit 2
rev=""
if [ "${1:-}" = "--rev" ]; then rev="${2:-}"; shift 2 || true; fi
config="$here/config.py"
# The one classification, shared by both modes: argv[3] "explain" prints "<path>: code|content (<why>)".
classify='
import json, os, re, sys
patterns = []
for p in json.loads(sys.argv[1]):
    try:
        patterns.append((p, re.compile(p)))
    except re.error as exc:  # exit 3 = a bad content regex only
        print("es-codigo: content regex " + json.dumps(p) + " is invalid: " + str(exc), file=sys.stderr)
        sys.exit(3)
mark, explain = sys.argv[2], sys.argv[3] == "explain"
guard = re.compile(r"^(\.claude/(gw\.json|settings\.json|gw/)|\.githooks/)")
try:
    for line in sys.stdin:
        path = line.rstrip("\n")
        if not path:
            continue
        hit = next((p for p, rx in patterns if rx.search(path)), None)
        if path == mark:
            kind, why = "content", "it is the review mark file, reviewMark"
        elif guard.search(path):
            kind, why = "code", "the workflow policy and guards are always code"
        elif hit is not None:
            kind, why = "content", "matches content regex " + json.dumps(hit)
        else:
            kind, why = "code", "matches no content regex"
        if explain:
            print(path + ": " + kind + " (" + why + ")", flush=True)
        elif kind == "code":
            print(path, flush=True)
except BrokenPipeError:  # the reader closed early (| head -1): it has what it wanted, not an error
    os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
'
# The classifier exits 3 for a bad content regex (it already printed which one); any other code is some other failure.
classify_failed() {
  if [ "$1" -eq 3 ]; then
    echo "es-codigo: fix the regex in .claude/gw.json: python3 $config --root $root validate" >&2
  else
    echo "es-codigo: the classification failed (exit $1), not because of a content regex; see the error above and check python3: python3 --version" >&2
  fi
  exit 2
}
if [ "${1:-}" = "--explicar" ]; then
  shift
  [ "$#" -gt 0 ] || { echo "es-codigo: usage: bash $0 [--rev <commit>] --explicar <path>..." >&2; exit 2; }
  [ -n "$rev" ] || rev="HEAD"
  content="$(python3 "$config" --root "$root" --rev "$rev" get content --json)" || {
    echo "es-codigo: cannot read the config of $rev; commit a valid .claude/gw.json: python3 $config --root $root --rev $rev validate" >&2; exit 2; }
  mark="$(python3 "$config" --root "$root" --rev "$rev" get reviewMark)" || {
    echo "es-codigo: cannot read reviewMark of $rev; fix it: python3 $config --root $root --rev $rev validate" >&2; exit 2; }
  printf '%s\n' "$@" | python3 -c "$classify" "$content" "$mark" explain
  rc=$?; [ "$rc" -eq 0 ] || classify_failed "$rc"
  exit 0
fi
if [ "$#" -ne 2 ] || [ -z "$2" ]; then
  echo "es-codigo: usage: bash $0 [--rev <commit>] <from-commit or empty> <to-commit>" >&2; exit 2
fi
from="$1"; to="$2"
[ -n "$rev" ] || rev="$to"
if [ -z "$from" ]; then
  from="$(git hash-object -t tree /dev/null)"
elif ! git cat-file -e "$from^{commit}" 2>/dev/null; then
  echo "es-codigo: commit $from is not in this clone; fetch it: git fetch --deepen=200 origin" >&2; exit 2
fi
if ! git cat-file -e "$to^{commit}" 2>/dev/null; then
  echo "es-codigo: commit $to is not in this clone; fetch it: git fetch --deepen=200 origin" >&2; exit 2
fi
content="$(python3 "$config" --root "$root" --rev "$rev" get content --json)" || {
  echo "es-codigo: cannot read the config of $rev; commit a valid .claude/gw.json: python3 $config --root $root --rev $rev validate" >&2; exit 2; }
mark="$(python3 "$config" --root "$root" --rev "$rev" get reviewMark)" || {
  echo "es-codigo: cannot read reviewMark of $rev; fix it: python3 $config --root $root --rev $rev validate" >&2; exit 2; }
changed="$(git diff --no-renames --name-only "$from" "$to")" || {
  echo "es-codigo: git diff $from $to failed; check both commits exist: git log -1 $from $to" >&2; exit 2; }
[ -n "$changed" ] || exit 0
printf '%s\n' "$changed" | python3 -c "$classify" "$content" "$mark" list
rc=$?; [ "$rc" -eq 0 ] || classify_failed "$rc"
