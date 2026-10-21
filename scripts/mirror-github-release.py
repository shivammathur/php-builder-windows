#!/usr/bin/env python3
"""Copy published GitHub release bytes to this repository's existing mirrors."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import quote

REPO = "shivammathur/php-builder-windows"
VERSIONS = ['5.3', '5.4', '5.5', '5.6', '7.0', '7.1', '7.2', '7.3', '7.4', '8.0', '8.1', '8.2', '8.3', '8.4', '8.5']


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", path]))


def release(tag):
    result = api(f"repos/{REPO}/releases/tags/{tag}")
    if result["draft"] or result["tag_name"] != tag:
        raise ValueError("Not a published release")
    pages = json.loads(subprocess.check_output([
        "gh", "api", "--paginate", "--slurp",
        f"repos/{REPO}/releases/{result['id']}/assets?per_page=100",
    ]))
    assets = [asset for page in pages for asset in page]
    if len({a["name"] for a in assets}) != len(assets):
        raise ValueError("Duplicate release asset names")
    return result["id"], {a["name"]: a for a in assets}


def identity(asset):
    return {key: asset[key] for key in ("id", "name", "size", "digest", "updated_at")}


def sha256(file):
    with file.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(asset, directory):
    name = asset["name"]
    if not re.fullmatch(r"[A-Za-z0-9_.+\-]+", name) or name in (".", ".."):
        raise ValueError("Unsafe asset filename")
    digest = asset.get("digest") or ""
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise ValueError(f"GitHub SHA256 missing: {name}")
    file = directory / name
    with file.open("wb") as stream:
        run("gh", "api", "-H", "Accept: application/octet-stream",
            f"repos/{REPO}/releases/assets/{asset['id']}", stdout=stream)
    if file.stat().st_size != asset["size"] or sha256(file) != digest[7:]:
        raise ValueError(f"GitHub asset checksum mismatch: {name}")
    return file


def select(version, assets, directory):
    if version == "shared":
        return ["Get-Php.ps1", "Get-PhpNightly.ps1"] if REPO.endswith("-windows") else ["install.sh"]
    if REPO.endswith("/php-ubuntu"):
        names = [f"php_{version}-{ts}{debug}+ubuntu{ubuntu}{arch}.tar.zst"
                 for ts in ("nts", "zts") for debug in ("", "-dbgsym")
                 for ubuntu in ("22.04", "24.04", "26.04") for arch in ("", "_arm64")]
        return names
    if REPO.endswith("/php5-darwin"):
        prefix = "php" + version.replace(".", "")
        return [prefix + suffix + "-cache.tar.zst" for suffix in ("", "-arm64", "-imagick", "-imagick-arm64")]
    if REPO.endswith("/php-darwin"):
        name = f"php-{version}-manifest.json"
        manifest = json.loads(download(assets[name], directory).read_text())
        if manifest["php_version"] != version or len(manifest["assets"]) != 8:
            raise ValueError("Unexpected Darwin manifest")
        names = [name, "install.sh"]
        for item in manifest["assets"]:
            filename = item.get("download", item["name"])
            asset = assets[filename]
            if asset["digest"] != "sha256:" + item["sha256"] or asset["size"] != item["bytes"]:
                raise ValueError("Darwin manifest and GitHub asset disagree")
            names.extend([filename, filename + ".sha256"])
        return names
    manifest = json.loads(download(assets["manifest.json"], directory).read_text())
    stable = manifest["stable"]
    if manifest["tag"] != "php" + version or not re.fullmatch(re.escape(version) + r"\.\d+", stable["version"]):
        raise ValueError("Unexpected Windows stable manifest")
    names = [stable["src"], stable["test"]]
    arches = ("x86",) if version in ("5.3", "5.4") else ("x86", "x64")
    for kind in ("php", "debug", "devel"):
        for ts in ("nts", "ts"):
            for arch in arches:
                name = stable[kind][ts][arch]
                if not name.endswith(".zip") or stable["version"] not in name or "-dev-" in name:
                    raise ValueError("Unexpected stable package")
                names.append(name)
                names.extend(name + suffix for suffix in (".cdx.json", ".spdx.json", ".openvex.json") if name + suffix in assets)
    # manifest.json is shared by release tags but not by Cloudsmith's flat namespace.
    # Keep it as provenance, never overwrite another version's mirror manifest.
    return names


def prepare(version, directory, source_version, plan_only=False):
    tag = ("php-" + source_version if REPO.endswith("/php-darwin") else
           "php" + source_version if REPO.endswith("-windows") else "builds")
    directory.mkdir(parents=True, exist_ok=True)
    release_id, assets = release(tag)
    names = select(version, assets, directory)
    if not names or len(names) != len(set(names)):
        raise ValueError("Empty or duplicate asset selection")
    chosen = [identity(assets[name]) for name in names]
    for asset in chosen:
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", asset.get("digest") or ""):
            raise ValueError(f"Missing SHA256: {asset['name']}")
    if not plan_only:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda a: download(a, directory), chosen))
    # Bind the entire selected set to unchanged GitHub asset IDs and digests.
    # Unrelated version uploads in a shared release do not invalidate this job.
    current_id, current = release(tag)
    if current_id != release_id or any(identity(current[a["name"]]) != a for a in chosen):
        raise ValueError("Selected release assets changed during download")
    if REPO.endswith("-windows") and version != "shared":
        if identity(current["manifest.json"]) != identity(assets["manifest.json"]):
            raise ValueError("Windows manifest changed during download")
    plan = {"repository": REPO, "version": version, "source_tag": tag,
            "release_id": release_id, "assets": chosen, "download_verified": not plan_only}
    (directory / "receipt.json").write_text(json.dumps(plan, indent=2) + "\n")
    print(f"{REPO} {version}: {len(chosen)} assets; " + ("metadata checked" if plan_only else "download hashes verified"))


def verify_public(file, base):
    target = file.parent / "verify-download"
    for attempt in range(12):
        url = base + "/" + quote(file.name) + "?verify=" + os.environ.get("GITHUB_RUN_ID", "local") + f"-{attempt}-{time.time_ns()}"
        result = subprocess.run(["curl", "--fail", "--silent", "--show-error", "--location",
                                 "--connect-timeout", "15", "--max-time", "300", url, "-o", str(target)])
        if result.returncode == 0 and target.stat().st_size == file.stat().st_size and sha256(target) == sha256(file):
            target.unlink()
            return
        if attempt < 11:
            time.sleep(10)
    raise ValueError(f"Public mirror checksum mismatch: {file.name}")


def publish(directory):
    receipt = json.loads((directory / "receipt.json").read_text())
    if receipt["repository"] != REPO or receipt["download_verified"] is not True:
        raise ValueError("Unverified download receipt")
    files = [directory / a["name"] for a in receipt["assets"]]
    for asset, file in zip(receipt["assets"], files):
        if file.stat().st_size != asset["size"] or sha256(file) != asset["digest"][7:]:
            raise ValueError("Staged bytes changed")
    if REPO.endswith("/php-darwin"):
        run("bash", "scripts/release/mirror-release.sh", str(directory), "all",
            env={**os.environ, "PHP_VERSION": receipt["version"]})
    else:
        required = ["CLOUDSMITH_API_KEY"]
        if REPO.endswith("/php-ubuntu"):
            required += [prefix + suffix for prefix in ("CF_R2_AWS_", "SETUP_PHP_AWS_")
                         for suffix in ("ACCESS_KEY_ID", "SECRET_ACCESS_KEY", "S3_ENDPOINT")]
        if any(not os.environ.get(key) for key in required):
            raise ValueError("Missing existing mirror credentials")
        cloud_files = files
        if REPO.endswith("/php-ubuntu") and receipt["version"] == "shared":
            alias = directory / "php-ubuntu.sh"
            alias.write_bytes(files[0].read_bytes())
            cloud_files = [alias]
        for file in cloud_files:
            run("cloudsmith", "push", "raw", REPO, str(file), "--republish",
                "--summary", file.name, "--description", file.name)
        # Upload this version to all destinations before verifying public downloads.
        if REPO.endswith("/php-ubuntu"):
            for prefix in ("CF_R2_AWS_", "SETUP_PHP_AWS_"):
                env = {**os.environ, "AWS_ACCESS_KEY_ID": os.environ[prefix + "ACCESS_KEY_ID"],
                       "AWS_SECRET_ACCESS_KEY": os.environ[prefix + "SECRET_ACCESS_KEY"],
                       "AWS_DEFAULT_REGION": "auto" if prefix == "CF_R2_AWS_" else "us-east-1",
                       "AWS_EC2_METADATA_DISABLED": "true", "AWS_PAGER": "",
                       "AWS_REQUEST_CHECKSUM_CALCULATION": "when_required",
                       "AWS_RESPONSE_CHECKSUM_VALIDATION": "when_required"}
                endpoint = os.environ[prefix + "S3_ENDPOINT"]
                for file in files:
                    run("aws", "--endpoint-url", endpoint, "s3", "cp", str(file),
                        "s3://php-ubuntu/" + file.name, "--only-show-errors",
                        "--cache-control", "no-cache, max-age=0, must-revalidate", env=env)
                # Read authenticated origin bytes; CDN caches cannot hide upload failure.
                for file in files:
                    target = directory / "verify-download"
                    run("aws", "--endpoint-url", endpoint, "s3", "cp", "s3://php-ubuntu/" + file.name,
                        str(target), "--only-show-errors", env=env)
                    if sha256(target) != sha256(file):
                        raise ValueError("S3 origin checksum mismatch")
                    target.unlink()
        for file in cloud_files:
            verify_public(file, "https://dl.cloudsmith.io/public/" + REPO + "/raw/files")
    receipt["mirror_verified"] = True
    (directory / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"Mirrored and verified {REPO} {receipt['version']}")


def main():
    command = sys.argv[1]
    if os.environ.get("GITHUB_REPOSITORY", REPO) != REPO:
        raise ValueError("Wrong repository")
    if command == "matrix":
        value = os.environ["PHP_VERSIONS"]
        versions = VERSIONS if value == "all" else value.split()
        if not versions or len(set(versions)) != len(versions) or any(v not in VERSIONS for v in versions):
            raise ValueError("Select supported minor versions, separated by spaces, or all")
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write("versions=" + json.dumps(versions) + "\n")
            output.write("shared_version=" + max(versions, key=lambda v: tuple(map(int, v.split(".")))) + "\n")
    elif command in ("download", "plan"):
        version, directory, source_version = sys.argv[2:]
        if source_version not in VERSIONS or version not in VERSIONS + ["shared"]:
            raise ValueError("Unsupported version")
        if version != "shared" and version != source_version:
            raise ValueError("Wrong source version")
        prepare(version, Path(directory), source_version, plan_only=command == "plan")
    elif command == "publish":
        publish(Path(sys.argv[2]))
    else:
        raise ValueError("Unknown command")


if __name__ == "__main__":
    main()
