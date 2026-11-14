#!/usr/bin/env bash
# galivelop-workflow v0.6.0
# Brings commits from a minor's branch onto the current PATCH branch (D81).
#   bash backport.sh [--from <branch>] [--refs <id>[,<id>]] [<sha>...]
#  - Refuses to start (exit 2, with the command that fixes it) on: no shas, an unknown sha or branch, a dirty tree
#    (tracked changes), a detached HEAD, or a cherry-pick/merge/rebase/revert already in progress.
#  - Cherry-picks the shas oldest first (topological order, whatever order they were given) with `-x`, and `-m 1`
#    for a merge commit.
#  - A conflict only in the log (`log` of the config) and/or the roadmap files (`roadmapFiles`) is resolved with this
#    branch's version (the HEAD side) and the pick goes on; the output says so. A conflict in any other file stops:
#    the cherry-pick stays in progress, it exits 1 and prints how to finish and which shas remain.
#  - A pick that ends empty is skipped (`git cherry-pick --skip`) and reported.
#  - At the end every requested sha must be accounted for: already in HEAD, picked (its `-x` line is in a new
#    commit), upstream (`git cherry` finds an equivalent patch) or skipped empty; otherwise exit 1.
#  - With --from <branch>, the harvest files of `proposalsDir` that exist in <branch> and not in HEAD (a `.md` whose
#    first line starts with "# Harvest ") are brought in one commit of their own. Its `Refs:` keep only the ids of the
#    requested commits that commit-message.py (the commit-msg check) accepts here, or the ones of --refs; with none
#    left and `commitRefs` on it stops before touching the index. --from works with no shas (the harvest only).
# Bash 3.2 compatible. Root from this script's path, never from $CLAUDE_PROJECT_DIR or the current directory.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
self="bash $0"
usage() { echo "backport: usage: $self [--from <branch>] [--refs <id>[,<id>]] [<sha>...]   (run it on the patch branch)" >&2; exit 2; }
die() { echo "backport: $*" >&2; exit 2; }
in_list() { case " $2 " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

from=""; shas=""; refsopt=""
while [ $# -gt 0 ]; do
  case "$1" in
    --from) [ $# -ge 2 ] || usage; from="$2"; shift 2 ;;
    --refs) [ $# -ge 2 ] || usage; refsopt="$2"; shift 2 ;;
    -h|--help) usage ;;
    -*) usage ;;
    *) shas="$shas $1"; shift ;;
  esac
done
shas="${shas# }"
[ -n "$shas" ] || [ -n "$from" ] || die "no commits given; pass the shas to bring: $self [--from <branch>] <sha>..."
fromopt=""
[ -z "$from" ] || fromopt="--from $from "
refsarg=""
[ -z "$refsopt" ] || refsarg="--refs $refsopt "

root="$(unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE; git -C "$here" rev-parse --show-toplevel 2>/dev/null)" || \
  die "$here is not inside a git repository; reinstall the workflow: /gw-update"
cd "$root" || exit 2
config="$here/config.py"
cfg() { python3 "$config" --root "$root" get "$1" 2>/dev/null; }
logfile="$(cfg log)" || die "cannot read 'log'; fix the config: python3 $config --root $root validate"
roadmaps="$(cfg roadmapFiles)" || die "cannot read 'roadmapFiles'; fix the config: python3 $config --root $root validate"
proposals="$(cfg proposalsDir)" || die "cannot read 'proposalsDir'; fix the config: python3 $config --root $root validate"
commitrefs="$(cfg commitRefs)" || die "cannot read 'commitRefs'; fix the config: python3 $config --root $root validate"
lang="$(cfg language)" || die "cannot read 'language'; fix the config: python3 $config --root $root validate"
# The files whose conflicts take this branch's side: the log and the path of each roadmap file (JSON lines).
rpaths="$(printf '%s\n' "$roadmaps" | python3 -c '
import json, sys
for line in sys.stdin:
    line = line.strip()
    if line:
        print(json.loads(line)["path"])
')" || die "cannot parse 'roadmapFiles'; fix the config: python3 $config --root $root validate"
auto="$logfile
$rpaths"
probe="$(mktemp "${TMPDIR:-/tmp}/gw-backport.XXXXXX")" || die "cannot create a temp file; free space and retry"
trap 'rm -f "$probe"' EXIT
is_auto() { printf '%s\n' "$auto" | grep -Fxq -- "$1"; }

