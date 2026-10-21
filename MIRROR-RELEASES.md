# Mirror published GitHub releases

`.github/workflows/mirror-github-releases.yml` is manual only. It copies already
published release assets using the existing repository secrets. Pushing this
branch does not publish anything.

The branch also supplies the same transfer workflow at the already registered
`.github/workflows/cache.yml` path, so it can be dispatched with
`--ref feature/mirror-github-releases` without merging or changing the default
branch. Pass `php-versions` and a unique `ticket` input. Dispatch this branch
explicitly; the default branch's workflow at that path retains its original
behavior. The registered entry contains only transfer jobs, with no build/test
or GitHub release publication steps.

Destination: Cloudsmith `shivammathur/php-builder-windows`.

`php-versions` accepts `all` or space-separated minor versions from:
`5.3 5.4 5.5 5.6 7.0 7.1 7.2 7.3 7.4 8.0 8.1 8.2 8.3 8.4 8.5`. Each version runs in its own parallel job, with
`fail-fast: false` and no `max-parallel` cap. Duplicate jobs for the same version
share a concurrency group. GitHub account concurrency limits still apply.

The workflow reads GitHub Releases, pins selected asset IDs, sizes and SHA256
digests, downloads on the Actions runner, verifies every byte and rejects source
changes observed during download. Missing assets or GitHub digests stop the job.
It never builds, repackages, runs PHP, changes GitHub releases, accesses private
build storage, deletes mirror objects or transfers build payloads locally.
Transfer receipts are retained as Actions artifacts, including partial failure
receipts. `mirror_verified` appears only after destination verification passes.

Each version follows the stable section of its GitHub `manifest.json`, including
runtime, debug, development, source and test ZIPs, plus existing SBOM/VEX sidecars.
It excludes nightly/dev packages and old MSI installers. The shared job takes
`Get-Php.ps1` and `Get-PhpNightly.ps1` from the highest selected minor version,
avoiding parallel overwrites of Cloudsmith's flat script names. Per-tag
`manifest.json` is retained for selection but is not uploaded to that flat
namespace. Cloudsmith downloads are SHA256-verified with bounded retries.
