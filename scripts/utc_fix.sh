#!/bin/sh
# Re-stamps this branch's own commits (the ones not on origin/main) in UTC: same
# moments, same trees, merges kept as they are; only the +HHMM offsets become +0000.
# The branch's commits get new IDs, so push it with --force-with-lease afterwards.
# Never on main (its history is never rewritten).
#   sh scripts/utc_fix.sh [base]      base defaults to origin/main
set -e
branch=$(git symbolic-ref --short HEAD)
[ "$branch" != main ] || { echo "Not on main: its history is never rewritten." >&2; exit 1; }
base=${1:-origin/main}
git diff --quiet && git diff --cached --quiet ||
    { echo "Commit or put away your changes first." >&2; exit 1; }
n=$(git rev-list --count "$base..HEAD")
[ "$n" -gt 0 ] || { echo "No commits of this branch's own to re-stamp."; exit 0; }
FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch -f --env-filter '
    export GIT_AUTHOR_DATE="${GIT_AUTHOR_DATE% *} +0000"
    export GIT_COMMITTER_DATE="${GIT_COMMITTER_DATE% *} +0000"
' "$base..HEAD" >/dev/null
git update-ref -d "refs/original/refs/heads/$branch" 2>/dev/null || true
echo "Re-stamped $n commit(s) on $branch in UTC. Push with: git push --force-with-lease"
