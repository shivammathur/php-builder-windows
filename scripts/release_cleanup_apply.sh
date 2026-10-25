#!/usr/bin/env bash
set -euo pipefail

input_file="${1:-cleanup-assets.tsv}"
source="${2:-github}"
case "$source" in
  github|cloudsmith) ;;
  *) echo "Unknown cleanup source: $source" >&2; exit 1 ;;
esac

if [[ ! -f "$input_file" ]]; then
  echo "Cleanup list not found: $input_file"
  exit 0
fi

if [[ ! -s "$input_file" ]]; then
  echo "No assets to delete."
  exit 0
fi

while IFS=$'\t' read -r _ id _ _ _; do
  [[ -z "$id" ]] && continue
  if [[ "$source" == "cloudsmith" ]]; then
    cloudsmith delete --yes "${GITHUB_REPOSITORY:?}/$id" \
      --error-retry-max 5 --error-retry-backoff 5
  else
    bash scripts/retry.sh 5 5 gh api \
      --method DELETE \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "/repos/${GITHUB_REPOSITORY}/releases/assets/${id}"
  fi
done < "$input_file"
