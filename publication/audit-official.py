"""Read-only ZIP integrity comparison against the current official Windows releases."""
import concurrent.futures
import datetime
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import urllib.request
import zipfile

from publish import DEST, save, sha

assert os.environ['GITHUB_REPOSITORY'] == DEST
assert os.environ['GITHUB_EVENT_NAME'] == 'workflow_dispatch'
BASE = 'https://downloads.php.net/~windows/releases/'
baseline = json.loads(Path('publication/8.5-archive-baseline.json').read_text())
Path('work').mkdir(exist_ok=True)

def get(name):
    assert re.fullmatch(r'[A-Za-z0-9._-]+', name)
    request = urllib.request.Request(BASE + name, headers={'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(request, timeout=180) as response:
        assert response.status == 200
        data = response.read(300_000_001)
        assert len(data) <= 300_000_000
        return data

sums = get('sha256sum.txt')
expected = {line.split()[1].removeprefix('*'): line.split()[0] for line in sums.decode().splitlines() if line.strip()}

def one(file):
    name = file['name']
    data = get(name)
    result = {'name': name, 'url': BASE + name, 'bytes': len(data), 'sha256': sha(data), 'sha256sum_matches': sha(data) == expected[name], 'matches_current_builder_artifact': sha(data) == file['sha256']}
    assert result['sha256sum_matches'], 'Official checksum mismatch: ' + name
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            result['members'] = len(archive.infolist())
            result['crc_error'] = archive.testzip()
            result['python_zip_valid'] = result['crc_error'] is None
            offset = data.rfind(b'PK\x05\x06', max(0, len(data)-65557))
            assert offset >= 0
            comment_size = struct.unpack_from('<H', data, offset+20)[0]
            result['trailing_bytes'] = len(data) - (offset+22+comment_size)
    except Exception as exc:
        result.update(python_zip_valid=False, error=f'{type(exc).__name__}: {exc}')
    if not result['python_zip_valid'] or result.get('trailing_bytes') != 0:
        path = Path('work', name)
        path.write_bytes(data)
        binary = shutil.which('7z') or shutil.which('7zz')
        assert binary
        check = subprocess.run([binary, 't', str(path)], capture_output=True, text=True)
        result.update(seven_zip_exit_code=check.returncode, seven_zip_output=check.stdout+check.stderr)
    print(json.dumps(result), flush=True)
    return result

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    files = list(pool.map(one, baseline['files']))
assert get('sha256sum.txt') == sums, 'Official checksum inventory changed during inspection'
save('official-archive-comparison', {'at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'base_url': BASE, 'official_manifest_sha256': sha(sums), 'builder_run_id': baseline['build_run_id'], 'builder_aggregate_sha256': baseline['artifact_sha256'], 'files': files, 'read_only': True, 'php_execution': False})
