#!/usr/bin/env bash
# galivelop-workflow v0.6.0
# Checks that a new test FAILS without the fix it covers (a test that passes either way proves nothing).
# With the fix still uncommitted: it stashes the fix files, runs the test command (it must fail), restores them and
# runs it again (it must pass).
#   bash red-without-fix.sh [--fix-at COMMIT] [--fails-with REGEX] [--reject-compile-red] [--compile-re REGEX]
#                           [--ran-one REGEX] "<test command>" <fix-file>...
#   e.g.  bash red-without-fix.sh "npx vitest run src/a.test.ts -t 'name'" src/a.ts
#   --fails-with REGEX  the failing run must also print REGEX (guards against failing for another reason, such as a
#                       typo in the test name or a missing import).
#   --ran-one REGEX     the run WITH the fix must print exactly one line matching REGEX, where REGEX is what your test
#                       runner prints once per test that ran (e.g. '^ok ' for TAP, '^PASSED|PASSED$' for pytest -v,
#                       '^test .* \.\.\. ok$' for cargo). Zero lines = the filter matched nothing; two or more = it ran
#                       more than the new test. It reads output, so it works with any runner that prints one line per test.
#   --fix-at COMMIT    the fix is ALREADY committed (COMMIT, an ancestor of HEAD): the run "without the fix" uses each
#                      fix file as it was at COMMIT^ (a file the commit created is removed), then restores it from HEAD.
#                      The fix files must have no uncommitted changes. Without it the fix must be uncommitted (below).
#                      Caveat: the filters of the repo (eol, LFS) are applied, but the test command runs on the working
#                      tree, so later commits that touch the fix files are not part of the "without" run.
#   The kind of red is always printed: an "assertion" red, or a "compile/load" red (the run without the fix failed
#   because the test cannot even load: SyntaxError, ModuleNotFoundError, "ERROR collecting", "error TS1234",
#   "could not compile"...), with the line(s) that matched. By default a compile/load red is only REPORTED (the exit
#   status is the one of an assertion red): it is the usual red when the fix adds the very symbol the test imports.
#   --reject-compile-red  a compile/load red exits 1 (unless --fails-with is given, whose regex then decides).
#   --compile-re REGEX    replaces the list of load-failure messages (redWithoutFix.compileRegex of .claude/gw.json, else the
#                         built-in one; for a runner it does not know). redWithoutFix.testRegex does the same for test code.
# Make the command run exactly the new test (by its exact name): a filter that matches nothing may "pass" without
# running it. Without --fix-at every fix file must have uncommitted changes (a new, untracked file counts).
# The test must NOT be uncommitted in a fix file: stashing the fix would take the test with it and the check could not
# tell (it may report "also passes WITHOUT the fix"). So a fix file whose uncommitted changes touch test code (a
# `def test_`, `it(`, `#[test]`... line changed, or enclosing a changed line, or in a new file) is refused with exit 2:
# commit the test first (`git add -p` for just its hunks, or move it to its own file) and pass only the fix files.
# It reads the diff, not the command: a command may legitimately name a fix file (grep, a linter, `foo.py --selftest`).
# Bash 3.2 compatible. Root from this script's path, never from $CLAUDE_PROJECT_DIR or the current directory.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
pattern=""
one=""
fixat=""
reject_compile=""
compile_re=""  # --compile-re, else redWithoutFix.compileRegex of .claude/gw.json
usage="usage: bash $0 [--fix-at COMMIT] [--fails-with REGEX] [--reject-compile-red] [--compile-re REGEX] [--ran-one REGEX] \"<test command>\" <fix-file>..."
while :; do
  case "${1:-}" in
    --reject-compile-red) reject_compile=1; shift ;;
    --fails-with | --ran-one | --fix-at | --compile-re)
      [ $# -ge 2 ] || { echo "red-without-fix: $1 needs a regex or value; $usage" >&2; exit 2; }
      case "$1" in
        --fails-with) pattern="$2" ;;
        --ran-one) one="$2" ;;
        --fix-at) fixat="$2" ;;
        --compile-re) compile_re="$2" ;;
      esac
      shift 2 ;;
    *) break ;;
  esac
