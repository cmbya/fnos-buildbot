"""StreamCap fixed-SHA native7 source build and offline CI acceptance."""
import ast
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import sys
import tarfile
import time
import urllib.request
from build_metube import run, sha

TOOLS = {
    'python': ('https://github.com/astral-sh/python-build-standalone/releases/download/20261013/cpython-3.12.15%2B202****1013-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz', '178d3d83b6e8e99285a65d3fce9c16b87952cc5efdb4d1a0e3ff3be18ff0fc9c'),
    'node': ('https://nodejs.org/dist/v20.20.2/node-v20.20.2-linux-x64.tar.xz', 'df770b2a6f130ed8627c9782c988fda9669fa23898329a61a871e32f965e007d'),
    'ffmpeg': ('https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-10-16-13-04/ffmpeg-n8.1.3-18-g46d899d7a0-linux64-gpl-8.1.tar.xz', 'c19bd7fec94e0c56032fad4f20bf56b2847f18fbe372c758b32ed10d4dec2176'),
}


def fetch(key, work):
    url, digest = TOOLS[key]
    if key == 'python':
        # Resolve exact upstream filename by its pinned digest. Avoid deriving
        # the asset's build suffix from presentation-filtered API output.
        with urllib.request.urlopen('https://api.github.com/repos/astral-sh/python-build-standalone/releases/tags/20261013') as response:
            assets = json.load(response)['assets']
        matches = [a for a in assets if a.get('digest') == 'sha256:' + digest]
        assert len(matches) == 1
        url = matches[0]['browser_download_url']
    path = work / (key + '.archive')
    run(['curl', '-fL', '--retry', '5', '-o', path, url])
    assert sha(path) == digest, key + ' digest mismatch'
    print('TOOL VERIFIED', key, digest, flush=True)
    return path


def patch_source(source):
    patch = Path(__file__).with_name('streamcap_native7_patch.py')
    result = subprocess.run([sys.executable, patch, source], capture_output=True, text=True)
    print(result.stdout, result.stderr, flush=True)
    assert result.returncode == 0 and 'WARN:' not in result.stdout, 'Native7 anchors changed; refusing release'
    # The historical patch adds recovery after its detach pass. Detach the newly
    # inserted recovery too, otherwise first startup still depends on Flet Page.
    p = source / 'app/core/recording/stream_manager.py'
    text = p.read_text()
    old = '''            self.app.page.run_task(
                self.app.record_manager.check_if_live,
                self.recording,
            )'''
    assert text.count(old) == 1
    p.write_text(text.replace(old, '            asyncio.create_task(self.app.record_manager.check_if_live(self.recording))'))
    markers = {
        'app/utils/utils.py': ['def fnos_now()', '_FNOS_MONITOR_TZ'],
        'app/core/recording/record_manager.py': ['# fnOS native7: scheduled recording lifecycle', '# fnOS native5: resilient web scheduler', '# fnOS native7: server-side recorder dispatch'],
        'app/core/recording/stream_manager.py': ['# fnOS native7: server-side recording engine', '[fnOS native7 recorder] dispatch ffmpeg', '[fnOS native7 recorder] dispatch direct downloader', '# fnOS native3: transient recording recovery'],
        'app/ui/components/business/recording_card.py': ['# fnOS native4: re-arm after scheduled settings edit'],
        'main.py': ['# fnOS native5: always rebind web scheduler'],
    }
    for path, needles in markers.items():
        text = (source / path).read_text()
        for needle in needles:
            assert needle in text, (path, needle)
        compile(text, path, 'exec')
    print('Native7 real fixed-source anchors PASS', flush=True)


def elf_check(bundle):
    maximum = (0, 0)
    count = 0
    for p in bundle.rglob('*'):
        if p.is_symlink():
            assert not os.path.isabs(os.readlink(p)) and p.exists(), p
            continue
        if not p.is_file():
            continue
        with p.open('rb') as f:
            header = f.read(64)
        if not header.startswith(b'\x7fELF'):
            continue
        count += 1
        assert header[:6] == b'\x7fELF\x02\x01' and struct.unpack('<H', header[18:20])[0] == 62, p
        text = subprocess.check_output(['readelf', '--version-info', p], text=True)
        versions = [tuple(map(int, v.split('.'))) for v in re.findall(r'GLIBC_(\d+\.\d+)', text)]
        maximum = max([maximum] + versions)
        assert maximum <= (2, 36), (p, maximum)
        res = subprocess.run(['ldd', p], capture_output=True, text=True)
        assert 'not found' not in res.stdout + res.stderr, (p, res.stdout, res.stderr)
    print('ELF PASS', count, 'x86_64; GLIBC max', maximum, 'closure resolved', flush=True)


