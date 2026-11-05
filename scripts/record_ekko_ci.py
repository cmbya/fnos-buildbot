"""Persist bounded cloud CI evidence for GitHub MCP inspection; no credentials logged."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

repository = os.environ['GITHUB_REPOSITORY']
run_id = os.environ['GITHUB_RUN_ID']
headers = {'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
base = 'https://api.github.com/repos/' + repository


def api(path):
    with urllib.request.urlopen(urllib.request.Request(base + path, headers=headers), timeout=60) as r:
        return json.load(r)


report = {'run_url': f'https://github.com/{repository}/actions/runs/{run_id}', 'commit': os.environ['GITHUB_SHA']}
if '--failure' in sys.argv:
    jobs = api(f'/actions/runs/{run_id}/jobs?per_page=100')['jobs']
    report['status'] = 'failure'
    report['jobs'] = [{'name': j['name'], 'conclusion': j['conclusion'], 'steps': [{'name': s['name'], 'conclusion': s['conclusion']} for s in j.get('steps', [])]} for j in jobs]
    for job in jobs:
        if job['conclusion'] != 'failure':
            continue
        try:
            req = urllib.request.Request(base + f'/actions/jobs/{job["id"]}/logs', headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r:
                text = r.read().decode(errors='replace')
            # Never persist auth headers, generated passwords, tokens or keys.
            lines = [line for line in text.splitlines() if not re.search(r'password|authorization|api.?key|token|secret|bearer', line, re.I)]
            report.setdefault('failure_tails', {})[job['name']] = '\n'.join(lines[-100:])[-18000:]
        except urllib.error.HTTPError as e:
            report.setdefault('log_errors', []).append(e.code)
else:
    file = Path('artifacts/Ekko-0.8.16-x86.fpk')
    report.update(status='published', artifact=file.name, size=file.stat().st_size, sha256=hashlib.sha256(file.read_bytes()).hexdigest(), assets=json.loads(Path('release-assets.json').read_text())['assets'])
path = '/contents/docs/ekko-ci-result.json'
try:
    sha = api(path)['sha']
except urllib.error.HTTPError as e:
    if e.code != 404:
        raise
    sha = None
body = {'message': 'chore(ekko): record verified cloud build outcome', 'branch': 'main', 'content': base64.b64encode((json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode()).decode()}
if sha:
    body['sha'] = sha
req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers=headers, method='PUT')
with urllib.request.urlopen(req, timeout=60) as r:
    result = json.load(r)
print('Evidence commit:', result['commit']['sha'])
