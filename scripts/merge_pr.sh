#!/bin/sh
# Merges pull request N into main with the merge commit stamped in UTC, instead of
# `gh pr merge` / the Merge button. Those have GitHub write the merge commit in the
# time zone the client reports, i.e. where you are (see CLAUDE.md, "Commit times").
# The merge is made here, in a throwaway worktree, and pushed to main; GitHub then
# marks the PR merged by itself.
#   sh scripts/merge_pr.sh N [--delete-branch]
# Needs: the PR's required checks green, its commits in UTC (scripts/utc_fix.sh on
# the branch if not), and a merge with main that needs no hand-fixing (else merge
# main into the PR branch first, push, wait for CI, then run this again).
set -e
n=$1
[ -n "$n" ] || { echo "usage: sh scripts/merge_pr.sh N [--delete-branch]" >&2; exit 2; }
root=$(git rev-parse --show-toplevel)
here=$(cd "$(dirname "$0")" && pwd)   # check_utc.sh beside this script (it can run from any repo)
cd "$root"

state=$(gh pr view "$n" --json state,baseRefName,headRefName,headRefOid,headRepositoryOwner,title \
        -q '[.state, .baseRefName, .headRefName, .headRefOid, .headRepositoryOwner.login] | join(" ")')
set -- $state "$2"
pr_state=$1 base=$2 branch=$3 head_oid=$4 owner=$5 del=$6
title=$(gh pr view "$n" --json title -q .title)
[ "$pr_state" = OPEN ] || { echo "PR #$n is $pr_state." >&2; exit 1; }
[ "$base" = main ] || { echo "PR #$n goes into $base, not main." >&2; exit 1; }

# required checks: gh exits 0 only when every one has passed
checks_passed=$(gh pr checks "$n" --required --json bucket \
    --jq 'length > 0 and all(.[]; .bucket == "pass")' 2>/dev/null || true)
if [ "$checks_passed" != true ]; then
    gh pr checks "$n" --required >&2 || true
    echo "PR #$n: its required checks haven't all passed yet." >&2
    exit 1
fi

tmp=""
cleanup() {
    [ -z "$tmp" ] || { git worktree remove --force "$tmp" 2>/dev/null || true; rm -rf "$tmp"; }
    git update-ref -d "refs/remotes/origin/pr/$n" 2>/dev/null || true
}
trap cleanup EXIT
git fetch -q origin main "+refs/pull/$n/head:refs/remotes/origin/pr/$n"
head=$(git rev-parse "origin/pr/$n")
[ "$head" = "$head_oid" ] || { echo "PR #$n changed while checking it; run this again." >&2; exit 1; }
sh "$here/check_utc.sh" "origin/main..$head"

tmp=$(mktemp -d "${TMPDIR:-/tmp}/merge_pr_$n.XXXXXX")
git worktree add -q --detach "$tmp" origin/main
now="$(date +%s) +0000"
if ! (cd "$tmp" && GIT_AUTHOR_DATE="$now" GIT_COMMITTER_DATE="$now" \
      git merge -q --no-ff -m "Merge pull request #$n from $owner/$branch" -m "$title" "$head"); then
    (cd "$tmp" && git merge --abort) 2>/dev/null || true
    echo "PR #$n doesn't merge cleanly with main: merge main into $branch first." >&2
    exit 1
fi
(cd "$tmp" && sh "$here/check_utc.sh" -1 HEAD)
if [ -n "$MERGE_PR_DRY_RUN" ]; then   # everything but the push
    (cd "$tmp" && git log -1 --format="Would push %h (%ad | %cd): %s" --date=raw)
    exit 0
fi
(cd "$tmp" && git push -q origin HEAD:main)
echo "Merged PR #$n into main as $(cd "$tmp" && git rev-parse --short HEAD) (UTC)."
if [ "$del" = --delete-branch ]; then
    git push -q origin --delete "$branch" 2>/dev/null && echo "Deleted the branch $branch."
fi
