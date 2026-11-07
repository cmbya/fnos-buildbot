"""Optional warning-only patch policy. Core/runtime failures remain fatal."""
import hashlib
import subprocess
from pathlib import Path

from patch_ekko_history import PATCH_ID, UnsupportedHistoryLayout, apply


def prepare_history(package, node, env=None):
    """Return auditable patch state, after syntax/required patch regressions.

    Only a typed, pre-write unsupported-layout decision can use upstream code.
    Do not catch regression, filesystem, dependency or unexpected patch errors.
    """
    target = Path(package) / 'dist/server/index.js'
    before = target.read_bytes()
    original_sha = hashlib.sha256(before).hexdigest()
    try:
        apply(package)
    except UnsupportedHistoryLayout as error:
        if target.read_bytes() != before:
            raise RuntimeError('Unsupported history patch modified the official bundle') from error
        state = {
            'id': PATCH_ID,
            'status': 'skipped_unsupported',
            'reason': 'No exact reviewed history layout; official bundle preserved byte-for-byte',
            'regression': 'not_applicable_unmodified_upstream',
        }
        print('::warning::Optional Ekko history warning patch not applied: unreviewed layout. '
              'Using unchanged official code; repeated/false empty-message warnings may remain. '
              'Native, lifecycle and FPK checks are still mandatory.', flush=True)
    else:
        state = {'id': PATCH_ID, 'status': 'applied', 'regression': 'pending'}
    # Invalid JavaScript is fatal even when no local patch was applied.
    subprocess.run([str(node), '--check', str(target)], env=env, check=True)
    if state['status'] == 'applied':
        subprocess.run([str(node), str(Path(__file__).with_name('test_ekko_history.cjs')),
                        str(target)], env=env, check=True)
        state['regression'] = 'passed'
    after = target.read_bytes()
    if state['status'] == 'skipped_unsupported' and after != before:
        raise RuntimeError('Unpatched official history bundle changed during verification')
    state.update(original_bundle_sha256=original_sha,
                 packaged_bundle_sha256=hashlib.sha256(after).hexdigest(),
                 syntax_check='passed')
    return state


def patch_metadata(history):
    """Only actually applied and verified patches belong in BUILD.json patches."""
    if history['status'] == 'applied':
        if history['regression'] != 'passed':
            raise RuntimeError('History patch has not passed regression')
        patches = [history['id']]
    elif history['status'] == 'skipped_unsupported':
        if history['original_bundle_sha256'] != history['packaged_bundle_sha256']:
            raise RuntimeError('Skipped history patch does not preserve the official bundle')
        patches = []
    else:
        raise RuntimeError('Unknown history patch state')
    return {'patches': patches, 'history_patch': history}
