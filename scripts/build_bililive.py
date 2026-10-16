"""Fixed upstream source build, relocatable runtime, strict CI gates."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.request
import zipfile
from build_source import run

ROOT = Path(__file__).resolve().parent


def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''):
            h.update(b)
    return h.hexdigest()


def replace(p, old, new):
    text = p.read_text()
    if text.count(old) != 1:
        raise RuntimeError(f'Patch anchor changed: {p}: {old}')
    p.write_text(text.replace(old, new))


def patch_time(source):
    manager = source / 'packages/liveManager/src/manager.ts'
    helper = (ROOT / 'bililive-time.cjs').read_text().replace('exports.allowed = function allowed(range, date = new Date())', 'export function fnosAllowed(range: any, date = new Date())').replace('const parse = x =>', 'const parse = (x: any) =>')
    (manager.parent / 'fnos-time.ts').write_text(helper)
    text = manager.read_text()
    manager.write_text('import { fnosAllowed } from "./fnos-time.js";\n' + text)
    replace(manager, 'if (!ignoreDataLimit && isBetweenTimeRange(recorder.handleTime)) return;', 'if (!ignoreDataLimit && !fnosAllowed(recorder.handleTime)) return;')
    replace(manager, 'const { ignoreDataLimit = true } = iOpts;', 'const { ignoreDataLimit = false } = iOpts;')
    replace(manager, '.filter((r) => r.providerId === "Bilibili"))', '.filter((r) => r.providerId === "Bilibili")\n        .filter((r) => fnosAllowed(r.handleTime)))')
    replace(manager, '.filter((r) => isBetweenTimeRange(r.handleTime))', '.filter((r) => fnosAllowed(r.handleTime))')
    replace(manager, '  isBetweenTimeRange,\n', '')
    replace(manager, 'setTimeout(() => {\n            recorder.checkLiveStatusAndRecord({', 'setTimeout(() => {\n            if (!fnosAllowed(recorder.handleTime)) return;\n            recorder.checkLiveStatusAndRecord({')
    # Exercise actual compiled manager methods with a network-free fake recorder.
    test = source / 'fnos-time-test.cjs'
    test.write_text('''const assert = require('node:assert/strict');
const {allowed} = require('./fnos-time.cjs');
for (const [range,date,want] of [
 [['10:00','11:00'],'2026-01-01T02:30:00Z',true],
 [['10:00','11:00'],'2026-01-01T03:01:00Z',false],
 [['22:00','02:00'],'2026-01-01T17:00:00Z',true],
 [['22:00','02:00'],'2026-01-01T07:00:00Z',false],
 [['00:00','00:00'],'2026-01-01T07:00:00Z',true],
 [['25:00','26:00'],'2026-01-01T07:00:00Z',false],
 [undefined,'2026-01-01T07:00:00Z',true]]) assert.equal(allowed(range,new Date(date)),want);
(async()=>{
 const {createRecorderManager: createManager} = await import('./packages/liveManager/lib/manager.js');
 const m=createManager({providers:[]}); let calls=0;
 const now=new Date();const hour=Number(new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',hour:'2-digit',hourCycle:'h23'}).format(now));
 const text=h=>String(h%24).padStart(2,'0')+':00:00';
 const r={id:'fake',handleTime:[text(hour+2),text(hour+3)],checkLiveStatusAndRecord:async()=>{calls++}};
 m.recorders.push(r); await m.startRecord('fake'); assert.equal(calls,0);
 r.handleTime=['00:00','00:00']; await m.startRecord('fake'); assert.equal(calls,1);
 console.log('TIME PASS: compiled startRecord blocks outside, permits inside; Beijing/overnight/malformed cases pass');
})().catch(e=>{console.error(e);process.exit(1)});
''')
    shutil.copy2(ROOT / 'bililive-time.cjs', source / 'fnos-time.cjs')


def download(url, dest, provenance):
    print('DOWNLOAD', url, flush=True)
    with urllib.request.urlopen(url, timeout=300) as r, dest.open('wb') as f:
        shutil.copyfileobj(r, f)
    digest = sha(dest)
    # GitHub release asset digest when available is mandatory.
    m = re.match(r'https://github.com/([^/]+/[^/]+)/releases/download/([^/]+)/(.+)', url)
    if m:
        req=urllib.request.Request(f'https://api.github.com/repos/{m[1]}/releases/tags/{m[2]}',headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'User-Agent':'fnos-buildbot'})
        with urllib.request.urlopen(req) as r:
            assets=json.load(r)['assets']
        asset=next(a for a in assets if a['name']==m[3])
        if asset['size'] != dest.stat().st_size or (asset.get('digest') and asset['digest'] != 'sha256:'+digest):
            raise RuntimeError('Asset integrity mismatch: '+url)
    provenance.append({'url':url,'sha256':digest,'size':dest.stat().st_size})


def build(app, source, stage, work):
    commit=subprocess.check_output(['git','-c','safe.directory='+str(source),'rev-parse','HEAD'],cwd=source,text=True).strip()
    assert commit == app['source_sha']
    node_version=(source/'.node-version').read_text().strip()
    actual=subprocess.check_output(['node','--version'],text=True).strip()
    assert actual == node_version, (actual,node_version)
    print('Bundled runtime',actual,'ABI',subprocess.check_output(['node','-p','process.versions.modules'],text=True),flush=True)
    patch_time(source)
    run(['pnpm','install','--frozen-lockfile','--ignore-scripts'],source)
    run(['pnpm','run','build:base'],source)
    run(['node','fnos-time-test.cjs'],source)
    env=dict(os.environ,VITE_FULLSTACK='true',VITE_DEFAULT_SERVER='')
    run(['pnpm','--filter','biliLive-tools','build:webui'],source,env=env)
    run(['pnpm','--filter','bililive-cli','build'],source)
    run(['node','scripts/removeDev.js'],source/'packages/CLI')
    bundle=stage/'app/native/bundle'; bundle.mkdir(parents=True)
    backend=bundle/'backend'; shutil.copytree(source/'packages/CLI/lib',backend)
    package=json.loads((source/'packages/CLI/package.json').read_text())
    # Resolve runtime deps against the same frozen workspace lock, not fresh semver.
    importer=(source/'pnpm-lock.yaml').read_text().split('  packages/CLI:')[1].split('\n  packages/')[0]
    for name in package['dependencies']:
        match=re.search(r'(?m)^      [\'"]?'+re.escape(name)+r'[\'"]?:\n        specifier:.*\n        version: ([^\s(]+)',importer)
        if not match: raise RuntimeError('Cannot pin production dependency '+name)
        package['dependencies'][name]=match[1].strip("'\"")
    package.pop('optionalDependencies',None)
    (backend/'package.json').write_text(json.dumps(package,indent=2))
    run(['npm','install','--omit=dev','--no-audit','--no-fund'],backend)
    # better-sqlite3 distributes prebuilds for every OS/CPU in one npm package.
    # Retain precisely the Linux x64 target, not unused ARM/musl artifacts.
    for p in (backend/'node_modules/better-sqlite3/prebuilds').glob('*'):
        if p.name != 'linux-x64.node':
            if p.is_dir(): shutil.rmtree(p)
            else: p.unlink()
    shutil.copytree(source/'packages/app/out/renderer',bundle/'webui')
    (bundle/'node/bin').mkdir(parents=True)
    shutil.copy2('/usr/local/bin/node',bundle/'node/bin/node')
    tools=bundle/'bin';tools.mkdir(); provenance=[]
    def get(repo,tag,name):
        dest=work/name; download(f'https://github.com/{repo}/releases/download/{tag}/{name}',dest,provenance);return dest
    def unzip(archive,target):
        with zipfile.ZipFile(archive) as z:
            for n in z.namelist():
                if n.startswith('/') or '..' in Path(n).parts: raise RuntimeError('Unsafe tool archive')
            z.extractall(target)
    unzip(get('renmu123/biliLive-tools','0.2.1','linux-x64-2.5.0.zip'),bundle/'resources')
    for p in (bundle/'resources').rglob('*'):
        if p.is_file() and p.name in ('ffmpeg','ffprobe'): shutil.copy2(p,tools/p.name)
    shutil.rmtree(bundle/'resources')
    shutil.copy2(get('hua0512/rust-srec','mesio-v0.5.0','mesio-x86_64-unknown-linux-musl'),tools/'mesio')
    unzip(get('renmu123/BililiveRecorder','v3.4.0','BililiveRecorder-CLI-linux-x64.zip'),tools)
    unzip(get('renmu123/DanmakuFactory','v2.1.2','DanmakuFactory-linux-x86_64-CLI.zip'),tools)
    deb=get('bbc/audiowaveform','1.10.2','audiowaveform_1.10.2-1-12_amd64.deb')
    run(['dpkg-deb','-x',str(deb),str(work/'audio')],work)
    shutil.copy2(work/'audio/usr/bin/audiowaveform',tools/'audiowaveform')
    for repo,tag,name,exe in [('qjfoidnh/BaiduPCS-Go','v4.0.1','BaiduPCS-Go-v4.0.1-linux-amd64.zip','BaiduPCS-Go'),('tickstep/aliyunpan','v0.3.7','aliyunpan-v0.3.7-linux-amd64.zip','aliyunpan')]:
        extract=work/exe;unzip(get(repo,tag,name),extract);shutil.copy2(next(extract.rglob(exe)),tools/exe)
    fonts=bundle/'fonts';fonts.mkdir()
    for name in ['NotoSansSC-Regular.ttf','NotoEmoji-Regular.ttf']:
        shutil.copy2(get('renmu123/biliLive-tools','0.2.1',name),fonts/name)
    # Collect transitive ELF dependencies privately, never overwrite global /app or /usr.
    lib=bundle/'lib';lib.mkdir()
    checked=set(); queue=[p for p in bundle.rglob('*') if p.is_file() and p.open('rb').read(4)==b'\x7fELF']
    elf_report=[]
    while queue:
        p=queue.pop()
        if p in checked: continue
        checked.add(p);p.chmod(0o755)
        hdr=subprocess.check_output(['readelf','-h',str(p)],text=True)
        assert 'Advanced Micro Devices X86-64' in hdr, str(p) + ': ' + hdr
        versions=subprocess.check_output(['readelf','--version-info',str(p)],text=True)
        required=[tuple(map(int,v.split('.'))) for v in re.findall(r'GLIBC_([0-9.]+)',versions)]
        if required and max(required) > (2,36):
            raise RuntimeError(f'{p}: GLIBC requirement exceeds Debian 12 baseline: {max(required)}')
        result=subprocess.run(['ldd',str(p)],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        if 'not found' in result.stdout: raise RuntimeError(str(p)+': '+result.stdout)
        elf_report.append({'file':str(p.relative_to(bundle)),'ldd':result.stdout})
        for dep in re.findall(r'=> (/[^\s]+)',result.stdout):
            src=Path(dep)
            if src.name.startswith(('libc.so','libm.so','libpthread.so','libdl.so','librt.so')): continue
            dst=lib/src.name
            if not dst.exists(): shutil.copy2(src,dst);queue.append(dst)
    for exe,args in [('ffmpeg',['-version']),('ffprobe',['-version']),('mesio',['--version']),('BililiveRecorder.Cli',['--version']),('DanmakuFactory',['--help']),('audiowaveform',['--version']),('BaiduPCS-Go',['--version']),('aliyunpan',['--version'])]:
        p=tools/exe
        assert p.is_file(),exe
        p.chmod(0o755)
        result=subprocess.run([str(p),*args],env=dict(os.environ,LD_LIBRARY_PATH=str(lib),DOTNET_SYSTEM_GLOBALIZATION_INVARIANT='1'),text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
        print('TOOL',exe,result.returncode,result.stdout[:1500],flush=True)
        if result.returncode != 0: raise RuntimeError('Media tool execution failed: '+exe)
    (bundle/'ELF.json').write_text(json.dumps(elf_report,indent=2))
    run(['node','-e',"const D=require('better-sqlite3');const d=new D(':memory:');d.exec('CREATE TABLE abi_test(x)');d.close();require('@napi-rs/canvas').createCanvas(10,10);require('shazamio-core');require('music-segment-detector');console.log('NATIVE ABI PASS sqlite/canvas/shazamio/music-segment-detector')"],backend,env=dict(os.environ,LD_LIBRARY_PATH=str(lib)))
    shutil.copy2(source/'LICENSE',stage/'LICENSE')
    # Keep license/copyright data of bundled Debian dependencies.
    shutil.copytree('/usr/share/doc',bundle/'debian-licenses',ignore=shutil.ignore_patterns('*.gz','examples','html'))
    meta={'repo':app['upstream_repo'],'tag':app['tag'],'commit':commit,'version':app['version'],'node':actual,'binary_sha256':sha(bundle/'node/bin/node'),'dependencies':provenance,'lockfile_sha256':sha(source/'pnpm-lock.yaml'),'production_lock_sha256':sha(backend/'package-lock.json'),'patch':'strict Beijing time: manual/batch/normal/retry; fail-closed anchors'}
    (stage/'app/native/BUILD.json').write_text(json.dumps(meta,indent=2)+'\n')
    runtime=work/'upgrade/native-runtime'; (runtime/'data').mkdir(parents=True);(runtime/'data/sentinel').write_text('keep');(runtime/'bilikey').write_text('existing-key');video=work/'recordings';video.mkdir();(video/'sentinel').write_text('recording')
    for _ in range(2):
        run(['python3',str(stage/'app/native/bootstrap.py'),'--runtime',str(runtime),'--video',str(video),'--appdest',str(stage/'app')],work)
    assert (runtime/'data/sentinel').read_text()=='keep' and (runtime/'bilikey').read_text()=='existing-key' and (video/'sentinel').read_text()=='recording'
    env=dict(os.environ,PATH=str(runtime/'node/bin')+':'+str(tools)+':'+os.environ['PATH'],LD_LIBRARY_PATH=str(runtime/'lib'),BILILIVE_TOOLS_PASSKEY='ci-isolated-test',DOTNET_SYSTEM_GLOBALIZATION_INVARIANT='1',FRONTEND_PORT='3000',BACKEND_PORT='18010',WEB_ROOT=str(runtime/'webui'),TZ='Asia/Shanghai')
    procs=[]
    with (work/'smoke.log').open('w+') as log:
        try:
            for args in [[str(runtime/'node/bin/node'),str(runtime/'backend/index.cjs'),'server','--config',str(runtime/'config.json')],[str(runtime/'node/bin/node'),str(runtime/'web_server.js')]]:
                procs.append(subprocess.Popen(args,cwd=runtime,env=env,stdout=log,stderr=log))
            for url,needle in [('http://127.0.0.1:18010/',b'Hello biliLive-tools'),('http://127.0.0.1:3000/',b'<html')]:
                for _ in range(120):
                    try:
                        with urllib.request.urlopen(url,timeout=2) as r:
                            if r.status==200 and needle in r.read(): break
                    except OSError: pass
                    time.sleep(1)
                else: raise RuntimeError('Readiness failed '+url)
            assert list((runtime/'data').rglob('*.db')), 'SQLite DB not initialized'
            print('SMOKE PASS backend HTTP 200, frontend HTTP 200, persistent SQLite, offline repeat installation preserves data and recordings',flush=True)
        finally:
            for p in procs: p.terminate()
            for p in procs: p.wait(timeout=30)
            log.seek(0);print(log.read(),flush=True)
    assert all(p.returncode in (0,-15) for p in procs)
    etc=work/'etc';etc.mkdir();(etc/'passkey').write_text('ci-lifecycle-only')
    lifecycle_env=dict(env,TRIM_PKGVAR=str(runtime.parent),TRIM_APPDEST=str(stage/'app'),TRIM_PKGETC=str(etc),TRIM_DATA_SHARE_PATHS=str(video),TRIM_TEMP_LOGFILE=str(work/'error.log'))
    lifecycle=stage/'cmd/main'
    try:
        run(['bash',str(lifecycle),'start'],work,env=lifecycle_env)
        run(['bash',str(lifecycle),'status'],work,env=lifecycle_env)
    finally:
        run(['bash',str(lifecycle),'stop'],work,env=lifecycle_env)
    assert subprocess.run(['bash',str(lifecycle),'status'],env=lifecycle_env).returncode == 3
    print('LIFECYCLE PASS actual cmd/main start/status/stop and retained time sidecar',flush=True)
    print('SIGTERM stop PASS; provenance',json.dumps(meta),flush=True)