# Fail closed before touching anything.
for f in CHERRY_PICK_HEAD MERGE_HEAD REVERT_HEAD rebase-merge rebase-apply; do
  if [ -e "$(git rev-parse --git-path "$f")" ]; then
    case "$f" in
      CHERRY_PICK_HEAD) fix="git cherry-pick --continue (or: git cherry-pick --abort)" ;;
      MERGE_HEAD) fix="git commit (or: git merge --abort)" ;;
      REVERT_HEAD) fix="git revert --continue (or: git revert --abort)" ;;
      *) fix="git rebase --continue (or: git rebase --abort)" ;;
    esac
    die "a $f operation is already in progress; finish or cancel it first: $fix"
  fi
done
branch="$(git symbolic-ref -q --short HEAD)" || \
  die "HEAD is detached; check out the patch branch first: git checkout <patch-branch>"
[ -z "$(git status --porcelain --untracked-files=no)" ] || \
  die "the working tree has uncommitted changes; commit them (WIP: ...) or discard them, then rerun: $self $fromopt$shas"
fromref=""
if [ -n "$from" ]; then
  for cand in "$from" "origin/$from"; do
    if git rev-parse --verify -q "$cand^{commit}" >/dev/null; then fromref="$cand"; break; fi
  done
  [ -n "$fromref" ] || die "unknown branch '$from'; fetch it and retry: git fetch origin $from && $self $fromopt$shas"
fi
full=""
for s in $shas; do
  r="$(git rev-parse --verify -q "$s^{commit}")" || \
    die "unknown commit '$s'; fetch it and retry: git fetch origin && $self $fromopt$shas"
  in_list "$r" "$full" || full="$full $r"
done
full="${full# }"

start="$(git rev-parse HEAD)"
# Oldest first: the commits reachable from the requested ones and not from HEAD, topologically, kept if requested.
order=""
# shellcheck disable=SC2086
[ -z "$full" ] || order="$(git rev-list --topo-order --reverse $full --not HEAD)" || die "cannot order the commits; check them: git log --oneline $full"
todo=""
for c in $order; do
  ! in_list "$c" "$full" || todo="$todo $c"
done
todo="${todo# }"

skipped=""
rest="$todo"
for c in $todo; do
  rest="${rest#"$c"}"; rest="${rest# }"
  opts="-x"
  [ "$(git rev-list --parents -n 1 "$c" | wc -w)" -gt 2 ] && opts="-x -m 1"
  # shellcheck disable=SC2086
  if out="$(git cherry-pick $opts "$c" 2>&1)"; then
    echo "backport: picked $(git log -1 --format='%h %s' "$c")"
    continue
  fi
  if [ ! -e "$(git rev-parse --git-path CHERRY_PICK_HEAD)" ]; then
    printf '%s\n' "$out" >&2
    echo "backport: git cherry-pick failed on $c before starting; fix the cause above and rerun: $self $fromopt$c${rest:+ $rest}" >&2
    exit 1
  fi
  unmerged="$(git diff --name-only -z --diff-filter=U | tr '\0' '\n')"
  bad=""
  while IFS= read -r f; do [ -z "$f" ] || is_auto "$f" || bad="$bad $f"; done <<<"$unmerged"
  if [ -n "$bad" ]; then
    echo "backport: conflict in$bad while picking $(git log -1 --format='%h %s' "$c")" >&2
    echo "backport: resolve it, git add the files, then: git cherry-pick --continue" >&2
    if [ -n "$rest" ]; then
      echo "backport: then rerun with the remaining commits: $self $fromopt$refsarg$rest" >&2
    elif [ -n "$from" ]; then
      echo "backport: then bring the harvest files (no shas left): $self $fromopt$refsarg" >&2
    else
      echo "backport: no commits remain after this one, so no rerun is needed" >&2
    fi
    echo "backport: or cancel this pick: git cherry-pick --abort" >&2
    exit 1
  fi
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    git checkout --ours -- "$f" 2>/dev/null || git rm -q -f -- "$f" 2>/dev/null
    git add -A -- "$f" 2>/dev/null
    echo "backport: conflict in $f resolved with this branch's version ($(git log -1 --format=%h "$c"))"
  done <<<"$unmerged"
  if git diff --cached --quiet; then
    git cherry-pick --skip >/dev/null 2>&1 || git cherry-pick --abort >/dev/null 2>&1
    skipped="$skipped $c"
    echo "backport: skipped $(git log -1 --format='%h %s' "$c") (empty: nothing left to apply here)"
  elif ! GIT_EDITOR=true git cherry-pick --continue >/dev/null 2>&1; then
    echo "backport: cannot continue the pick of $c; finish it by hand (git cherry-pick --continue) and rerun with: $self $fromopt$refsarg$rest" >&2
    exit 1
  else
    echo "backport: picked $(git log -1 --format='%h %s' "$c")"
  fi
done

