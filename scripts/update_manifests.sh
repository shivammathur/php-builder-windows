#!/usr/bin/env bash
set -euo pipefail

repository=${GITHUB_REPOSITORY:-shivammathur/php-builder-windows}

if (( $# > 0 )); then
  releases=("$@")
else
  releases=()
  while IFS= read -r release; do
    releases+=("$release")
  done < <(
      gh api --paginate "/repos/$repository/releases?per_page=100" \
        -q '.[].tag_name' \
        | grep -E '^(php[0-9]+\.[0-9]+|master)$'
    )
fi

manifest_dir=$(mktemp -d)
trap 'rm -rf "$manifest_dir"' EXIT

for release in "${releases[@]}"; do
  bash scripts/manifest.sh "$release" "$manifest_dir/manifest.json"
  bash scripts/retry.sh 5 5 gh release upload "$release" "$manifest_dir/manifest.json" --clobber --repo "$repository"
done
