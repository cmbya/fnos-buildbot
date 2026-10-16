#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile

def main() -> int:
    from offline import install
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--runtime', required=True)
    p.add_argument('--video', required=True)
    p.add_argument('--appdest', required=True)
    p.add_argument('--back-port', type=int, default=18010)
    a = p.parse_args()
    install(Path(a.runtime).resolve(), Path(a.video).resolve(), Path(a.appdest).resolve(), a.back_port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
