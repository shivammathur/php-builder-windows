"""Publish reviewed public Windows build bytes through GitHub Actions only."""
import concurrent.futures as cf
import hashlib
import io
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import zipfile
import urllib.request
import urllib.parse

DEST = 'shivammathur/php-builder-windows'
SOURCE = 'shivammathur/php-windows-builder'

def api(path):
    return json.loads(subprocess.check_output(['gh', 'api', path]))

def sha(data):
    return hashlib.sha256(data).hexdigest()

def save(name, data):
    Path('receipts').mkdir(exist_ok=True)
    Path('receipts', name + '.json').write_text(json.dumps(data, indent=2) + '\n')

def download(endpoint, path, asset=False):
    args = ['gh', 'api', endpoint, '--allow-escape-sequences']
    if asset:
        args += ['-H', 'Accept: application/octet-stream']
    with Path(path).open('wb') as out:
        subprocess.run(args, stdout=out, check=True)

def inventory(plan):
    pages = json.loads(subprocess.check_output(['gh', 'api', f'repos/{DEST}/releases/{plan["release_id"]}/assets?per_page=100', '--paginate', '--slurp']))
    assets = [a for page in pages for a in page]
    assert len(assets) == len({a['name'] for a in assets})
    return {a['name']: a for a in assets}

def same(asset, file):
    return asset and asset['state'] == 'uploaded' and asset['size'] == file['bytes'] and asset.get('digest') == 'sha256:' + file['sha256']

