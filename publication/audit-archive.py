"""Read-only diagnosis of existing aggregate ZIPs; no PHP execution or publication."""
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zipfile

from publish import SOURCE, DEST, api, download, sha, save

def inspect_tail(data, offsets):
    records = []
    valid_prefix = None
    valid_end = None
    for offset in offsets:
        fields = struct.unpack_from('<4s4H2IH', data, offset)
        record = dict(zip(('disk', 'directory_disk', 'disk_entries', 'entries', 'directory_size', 'directory_offset', 'comment_bytes'), fields[1:]))
        record['offset'] = offset
        record['directory_signature'] = data[record['directory_offset']:record['directory_offset']+4].hex()
        end = offset + 22 + record['comment_bytes']
        record['end'] = end
        try:
            # Analyze a view ending here, without modifying or publishing any bytes.
            with zipfile.ZipFile(io.BytesIO(data[:end])) as view:
                record['crc_error'] = view.testzip()
                record['parsed_members'] = len(view.infolist())
                if record['crc_error'] is None and valid_prefix is None:
                    valid_prefix = {i.filename: i for i in view.infolist()}
                    valid_end = end
        except Exception as exc:
            record['parse_error'] = f'{type(exc).__name__}: {exc}'
        records.append(record)
    result = {'end_records': records}
    if valid_prefix is None:
        return result
    tail = data[valid_end:]
    result.update(valid_prefix_bytes=valid_end, trailing_bytes=len(tail), tail_sha256=sha(tail), first_tail_bytes_hex=tail[:64].hex())
    result['signatures'] = {sig.hex(): [valid_end+i for i in range(len(tail)-3) if tail[i:i+4] == sig] for sig in (b'PK\x01\x02', b'PK\x03\x04', b'PK\x05\x06', b'PK\x06\x06', b'PK\x06\x07')}
    directory_entries = []
    for offset in result['signatures'][b'PK\x01\x02'.hex()]:
        if offset+46 > len(data):
            continue
        f = struct.unpack_from('<4s6H3I5H2I', data, offset)
        n, e, c = f[10:13]
        if offset+46+n+e+c > len(data):
            continue
        name = data[offset+46:offset+46+n].decode('utf-8', errors='replace')
        entry = {'offset': offset, 'name': name, 'crc32': f[7], 'compressed_bytes': f[8], 'bytes': f[9], 'local_header_offset': f[16]}
        original = valid_prefix.get(name)
        entry['present_in_valid_prefix'] = original is not None
        if original is not None:
            entry['matches_content_crc_and_size'] = (original.CRC, original.file_size) == (f[7], f[9])
            entry['matches_compressed_size_and_offset'] = (original.compress_size, original.header_offset) == (f[8], f[16])
        directory_entries.append(entry)
    result['tail_directory_entries'] = directory_entries
    return result

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
            result['tail_analysis'] = inspect_tail(data, result['end_records'])
        results.append(result)
        print(json.dumps(result), flush=True)
save('archive-diagnosis', {'minor': minor, 'artifact_id': asset['id'], 'artifact_sha256': plan['artifact_sha256'], 'build_run_id': plan['build_run_id'], 'files': results, 'read_only': True, 'php_execution': False})
