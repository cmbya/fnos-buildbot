"""Run actual patched Login/init/interceptor JavaScript using Node, no credentials."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from patch_bililive_login import patch

source=Path(sys.argv[1])
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    relative=Path('packages/app/src/renderer/src')
    for name in ['pages/Login/index.vue','apis/request.ts']:
        target=root/relative/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source/relative/name,target)
    patch(root)
    login=(root/relative/'pages/Login/index.vue').read_text()
    request=(root/relative/'apis/request.ts').read_text()
    initializer=login.split('api.value =\n')[1].split('// key.value')[0]
    initializer=initializer.replace('import.meta.env.VITE_DEFAULT_SERVER','""')
    interceptor=request.split('api.interceptors.request.use(\n  (config) => {')[1].split('\n  },')[0]
    check=f'''const assert=require('node:assert/strict');
const storage=new Map([['api','http://nas:18010'],['key','old-secret']]);
const window={{location:{{origin:'https://nas.example:3000'}},localStorage:{{getItem:k=>storage.get(k)}}}};
const api={{value:''}};api.value={initializer}
assert.equal(api.value,window.location.origin);
const intercept=config=>{{{interceptor}}};
const explicit=intercept({{url:'https://nas.example:3000/common/version',headers:{{Authorization:'new-secret'}}}});
assert.equal(explicit.headers.Authorization,'new-secret');
assert.equal(explicit.baseURL,undefined);
const normal=intercept({{url:'/common/version',headers:{{}}}});
assert.equal(normal.headers.Authorization,'old-secret');
assert.equal(normal.baseURL,'http://nas:18010');
console.log('LOGIN PASS same-origin incl HTTPS, fresh key overrides stale cache, explicit URL preserved, normal authenticated requests preserved');'''
    subprocess.run(['node','-e',check],check=True)
    assert 'window.location.reload()' not in login
    assert 'window.localStorage.removeItem("api")' not in login
    try:patch(root)
    except RuntimeError:pass
    else:raise AssertionError('Repeated patch must fail closed')
    print('PATCH PASS reload loop removed; repeated/drifted patch rejected')
