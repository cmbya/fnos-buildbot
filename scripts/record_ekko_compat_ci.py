"""Record this no-publish CI run using its own Actions permissions.

Only bounded error/traceback lines are retained; no service logs, dependency
inventories, credentials or complete command environments are persisted.
"""
import base64
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request


def main():
    repository = os.environ['GITHUB_REPOSITORY']
    run_id = os.environ['GITHUB_RUN_ID']
    base = 'https://api.github.com/repos/' + repository
    headers = {'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
               'Accept': 'application/vnd.github+json'}

    def api(path):
        with urllib.request.urlopen(urllib.request.Request(base + path, headers=headers), timeout=60) as response:
            return json.load(response)

    regression = os.environ['REGRESSION_RESULT']
    build = os.environ['BUILD_RESULT']
    report = {
        'run_url': f'https://github.com/{repository}/actions/runs/{run_id}',
        'commit': os.environ['GITHUB_SHA'],
        'status': 'verified' if regression == build == 'success' else 'failure',
        'regression': regression,
        'build': build,
        'published': False,
        'app': json.loads(os.environ.get('APP_JSON') or '{}'),
    }
    jobs = api(f'/actions/runs/{run_id}/jobs?per_page=100')['jobs']
    report['jobs'] = [{'name': job['name'], 'conclusion': job['conclusion'],
                       'steps': [{'name': step['name'], 'conclusion': step['conclusion']}
                                 for step in job.get('steps', [])]}
                      for job in jobs if job['name'] != 'report']
    for name in ['ekko-history.json', 'ekko-build-metadata.json']:
        file = Path('evidence') / name
        if file.is_file():
            report[name] = json.loads(file.read_text())
    report['artifacts'] = [{key: artifact[key] for key in ['name', 'size_in_bytes', 'expired', 'digest'] if key in artifact}
                           for artifact in api(f'/actions/runs/{run_id}/artifacts')['artifacts']]
    if report['status'] == 'verified' and 'ekko-build-metadata.json' not in report:
        raise RuntimeError('Successful build is missing required patch provenance evidence')
    # Failure diagnostics are read ONLY within this authorized cloud run.
    # Whitelist error lines, rather than copying broad logs/auth material.
    sensitive = re.compile(r'password|authorization|api.?key|token|secret|bearer|https?://[^\s]+@', re.I)
    diagnostic = re.compile(r'Traceback \(most recent|File ".*", line \d+|(?:RuntimeError|AssertionError|HTTPError|TypeError|ReferenceError|Error|CalledProcessError):|npm error|EKKO BUILD STAGE:|Process completed with exit code')
    for job in jobs:
        if job['conclusion'] != 'failure':
            continue
        try:
            request = urllib.request.Request(base + f'/actions/jobs/{job["id"]}/logs', headers=headers)
            with urllib.request.urlopen(request, timeout=60) as response:
                text = response.read(8 * 1024 * 1024).decode(errors='replace')
            lines = [line[:1000] for line in text.splitlines()
                     if diagnostic.search(line) and not sensitive.search(line)]
            report.setdefault('failure_diagnostics', {})[job['name']] = lines[-50:]
        except urllib.error.HTTPError as error:
            report.setdefault('log_errors', []).append(error.code)
    path = '/contents/docs/ekko-compat-ci.json'
    body = {'message': 'chore(ekko): record no-publish compatibility verification',
            'branch': 'main',
            'content': base64.b64encode((json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode()).decode()}
    try:
        body['sha'] = api(path)['sha']
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    request = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers=headers, method='PUT')
    with urllib.request.urlopen(request, timeout=60) as response:
        result = json.load(response)
    print('No-publish CI evidence commit:', result['commit']['sha'])
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
        summary.write('## Ekko 上游兼容验证\n\n')
        summary.write(f'- 回归：{regression}\n- FPK 构建：{build}\n- 发布：未执行\n')
        history = report.get('ekko-history.json', {})
        summary.write(f'- 可选历史告警补丁：{history.get("status", "未完成")}\n')


if __name__ == '__main__':
    main()
