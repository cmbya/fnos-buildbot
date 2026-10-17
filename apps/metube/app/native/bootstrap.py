#!/usr/bin/env python3
import argparse, hashlib, http.client, io, json, os, pathlib, re, shutil, stat, subprocess, sys, tarfile, tempfile, time, urllib.request, zipfile

UA='MeTube-fnOS-native/1.0'

def log(msg):
    print(msg, flush=True)

def req(url, timeout=180, retries=5):
    """Small-response helper with retry support."""
    last=None
    for attempt in range(1,retries+1):
        try:
            r=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'*/*'})
            with urllib.request.urlopen(r,timeout=timeout) as x:
                return x.read()
        except (OSError, urllib.error.URLError, http.client.HTTPException, http.client.IncompleteRead) as e:
            last=e
            if attempt>=retries:
                raise
            wait=min(3*attempt,15)
            log(f'网络读取失败，第 {attempt}/{retries} 次，{wait}s 后重试: {e!r}')
            time.sleep(wait)
    raise last

def download(url,path,timeout=300,retries=8):
    """Resumable streaming download for large GitHub/CDN assets.

    Writes to <path>.part, retries interrupted transfers, and uses HTTP Range
    when supported. The final file is only replaced after the transfer is
    complete, so a broken connection never leaves a truncated final archive.
    """
    path=pathlib.Path(path)
    part=pathlib.Path(str(path)+'.part')
    path.parent.mkdir(parents=True,exist_ok=True)
    log('下载: '+url)
    last=None

    for attempt in range(1,retries+1):
        offset=part.stat().st_size if part.exists() else 0
        headers={'User-Agent':UA,'Accept':'*/*'}
        if offset:
            headers['Range']=f'bytes={offset}-'
        try:
            r=urllib.request.Request(url,headers=headers)
            with urllib.request.urlopen(r,timeout=timeout) as x:
                status=getattr(x,'status',200)
                # Range ignored: restart cleanly instead of appending duplicate data.
                if offset and status!=206:
                    log('服务器不支持断点续传，本次从头重新下载。')
                    offset=0
                    try: part.unlink()
                    except FileNotFoundError: pass

                total=None
                cr=x.headers.get('Content-Range','')
                m=re.search(r'/([0-9]+)$',cr)
                if m:
                    total=int(m.group(1))
                elif x.headers.get('Content-Length'):
                    total=offset+int(x.headers['Content-Length'])

                mode='ab' if offset else 'wb'
                with part.open(mode) as f:
                    while True:
                        try:
                            chunk=x.read(1024*1024)
                        except http.client.IncompleteRead as e:
                            if e.partial:
                                f.write(e.partial)
                                f.flush()
                            raise
                        if not chunk:
                            break
                        f.write(chunk)
                    f.flush()
                    os.fsync(f.fileno())

            size=part.stat().st_size
            if total is not None and size < total:
                raise IOError(f'下载不完整: {size}/{total} bytes')
            if total is not None and size > total:
                raise IOError(f'下载大小异常: {size}>{total} bytes')
            part.replace(path)
            log(f'下载完成: {path.name} ({path.stat().st_size} bytes)')
            return path
        except (OSError, urllib.error.URLError, http.client.HTTPException, http.client.IncompleteRead) as e:
            last=e
            size=part.stat().st_size if part.exists() else 0
            if attempt>=retries:
                break
            wait=min(4*attempt,20)
            log(f'下载中断，已保存 {size} bytes；第 {attempt}/{retries} 次失败，{wait}s 后续传: {e!r}')
            time.sleep(wait)

    raise RuntimeError(f'多次重试后仍下载失败: {url}: {last!r}')

def run(cmd,cwd=None,env=None,check=True):
    log('RUN: '+' '.join(map(str,cmd)))
    return subprocess.run(cmd,cwd=cwd,env=env,check=check)

def replace_dir(new,final):
    backup=pathlib.Path(str(final)+'.old')
    if backup.exists(): shutil.rmtree(backup,ignore_errors=True)
    if final.exists(): final.rename(backup)
    new.rename(final)
    shutil.rmtree(backup,ignore_errors=True)

def install_uv(runtime):
    b=runtime/'bin'; b.mkdir(parents=True,exist_ok=True)
    uv=b/'uv'
    if uv.exists(): return uv
    url='https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-unknown-linux-gnu.tar.gz'
    archive=runtime/'uv-x86_64-unknown-linux-gnu.tar.gz'
    download(url,archive,timeout=300,retries=10)
    with tarfile.open(archive,mode='r:gz') as tf:
        members=tf.getmembers()
        uv_member=next((m for m in members if m.name.endswith('/uv') or m.name=='uv'),None)
        if not uv_member: raise RuntimeError('uv 压缩包中找不到 uv')
        f=tf.extractfile(uv_member)
        uv.write_bytes(f.read())
    uv.chmod(0o755)
    try: archive.unlink()
    except FileNotFoundError: pass
    return uv

