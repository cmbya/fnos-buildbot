"""Fail-closed patch for npm 0.7.38/0.7.39 history adapters. No database access."""
from pathlib import Path

HELPER = '''const ekkoEmptyHistoryWarnings=new Set();function ekkoWarnEmptyHistory(session,message){const present=v=>typeof v==="string"?v.trim().length>0:Array.isArray(v)&&v.length>0;if([message.reasoning,message.reasoning_content,message.reasoning_details].some(present))return;const key=String(session)+":"+String(message.id??"unknown");if(ekkoEmptyHistoryWarnings.has(key))return;if(ekkoEmptyHistoryWarnings.size>=1024)ekkoEmptyHistoryWarnings.delete(ekkoEmptyHistoryWarnings.values().next().value);ekkoEmptyHistoryWarnings.add(key);C.warn("[chat-run-socket] skipped genuinely empty assistant message %s in session %s",message.id??"unknown",session)}'''


def apply(package):
    target = Path(package) / 'dist/server/index.js'
    text = target.read_text()
    # Reviewed bundle signatures; reject unknown or ambiguous layouts.
    anchors = [anchor for anchor in ('function t8e(t){', 'function W8e(t){')
               if text.count(anchor) == 1]
    if len(anchors) != 1:
        raise RuntimeError('Upstream history code changed; expected one reviewed history anchor')
    anchor = anchors[0]
    edits = [
        (anchor, HELPER + anchor),
        ('C.warn("[chat-run-socket] skipped empty assistant message %s while loading session %s",n.id,e)', 'ekkoWarnEmptyHistory(e,n)'),
        ('C.warn("[chat-run-socket] skipped empty assistant message while building history for session %s",t)', 'ekkoWarnEmptyHistory(t,o)'),
    ]
    if 'function ekkoWarnEmptyHistory(' in text:
        raise RuntimeError('History patch already applied; refusing double patch')
    for old, new in edits:
        if text.count(old) != 1:
            raise RuntimeError('Upstream history code changed; review patch before publishing')
        text = text.replace(old, new, 1)
    target.write_text(text)
    print('Applied history classification/log dedup patch; message filtering unchanged', flush=True)


if __name__ == '__main__':
    import sys
    apply(sys.argv[1])
