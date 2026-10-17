#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import py_compile
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "scripts/streamcap-native7-reference.sh"


def extract_patch_body(text: str) -> str:
    m = re.search(
        r"apply_native3_patch\(\) \{\n"
        r"  \"\$VENV/bin/python\" - \"\$SOURCE\" <<'PY'\n"
        r"(.*?)\nPY\n\}",
        text,
        re.S,
    )
    if not m:
        raise RuntimeError("cannot extract runtime patch body")
    return m.group(1)


def write_fixture(root: Path) -> None:
    (root / "app/utils").mkdir(parents=True)
    (root / "app/core/recording").mkdir(parents=True)
    (root / "app/ui/components/business").mkdir(parents=True)

    (root / "app/utils/utils.py").write_text(
        '''from datetime import datetime, time, timedelta, timezone
# fnOS native3: deterministic UTC+8 monitor clock
_FNOS_MONITOR_TZ = timezone(timedelta(hours=8))
def fnos_now():
    return datetime.now(_FNOS_MONITOR_TZ).replace(tzinfo=None)
def is_current_time_within_range(s): return True
def is_time_interval_exceeded(a,b): return True
''', encoding="utf-8")

    (root / "app/core/recording/record_manager.py").write_text(
        '''import asyncio
from datetime import datetime
class RecordingStatus:
    NOT_IN_SCHEDULED_CHECK = "not"
# fnOS native3: scheduled-monitor diagnostics
class RecordingManager:
    async def check_all_live_status(self):
        # fnOS native4: scheduled window transition re-arm
        for recording in self.recordings:
            if not recording.monitor_status or recording.is_recording:
                continue
    # fnOS native5: resilient web scheduler
    _periodic_task_running = False
    _periodic_task = None
    _periodic_manager = None
    async def setup_periodic_live_check(self, interval: int = 180):
        pass
    async def check_if_live(self, recording):
        if True:
            self.start_update(recording)
            self.app.page.run_task(
                recorder.start_recording,
                stream_info,
            )
    @staticmethod
    def start_update(recording):
        recording.is_recording = True
    def stop_recording(self, recording, manually_stopped=True):
        pass
    async def get_scheduled_time_range(self, a, b):
        return []
''', encoding="utf-8")

    (root / "app/core/recording/stream_manager.py").write_text(
        '''import asyncio
import time
# fnOS native3: transient recording recovery
class LiveStreamRecorder:
    def _get_output_dir(self, stream_info):
        self.app.page.run_task(self.app.record_manager.persist_recordings)
        return "x"
    async def start_recording(self, stream_info):
        record_url = "x"
        save_path = "x"
        ffmpeg_command = []
        if use_direct_download:
            self.app.page.run_task(
                self.start_direct_download,
                stream_info.anchor_name,
                self.live_url,
                record_url,
                save_path,
                self.save_format,
                self.user_config.get("custom_script_command"),
            )
        else:
            self.app.page.run_task(
                self.start_ffmpeg,
                stream_info.anchor_name,
                self.live_url,
                record_url,
                ffmpeg_command,
                self.save_format,
                self.user_config.get("custom_script_command"),
            )
    async def recheck_live_status(self):
        if True:
            self.app.page.run_task(
                self.app.record_manager.check_if_live,
                self.recording,
            )
    async def start_ffmpeg(self):
        pass
''', encoding="utf-8")

    (root / "app/ui/components/business/recording_card.py").write_text(
        "# fnOS native4: re-arm after scheduled settings edit\nx = 1\n",
        encoding="utf-8",
    )
    (root / "main.py").write_text(
        "# fnOS native5: always rebind web scheduler\nx = 1\n",
        encoding="utf-8",
    )