def install_ffmpeg(runtime, venv_python):
    """Prepare FFmpeg/FFprobe without downloading FFmpeg from GitHub.

    native6 bundles a static Linux x86_64 FFmpeg binary inside the FPK.
    FFprobe is installed from the platform-specific npm package, whose tarball
    itself contains the static ffprobe binary. This avoids the fragile BtbN
    GitHub asset URL that previously returned 404 on fnOS.
    """
    b=runtime/'bin'; b.mkdir(parents=True,exist_ok=True)
    vendor=pathlib.Path(__file__).resolve().parent/'vendor'
    bundled=vendor/'ffmpeg'
    ffmpeg=b/'ffmpeg'
    ffprobe=b/'ffprobe'

    if not bundled.exists():
        raise RuntimeError('FPK 内置 FFmpeg 缺失，请重新下载安装包')

    # Refresh the bundled binary when packaging revision changes. SHA comparison
    # avoids rewriting the 77MB file on every restart/upgrade callback.
    def sha256_file(path):
        h=hashlib.sha256()
        with pathlib.Path(path).open('rb') as f:
            while True:
                chunk=f.read(1024*1024)
                if not chunk: break
                h.update(chunk)
        return h.hexdigest()

    if (not ffmpeg.exists()) or sha256_file(ffmpeg)!=sha256_file(bundled):
        log('安装 FPK 内置 FFmpeg（无需联网下载）')
        shutil.copy2(bundled,ffmpeg)
        ffmpeg.chmod(0o755)
    else:
        log('复用已安装的内置 FFmpeg')

    # FFprobe platform package is distributed directly through npm and contains
    # the static ffprobe executable at package root. npm access has already been
    # required/successful for the MeTube Angular build, so this avoids another
    # GitHub release-asset dependency.
    if not ffprobe.exists():
        nodebin=runtime/'node/bin'
        npm=nodebin/'npm'
        if not npm.exists():
            raise RuntimeError('本地 Node.js npm 不存在，无法准备 ffprobe')

        tools=runtime/'ffprobe-tools'
        home=runtime/'home'
        cache=runtime/'npm-cache'
        tools.mkdir(parents=True,exist_ok=True)
        home.mkdir(parents=True,exist_ok=True)
        cache.mkdir(parents=True,exist_ok=True)
        env=os.environ.copy()
        env['HOME']=str(home)
        env['USERPROFILE']=str(home)
        env['NPM_CONFIG_CACHE']=str(cache)
        env['npm_config_cache']=str(cache)
        env['PATH']=str(nodebin)+':'+env.get('PATH','')

        last=None
        for attempt in range(1,5):
            try:
                run([
                    str(npm),'install','--no-audit','--no-fund',
                    '--prefix',str(tools),'@ffprobe-installer/linux-x64@5.2.0'
                ],env=env)
                last=None
                break
            except subprocess.CalledProcessError as e:
                last=e
                if attempt>=4: break
                wait=min(4*attempt,12)
                log(f'ffprobe npm 安装失败，第 {attempt}/4 次，{wait}s 后重试')
                time.sleep(wait)
        if last is not None:
            raise RuntimeError('多次重试后仍无法通过 npm 安装 ffprobe') from last

        src=tools/'node_modules/@ffprobe-installer/linux-x64/ffprobe'
        if not src.exists():
            raise RuntimeError('npm 包已安装，但未找到 @ffprobe-installer/linux-x64/ffprobe')
        shutil.copy2(src,ffprobe)
        ffprobe.chmod(0o755)

    # Quick executable checks make installation fail early with a useful error
    # instead of discovering a broken binary only when the first download runs.
    run([str(ffmpeg),'-version'])
    run([str(ffprobe),'-version'])
    log('FFmpeg / FFprobe 已准备完成')

def install_deno(runtime):
    b=runtime/'bin'; b.mkdir(parents=True,exist_ok=True)
    p=b/'deno'
    if p.exists(): return
    url='https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip'
    archive=runtime/'deno-x86_64-unknown-linux-gnu.zip'
    download(url,archive,timeout=300,retries=8)
    with zipfile.ZipFile(archive) as z:
        p.write_bytes(z.read('deno'))
    p.chmod(0o755)
    try: archive.unlink()
    except FileNotFoundError: pass

