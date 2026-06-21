#!/usr/bin/env bash
# Freeze the full source a code-review task reviewed into the task's source/
# snapshot, so the eval replays against a point-in-time tree and never expires
# as main moves on (see docs/EVAL_BACKLOG.md).
#
# The snapshot scope is derived from the diff: the project component each
# changed file lives in (todo-api, agents/<name>, or a root file like
# README.md) — enough sibling context for the reviewer to judge convention,
# without snapshotting the whole repo (which would recurse into evals/).
#
# Modes (all produce <task-dir>/source/<component>/... at repo-relative paths,
# the layout Pi reviews in):
#   current            copy components from the working tree, apply diff.patch
#   base <ref>         archive components at <ref> (the diff's base), apply diff.patch
#   head <ref>         archive components at <ref> whose tree ALREADY has the change
#
# current/base apply the stored diff, so source/ is guaranteed consistent with
# diff.patch. head trusts <ref> to already be the post-change tree.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
task_dir="$(cd "${1:?usage: capture_snapshot.sh <task-dir> current|base <ref>|head <ref>}" && pwd)"
mode="${2:?mode required: current|base|head}"
ref="${3:-}"
diff="$task_dir/diff.patch"
snap="$task_dir/source"
[ -f "$diff" ] || { echo "no diff.patch in $task_dir" >&2; exit 2; }

# Map each changed path to its project component:
#   todo-api/...      -> todo-api
#   agents/<name>/... -> agents/<name>
#   <root-file>       -> <root-file>
components="$(git apply --numstat "$diff" | awk '{print $3}' \
  | awk -F/ '{ if ($1=="agents" && NF>=2) print $1"/"$2; else if (NF>=2) print $1; else print $0 }' \
  | sort -u)"

# Assemble in a tmpdir OUTSIDE the repo: `git apply` run inside the working
# tree special-cases new-file patches whose path already exists on the current
# checkout (e.g. agents/rca/suppressions.json), silently not creating them.
# A plain directory has no such index, so apply behaves predictably.
build="$(mktemp -d "${TMPDIR:-/tmp}/talos-snap.XXXXXX")"
trap 'rm -rf "$build"' EXIT
case "$mode" in
  current)
    for c in $components; do
      mkdir -p "$build/$(dirname "$c")"; cp -R "$REPO_ROOT/$c" "$build/$c"
    done
    ( cd "$build" && git apply "$diff" )
    ;;
  base)
    [ -n "$ref" ] || { echo "base mode needs a ref" >&2; exit 2; }
    git -C "$REPO_ROOT" archive "$ref" $components | tar -x -C "$build"
    ( cd "$build" && git apply "$diff" )
    ;;
  head)
    [ -n "$ref" ] || { echo "head mode needs a ref" >&2; exit 2; }
    git -C "$REPO_ROOT" archive "$ref" $components | tar -x -C "$build"
    ;;
  *) echo "unknown mode: $mode" >&2; exit 2;;
esac

# Assert the change is actually PRESENT in the assembled tree — reverse-applying
# the diff must check clean. This catches a silently-failed forward apply that
# would otherwise leave a base-only snapshot (the reviewer would then see code
# that contradicts its diff). Run in build/ (outside the repo) so git apply
# doesn't special-case paths that exist on the current checkout.
if ! ( cd "$build" && git apply --reverse --check "$diff" 2>/dev/null ); then
  echo "snapshot does NOT contain the diff's change (apply failed?) — $task_dir" >&2
  exit 4
fi

rm -rf "$snap"; mkdir -p "$snap"
cp -R "$build"/. "$snap"/

# Every file the diff touches must exist in the snapshot post-capture.
miss=0
while IFS= read -r f; do
  [ -e "$snap/$f" ] || { echo "MISSING in snapshot: $f" >&2; miss=1; }
done < <(git apply --numstat "$diff" | awk '{print $3}')
[ "$miss" -eq 0 ] || { echo "snapshot incomplete for $task_dir" >&2; exit 3; }
echo "$(basename "$task_dir"): captured $(find "$snap" -type f | wc -l | tr -d ' ') files [$mode${ref:+ $ref}] components: $(echo $components | tr '\n' ' ')"