def backend(source, bundle, work):
    bundle.mkdir(parents=True)
    (bundle / 'bin').mkdir()
    (bundle / 'licenses').mkdir()
    with tarfile.open(fetch('python', work)) as tf:
        tf.extractall(bundle)
    py = bundle / 'python/bin/python3.12'
    # Upstream has lower bounds, not a lock. Resolve in CI and retain all wheel
    # hashes + exact freeze in the payload, install only those downloaded wheels.
    wheels = work / 'wheels'
    wheels.mkdir()
    run([py, '-m', 'pip', 'wheel', '--prefer-binary', '-r', source / 'requirements-web.txt', '-w', wheels])
    names = sorted(p.name for p in wheels.iterdir())
    (bundle / 'dependency-wheels.json').write_text(json.dumps({n: sha(wheels/n) for n in names}, indent=2))
    run([py, '-m', 'pip', 'install', '--no-index', '--find-links', wheels, '-r', source / 'requirements-web.txt'])
    frozen = subprocess.check_output([py, '-m', 'pip', 'freeze'], text=True)
    (bundle / 'requirements-resolved.txt').write_text(frozen)
    print('RESOLVED DEPENDENCIES', frozen, flush=True)
    shutil.copytree(source, bundle / 'source', ignore=shutil.ignore_patterns('.git','__pycache__','*.pyc'))
    for key in ['node', 'ffmpeg']:
        with tarfile.open(fetch(key, work)) as tf:
            executables = ['node'] if key == 'node' else ['ffmpeg', 'ffprobe']
            for name in executables:
                member = next(m for m in tf.getmembers() if m.name.endswith('/bin/'+name))
                out = bundle / 'bin' / name
                out.write_bytes(tf.extractfile(member).read())
                out.chmod(0o755)
            for member in tf.getmembers():
                if member.isfile() and ('license' in member.name.lower() or 'readme' in member.name.lower()):
                    (bundle/'licenses'/(key+'-'+Path(member.name).name)).write_bytes(tf.extractfile(member).read())
    # Explicit bookworm dynamic closure for Node and native Python wheels.
    (bundle / 'lib').mkdir()
    for name in ['libstdc++.so.6','libgcc_s.so.1','libssl.so.3','libcrypto.so.3','libz.so.1']:
        shutil.copy2(Path('/usr/lib/x86_64-linux-gnu') / name, bundle/'lib'/name)
    for package in ['libstdc++6','libgcc-s1','libssl3','zlib1g','ca-certificates']:
        shutil.copy2(Path('/usr/share/doc')/package/'copyright', bundle/'licenses'/(package+'-copyright'))
    shutil.copy2('/etc/ssl/certs/ca-certificates.crt', bundle/'cacert.pem')
    # App explicitly needs UTC+8 even on hosts without tzdata.
    shutil.copy2('/usr/share/zoneinfo/Asia/Shanghai', bundle/'Shanghai')
    for p in (bundle/'python/bin').iterdir():
        if p.is_file() and p.read_bytes()[:2] == b'#!': p.unlink()
    for p in (bundle/'python/bin').iterdir():
        if p.is_symlink() and not p.exists(): p.unlink()
    os.environ['LD_LIBRARY_PATH'] = str(bundle/'lib')
    elf_check(bundle)


