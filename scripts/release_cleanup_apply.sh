#!/usr/bin/env bash
set -euo pipefail

input_file="${1:-cleanup-assets.tsv}"

if [[ ! -f "$input_file" ]]; then
  echo "Cleanup list not found: $input_file"
  exit 0
fi

if [[ ! -s "$input_file" ]]; then
  echo "No assets to delete."
  exit 0
fi

while IFS=$'\t' read -r release id name kind version; do
  [[ -z "$id" ]] && continue
  bash scripts/retry.sh 5 5 gh api \
    --method DELETE \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "/repos/${GITHUB_REPOSITORY}/releases/assets/${id}"
done < "$input_file"