def upload_bytes(plan, file, data, old):
    headers = {'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
    if old:
        request = urllib.request.Request(f'https://api.github.com/repos/{DEST}/releases/assets/{old["id"]}', headers=headers, method='DELETE')
        with urllib.request.urlopen(request, timeout=60):
            pass
    url = f'https://uploads.github.com/repos/{DEST}/releases/{plan["release_id"]}/assets?name=' + urllib.parse.quote(file['name'], safe='')
    request = urllib.request.Request(url, data=data, headers={**headers, 'Content-Type': 'application/octet-stream'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            asset = json.load(response)
    except Exception:
        asset = inventory(plan).get(file['name'])
        if not same(asset, file):
            raise RuntimeError('Upload outcome requires recovery: ' + file['name']) from None
    assert same(asset, file), ('Uploaded bytes differ', file['name'])
    return asset

def inspect_archive(data, plan):
    assert sha(data) == plan['artifact_sha256'], 'Aggregate digest mismatch'
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names)) and all('/' not in n and '\\' not in n and ':' not in n and n not in ('.', '..') for n in names)
        assert archive.testzip() is None
        files = {n: archive.read(n) for n in names}
    if plan.get('inspected_files'):
        assert {n: sha(b) for n, b in files.items()} == {f['name']: f['sha256'] for f in plan['inspected_files']}
    version = plan['version']
    runtime_pattern = rf'php-{re.escape(version)}(-nts)?-Win32-(v[sc]\d+)-(x86|x64)\.zip'
    runtime = {n: re.fullmatch(runtime_pattern, n, re.I) for n in files}
    runtime = {n: m for n, m in runtime.items() if m}
    expected = {(a, t) for a in plan['architectures'] for t in ('nts', 'ts')}
    assert {(m[3], 'nts' if m[1] else 'ts') for m in runtime.values()} == expected
    review = []
    for name, match in runtime.items():
        arch = match[3]
        with zipfile.ZipFile(io.BytesIO(files[name])) as package:
            assert package.testzip() is None
            assert {'php.exe', 'php-cgi.exe'} <= set(package.namelist())
            pe_count = 0
            data_dlls = []
            for member in package.namelist():
                if not member.lower().endswith(('.exe', '.dll')):
                    continue
                binary = package.read(member)
                assert binary[:2] == b'MZ'
                offset = struct.unpack_from('<I', binary, 0x3c)[0]
                assert binary[offset:offset + 4] == b'PE\0\0'
                machine = struct.unpack_from('<H', binary, offset + 4)[0]
                if machine != {'x86': 0x14c, 'x64': 0x8664}[arch]:
                    assert arch == 'x64' and machine == 0x14c and re.fullmatch(r'icudt\d+\.dll', member)
                    opt = offset + 24
                    assert struct.unpack_from('<H', binary, opt)[0] == 0x10b
                    assert struct.unpack_from('<I', binary, opt + 4)[0] == 0 and struct.unpack_from('<I', binary, opt + 16)[0] == 0
                    for directory in (1, 9, 13, 14):
                        assert struct.unpack_from('<II', binary, opt + 96 + directory * 8) == (0, 0)
                    count = struct.unpack_from('<H', binary, offset + 6)[0]
                    opt_size = struct.unpack_from('<H', binary, offset + 20)[0]
                    for section in range(count):
                        assert struct.unpack_from('<I', binary, opt + opt_size + section * 40 + 36)[0] & (0x20000000 | 0x20) == 0
                    data_dlls.append({'name': member, 'sha256': sha(binary), 'reason': 'ICU data only; no code, entry point, executable sections, imports or callbacks'})
                pe_count += 1
        suffix = name.removeprefix('php-' + version)
        for kind in ('debug', 'devel'):
            pack_name = f'php-{kind}-pack-{version}{suffix}'
            with zipfile.ZipFile(io.BytesIO(files[pack_name])) as pack:
                assert pack.testzip() is None
                if kind == 'debug':
                    pdbs = [n for n in pack.namelist() if n.endswith('.pdb')]
                    assert pdbs and all(pack.read(n).startswith(b'Microsoft C/C++ MSF 7.00') for n in pdbs)
                else:
                    headers = [n for n in pack.namelist() if n.endswith('/php_version.h') or n == 'php_version.h']
                    assert len(headers) == 1 and f'#define PHP_VERSION "{version}"'.encode() in pack.read(headers[0])
                    assert any(n.endswith('.lib') for n in pack.namelist())
        review.append({'archive': name, 'pe_files': pe_count, 'data_only_dlls': data_dlls})
    allowed = set(runtime)
    for name in runtime:
        suffix = name.removeprefix('php-' + version)
        allowed.update(f'php-{kind}-pack-{version}{suffix}' for kind in ('debug', 'devel'))
        for kind in ('cdx', 'spdx'):
            sidecar = name + '.' + kind + '.json'
            if sidecar in files:
                json.loads(files[sidecar]); allowed.add(sidecar)
    for name in (f'php-{version}-src.zip', f'php-test-pack-{version}.zip'):
        assert name in files
        with zipfile.ZipFile(io.BytesIO(files[name])) as archive:
            assert archive.testzip() is None
        allowed.add(name)
    assert set(files) - allowed <= {'source-provenance.json'}, 'Unreviewed aggregate files'
    return {n: files[n] for n in sorted(allowed)}, review

def publish(plan):
    run = api(f'repos/{SOURCE}/actions/runs/{plan["build_run_id"]}')
    assert run['head_sha'] == plan['build_revision']
    pages = json.loads(subprocess.check_output(['gh', 'api', f'repos/{SOURCE}/actions/runs/{run["id"]}/jobs?per_page=100', '--paginate', '--slurp']))
    jobs = [j for page in pages for j in page['jobs']]
    expected = {(a, t) for a in plan['architectures'] for t in ('nts', 'ts')}
    build = [j for j in jobs if j['name'].startswith('php (')]
    smoke = [j for j in jobs if j['name'].startswith(plan['smoke_prefix'] + ' (')]
    for group, prefix in ((build, 'php'), (smoke, plan['smoke_prefix'])):
        assert len(group) == len(expected) and all(j['status'] == 'completed' and j['conclusion'] == 'success' for j in group), 'Build/smoke gate not satisfied'
        assert {tuple(j['name'][len(prefix) + 2:-1].split(', ')) for j in group} == expected
    save('build-smoke-gate', {'run_id': run['id'], 'revision': run['head_sha'], 'jobs': [{'id': j['id'], 'name': j['name'], 'conclusion': j['conclusion']} for j in build + smoke], 'phpt': 'Not a publication gate; reported separately'})
    asset = api(f'repos/{SOURCE}/actions/artifacts/{plan["artifact_id"]}')
    assert not asset['expired'] and asset['name'] == 'artifacts' and asset['workflow_run']['id'] == run['id'] and asset['digest'] == 'sha256:' + plan['artifact_sha256']
    Path('work').mkdir(exist_ok=True)
    download(f'repos/{SOURCE}/actions/artifacts/{asset["id"]}/zip', 'work/aggregate.zip')
    files, review = inspect_archive(Path('work/aggregate.zip').read_bytes(), plan)
    save('archive-review', {'artifact': asset, 'variants': review, 'files': [{'name': n, 'bytes': len(b), 'sha256': sha(b)} for n, b in files.items()]})
    before = inventory(plan)
    save('destination-before', before)
    def upload(pair):
        name, data = pair
        file = {'name': name, 'bytes': len(data), 'sha256': sha(data)}
        current = before.get(name)
        if same(current, file):
            return {**file, 'asset_id': current['id'], 'already_identical': True}
        approved = plan['before'].get(name)
        assert current is None or approved and all(current.get(k) == approved.get(k) for k in ('id', 'size', 'digest')), ('Unreviewed replacement', name)
        current = upload_bytes(plan, file, data, current)
        receipt = {**file, 'asset_id': current['id'], 'replaced_asset_id': approved['id'] if approved else None}
        save(name, receipt); print('Uploaded', name, flush=True)
        return receipt
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        uploaded = list(pool.map(upload, files.items()))
    # Regenerate only this release's manifest from the fresh, complete asset inventory.
    subprocess.run(['bash', 'publication/manifest.sh', plan['tag'], 'work/manifest.json'], check=True)
    manifest = Path('work/manifest.json').read_bytes(); parsed = json.loads(manifest)
    assert parsed['tag'] == plan['tag'] and parsed['stable']['version'] == plan['version']
    expected_manifest = {'name': 'manifest.json', 'bytes': len(manifest), 'sha256': sha(manifest)}
    upload_bytes(plan, expected_manifest, manifest, inventory(plan).get('manifest.json'))
    after = inventory(plan); assert same(after.get('manifest.json'), expected_manifest), 'Manifest upload failed'
    for name, old in before.items():
        if name not in files and name != 'manifest.json':
            assert name in after and after[name]['id'] == old['id'], ('Unrelated asset changed concurrently', name)
    uploaded.append({**expected_manifest, 'asset_id': after['manifest.json']['id']})
    save('summary', {'repository': DEST, 'minor': plan['minor'], 'tag': plan['tag'], 'build_run_id': plan['build_run_id'], 'artifact_sha256': plan['artifact_sha256'], 'uploaded': True, 'files': uploaded, 'no_rebuild_or_php_retest': True})

def verify(plan):
    receipt = json.loads(Path('publication-receipts/summary.json').read_text())
    assert receipt['build_run_id'] == plan['build_run_id'] and receipt['artifact_sha256'] == plan['artifact_sha256']
    assets = inventory(plan); Path('verify').mkdir(exist_ok=True)
    def one(file):
        asset = assets.get(file['name']); assert same(asset, file)
        path = Path('verify', file['name'])
        download(f'repos/{DEST}/releases/assets/{asset["id"]}', path, True)
        assert path.stat().st_size == file['bytes'] and sha(path.read_bytes()) == file['sha256']
        return {**file, 'download_verified': True}
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        files = list(pool.map(one, receipt['files']))
    save('verification', {**receipt, 'verified': True, 'files': files})
    print('Verified release downloads:', plan['minor'], len(files))

if __name__ == '__main__':
    mode, minor = sys.argv[1:]
    assert os.environ['GITHUB_REPOSITORY'] == DEST and os.environ['GITHUB_EVENT_NAME'] == 'workflow_dispatch'
    plan = json.loads(Path('publication', minor + '.json').read_text())
    assert plan['repository'] == DEST and plan['minor'] == minor and plan['tag'] == 'php' + minor
    {'publish': publish, 'verify': verify}[mode](plan)
