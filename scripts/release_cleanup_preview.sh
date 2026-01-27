#!/usr/bin/env bash
set -euo pipefail

output_file="${1:-cleanup-assets.tsv}"
: > "$output_file"

summary_file="${GITHUB_STEP_SUMMARY:-}"
if [[ -n "$summary_file" ]]; then
  {
    echo "## Release cleanup candidates"
    echo ""
  } >> "$summary_file"
fi

IFS=' ' read -r -a releases <<< "${GITHUB_RELEASES:?}"

for release in "${releases[@]}"; do
  release_id=$(gh api \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "/repos/${GITHUB_REPOSITORY}/releases/tags/${release}" \
    -q '.id' || true)
  if [[ -z "$release_id" || "$release_id" == "null" ]]; then
    if [[ -n "$summary_file" ]]; then
      echo "### $release" >> "$summary_file"
      echo "_Release not found_" >> "$summary_file"
      echo "" >> "$summary_file"
    fi
    continue
  fi

  assets=""
  page=1
  while true; do
    page_assets=$(gh api \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "/repos/${GITHUB_REPOSITORY}/releases/${release_id}/assets?per_page=100&page=${page}" \
      -q '.[] | [.id, .name] | @tsv' || true)
    [[ -z "$page_assets" ]] && break
    if [[ -z "$assets" ]]; then
      assets="$page_assets"
    else
      assets+=$'\n'
      assets+="$page_assets"
    fi
    ((page++))
  done
  if [[ -z "$assets" ]]; then
    if [[ -n "$summary_file" ]]; then
      echo "### $release" >> "$summary_file"
      echo "_No assets found_" >> "$summary_file"
      echo "" >> "$summary_file"
    fi
    continue
  fi

  tmp_all=$(mktemp)
  tmp_delete=$(mktemp)
  dev_versions=()
  stable_versions=()

  while IFS=$'\t' read -r id name; do
    [[ "$name" != *.zip ]] && continue
    if [[ "$name" == *-dev-* || "$name" == *-dev.* ]]; then
      version=$(echo "$name" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+-dev' | head -n1 || true)
      version=${version//$'\r'/}
      version=${version//$'\t'/}
      version=${version//$'\n'/}
      [[ -z "$version" ]] && continue
      echo -e "$release\t$id\t$name\tdev\t$version" >> "$tmp_all"
      dev_versions+=("$version")
    else
      version=$(echo "$name" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n1 || true)
      version=${version//$'\r'/}
      version=${version//$'\t'/}
      version=${version//$'\n'/}
      [[ -z "$version" ]] && continue
      echo -e "$release\t$id\t$name\tstable\t$version" >> "$tmp_all"
      stable_versions+=("$version")
    fi
  done <<< "$assets"

  dev_max=""
  stable_max=""
  if (( ${#dev_versions[@]} > 0 )); then
    dev_max=$(printf '%s\n' "${dev_versions[@]}" | sort -V | tail -n1)
  fi
  if (( ${#stable_versions[@]} > 0 )); then
    stable_max=$(printf '%s\n' "${stable_versions[@]}" | sort -V | tail -n1)
  fi

  while IFS=$'\t' read -r r id name kind version; do
    version=${version//$'\r'/}
    version=${version//$'\t'/}
    version=${version//$'\n'/}
    if [[ "$kind" == "dev" ]]; then
      [[ -n "$dev_max" && "$version" == "$dev_max" ]] && continue
    else
      [[ -n "$stable_max" && "$version" == "$stable_max" ]] && continue
    fi
    echo -e "$r\t$id\t$name\t$kind\t$version" >> "$tmp_delete"
  done < "$tmp_all"

  cat "$tmp_delete" >> "$output_file"

  if [[ -n "$summary_file" ]]; then
    echo "### $release" >> "$summary_file"
    if [[ -s "$tmp_delete" ]]; then
      echo "| Asset | Kind | Version |" >> "$summary_file"
      echo "| --- | --- | --- |" >> "$summary_file"
      while IFS=$'\t' read -r _ id name kind version; do
        echo "| $name | $kind | $version |" >> "$summary_file"
      done < "$tmp_delete"
    else
      echo "_No deletions_" >> "$summary_file"
    fi
    echo "" >> "$summary_file"
  fi

  rm -f "$tmp_all" "$tmp_delete"
done