done
if [ $# -lt 2 ]; then
  echo "red-without-fix: $usage" >&2; exit 2
fi
cmd="$1"; shift
# Git exports GIT_DIR (and friends) to hooks, also in a linked worktree; with GIT_DIR set `rev-parse --show-toplevel`
# answers $here, not the repo root.
root="$(unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE; git -C "$here" rev-parse --show-toplevel 2>/dev/null)" || {
  echo "red-without-fix: $here is not inside a git repository; reinstall the workflow: /gw-update" >&2; exit 2; }
cd "$root" || exit 2
if [ -z "$compile_re" ]; then
  compile_re="$(python3 "$here/config.py" --root "$root" get redWithoutFix.compileRegex)" || {
    echo "red-without-fix: cannot read redWithoutFix.compileRegex; fix .claude/gw.json: python3 $here/config.py --root $root validate" >&2; exit 2; }
fi
test_re="$(python3 "$here/config.py" --root "$root" get redWithoutFix.testRegex)" || {
  echo "red-without-fix: cannot read redWithoutFix.testRegex; fix .claude/gw.json: python3 $here/config.py --root $root validate" >&2; exit 2; }
for re in "$pattern" "$one" "$compile_re" "$test_re"; do  # an invalid regex would make grep print nothing and the check pass: refuse it now
  [ -n "$re" ] || continue
  printf '\n' | grep -Eq -- "$re" 2>/dev/null
  [ $? -ne 2 ] || { echo "red-without-fix: /$re/ is not a valid extended regex (grep -E); fix it (a regex of redWithoutFix in .claude/gw.json, or the flag) and rerun: $usage" >&2; exit 2; }
done
if [ -n "$fixat" ]; then
  fixc="$(git rev-parse --verify --quiet "$fixat^{commit}")" || {
    echo "red-without-fix: --fix-at $fixat is not a commit; check: git log --oneline" >&2; exit 2; }
  git rev-parse --verify --quiet "$fixc^" > /dev/null || {
    echo "red-without-fix: --fix-at $fixat has no parent commit to compare with; the fix cannot be a root commit" >&2; exit 2; }
  git merge-base --is-ancestor "$fixc" HEAD || {
    echo "red-without-fix: --fix-at $fixat is not an ancestor of HEAD; check out the branch that holds it: git branch --contains $fixat" >&2; exit 2; }
  for f in "$@"; do
    [ -z "$(git status --porcelain -- "$f")" ] || {
      echo "red-without-fix: $f has uncommitted changes; with --fix-at the fix files must be clean (commit or stash them): git status -- $f" >&2; exit 2; }
    git cat-file -e "HEAD:$f" 2> /dev/null || {
      echo "red-without-fix: $f is not in HEAD; with --fix-at name files that exist there: git ls-files -- $f" >&2; exit 2; }
    git diff --quiet "$fixc^" "$fixc" -- "$f" && {
      echo "red-without-fix: commit $fixat does not change $f; name the files that commit fixed: git show --stat $fixat" >&2; exit 2; }
  done
else
  for f in "$@"; do
    [ -n "$(git status --porcelain -- "$f")" ] || {
      echo "red-without-fix: $f has no uncommitted changes (is it the fix file? the fix must not be committed yet; if it is, use --fix-at <commit>); check: git status -- $f" >&2; exit 2; }
  done
fi
# Test code in the uncommitted changes of a fix file: the changed lines (-U0, with the hunk header) and the lines that
# enclose each one (walking up, each line less indented than the last), so an edit deep inside an indented test method
# still shows its `def test_` line, while an edit in a flat file (a shell script, a config) adds nothing around it.
changed_lines() {  # `git diff -U0` on stdin -> the new file's line numbers it changes (a deletion: the lines around it)
  awk '/^@@ /{ split($3, a, ","); s = substr(a[1], 2) + 0; c = (a[2] == "") ? 1 : a[2] + 0
               if (c == 0) { print s; print s + 1 } else for (i = 0; i < c; i++) print s + i }'
}
enclosing() {  # <file>; line numbers on stdin -> the lines above each one that are less indented, nearest first
  awk -v f="$1" 'function ind(s) { match(s, /^[ \t]*/); return RLENGTH }
    BEGIN { while ((getline l < f) > 0) L[++n] = l }
    { t = $1 + 0; if (t < 1 || t > n) next; m = ind(L[t])
      for (i = t - 1; i >= 1 && m > 0; i--) if (L[i] !~ /^[ \t]*$/ && ind(L[i]) < m) { print L[i]; m = ind(L[i]) } }'
}
kindchg="uncommitted"; verb="stashing"
[ -z "$fixat" ] || { kindchg="committed"; verb="reverting"; }
# Text and data files (nonTestExtensions of .claude/gw.json) hold no test code: prose such as "improve it (URL)" would
# match `it(`. The extension is what follows the last dot of the file name, compared in lower case; a name without a
# dot (Makefile) or with only a leading one (.env) has none and is always searched.
skipexts="$(python3 "$here/config.py" --root "$root" get nonTestExtensions)" || {
  echo "red-without-fix: cannot read nonTestExtensions; fix .claude/gw.json: python3 $here/config.py --root $root validate" >&2; exit 2; }
