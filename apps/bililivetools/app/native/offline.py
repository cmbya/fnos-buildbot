"""Offline-only installation; preserve the established native-runtime/data layout."""
import json
from pathlib import Path
import shutil


def install(runtime, video, appdest, port):
    bundle = appdest / 'native/bundle'
    if not (bundle/'backend/index.cjs').is_file():
        raise RuntimeError('Bundled backend missing')
    runtime.mkdir(parents=True, exist_ok=True)
    for name in ('backend','webui','bin','node','lib','fonts'):
        new = runtime/(name+'.new')
        if new.exists(): shutil.rmtree(new)
        shutil.copytree(bundle/name,new,symlinks=False)
        old = runtime/(name+'.old')
        if old.exists(): shutil.rmtree(old)
        target=runtime/name
        if target.exists(): target.rename(old)
        new.rename(target)
        if old.exists(): shutil.rmtree(old)
    for name in ('data','home'):
        (runtime/name).mkdir(exist_ok=True)
    if not (runtime/'bilikey').exists():
        import secrets
        (runtime/'bilikey').write_text(secrets.token_hex(32)+'\n')
        (runtime/'bilikey').chmod(0o600)
    video.mkdir(parents=True,exist_ok=True)
    link=runtime/'video'
    if link.is_symlink(): link.unlink()
    if not link.exists(): link.symlink_to(video,target_is_directory=True)
    config={'host':'127.0.0.1','port':port,'configFolder':str(runtime/'data'),'logPath':str(runtime/'data/main.log')}
    for key,name in {'ffmpegPath':'ffmpeg','ffprobePath':'ffprobe','mesioPath':'mesio','bililiveRecorderPath':'BililiveRecorder.Cli','danmakuFactoryPath':'DanmakuFactory','audiowaveformPath':'audiowaveform'}.items():
        config[key]=str(runtime/'bin'/name)
    (runtime/'config.json').write_text(json.dumps(config,indent=2)+'\n')
    (runtime/'backend/ENTRY').write_text('index.cjs\n')
    (runtime/'VERSION').write_text(json.loads((appdest/'native/BUILD.json').read_text())['version']+'\n')
    shutil.copy2(appdest/'native/web_server.js',runtime/'web_server.js')
    print('Offline install complete; existing data, key and recording directory retained')
