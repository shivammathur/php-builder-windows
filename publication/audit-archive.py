"""Read-only diagnosis of existing aggregate ZIPs; no PHP execution or publication."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

from publish import SOURCE, DEST, api, download, sha, save

minor = sys.argv[1]
assert os.environ['GITHUB_REPOSITORY'] == DEST
assert os.environ['GITHUB_EVENT_NAME'] == 'workflow_dispatch'
plan = json.loads(Path('publication', minor + '.json').read_text())
asset = api(f'repos/{SOURCE}/actions/artifacts/{plan["artifact_id"]}')
assert not asset['expired'] and asset['workflow_run']['id'] == plan['build_run_id']
assert asset['workflow_run']['head_sha'] == plan['build_revision']
assert asset['digest'] == 'sha256:' + plan['artifact_sha256']
Path('work').mkdir(exist_ok=True)
download(f'repos/{SOURCE}/actions/artifacts/{asset["id"]}/zip', 'work/aggregate.zip')
payload = Path('work/aggregate.zip').read_bytes()
assert sha(payload) == plan['artifact_sha256']
results = []
with zipfile.ZipFile(io.BytesIO(payload)) as aggregate:
    assert aggregate.testzip() is None
    for name in aggregate.namelist():
        assert '/' not in name and '\\' not in name and ':' not in name
        if not name.endswith('.zip'):
            continue
        data = aggregate.read(name)
        result = {'name': name, 'bytes': len(data), 'sha256': sha(data)}
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                result['members'] = len(archive.infolist())
                result['crc_error'] = archive.testzip()
                result['python_zip_valid'] = result['crc_error'] is None
        except Exception as exc:
            result.update(python_zip_valid=False, error=f'{type(exc).__name__}: {exc}')
        if not result['python_zip_valid']:
            path = Path('work', name)
            path.write_bytes(data)
            binary = shutil.which('7z') or shutil.which('7zz')
            assert binary, '7-Zip is required for independent diagnosis'
            check = subprocess.run([binary, 't', str(path)], capture_output=True, text=True)
            result.update(seven_zip_exit_code=check.returncode, seven_zip_output=check.stdout + check.stderr)
            # Record the end record offsets to distinguish malformed ZIP structure.
            result['end_records'] = [i for i in range(max(0, len(data)-65557), len(data)-3) if data[i:i+4] == b'PK\x05\x06']
        results.append(result)
        print(json.dumps(result), flush=True)
save('archive-diagnosis', {'minor': minor, 'artifact_id': asset['id'], 'artifact_sha256': plan['artifact_sha256'], 'build_run_id': plan['build_run_id'], 'files': results, 'read_only': True, 'php_execution': False})
