"""Fail-closed patch for reviewed npm history adapters. No database access."""
import hashlib
from pathlib import Path

PATCH_ID = 'history-reasoning-classification-v2'
# The 0.8.14 message-format + context-history region is pinned as well as
# individual edit sites: a changed projection/cursor implementation needs review.
REGION_0814_SHA256 = '5561e7086dd6e2768902104c98041bcd40bf26f24106058482967d5926963086'
HELPER = '''const ekkoEmptyHistoryWarnings=new Set();function ekkoWarnEmptyHistory(session,message,parsed,logger){const present=v=>typeof v==="string"?v.trim().length>0:Array.isArray(v)?v.length>0:v!==null&&typeof v==="object"&&Object.keys(v).length>0;const reasoning=m=>m&&([m.reasoning,m.reasoning_content,m.reasoning_details].some(present)||(Array.isArray(m.content)&&m.content.some(b=>b?.type==="thinking"&&present(b.thinking))));if(reasoning(message)||reasoning(parsed))return;const key=JSON.stringify([String(session),String(message.id??"unknown")]);if(ekkoEmptyHistoryWarnings.has(key))return;if(ekkoEmptyHistoryWarnings.size>=1024)ekkoEmptyHistoryWarnings.delete(ekkoEmptyHistoryWarnings.values().next().value);ekkoEmptyHistoryWarnings.add(key);logger.warn("[chat-run-socket] skipped genuinely empty assistant message %s in session %s",message.id??"unknown",session)}'''


def apply(package):
    target = Path(package) / 'dist/server/index.js'
    text = target.read_text()
    if 'function ekkoWarnEmptyHistory(' in text:
        raise RuntimeError('History patch already applied; refusing double patch')
    # Recognize all signatures, including duplicated ones, before selecting.
    anchors = ('function t8e(t){', 'function W8e(t){', 'function Frt(t,e,r={}){')
    if sum(text.count(anchor) for anchor in anchors) != 1:
        raise RuntimeError('Upstream history code changed; expected one reviewed history anchor')
    anchor = next(a for a in anchors if a in text)
    modern = anchor == anchors[2]
    if modern:
        start = text.find('function lts(')
        end = text.find('var Z$=', start)
        if start < 0 or end < start or hashlib.sha256(text[start:end].encode()).hexdigest() != REGION_0814_SHA256:
            raise RuntimeError('Upstream 0.8.14 history region changed; review before publishing')
        insertion = 'function lts('
        logger = 'X'
        load_call = 'ekkoWarnEmptyHistory(e,n,i,X)'
    else:
        insertion = anchor
        logger = 'C'
        load_call = 'ekkoWarnEmptyHistory(e,n,void 0,C)'
    edits = [
        (insertion, HELPER + insertion),
        (logger + '.warn("[chat-run-socket] skipped empty assistant message %s while loading session %s",n.id,e)', load_call),
        (logger + '.warn("[chat-run-socket] skipped empty assistant message while building history for session %s",t)',
         'ekkoWarnEmptyHistory(t,o,void 0,' + logger + ')'),
    ]
    # Validate every site before writing anything. Never fall back to a fuzzy edit.
    for old, _ in edits:
        if text.count(old) != 1:
            raise RuntimeError('Upstream history code changed; review patch before publishing')
    for old, new in edits:
        text = text.replace(old, new, 1)
    target.write_text(text)
    print('Applied ' + PATCH_ID + '; message filtering and context projection unchanged', flush=True)


if __name__ == '__main__':
    import sys
    apply(sys.argv[1])