def latest_bgutil():
    data=json.loads(req('https://api.github.com/repos/jim60105/bgutil-ytdlp-pot-provider-rs/releases/latest').decode())
    return data

def install_bgutil(runtime,venv_python):
    try:
        data=latest_bgutil(); assets={a['name']:a['browser_download_url'] for a in data.get('assets',[])}
        b=runtime/'bin'; b.mkdir(parents=True,exist_ok=True)
        bin_name=next((n for n in assets if n=='bgutil-pot-linux-x86_64'),None)
        zip_name=next((n for n in assets if n.endswith('.zip') and 'provider' in n),None)
        if bin_name:
            p=b/'bgutil-pot'; p.write_bytes(req(assets[bin_name])); p.chmod(0o755)
        if zip_name:
            site=subprocess.check_output([str(venv_python),'-c','import site; print(site.getsitepackages()[0])'],text=True).strip()
            with zipfile.ZipFile(io.BytesIO(req(assets[zip_name]))) as z: z.extractall(site)
        log('bgutil POT provider 已准备')
    except Exception as e:
        log('警告：bgutil POT provider 安装失败，不阻止 MeTube 安装：'+repr(e))

def fetch_source(runtime,version):
    url=f'https://github.com/alexta69/metube/archive/refs/tags/{version}.tar.gz'
    archive=runtime/f'metube-{version}.tar.gz'
    download(url,archive,timeout=300,retries=8)
    temp=runtime/'source.new'
    if temp.exists(): shutil.rmtree(temp)
    temp.mkdir(parents=True)
    with tarfile.open(archive,mode='r:gz') as tf:
        top=None
        for m in tf.getmembers():
            if '/' in m.name: top=m.name.split('/',1)[0]; break
        tf.extractall(temp)
    children=[p for p in temp.iterdir() if p.is_dir()]
    if len(children)==1:
        inner=children[0]
        stage=runtime/'source.stage'
        if stage.exists(): shutil.rmtree(stage)
        inner.rename(stage); shutil.rmtree(temp,ignore_errors=True); temp=stage
    try: archive.unlink()
    except FileNotFoundError: pass
    return temp

def parse_version_tuple(text):
    m=re.search(r'(\d+)\.(\d+)\.(\d+)', text or '')
    return tuple(map(int,m.groups())) if m else (0,0,0)

def install_node(runtime):
    """Install an official Node.js latest-v22.x x64 runtime into app data.

    fnOS nodejs_v22 may lag behind Angular CLI's patch-level minimum.
    Keeping Node local makes the MeTube build independent of fnOS runtime updates.
    """
    node_root=runtime/'node'
    nodebin=node_root/'bin'
    node=nodebin/'node'
    minimum=(22,22,3)

    if node.exists():
        try:
            ver=subprocess.check_output([str(node),'--version'],text=True).strip()
            if parse_version_tuple(ver) >= minimum:
                log('复用本地 Node.js '+ver)
                return nodebin
        except Exception:
            pass

    sums_url='https://nodejs.org/download/release/latest-v22.x/SHASUMS256.txt'
    sums=req(sums_url,180).decode('utf-8','replace')
    chosen=None
    expected=None
    for line in sums.splitlines():
        parts=line.strip().split()
        if len(parts)==2 and parts[1].startswith('node-v22.') and parts[1].endswith('-linux-x64.tar.gz'):
            expected,chosen=parts[0],parts[1]
            break
    if not chosen:
        raise RuntimeError('Node.js latest-v22.x 校验文件中找不到 linux-x64.tar.gz')

    url='https://nodejs.org/download/release/latest-v22.x/'+chosen
    archive=runtime/chosen
    download(url,archive,timeout=300,retries=8)
    actual=hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual.lower()!=expected.lower():
        raise RuntimeError(f'Node.js SHA256 校验失败: expected={expected} actual={actual}')

    temp=runtime/'node.new'
    if temp.exists(): shutil.rmtree(temp,ignore_errors=True)
    temp.mkdir(parents=True)
    with tarfile.open(archive,mode='r:gz') as tf:
        tf.extractall(temp)
    children=[x for x in temp.iterdir() if x.is_dir()]
    if len(children)!=1:
        raise RuntimeError('Node.js 压缩包目录结构异常')
    stage=runtime/'node.stage'
    if stage.exists(): shutil.rmtree(stage,ignore_errors=True)
    children[0].rename(stage)
    shutil.rmtree(temp,ignore_errors=True)
    replace_dir(stage,node_root)
    try: archive.unlink()
    except FileNotFoundError: pass

    ver=subprocess.check_output([str(node),'--version'],text=True).strip()
    if parse_version_tuple(ver) < minimum:
        raise RuntimeError(f'Node.js 版本仍过低: {ver}，最低需要 v22.22.3')
    log('Node.js 已准备: '+ver)
    return nodebin