for f in "$@"; do
  base="${f##*/}"; ext=""
  case "${base#.}" in *.*) ext="$(printf '%s' "${base##*.}" | tr '[:upper:]' '[:lower:]')" ;; esac
  case "$ext" in *[!a-z0-9]*) ext="" ;; esac  # the schema allows only [a-z0-9]: anything else (a newline would split the grep patterns) is never skipped
  if [ -n "$ext" ] && printf '%s\n' "$skipexts" | grep -Fxq -- "$ext"; then
    echo "red-without-fix: $f is a .$ext text/data file (nonTestExtensions), so it is not searched for test code"
    continue
  fi
  if [ -n "$fixat" ]; then
    diff="$(git diff "$fixc^" "$fixc" -U0 -- "$f" 2>/dev/null)"
    hit="$( { printf '%s\n' "$diff" | grep -Ev '^(\+\+\+|---|diff --git|index )'
              printf '%s\n' "$diff" | changed_lines | enclosing "$f"; } | grep -Em1 -- "$test_re")"
  elif git ls-files --error-unmatch -- "$f" > /dev/null 2>&1; then
    diff="$(git diff HEAD -U0 -- "$f" 2>/dev/null)"
    hit="$( { printf '%s\n' "$diff" | grep -Ev '^(\+\+\+|---|diff --git|index )'
              printf '%s\n' "$diff" | changed_lines | enclosing "$f"; } | grep -Em1 -- "$test_re")"
  elif [ -f "$f" ]; then
    hit="$(grep -Em1 -- "$test_re" "$f")"
  else
    hit=""
  fi
  [ -z "$hit" ] || {
    echo "red-without-fix: $f has $kindchg changes that touch test code ($hit); $verb the fix would remove that test too, so the check could not tell if the test covers the fix. Put the test in its own file or commit it first (git add -p), then rerun with only the fix files: bash $0 \"$cmd\" <fix-file>..." >&2; exit 2; }