def behavior(source):
    # Execute actual patched class method bodies with only external I/O mocked.
    # This is not the historical synthetic fixture: bodies come from fixed SHA.
    import types
    sys.path.insert(0, str(source))
    from app.utils import utils
    from app.models.recording.recording_status_model import RecordingStatus
    from app.core.recording.record_manager import RecordingManager, GlobalRecordingState
    from app.models.recording.recording_model import Recording
    class Log:
        def __getattr__(self, _): return lambda *a, **kw: None
    from app.core.recording import record_manager as mod
    original_utils = mod.utils
    class Clock:
        in_range = True
        is_current_time_within_range = staticmethod(lambda _: Clock.in_range)
        is_time_interval_exceeded = staticmethod(lambda *_: True)
        fnos_now = staticmethod(utils.fnos_now)
    mod.utils = Clock
    async def test():
        rec = types.SimpleNamespace(monitor_status=True,is_recording=False,scheduled_recording=True,scheduled_start_time='20:00:00',monitor_hours='2',rec_id='ci',url='https://example.invalid/live',detection_time=None,loop_time_seconds=300,showed_checking_status=False,force_stop=True,is_live=False,is_checking=False,status_info=None,start_time=None,stopping_in_progress=False,manually_stopped=False)
        m = RecordingManager.__new__(RecordingManager)
        GlobalRecordingState.recordings = [rec]
        m.active_recorders = {}
        calls=[]
        async def ranges(*_): return ['20:00:00~22:00:00']
        async def check(_): calls.append('check')
        m.get_scheduled_time_range = ranges
        m.check_if_live = check
        def stop(r, manually_stopped=True):
            assert manually_stopped is False
            calls.append('stop'); m.active_recorders.pop(r.rec_id); r.is_recording=False
        m.stop_recording = stop
        await m.check_all_live_status(); await asyncio.sleep(0)
        assert calls == ['check'] and rec.force_stop is False
        rec.is_recording=True
        await m.check_all_live_status(); await asyncio.sleep(0)
        assert calls == ['check','check'] and not rec.is_recording
        m.active_recorders[rec.rec_id] = object(); rec.is_recording=True
        await m.check_all_live_status(); assert calls == ['check','check']
        Clock.in_range=False
        await m.check_all_live_status()
        assert calls[-1]=='stop' and not m.active_recorders and rec.status_info == RecordingStatus.NOT_IN_SCHEDULED_CHECK
        rec.force_stop=True
        await m.check_all_live_status(); assert not rec.force_stop
        Clock.in_range=True
        await m.check_all_live_status(); await asyncio.sleep(0)
        assert calls[-1]=='check'
        GlobalRecordingState.recordings=[]
    asyncio.run(test())
    mod.utils = original_utils
    # Real patched helper: midnight crossing, inclusive bounds, invalid input.
    from datetime import datetime
    original_now=utils.fnos_now
    for clock, window, expected in [('00:30:00','23:00:00~01:00:00',True),('12:00:00','23:00:00~01:00:00',False),('20:00:00','20:00:00~22:00:00',True)]:
        utils.fnos_now=lambda: datetime.strptime('2026-10-17 '+clock,'%Y-%m-%d %H:%M:%S')
        assert utils.is_current_time_within_range(window) is expected
    try: utils.is_current_time_within_range('bad')
    except ValueError: pass
    else: raise AssertionError('invalid range accepted')
    utils.fnos_now=original_now
    print('Native7 REAL SOURCE behavior PASS: scheduled enter/start dispatch, fake state retry, active reconciliation, exit stop+cleanup, re-enter, UTC+8/cross-midnight/invalid range', flush=True)


def probe(stage, work):
    work.mkdir(parents=True, exist_ok=True)
    var=work/'pkgvar';etc=work/'etc';downloads=work/'downloads';authorized=work/'authorized'
    for d in [var,etc,downloads,authorized]: d.mkdir(exist_ok=True); (d/'sentinel').write_text('preserve')
    with socket.socket() as s: s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    bundle=stage/'app/native/bundle'
    env=dict(os.environ,TRIM_APPDEST=str(stage/'app'),TRIM_PKGVAR=str(var),TRIM_PKGETC=str(etc),TRIM_DATA_SHARE_PATHS=str(downloads),TRIM_DATA_ACCESSIBLE_PATHS=str(authorized),TRIM_SERVICE_PORT=str(port),TRIM_TEMP_LOGFILE=str(work/'error.log'),PATH=str(bundle/'bin')+':/usr/bin:/bin',LD_LIBRARY_PATH=str(bundle/'lib'),SSL_CERT_FILE=str(bundle/'cacert.pem'),TZ=':'+str(bundle/'Shanghai'),PYTHONDONTWRITEBYTECODE='1')
    os.environ.update({k:env[k] for k in ['PATH','LD_LIBRARY_PATH','SSL_CERT_FILE','TZ','PYTHONDONTWRITEBYTECODE']})
    for name in ['install_callback','upgrade_callback']: run(['bash',stage/'cmd'/name],env=env)
    runtime=var/'native-runtime';source=runtime/'source';py=runtime/'python/bin/python3.12'
    run([py,'-c','import ssl,sqlite3,flet,flet_web,flet_video,httpx,screeninfo,aiofiles,streamget,dotenv,cachetools,deprecated; from app.core.config.config_manager import ConfigManager; c=ConfigManager("."); assert isinstance(c.load_user_config(),dict); print("imports and persistent JSON state PASS")'],cwd=source,env=env)
    saved={p.name:p.read_bytes() for p in (runtime/'userdata/config').iterdir()}
    run(['bash',stage/'cmd/upgrade_callback'],env=env)
    assert saved=={p.name:p.read_bytes() for p in (runtime/'userdata/config').iterdir()}
    for d in [var,etc,downloads,authorized]: assert (d/'sentinel').read_text()=='preserve'
    run(['bash',stage/'cmd/config_callback'],env=env)
    for tool in ['node','ffmpeg','ffprobe']: run([bundle/'bin'/tool,'--version' if tool=='node' else '-version'],env=env)
    run([bundle/'bin/ffmpeg','-y','-f','lavfi','-i','sine=frequency=440:duration=0.2',work/'test.wav'],env=env)
    run([bundle/'bin/ffprobe','-v','error','-show_entries','format=duration',work/'test.wav'],env=env)
    run([py,Path(__file__),'behavior',source],cwd=source,env=env)
    log=authorized/'StreamCap-Logs/streamcap-fnos.log'
    try:
        run(['bash',stage/'cmd/main','start'],env=env)
        for _ in range(90):
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/',timeout=2) as r:
                    body=r.read();assert r.status==200 and b'<html' in body.lower();break
            except OSError: time.sleep(1)
        else: raise RuntimeError('StreamCap Flet HTTP not ready')
        run(['bash',stage/'cmd/main','status'],env=env)
        for path in ['/flutter_bootstrap.js','/manifest.json']:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}',timeout=10) as r: assert r.status==200;print('Flet HTTP PASS',path,len(r.read()),flush=True)
        assert (source/'downloads').resolve()==authorized
        print('HTTP Flet frontend/server PASS; JSON persistence and authorized recording path PASS',flush=True)
    finally:
        run(['bash',stage/'cmd/main','stop'],env=env)
        print(log.read_text() if log.exists() else 'NO LOG',flush=True)
    assert subprocess.run(['bash',stage/'cmd/main','status'],env=env).returncode==3
    with socket.socket() as s: assert s.connect_ex(('127.0.0.1',port))!=0
    print('OFFLINE nonroot network-none PASS: lifecycle, repeated deployment, config/recording sentinels, native tools, HTTP server, terminated port',flush=True)


