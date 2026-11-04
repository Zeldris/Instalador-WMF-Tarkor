#!/usr/bin/env bash
# galivelop-workflow v0.5.0
# Lists the files that are code among those changed between two commits: everything that matches none of the
# config's `content` regexes (Python syntax, on repo-relative paths). The review mark file and the local CI log
# (`ciLocalLog`, written by ci-local.py --record) are never code; the workflow's own policy and guards always are, whatever `content` says (.claude/gw.json, .claude/settings.json,
# .claude/gw/ and .githooks/): otherwise a commit could widen `content` and pass its own code as content.
# Only code needs /code-review (plan §5.3). Used by .githooks/pre-push and the PR hook.
#   bash is-code.sh [--rev REV] A B   # A empty = from the empty tree (a brand-new branch)
#   bash is-code.sh [--rev REV] --explain PATH...   # says, for each path, code or content and why (REV: HEAD)
# The config (`content`, `reviewMark`, `ciLocalLog`) is read as commit REV has it (default B, the commit being checked), never
# from the working tree: an uncommitted edit cannot turn the pushed code into content.
# (--explicar, the old name of --explain, still works in 0.x, with a warning.)
# Exit 0 with the list (possibly empty) on stdout; exit 2 if the config or a commit is missing (fail closed).
# Bash 3.2 compatible.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# Git exports GIT_DIR (and friends) to hooks, also in a linked worktree; with GIT_DIR set `rev-parse --show-toplevel`
# answers $here, not the repo root.
root="$(unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE; git -C "$here" rev-parse --show-toplevel 2>/dev/null)" || {
  echo "is-code: $here is not inside a git repository; reinstall the workflow: /gw-update" >&2; exit 2; }
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
        print("is-code: content regex " + json.dumps(p) + " is invalid: " + str(exc), file=sys.stderr)
        sys.exit(3)
mark, explain, cilog = sys.argv[2], sys.argv[3] == "explain", sys.argv[4]
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
        elif path == cilog:
            kind, why = "content", "it is the local CI log, ciLocalLog"
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
    sys.stdin.read()  # drain it: with pipefail, a writer killed by SIGPIPE (141) would fail the whole pipeline
'
# The classifier exits 3 for a bad content regex (it already printed which one); any other code is some other failure.
classify_failed() {
  if [ "$1" -eq 3 ]; then
    echo "is-code: fix the regex in .claude/gw.json: python3 $config --root $root validate" >&2
  else
    echo "is-code: the classification failed (exit $1), not because of a content regex; see the error above and check python3: python3 --version" >&2
  fi
  exit 2
}
if [ "${1:-}" = "--explicar" ]; then
  echo "is-code: warning: --explicar is deprecated and will stop working in 1.0; use --explain" >&2
  shift
  set -- --explain "$@"
fi
if [ "${1:-}" = "--explain" ]; then
  shift
  [ "$#" -gt 0 ] || { echo "is-code: usage: bash $0 [--rev <commit>] --explain <path>..." >&2; exit 2; }
  [ -n "$rev" ] || rev="HEAD"
  paths="$rev"
  content="$(python3 "$config" --root "$root" --rev "$rev" get content --json)" || {
    echo "is-code: cannot read the config of $rev; commit a valid .claude/gw.json: python3 $config --root $root --rev $rev validate" >&2; exit 2; }
  mark="$(python3 "$config" --root "$root" --rev "$rev" --paths-at "$paths" get reviewMark)" || {
    echo "is-code: cannot read reviewMark of $rev; fix it: python3 $config --root $root --rev $rev validate" >&2; exit 2; }
  cilog="$(python3 "$config" --root "$root" --rev "$rev" --paths-at "$paths" get ciLocalLog)" || {
    echo "is-code: cannot read ciLocalLog of $rev; fix it: python3 $config --root $root --rev $rev validate" >&2; exit 2; }
  printf '%s\n' "$@" | python3 -c "$classify" "$content" "$mark" explain "$cilog"
  rc=$?; [ "$rc" -eq 0 ] || classify_failed "$rc"
  exit 0
fi
if [ "$#" -ne 2 ] || [ -z "$2" ]; then
  echo "is-code: usage: bash $0 [--rev <commit>] <from-commit or empty> <to-commit>" >&2; exit 2
fi
from="$1"; to="$2"
[ -n "$rev" ] || rev="$to"
paths="$to"  # the old-name fallback of the path keys is judged on the commit being checked
if [ -z "$from" ]; then
  from="$(git hash-object -t tree /dev/null)"
elif ! git cat-file -e "$from^{commit}" 2>/dev/null; then
  echo "is-code: commit $from is not in this clone; fetch it: git fetch --deepen=200 origin" >&2; exit 2
fi
if ! git cat-file -e "$to^{commit}" 2>/dev/null; then
  echo "is-code: commit $to is not in this clone; fetch it: git fetch --deepen=200 origin" >&2; exit 2
fi
content="$(python3 "$config" --root "$root" --rev "$rev" get content --json)" || {
  echo "is-code: cannot read the config of $rev; commit a valid .claude/gw.json: python3 $config --root $root --rev $rev validate" >&2; exit 2; }
mark="$(python3 "$config" --root "$root" --rev "$rev" --paths-at "$paths" get reviewMark)" || {
  echo "is-code: cannot read reviewMark of $rev; fix it: python3 $config --root $root --rev $rev validate" >&2; exit 2; }
cilog="$(python3 "$config" --root "$root" --rev "$rev" --paths-at "$paths" get ciLocalLog)" || {
  echo "is-code: cannot read ciLocalLog of $rev; fix it: python3 $config --root $root --rev $rev validate" >&2; exit 2; }
changed="$(git diff --no-renames --name-only "$from" "$to")" || {
  echo "is-code: git diff $from $to failed; check both commits exist: git log -1 $from $to" >&2; exit 2; }
[ -n "$changed" ] || exit 0
printf '%s\n' "$changed" | python3 -c "$classify" "$content" "$mark" list "$cilog"
rc=$?; [ "$rc" -eq 0 ] || classify_failed "$rc"