done
out="$(mktemp -d "${TMPDIR:-/tmp}/gw-rojo.XXXXXX")" || { echo "red-without-fix: cannot create a temp dir; free space and retry" >&2; exit 2; }
restored=""
if [ -n "$fixat" ]; then
  restore() {
    [ -z "$restored" ] || return 0
    restored=1
    git checkout -q HEAD -- "$@" || { echo "red-without-fix: could not restore the fix files; run: git checkout HEAD -- $*" >&2; return 1; }
  }
  trap 'restore "$@"; rm -rf "$out"' EXIT
  for f in "$@"; do
    if git cat-file -e "$fixc^:$f" 2> /dev/null; then
      git checkout -q "$fixc^" -- "$f" || { echo "red-without-fix: cannot revert $f; restore with: git checkout HEAD -- $f" >&2; exit 2; }
    else
      rm -f -- "$f"  # the fix commit created it
    fi
  done
else
  stashes_before="$(git stash list | grep -c .)"
  git stash push --quiet --include-untracked -- "$@" || { rm -rf "$out"; echo "red-without-fix: cannot stash the fix files; check: git status" >&2; exit 2; }
  if [ "$(git stash list | grep -c .)" -le "$stashes_before" ]; then
    rm -rf "$out"; echo "red-without-fix: nothing was stashed; check the fix files: git status -- $*" >&2; exit 2
  fi
  restore() {
    [ -z "$restored" ] || return 0
    restored=1
    git stash pop --quiet || { echo "red-without-fix: could not restore the fix files; they are in the stash: git stash list; git stash pop" >&2; return 1; }
  }
  trap 'restore; rm -rf "$out"' EXIT
fi
bash -c "$cmd" > "$out/without.log" 2>&1 < /dev/null
without=$?
restore "$@" || exit 2
bash -c "$cmd" > "$out/with.log" 2>&1 < /dev/null
with=$?

echo "red-without-fix: without the fix: exit $without; with the fix: exit $with"
if [ "$with" -ne 0 ]; then
  tail -n 20 "$out/with.log" >&2
  echo "red-without-fix: the test does not pass with the fix (or the command is wrong); run it: $cmd" >&2; exit 1
fi
if [ "$without" -eq 0 ]; then
  echo "red-without-fix: the test also passes WITHOUT the fix, so it does not cover it; make it fail first, then rerun: bash $0 \"$cmd\" $*" >&2; exit 1
fi
kind="assertion"
hitline="$(grep -Em3 -- "$compile_re" "$out/without.log")"
if [ -n "$hitline" ]; then kind="compile/load"; fi
art="a"; [ "$kind" != "assertion" ] || art="an"
echo "red-without-fix: the red without the fix is $art $kind red"
if [ "$kind" = "compile/load" ]; then
  printf '%s\n' "$hitline" | sed 's/^/red-without-fix:   matched: /'
fi
if [ -z "$pattern" ] && [ "$kind" = "compile/load" ] && [ -n "$reject_compile" ]; then
  tail -n 20 "$out/without.log" >&2
  echo "red-without-fix: it fails without the fix only because the test cannot load (compile/import/collection error), which says nothing about the assertion; make the test load and fail on its assertion, or pass --fails-with REGEX, then rerun: bash $0 \"$cmd\" $*" >&2; exit 1
fi
if [ -n "$pattern" ] && ! grep -Eq -- "$pattern" "$out/without.log"; then
  tail -n 20 "$out/without.log" >&2
  echo "red-without-fix: it fails without the fix but not with /$pattern/, maybe for another reason; check the output above and rerun" >&2; exit 1
fi
if [ -n "$one" ]; then
  ran="$(grep -Ec -- "$one" "$out/with.log")"
  case "$ran" in '' | *[!0-9]*) echo "red-without-fix: cannot count the lines matching /$one/; check the regex and rerun: $usage" >&2; exit 2 ;; esac
  if [ "$ran" -ne 1 ]; then
    tail -n 20 "$out/with.log" >&2
    echo "red-without-fix: $ran lines match /$one/ in the run with the fix, expected exactly 1 (the new test); narrow the command's test filter so it runs only that test, then rerun" >&2; exit 1
  fi
fi
echo "red-without-fix: OK, the test fails without the fix and passes with it"
exit 0
