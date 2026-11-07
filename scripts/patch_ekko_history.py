"""Strict patch for reviewed npm history adapters. No database access."""
import hashlib
from pathlib import Path

PATCH_ID = 'history-reasoning-classification-v3'
REGION_0814_SHA256 = '5561e7086dd6e2768902104c98041bcd40bf26f24106058482967d5926963086'
REGION_0816_SHA256 = 'f9d25c57cf9e1310d0d2ee6d8bf0a0c2baec717341126e28081d33530f752174'
HELPER = '''const ekkoEmptyHistoryWarnings=new Set();function ekkoWarnEmptyHistory(session,message,parsed,logger){const present=v=>typeof v==="string"?v.trim().length>0:Array.isArray(v)?v.length>0:v!==null&&typeof v==="object"&&Object.keys(v).length>0;const reasoning=m=>m&&([m.reasoning,m.reasoning_content,m.reasoning_details].some(present)||(Array.isArray(m.content)&&m.content.some(b=>b?.type==="thinking"&&present(b.thinking))));if(reasoning(message)||reasoning(parsed))return;const key=JSON.stringify([String(session),String(message.id??"unknown")]);if(ekkoEmptyHistoryWarnings.has(key))return;if(ekkoEmptyHistoryWarnings.size>=1024)ekkoEmptyHistoryWarnings.delete(ekkoEmptyHistoryWarnings.values().next().value);ekkoEmptyHistoryWarnings.add(key);logger.warn("[chat-run-socket] skipped genuinely empty assistant message %s in session %s",message.id??"unknown",session)}'''
LOAD_WARNING = '.warn("[chat-run-socket] skipped empty assistant message %s while loading session %s",n.id,e)'
BUILD_WARNING = '.warn("[chat-run-socket] skipped empty assistant message while building history for session %s",t)'


class UnsupportedHistoryLayout(RuntimeError):
    """Preflight found no reviewed layout; the target has NOT been written."""


def apply(package):
    target = Path(package) / 'dist/server/index.js'
    text = target.read_text()
    # Partial patches are errors too, not an unsupported official bundle.
    if 'ekkoWarnEmptyHistory' in text or 'ekkoEmptyHistoryWarnings' in text:
        raise RuntimeError('History patch already or partially applied; refusing to continue')
    # Minified names are NOT identities: 0.8.16 reuses W8e for a sleep helper.
    # A layout must match its boundaries, logger and both exact edit sites.
    layouts = [
        ('0.7.38', 'function t8e(t){', 'function t8e(t){', None, None, 'C'),
        ('0.7.39', 'function W8e(t){', 'function W8e(t){', None, None, 'C'),
        ('0.8.14', 'function Frt(t,e,r={}){', 'function lts(', 'var Z$=', REGION_0814_SHA256, 'X'),
        ('0.8.16', 'function Mrt(t,e,r={}){', 'function wWr(', 'var R$=', REGION_0816_SHA256, 'X'),
    ]
    candidates = [layout for layout in layouts
                  if layout[1] in text and layout[2] in text
                  and text.count(layout[5] + LOAD_WARNING) == 1
                  and text.count(layout[5] + BUILD_WARNING) == 1]
    if len(candidates) != 1:
        raise UnsupportedHistoryLayout('Upstream history code changed; expected one reviewed history layout')
    version, anchor, insertion, end_marker, expected, logger = candidates[0]
    if text.count(anchor) != 1 or text.count(insertion) != 1:
        raise UnsupportedHistoryLayout('Upstream history code changed; duplicated history boundary')
    modern = expected is not None
    if modern:
        start = text.index(insertion)
        end = text.find(end_marker, start)
        if text.count(end_marker) != 1 or end < start or hashlib.sha256(text[start:end].encode()).hexdigest() != expected:
            raise UnsupportedHistoryLayout(f'Upstream {version} history region changed; review before patching')
    load_call = f'ekkoWarnEmptyHistory(e,n,{"i" if modern else "void 0"},{logger})'
    edits = [
        (insertion, HELPER + insertion),
        (logger + LOAD_WARNING, load_call),
        (logger + BUILD_WARNING, f'ekkoWarnEmptyHistory(t,o,void 0,{logger})'),
    ]
    # Validate EVERY site before writing. Never fall back to a fuzzy edit.
    for old, _ in edits:
        count = text.count(old)
        if count != 1:
            raise UnsupportedHistoryLayout(f'Upstream history code changed; edit site count={count}: {old}')
    for old, new in edits:
        text = text.replace(old, new, 1)
    target.write_text(text)
    print(f'Applied {PATCH_ID} for reviewed {version}; message filtering and context projection unchanged', flush=True)


if __name__ == '__main__':
    import sys
    apply(sys.argv[1])