def build_ui(source,runtime):
    nodebin=install_node(runtime)
    npm=nodebin/'npm'
    if not npm.exists(): raise RuntimeError('本地 Node.js npm 不存在')

    # fnOS 应用用户通常没有可写的 /home/<app>。
    # npm/pnpm 如果沿用系统 HOME，会尝试创建 /home/metube/.npm 并触发 EACCES。
    home=runtime/'home'
    npm_cache=runtime/'npm-cache'
    pnpm_store=runtime/'pnpm-store'
    xdg_cache=runtime/'xdg-cache'
    xdg_config=runtime/'xdg-config'
    xdg_data=runtime/'xdg-data'
    tools=runtime/'node-tools'
    for d in (home,npm_cache,pnpm_store,xdg_cache,xdg_config,xdg_data,tools):
        d.mkdir(parents=True,exist_ok=True)

    env=os.environ.copy()
    env['HOME']=str(home)
    env['USERPROFILE']=str(home)
    env['NPM_CONFIG_CACHE']=str(npm_cache)
    env['npm_config_cache']=str(npm_cache)
    env['NPM_CONFIG_PREFIX']=str(tools)
    env['npm_config_prefix']=str(tools)
    env['PNPM_HOME']=str(tools/'pnpm-home')
    env['XDG_CACHE_HOME']=str(xdg_cache)
    env['XDG_CONFIG_HOME']=str(xdg_config)
    env['XDG_DATA_HOME']=str(xdg_data)
    env['CI']='true'
    env['PATH']=str(nodebin)+':'+str(tools/'node_modules/.bin')+':'+env.get('PATH','')
    pathlib.Path(env['PNPM_HOME']).mkdir(parents=True,exist_ok=True)

    pnpm=tools/'node_modules/.bin/pnpm'
    if not pnpm.exists():
        run([str(npm),'install','--no-audit','--no-fund','--prefix',str(tools),'pnpm@10'],env=env)

    run([str(pnpm),'install','--frozen-lockfile','--store-dir',str(pnpm_store)],cwd=source/'ui',env=env)
    run([str(pnpm),'run','build'],cwd=source/'ui',env=env)
    if not (source/'ui/dist/metube').exists(): raise RuntimeError('MeTube WebUI 构建后未找到 ui/dist/metube')

def sync_python(source,runtime):
    uv=install_uv(runtime)
    env=os.environ.copy()
    env['UV_PYTHON_INSTALL_DIR']=str(runtime/'python')
    env['UV_CACHE_DIR']=str(runtime/'uv-cache')
    env['UV_PROJECT_ENVIRONMENT']=str(runtime/'venv')
    run([str(uv),'python','install','3.13'],env=env)
    run([str(uv),'sync','--frozen','--no-dev','--python','3.13'],cwd=source,env=env)
    py=runtime/'venv/bin/python'
    if not py.exists(): raise RuntimeError('Python 3.13 虚拟环境创建失败')
    return py

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--runtime',required=True); ap.add_argument('--version',required=True); ap.add_argument('--download-dir',required=True)
    a=ap.parse_args(); runtime=pathlib.Path(a.runtime); runtime.mkdir(parents=True,exist_ok=True)
    (runtime/'home').mkdir(exist_ok=True); (runtime/'state').mkdir(exist_ok=True); pathlib.Path(a.download_dir).mkdir(parents=True,exist_ok=True)
    marker=runtime/'VERSION'
    source=runtime/'source'
    py=runtime/'venv/bin/python'
    need=(not source.exists()) or (not marker.exists()) or marker.read_text(errors='ignore').strip()!=a.version
    if need:
        temp=fetch_source(runtime,a.version)
        build_ui(temp,runtime)
        py=sync_python(temp,runtime)
        install_ffmpeg(runtime,py); install_deno(runtime); install_bgutil(runtime,py)
        replace_dir(temp,source)
        marker.write_text(a.version+'\n')
    else:
        log('MeTube 程序版本未变化，复用现有源码和 Python 环境。')
        install_ffmpeg(runtime,py); install_deno(runtime)
    # quick import check
    py=runtime/'venv/bin/python'
    run([str(py),'-c','import aiohttp,socketio,yt_dlp,mutagen,curl_cffi,watchfiles; print("python deps ok")'])
    log('MeTube 原生运行环境准备完成。')

if __name__=='__main__': main()