def behavior_test(record_manager_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("fnos_native7_rm", record_manager_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load patched fixture")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Utils:
        in_range = True
        @staticmethod
        def is_current_time_within_range(_): return Utils.in_range
        @staticmethod
        def is_time_interval_exceeded(_, __): return True
        class Now:
            def strftime(self, _): return "2026-08-19 20:00:00"
        @staticmethod
        def fnos_now(): return Utils.Now()

    class Logger:
        def __getattr__(self, _): return lambda *args, **kwargs: None

    module.utils = Utils
    module.logger = Logger()

    class Recording:
        def __init__(self):
            self.monitor_status = True
            self.is_recording = False
            self.scheduled_recording = True
            self.scheduled_start_time = "20:00:00"
            self.monitor_hours = "2"
            self.rec_id = "rec-1"
            self.url = "https://example.invalid/live"
            self.detection_time = None
            self.loop_time_seconds = 300
            self.showed_checking_status = False
            self.force_stop = False
            self.is_live = False
            self.is_checking = False
            self.status_info = None
            self.start_time = None
            self.stopping_in_progress = False
            self.manually_stopped = False

    class Manager(module.RecordingManager):
        def __init__(self, recording):
            self.recordings = [recording]
            self.active_recorders = {}
            self.check_calls = 0
            self.stop_calls = 0
        async def get_scheduled_time_range(self, *_):
            return ["20:00:00~22:00:00"]
        async def check_if_live(self, _):
            self.check_calls += 1
        def stop_recording(self, recording, manually_stopped=True):
            self.stop_calls += 1
            recording.is_recording = False
            recording.manually_stopped = manually_stopped

    async def run():
        rec = Recording()
        manager = Manager(rec)
        Utils.in_range = True
        await manager.check_all_live_status()
        await asyncio.sleep(0)
        assert manager.check_calls == 1

        rec.is_recording = True
        rec.detection_time = None
        await manager.check_all_live_status()
        await asyncio.sleep(0)
        assert rec.is_recording is False
        assert manager.check_calls >= 2

        rec.is_recording = True
        manager.active_recorders[rec.rec_id] = object()
        Utils.in_range = False
        await manager.check_all_live_status()
        assert manager.stop_calls == 1
        assert rec.status_info == module.RecordingStatus.NOT_IN_SCHEDULED_CHECK

    asyncio.run(run())


def main() -> int:
    subprocess.run(["bash", "-n", str(MAIN)], check=True)
    main_text = MAIN.read_text(encoding="utf-8")
    body = extract_patch_body(main_text)

    with tempfile.TemporaryDirectory(prefix="streamcap-native7-check-") as td:
        temp = Path(td)
        patch_file = temp / "runtime_patch.py"
        patch_file.write_text(body, encoding="utf-8")
        py_compile.compile(str(patch_file), doraise=True)

        fixture = temp / "source"
        write_fixture(fixture)
        subprocess.run([sys.executable, str(patch_file), str(fixture)], check=True)

        rm_path = fixture / "app/core/recording/record_manager.py"
        sm_path = fixture / "app/core/recording/stream_manager.py"
        py_compile.compile(str(rm_path), doraise=True)
        py_compile.compile(str(sm_path), doraise=True)

        rm_text = rm_path.read_text(encoding="utf-8")
        sm_text = sm_path.read_text(encoding="utf-8")

        for token in [
            "# fnOS native7: scheduled recording lifecycle",
            "[fnOS native7 schedule] REAL STOP",
            "[fnOS native7 schedule] FAKE STATE detected",
            "# fnOS native7: server-side recorder dispatch",
            "recorder.start_recording(stream_info)",
        ]:
            if token not in rm_text:
                raise RuntimeError(f"record_manager missing: {token}")

        for token in [
            "# fnOS native7: server-side recording engine",
            "[fnOS native7 recorder] dispatch ffmpeg",
            "self.start_ffmpeg(",
            "asyncio.create_task(self.app.record_manager.persist_recordings())",
        ]:
            if token not in sm_text:
                raise RuntimeError(f"stream_manager missing: {token}")

        behavior_test(rm_path)

    print("✅ native7 runtime patch syntax: OK")
    print("✅ scheduled ENTER -> check: OK")
    print("✅ fake is_recording -> reset/retry: OK")
    print("✅ scheduled EXIT + active recorder -> REAL STOP: OK")
    print("✅ recording engine detached from Flet page: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
