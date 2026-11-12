#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" != 2 ]]; then
  echo "Usage: bootstrap_linux.sh SOURCE_CHECKOUT LINUX_CHECKOUT" >&2
  exit 2
fi
source_path="$1"
target_path="$2"
if [[ ! -e "$target_path" ]]; then
  mkdir -p -- "$(dirname -- "$target_path")"
  git clone --no-hardlinks -- "$source_path" "$target_path"
  exit 0
fi
if [[ ! -d "$target_path/.git" ]]; then
  echo "Existing target is not a Git checkout; it is preserved: $target_path" >&2
  exit 1
fi
if [[ -n "$(git -C "$target_path" status --porcelain)" ]]; then
  echo "Existing Linux checkout has local changes; it is preserved: $target_path" >&2
  exit 1
fi
git -C "$target_path" fetch -- "$source_path" HEAD
git -C "$target_path" checkout --detach FETCH_HEAD
