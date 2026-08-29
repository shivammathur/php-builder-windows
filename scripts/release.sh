#!/usr/bin/env bash

release_cds() {
  sudo cp ./scripts/cds /usr/local/bin/cds && sudo sed -i "s|REPO|$GITHUB_REPOSITORY|" /usr/local/bin/cds && sudo chmod a+x /usr/local/bin/cds
  if [[ "$GITHUB_MESSAGE" != *skip-cloudsmith* ]]; then
    echo "${assets[@]}" | xargs -n 1 -P 8 cds
  fi
}

release_create() {
  release=$1
  bash scripts/retry.sh 5 5 gh release create "$release" "${assets[@]}" -n "$release" -t "$release"
}

release_upload() {
  release=$1
  for asset in "${assets[@]}"; do
    bash scripts/retry.sh 5 5 gh release upload "$release" "$asset" --clobber
  done
}

release_manifest() {
  release=$1
  manifest_dir=$(mktemp -d)
  bash scripts/manifest.sh "$release" "$manifest_dir/manifest.json"
  bash scripts/retry.sh 5 5 gh release upload "$release" "$manifest_dir/manifest.json" --clobber
  rm -rf "$manifest_dir"
}

set -x
assets=()
IFS=' ' read -r -a github_releases <<<"${GITHUB_RELEASES:?}"
rm -rf builds/**/*-src-*.zip || true
assets=($(find builds -type f -regex "^.*$"))
assets+=("./scripts/Get-PhpNightly.ps1")
assets+=("./scripts/Get-Php.ps1")
for release in "${github_releases[@]}"; do
  if ! gh release view "$release"; then
    release_create "$release"
  else
    release_upload "$release"
  fi
  release_manifest "$release"
done
release_cds