def build(app, source, stage, work):
    actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
    assert actual==app['source_sha'] and re.fullmatch(r'v\d+\.\d+\.\d+',app['tag'])
    assert 'python:3.12-slim' in (source/'Dockerfile').read_text() and 'setup_20.x' in (source/'Dockerfile').read_text()
    script=Path(__file__).resolve()
    run([sys.executable,script.with_name('validate_streamcap_native7.py')])
    patch_source(source)
    bundle=stage/'app/native/bundle'
    run(['docker','run','--rm','-e',f'HOST_UID={os.getuid()}','-e',f'HOST_GID={os.getgid()}','-v',f'{script.parent}:/scripts:ro','-v',f'{source}:/source:ro','-v',f'{stage}:/stage','-v',f'{work}:/build','debian:bookworm-slim','bash','-euc','trap \'chown -R "$HOST_UID:$HOST_GID" /build\' EXIT; apt-get update -qq; apt-get install -y -qq python3 curl ca-certificates binutils xz-utils tzdata libstdc++6; python3 /scripts/build_streamcap.py backend /source /stage/app/native/bundle /build'])
    (bundle/'VERSION').write_text(app['tag']+'\n')
    (stage/'app/native/bootstrap.py').unlink()
    for p in (stage/'cmd').iterdir():p.chmod(0o755)
    meta={'repo':app['upstream_repo'],'tag':app['tag'],'commit':actual,'version':app['version'],'source_modified':True,'patch':'native7 + server-side recovery ordering fix','binary_sha256':sha(stage/app['binary_dest']),'glibc_baseline_max':'2.36','tools':TOOLS,'requirements_sha256':sha(source/'requirements-web.txt'),'patch_sha256':sha(script.with_name('streamcap_native7_patch.py')),'runtime_files_sha256':{str(p.relative_to(bundle)):sha(p) for p in bundle.rglob('*') if p.is_file() and not p.is_symlink()}}
    (stage/'app/native/BUILD.json').write_text(json.dumps(meta,indent=2)+'\n')
    relocated=work/'relocated';shutil.copytree(stage,relocated,symlinks=True)
    run(['docker','run','--rm','--network','none','--user',f'{os.getuid()}:{os.getgid()}','-v',f'{script.parent}:/scripts:ro','-v',f'{relocated}:/relocated:ro','-v',f'{work}:/test','debian:bookworm-slim','/relocated/app/native/bundle/python/bin/python3.12','/scripts/build_streamcap.py','probe','/relocated','/test/offline'])
    print('StreamCap ACCEPTANCE PASS fixed SHA',actual,flush=True)


if __name__=='__main__':
    if sys.argv[1]=='backend':backend(*map(Path,sys.argv[2:]))
    elif sys.argv[1]=='probe':probe(*map(Path,sys.argv[2:]))
    elif sys.argv[1]=='behavior':behavior(Path(sys.argv[2]))
