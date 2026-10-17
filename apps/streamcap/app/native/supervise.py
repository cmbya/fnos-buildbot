"""Forward one shutdown signal, reap the server, and record its exit status."""
import os
from pathlib import Path
import signal
import subprocess
import sys

child = subprocess.Popen(sys.argv[1:], start_new_session=True)
forwarded = False

def stop(signum, _):
    global forwarded
    if not forwarded and child.poll() is None:
        forwarded = True
        os.killpg(child.pid, signum)

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
code = child.wait()
Path(os.environ['STREAMCAP_EXIT_FILE']).write_text(str(code))
print(f'StreamCap shutdown exit={code}', flush=True)
sys.exit(code if code >= 0 else 128 - code)