# Accounting: every requested sha must be somewhere.
missing=""; summary=""
for c in $full; do
  short="$(git log -1 --format='%h %s' "$c")"
  if git merge-base --is-ancestor "$c" "$start"; then st="already in HEAD"
  elif in_list "$c" "$skipped"; then st="skipped (empty)"
  elif [ -n "$(git log --fixed-strings --grep="(cherry picked from commit $c)" --format=%h "$start..HEAD")" ]; then st="picked"
  elif git cherry HEAD "$c" "$c^" 2>/dev/null | grep -q '^-'; then st="upstream (equivalent patch)"
  else st="MISSING"; missing="$missing $c"
  fi
  summary="$summary
  $st: $short"
done
echo "backport: summary for $branch:$summary"
if [ -n "$missing" ]; then
  echo "backport: not accounted for:$missing; pick them by hand (git cherry-pick -x <sha>) or rerun: $self $fromopt${missing# }" >&2
  exit 1
fi

# --from: the harvest files <branch> has and HEAD lacks, in one commit of their own.
if [ -n "$fromref" ]; then
  found=""
  while IFS= read -r -d '' f; do
    case "$f" in *.md) ;; *) continue ;; esac
    git cat-file -e "HEAD:$f" 2>/dev/null && continue
    case "$(git show "$fromref:$f" | head -n 1)" in "# Harvest "*) found="$found$f
" ;; esac
  done < <(git ls-tree -r -z --name-only "$fromref" -- "$proposals")
  if [ -z "$found" ]; then
    echo "backport: no harvest files in $fromref that HEAD lacks; nothing more to bring"
    exit 0
  fi
  # The ids for `Refs:`: the --refs ones, else the ones of the requested commits; only those the commit-msg check
  # accepts in this branch (its roadmap may lack a row the minor has). With none left, stop before the index.
  cand="$(printf '%s' "$refsopt" | tr ',' ' ')"
  if [ -z "$cand" ]; then
    for c in $full; do
      for i in $(git log -1 --format=%B "$c" | git interpret-trailers --parse --no-divider | sed -n 's/^Refs:[[:space:]]*//p' | tr ',' ' '); do
        in_list "$i" "$cand" || cand="$cand $i"
      done
    done
  fi
  nextword="Next"; [ "$lang" != "es" ] || nextword="Siguiente"
  ids=""
  if [ "$commitrefs" = "true" ]; then
    for i in $cand; do
      printf 'docs(%s): probe\n\nRefs: %s\n%s: x\n' "$i" "$i" "$nextword" > "$probe"
      if [ ! -f "$here/commit-message.py" ] || python3 "$here/commit-message.py" --root "$root" "$probe" >/dev/null 2>&1; then
        ids="$ids $i"
      fi
    done
    ids="${ids# }"
    if [ -z "$ids" ]; then
      echo "backport: no task id for the harvest commit's Refs that this branch accepts (commitRefs is on; tried: ${cand:-none}); nothing was staged. Name one that a row of its roadmap opens: $self $fromopt--refs <id> $shas" >&2
      exit 1
    fi
  else
    ids="${cand# }"
  fi
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    git checkout "$fromref" -- "$f" || { echo "backport: cannot bring $f; bring the harvest files by hand: git checkout $fromref -- <file>" >&2; exit 1; }
  done <<<"$found"
  scope=""; refs=""
  if [ -n "$ids" ]; then
    scope="(${ids%% *})"; refs="Refs: $(printf '%s' "$ids" | sed 's/ /, /g')"
  fi
  list="$(printf '%s' "$found" | sed 's/^/- /')"
  if [ "$lang" = "es" ]; then
    subject="docs$scope: trae las recogidas de $fromref al parche"
    body="Hecho: archivos de recogida que $fromref tiene y esta rama no.
$list
Queda: nada de esto."
    next="Siguiente: seguir con el parche"
  else
    subject="docs$scope: bring the harvest files of $fromref into the patch"
    body="Done: harvest files that $fromref has and this branch lacks.
$list
Left: nothing of this."
    next="Next: go on with the patch"
  fi
  msg="$subject

$body

${refs:+$refs
}$next"
  if ! git commit -q -m "$msg"; then
    while IFS= read -r f; do
      [ -z "$f" ] || { git reset -q -- "$f"; rm -f -- "$f"; }
    done <<<"$found"
    echo "backport: the harvest commit failed (see above); its files were unstaged and removed again. Fix the cause (for the Refs: --refs <id>) and rerun for the harvest only: $self $fromopt$refsarg" >&2
    exit 1
  fi
  echo "backport: harvest files brought in one commit: $(git log -1 --format='%h %s')"
fi
exit 0
