"""Transfer exact owner-approved files; never build or run PHP."""
import base64,concurrent.futures as cf,hashlib,json,os,subprocess,sys,time,urllib.request,zipfile,zlib
from pathlib import Path
mode,minor=sys.argv[1:];plan=json.loads(Path('publication/'+minor+'.json').read_text());repo=os.environ['GITHUB_REPOSITORY'];assert repo==plan['repository'] and os.environ['GITHUB_EVENT_NAME']=='workflow_dispatch'
files={f['name']:f for f in plan['files']};assert len(files)==len(plan['files']) and all(Path(n).name==n for n in files)
Path('receipts').mkdir(exist_ok=True)
def api(path):return json.loads(subprocess.check_output(['gh','api',path]))
def inventory():
 pages=json.loads(subprocess.check_output(['gh','api',f'repos/{repo}/releases/{plan["release_id"]}/assets?per_page=100','--paginate','--slurp']))
 out=[a for p in pages for a in p];assert len(out)==len({a['name'] for a in out});return {a['name']:a for a in out}
def sha(p):
 with Path(p).open('rb') as h:return hashlib.file_digest(h,'sha256').hexdigest()
def same(a,f):return a and a['state']=='uploaded' and a['size']==f['bytes'] and a.get('digest')=='sha256:'+f['sha256']
def save(name,data):Path('receipts/'+name+'.json').write_text(json.dumps(data,indent=2)+'\n')
def read_url(url,p,expected):
 for attempt in range(4):
  try:
   with urllib.request.urlopen(url,timeout=180) as src,Path(p).open('wb') as out:
    for chunk in iter(lambda:src.read(4*1024*1024),b''):out.write(chunk)
   assert Path(p).stat().st_size==expected['bytes'] and sha(p)==expected['sha256'];return
  except Exception:
   if attempt==3:raise RuntimeError('Download/hash verification failed for '+Path(p).name) from None
   time.sleep(2**attempt)
def checked_inventory():
 inv=inventory()
 for n,a in inv.items():
  if n in files and not same(a,files[n]):
   prior=plan['before'].get(n);assert prior and all(a.get(k)==prior.get(k) for k in ('id','size','digest','state')),('Unreviewed destination change',n)
 for n,old in plan['before'].items():
  if n not in files:assert n in inv and inv[n]['id']==old['id'],('Unrelated asset changed',n)
 return inv
if mode=='backup':
 assert plan['backup_replacements'];inv=checked_inventory();Path('backup').mkdir();receipts=[]
 for n,f in files.items():
  a=inv.get(n)
  if not a or same(a,f):continue
  p=Path('backup')/n
  with p.open('wb') as out:subprocess.run(['gh','api',a['url'],'-H','Accept: application/octet-stream'],stdout=out,check=True)
  assert p.stat().st_size==a['size'];digest=sha(p)
  assert not a.get('digest') or a['digest']=='sha256:'+digest
  receipts.append({'name':n,'id':a['id'],'bytes':a['size'],'sha256':digest})
 Path('backup/inventory.json').write_text(json.dumps(receipts,indent=2)+'\n');print('Backed up',len(receipts),'existing mutable release assets')
elif mode=='publish':
 before=checked_inventory();Path('work').mkdir(exist_ok=True)
 caps=json.loads(zlib.decompress(base64.b64decode(os.environ.pop('PRIVATE_PACKAGE_ACCESS'))))
 if plan['backup_replacements']:assert os.environ.get('BACKUP_ARTIFACT_ID') and os.environ.get('BACKUP_ARTIFACT_DIGEST')
 if plan['transport']=='bundle':
  bundle=caps['bundle'];p=Path('work/input.zip');read_url(bundle['url'],p,bundle)
  with zipfile.ZipFile(p) as z:
   expected={n for n,f in files.items() if not f.get('metadata')};assert set(z.namelist())==expected and len(z.namelist())==len(expected)
   for n in sorted(expected):
    assert z.getinfo(n).file_size==files[n]['bytes']
    with z.open(n) as src,(Path('work')/n).open('wb') as out:
     for chunk in iter(lambda:src.read(4*1024*1024),b''):out.write(chunk)
    assert sha(Path('work')/n)==files[n]['sha256']
  p.unlink()
 def publish(f):
  n=f['name'];old=before.get(n)
  if same(old,f):save(n,{'name':n,'asset_id':old['id'],'identical_existing':True,'uploaded':True});return
  p=Path('work')/n
  if f.get('metadata'):p.write_bytes(base64.b64decode(f['content_base64']))
  elif plan['transport']=='individual':read_url(caps[n],p,f)
  assert p.stat().st_size==f['bytes'] and sha(p)==f['sha256']
  receipt={'name':n,'sha256':f['sha256'],'bytes':f['bytes'],'uploaded':False};save(n,receipt)
  if old:
   subprocess.run(['gh','api','--method','DELETE',old['url']],check=True,stdout=subprocess.DEVNULL)
   receipt['replaced_asset_id']=old['id'];save(n,receipt)
  q=subprocess.run(['gh','release','upload',plan['tag'],str(p),'--repo',repo],capture_output=True,text=True)
  if q.returncode:
   current=inventory().get(n)
   if not same(current,f):raise RuntimeError('Uncertain upload outcome for '+n)
  receipt['uploaded']=True;save(n,receipt);p.unlink();print('Uploaded',n,flush=True)
 with cf.ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(publish,[f for f in files.values() if not f.get('metadata')]))
 for f in files.values():
  if f.get('metadata'):publish(f)
 after=checked_inventory();assert all(same(after.get(n),f) for n,f in files.items())
 save('summary',{'repository':repo,'minor':minor,'run_id':os.environ['GITHUB_RUN_ID'],'revision':os.environ['GITHUB_SHA'],'uploaded':True,'files':len(files),'download_verification':'following read-only job','no_rebuild':True,'backup_artifact_id':os.environ.get('BACKUP_ARTIFACT_ID')});print('Publication complete:',minor,len(files),'assets')
elif mode=='verify':
 inv=checked_inventory();assert all(same(inv.get(n),f) for n,f in files.items());Path('verify').mkdir(exist_ok=True)
 def verify(f):
  p=Path('verify')/f['name'];a=inv[f['name']]
  # Run on GitHub; no package transfer to the operator workstation.
  with p.open('wb') as out:subprocess.run(['gh','api',a['url'],'-H','Accept: application/octet-stream'],stdout=out,check=True,stderr=subprocess.DEVNULL)
  assert p.stat().st_size==f['bytes'] and sha(p)==f['sha256'];p.unlink()
  return {'name':f['name'],'asset_id':a['id'],'bytes':f['bytes'],'sha256':f['sha256'],'download_verified':True}
 with cf.ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(verify,files.values()))
 save('verification',{'repository':repo,'minor':minor,'run_id':os.environ['GITHUB_RUN_ID'],'revision':os.environ['GITHUB_SHA'],'verified':True,'files':results,'unrelated_assets_preserved':True,'no_php_retest':True});print('Verified downloads and preserved unrelated assets:',minor,len(results))
else:raise ValueError('Unknown operation')
