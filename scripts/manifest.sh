#!/usr/bin/env bash
set -euo pipefail

release=${1:?Release tag is required}
output=${2:-manifest.json}
repository=${GITHUB_REPOSITORY:-shivammathur/php-builder-windows}
release_id=$(gh api \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "/repos/$repository/releases/tags/$release" \
  -q '.id')
assets_file=$(mktemp)
trap 'rm -f "$assets_file"' EXIT

page=1
while true; do
  page_assets=$(gh api \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "/repos/$repository/releases/$release_id/assets?per_page=100&page=$page" \
    -q '.[].name')
  [[ -z "$page_assets" ]] && break
  printf '%s\n' "$page_assets" >> "$assets_file"
  ((page += 1))
done

jq -Rn --arg release "$release" '
  [
    inputs as $name
    | try (
        $name
        | capture("^(?<kind>php|php-debug-pack)-(?<version>[0-9]+\\.[0-9]+\\.[0-9]+)(?<dev>-dev)?(?<nts>-nts)?-[Ww]in32-[^-]+-(?<arch>x64|x86)\\.zip$")
      ) catch empty
    | .name = $name
    | .kind = if .kind == "php" then "php" else "debug" end
    | .stability = if .dev == "-dev" then "dev" else "stable" end
    | .thread_safety = if .nts == "-nts" then "nts" else "ts" end
    | .version_parts = (.version | split(".") | map(tonumber))
  ]
  | sort_by(.version_parts)
  | reduce (
      group_by(.stability)[]
      | . as $assets
      | ($assets | max_by(.version_parts).version_parts) as $latest
      | $assets[]
      | select(.version_parts == $latest)
    ) as $asset (
      {schema: 1, tag: $release};
      .[$asset.stability].version = $asset.version
      | .[$asset.stability][$asset.kind][$asset.thread_safety][$asset.arch] = $asset.name
    )
' "$assets_file" > "$output"
