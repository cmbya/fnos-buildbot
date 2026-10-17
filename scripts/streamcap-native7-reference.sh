#!/bin/bash
set -u

RUNTIME="${TRIM_PKGVAR}/native-runtime"
SOURCE="$RUNTIME/source"
VENV="$RUNTIME/venv"
PID_FILE="${TRIM_PKGVAR}/streamcap.pid"
PORT="${TRIM_SERVICE_PORT:-6006}"
DEFAULT_DOWNLOADS="${TRIM_DATA_SHARE_PATHS%%:*}"
PATH_FILE="${TRIM_PKGETC}/recording_path.conf"

recording_path() {
  local p=""
  if [ -s "$PATH_FILE" ]; then
    IFS= read -r p < "$PATH_FILE" || true
  fi
  if [ -z "$p" ] && [ -n "${TRIM_DATA_ACCESSIBLE_PATHS:-}" ]; then
    p="${TRIM_DATA_ACCESSIBLE_PATHS%%:*}"
  fi
  if [ -z "$p" ]; then
    p="$DEFAULT_DOWNLOADS"
  fi
  printf '%s' "$p"
}

DOWNLOADS="$(recording_path)"

# fnOS native7:
# 将日志放到已授权的录像目录，用户可以直接用飞牛文件管理器查看。
LOG_DIR="${DOWNLOADS}/StreamCap-Logs"
LOG_FILE="${LOG_DIR}/streamcap-fnos.log"
LOG_OLD="${LOG_FILE}.1"

export PATH="$RUNTIME/ffmpeg/bin:/var/apps/python312/target/bin:/var/apps/nodejs_v22/target/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export PLATFORM=web
export HOST=0.0.0.0
export PORT
export TZ=Asia/Shanghai
export PYTHONUNBUFFERED=1

is_running() {
  if [ -f "$PID_FILE" ]; then
    pid="$(head -n 1 "$PID_FILE" | tr -d '[:space:]')"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    rm -f "$PID_FILE"
  fi
  return 1
}

repair_download_link() {
  [ -n "$DOWNLOADS" ] || return 1
  mkdir -p "$DOWNLOADS" || return 1
  mkdir -p "$LOG_DIR" || return 1

  # fnOS native7: 日志超过 10 MiB 时保留一份旧日志，避免无限增长。
  if [ -f "$LOG_FILE" ]; then
    LOG_SIZE="$(wc -c < "$LOG_FILE" 2>/dev/null || echo 0)"
    if [ "${LOG_SIZE:-0}" -ge 10485760 ]; then
      rm -f "$LOG_OLD"
      mv "$LOG_FILE" "$LOG_OLD"
    fi
  fi

  if [ -L "$SOURCE/downloads" ]; then
    current="$(readlink "$SOURCE/downloads" 2>/dev/null || true)"
    if [ "$current" != "$DOWNLOADS" ]; then
      rm -f "$SOURCE/downloads"
      ln -s "$DOWNLOADS" "$SOURCE/downloads"
    fi
  elif [ -e "$SOURCE/downloads" ]; then
    if [ -d "$SOURCE/downloads" ] && [ -z "$(ls -A "$SOURCE/downloads" 2>/dev/null)" ]; then
      rmdir "$SOURCE/downloads"
      ln -s "$DOWNLOADS" "$SOURCE/downloads"
    fi
  else
    ln -s "$DOWNLOADS" "$SOURCE/downloads"
  fi
}

apply_native3_patch() {
  "$VENV/bin/python" - "$SOURCE" <<'PY'
from __future__ import annotations

from pathlib import Path
import py_compile
import re
import sys

source = Path(sys.argv[1]).resolve()

utils_path = source / "app/utils/utils.py"
record_manager_path = source / "app/core/recording/record_manager.py"
stream_manager_path = source / "app/core/recording/stream_manager.py"
recording_card_path = source / "app/ui/components/business/recording_card.py"
main_py_path = source / "main.py"

for path in (
    utils_path,
    record_manager_path,
    stream_manager_path,
    recording_card_path,
    main_py_path,
):
    if not path.is_file():
        raise SystemExit(f"[fnOS native4] missing upstream file: {path}")


def write_if_changed(path: Path, old: str, new: str) -> None:
    if new == old:
        return
    path.write_text(new, encoding="utf-8")
    print(f"[fnOS native3] patched: {path.relative_to(source)}", flush=True)


# ================================================================
# 1) 定时监听统一使用 UTC+8。
# ================================================================
text = utils_path.read_text(encoding="utf-8")
old_text = text

if "# fnOS native3: deterministic UTC+8 monitor clock" not in text:
    text = text.replace(
        "from datetime import datetime, time, timedelta",
        "from datetime import datetime, time, timedelta, timezone",
        1,
    )

    start = text.find("def is_time_greater_than_now(time_str: str) -> bool:")
    end_marker = "    return time_diff.total_seconds() > interval_seconds"
    end = text.find(end_marker, start)

    if start < 0 or end < 0:
        print(
            "[fnOS native3] WARN: monitor time helpers changed upstream; "
            "skip UTC+8 helper patch",
            flush=True,
        )
    else:
        end += len(end_marker)

        replacement = """# fnOS native3: deterministic UTC+8 monitor clock
_FNOS_MONITOR_TZ = timezone(timedelta(hours=8))


def fnos_now() -> datetime:
    return datetime.now(_FNOS_MONITOR_TZ).replace(tzinfo=None)


def is_time_greater_than_now(time_str: str) -> bool:
    time_format: str = "%H:%M:%S"
    input_time: time = datetime.strptime(time_str, time_format).time()
    current_time: time = fnos_now().time()
    return input_time > current_time


def is_current_time_within_range(time_range_str: str):
    start_str, end_str = time_range_str.split("~")
    time_format = "%H:%M:%S"
    start_time = datetime.strptime(start_str.strip(), time_format).time()
    end_time = datetime.strptime(end_str.strip(), time_format).time()
    now = fnos_now().time()

    # 上游本来就支持跨午夜，这里只把“当前时间”固定为 UTC+8。
    if end_time < start_time:
        return now >= start_time or now <= end_time
    return start_time <= now <= end_time


def is_time_interval_exceeded(last_check_time, interval_seconds=60):
    now_dt = fnos_now()
    now = now_dt.time()

    if not last_check_time or last_check_time > now:
        return True

    last_check_datetime = datetime.combine(now_dt.date(), last_check_time)
    current_datetime = datetime.combine(now_dt.date(), now)
    time_diff = current_datetime - last_check_datetime
    return time_diff.total_seconds() > interval_seconds"""

        text = text[:start] + replacement + text[end:]

write_if_changed(utils_path, old_text, text)

has_fnos_clock = "def fnos_now()" in text

if not has_fnos_clock:
    print(
        "[fnOS native3] WARN: UTC+8 helper is unavailable; "
        "leave upstream scheduled clock untouched",
        flush=True,
    )


# ================================================================
# 2) RecordingManager 使用同一 UTC+8 时钟，并输出定时判断日志。
# ================================================================
text = record_manager_path.read_text(encoding="utf-8")
old_text = text

if (
    has_fnos_clock
    and "recording.detection_time = datetime.now().time()" in text
):
    text = text.replace(
        "recording.detection_time = datetime.now().time()",
        "recording.detection_time = utils.fnos_now().time()",
        1,
    )

schedule_marker = "# fnOS native3: scheduled-monitor diagnostics"

if has_fnos_clock and schedule_marker not in text:
    needle = """            if not in_scheduled:
                recording.status_info = RecordingStatus.NOT_IN_SCHEDULED_CHECK
"""

    insert = """            # fnOS native3: scheduled-monitor diagnostics
            logger.info(
                "[fnOS native3 schedule] "
                f"url={recording.url} "
                f"now={utils.fnos_now().strftime('%Y-%m-%d %H:%M:%S')} "
                f"ranges={scheduled_time_range_list} "
                f"in_range={in_scheduled}"
            )
            if not in_scheduled:
                recording.status_info = RecordingStatus.NOT_IN_SCHEDULED_CHECK
"""

    if needle in text:
        text = text.replace(needle, insert, 1)
    else:
        print(
            "[fnOS native3] WARN: scheduled block changed upstream; "
            "diagnostic log not injected",
            flush=True,
        )

write_if_changed(record_manager_path, old_text, text)


# ================================================================
# 2.5) native4：每日定时窗口切换时自动重新布防。
# ================================================================
text = record_manager_path.read_text(encoding="utf-8")
old_text = text

native4_schedule_marker = "# fnOS native4: scheduled window transition re-arm"

if native4_schedule_marker not in text:
    start = text.find("    async def check_all_live_status(self):")
    end = text.find("    _periodic_task_running = False", start)

    if start < 0 or end < 0:
        print(
            "[fnOS native4] WARN: check_all_live_status changed upstream; "
            "skip schedule transition patch",
            flush=True,
        )
    else:
        replacement = """    async def check_all_live_status(self):
        # fnOS native4: scheduled window transition re-arm
        for recording in self.recordings:
            if not recording.monitor_status or recording.is_recording:
                continue

            if recording.scheduled_recording:
                scheduled_time_range_list = await self.get_scheduled_time_range(
                    recording.scheduled_start_time,
                    recording.monitor_hours,
                ) or []

                in_scheduled = any(
                    utils.is_current_time_within_range(time_range)
                    for time_range in scheduled_time_range_list
                )

                previous_in_scheduled = getattr(
                    recording,
                    "_fnos_native4_in_scheduled",
                    None,
                )

                if in_scheduled and previous_in_scheduled is not True:
                    setattr(
                        recording,
                        "_fnos_native4_in_scheduled",
                        True,
                    )
                    recording.detection_time = None
                    recording.showed_checking_status = False

                    logger.info(
                        "[fnOS native4 schedule] "
                        f"ENTER window url={recording.url} "
                        f"now={utils.fnos_now().strftime('%Y-%m-%d %H:%M:%S')} "
                        f"ranges={scheduled_time_range_list}; "
                        "trigger immediate live check"
                    )

                    self.app.page.run_task(
                        self.check_if_live,
                        recording,
                    )
                    continue

                if not in_scheduled:
                    if previous_in_scheduled is not False:
                        logger.info(
                            "[fnOS native4 schedule] "
                            f"OUTSIDE window url={recording.url} "
                            f"now={utils.fnos_now().strftime('%Y-%m-%d %H:%M:%S')} "
                            f"ranges={scheduled_time_range_list}"
                        )

                    setattr(
                        recording,
                        "_fnos_native4_in_scheduled",
                        False,
                    )

                    if (
                        recording.status_info
                        != RecordingStatus.NOT_IN_SCHEDULED_CHECK
                    ):
                        recording.status_info = (
                            RecordingStatus.NOT_IN_SCHEDULED_CHECK
                        )
                        recording.is_live = False
                        recording.is_checking = False
                        self.app.page.run_task(
                            self.app.record_card_manager.update_card,
                            recording,
                        )

                    continue

            is_exceeded = utils.is_time_interval_exceeded(
                recording.detection_time,
                recording.loop_time_seconds,
            )

            if not recording.detection_time or is_exceeded:
                self.app.page.run_task(
                    self.check_if_live,
                    recording,
                )

"""
        text = text[:start] + replacement + text[end:]

# 有每日定时监听任务时，每 60 秒检查一次是否跨入定时窗口。
# 实际平台请求仍由 check_all_live_status 的 loop_time 控制。
if "# fnOS native4: dynamic scheduled polling interval" not in text:
    old_sleep = """                if immediate_check_on_startup:
                    await asyncio.sleep(interval)
"""
    new_sleep = """                # fnOS native4: dynamic scheduled polling interval
                if immediate_check_on_startup:
                    has_scheduled_monitor = any(
                        rec.monitor_status and rec.scheduled_recording
                        for rec in self.recordings
                    )
                    await asyncio.sleep(
                        min(interval, 60)
                        if has_scheduled_monitor
                        else interval
                    )
"""

    if old_sleep in text:
        text = text.replace(old_sleep, new_sleep, 1)
    else:
        print(
            "[fnOS native4] WARN: periodic sleep block changed upstream",
            flush=True,
        )

write_if_changed(record_manager_path, old_text, text)


# ================================================================
# 2.6) native4：编辑保存定时配置后立即重新布防。
# ================================================================
text = recording_card_path.read_text(encoding="utf-8")
old_text = text

native4_edit_marker = "# fnOS native4: re-arm after scheduled settings edit"

if native4_edit_marker not in text:
    needle = """        recording.scheduled_time_range = await self.app.record_manager.get_scheduled_time_range(
            recording.scheduled_start_time, recording.monitor_hours
        )

        await self.update_card(recording)
"""

    replacement = """        recording.scheduled_time_range = await self.app.record_manager.get_scheduled_time_range(
            recording.scheduled_start_time, recording.monitor_hours
        )

        # fnOS native4: re-arm after scheduled settings edit
        if recording.monitor_status and recording.scheduled_recording:
            recording.detection_time = None
            recording.showed_checking_status = False
            setattr(
                recording,
                "_fnos_native4_in_scheduled",
                None,
            )

            logger.info(
                "[fnOS native4 schedule] "
                f"schedule edited; re-arm url={recording.url} "
                f"start={recording.scheduled_start_time} "
                f"hours={recording.monitor_hours}"
            )

            self.app.page.run_task(
                self.app.record_manager.check_if_live,
                recording,
            )

        await self.update_card(recording)
"""

    if needle in text:
        text = text.replace(needle, replacement, 1)
    else:
        print(
            "[fnOS native4] WARN: edit_recording_callback changed upstream; "
            "skip edit re-arm patch",
            flush=True,
        )

write_if_changed(recording_card_path, old_text, text)


# ================================================================
# 2.7) native5：修复 Web 模式周期任务绑定第一浏览器会话的问题。
#
# v1.0.3:
# - main.py 只在第一个 web session 启动 periodic tasks；
# - RecordingManager 用 class bool 标记“已经启动”；
# - 周期 loop 没有异常自恢复；
# - 后续刷新/重连不会把 scheduler 重新绑定到最新 App/Page。
#
# native5:
# - 每次 Web 会话 load 都调用 start_periodic_tasks；
# - setup_periodic_live_check 幂等：
#   * 活着 -> 只 rebind 到最新 RecordingManager；
#   * 已死 -> 自动重建；
# - loop 每轮异常不会导致整个 scheduler 永久死亡。
# ================================================================

# ---- main.py：每个 web session 都重新绑定 scheduler ----
text = main_py_path.read_text(encoding="utf-8")
old_text = text

native5_main_marker = "# fnOS native5: always rebind web scheduler"

if native5_main_marker not in text:
    old_block = """        if page.web:
            global global_state
            if not global_state.periodic_tasks_started:
                global_state.periodic_tasks_started = True
                logger.info("Starting periodic tasks for the first time in web mode")
                page.run_task(app.start_periodic_tasks)
            else:
                logger.info("Periodic tasks already running in web mode, skipping initialization")
        else:
"""

    new_block = """        if page.web:
            # fnOS native5: always rebind web scheduler
            logger.info(
                "[fnOS native5 scheduler] "
                "bind/rebind periodic scheduler to current web session"
            )
            page.run_task(app.start_periodic_tasks)
        else:
"""

    if old_block in text:
        text = text.replace(old_block, new_block, 1)
    else:
        print(
            "[fnOS native5] WARN: main.py web periodic block changed upstream",
            flush=True,
        )

write_if_changed(main_py_path, old_text, text)


# ---- RecordingManager：真实 task handle + rebind + watchdog ----
text = record_manager_path.read_text(encoding="utf-8")
old_text = text

native5_scheduler_marker = "# fnOS native5: resilient web scheduler"

if native5_scheduler_marker not in text:
    start = text.find("    _periodic_task_running = False")
    end = text.find("    async def check_if_live(self, recording: Recording):", start)

    if start < 0 or end < 0:
        print(
            "[fnOS native5] WARN: periodic scheduler block changed upstream",
            flush=True,
        )
    else:
        replacement = """    # fnOS native5: resilient web scheduler
    _periodic_task_running = False
    _periodic_task = None
    _periodic_manager = None

    @classmethod
    def is_periodic_task_running(cls):
        task = getattr(cls, "_periodic_task", None)
        return bool(task is not None and not task.done())

    @classmethod
    def set_periodic_task_running(cls, value=True):
        cls._periodic_task_running = value

    async def setup_periodic_live_check(self, interval: int = 180):
        # Always point the global scheduler at the newest Web App/RecordingManager.
        RecordingManager._periodic_manager = self

        current_task = getattr(
            RecordingManager,
            "_periodic_task",
            None,
        )

        if current_task is not None and not current_task.done():
            RecordingManager._periodic_task_running = True
            self.periodic_task_started = True
            logger.info(
                "[fnOS native5 scheduler] "
                "scheduler alive; rebound to latest web session"
            )
            return

        async def periodic_check():
            logger.info(
                "[fnOS native5 scheduler] "
                "persistent periodic scheduler started"
            )

            RecordingManager._periodic_task_running = True

            try:
                while True:
                    manager = (
                        RecordingManager._periodic_manager
                        or self
                    )

                    try:
                        has_scheduled_monitor = any(
                            rec.monitor_status
                            and rec.scheduled_recording
                            for rec in manager.recordings
                        )

                        sleep_seconds = (
                            min(interval, 30)
                            if has_scheduled_monitor
                            else interval
                        )

                        immediate_check_on_startup = (
                            manager.app.settings.user_config.get(
                                "check_live_on_browser_refresh",
                                True,
                            )
                        )

                        if immediate_check_on_startup:
                            await asyncio.sleep(sleep_seconds)

                        await manager.check_free_space()

                        if manager.app.recording_enabled:
                            await manager.check_all_live_status()

                        if not immediate_check_on_startup:
                            await asyncio.sleep(sleep_seconds)

                    except asyncio.CancelledError:
                        raise

                    except Exception as exc:
                        # Never let one stale/disconnected Flet page
                        # permanently kill the NAS scheduler.
                        logger.exception(
                            "[fnOS native5 scheduler] "
                            f"periodic cycle failed but scheduler stays alive: {exc}"
                        )
                        await asyncio.sleep(10)

            finally:
                RecordingManager._periodic_task_running = False
                RecordingManager._periodic_task = None
                logger.warning(
                    "[fnOS native5 scheduler] "
                    "periodic scheduler stopped"
                )

        task = asyncio.create_task(periodic_check())

        RecordingManager._periodic_task = task
        RecordingManager._periodic_task_running = True
        self.periodic_task_started = True

        logger.info(
            "[fnOS native5 scheduler] "
            f"new scheduler task created: {id(task)}"
        )

"""
        text = text[:start] + replacement + text[end:]

# native4 check_all 里由 scheduler 触发 check_if_live 时，
# 不再经由旧 page.run_task 包一层，直接在服务端事件循环启动。
text = text.replace(
    """                    self.app.page.run_task(
                        self.check_if_live,
                        recording,
                    )
""",
    """                    asyncio.create_task(
                        self.check_if_live(recording)
                    )
""",
)

text = text.replace(
    """                self.app.page.run_task(
                    self.check_if_live,
                    recording,
                )
""",
    """                asyncio.create_task(
                    self.check_if_live(recording)
                )
""",
)

write_if_changed(record_manager_path, old_text, text)


# ================================================================
# 2.8) native7：定时窗口拥有“真正的录制生命周期”。
#
# native6 剩余问题：
# - check_all_live_status 一开始遇到 recording.is_recording 就 continue，
#   所以跨出定时窗口时不会真正停止 FFmpeg；
# - Web/Flet 会话断开后，check_if_live 可能已经执行 start_update()，
#   但 recorder.start_recording 仍通过 page.run_task 启动。
#   这会造成：is_recording=True，但 active_recorders 为空、目录没有文件；
# - stream_manager 内部启动 FFmpeg / direct downloader 也依赖 page.run_task。
#
# native7：
# - 定时窗口先于 is_recording 判断；
# - EXIT 时主动 stop_recording(..., manually_stopped=False)；
# - ENTER/窗口内检查 fake state：is_recording=True 但 active recorder 不存在；
# - 真正录制链路全部改为 asyncio.create_task，不依赖浏览器 WebSocket；
# - 清理残留 force_stop，避免下一次到点后刚启动就被旧停止标志杀掉。
# ================================================================

# ---- RecordingManager: server-side start_recording dispatch ----
text = record_manager_path.read_text(encoding="utf-8")
old_text = text

native7_dispatch_marker = "# fnOS native7: server-side recorder dispatch"

if native7_dispatch_marker not in text:
    patterns = [
        (
            re.compile(
                r'(?P<i>[ \t]+)self\.start_update\(recording\)\n'
                r'(?P=i)self\.app\.page\.run_task\(\n'
                r'(?P=i)    recorder\.start_recording,\n'
                r'(?P=i)    stream_info,\n'
                r'(?P=i)\)',
                re.M,
            ),
            lambda m: (
                f"{m.group('i')}self.start_update(recording)\n"
                f"{m.group('i')}# fnOS native7: server-side recorder dispatch\n"
                f"{m.group('i')}recording.force_stop = False\n"
                f"{m.group('i')}recording.manually_stopped = False\n"
                f"{m.group('i')}logger.info(\n"
                f"{m.group('i')}    '[fnOS native7 recorder] dispatch start_recording ' \n"
                f"{m.group('i')}    f'rec_id={{recording.rec_id}} url={{recording.url}}'\n"
                f"{m.group('i')})\n"
                f"{m.group('i')}asyncio.create_task(\n"
                f"{m.group('i')}    recorder.start_recording(stream_info)\n"
                f"{m.group('i')})"
            ),
        ),
        (
            re.compile(
                r'(?P<i>[ \t]+)self\.start_update\(recording\)\n'
                r'(?P=i)self\.app\.page\.run_task\('
                r'recorder\.start_recording,\s*stream_info\)',
                re.M,
            ),
            lambda m: (
                f"{m.group('i')}self.start_update(recording)\n"
                f"{m.group('i')}# fnOS native7: server-side recorder dispatch\n"
                f"{m.group('i')}recording.force_stop = False\n"
                f"{m.group('i')}recording.manually_stopped = False\n"
                f"{m.group('i')}logger.info(\n"
                f"{m.group('i')}    '[fnOS native7 recorder] dispatch start_recording ' \n"
                f"{m.group('i')}    f'rec_id={{recording.rec_id}} url={{recording.url}}'\n"
                f"{m.group('i')})\n"
                f"{m.group('i')}asyncio.create_task(\n"
                f"{m.group('i')}    recorder.start_recording(stream_info)\n"
                f"{m.group('i')})"
            ),
        ),
    ]

    replaced = 0
    for pattern, repl in patterns:
        text, count = pattern.subn(repl, text, count=1)
        if count:
            replaced += count
            break

    if replaced != 1:
        raise SystemExit(
            "[fnOS native7] ERROR: cannot replace recorder.start_recording page.run_task"
        )

write_if_changed(record_manager_path, old_text, text)


# ---- RecordingManager: scheduled recording lifecycle ----
text = record_manager_path.read_text(encoding="utf-8")
old_text = text

native7_schedule_marker = "# fnOS native7: scheduled recording lifecycle"

if native7_schedule_marker not in text:
    start = text.find("    async def check_all_live_status(self):")
    end = text.find("    # fnOS native5: resilient web scheduler", start)

    if end < 0:
        end = text.find("    _periodic_task_running = False", start)

    if start < 0 or end < 0:
        raise SystemExit(
            "[fnOS native7] ERROR: cannot locate check_all_live_status boundary"
        )

    replacement = '''    async def check_all_live_status(self):
        # fnOS native7: scheduled recording lifecycle
        for recording in self.recordings:
            if not recording.monitor_status:
                continue

            active = recording.rec_id in self.active_recorders

            if recording.scheduled_recording:
                scheduled_time_range_list = await self.get_scheduled_time_range(
                    recording.scheduled_start_time,
                    recording.monitor_hours,
                ) or []

                in_scheduled = any(
                    utils.is_current_time_within_range(time_range)
                    for time_range in scheduled_time_range_list
                )

                previous_in_scheduled = getattr(
                    recording,
                    "_fnos_native7_in_scheduled",
                    None,
                )

                # 离开时间窗：定时规则必须真正停止正在运行的 recorder。
                if not in_scheduled:
                    if previous_in_scheduled is not False:
                        logger.info(
                            "[fnOS native7 schedule] "
                            f"EXIT/OUTSIDE url={recording.url} "
                            f"now={utils.fnos_now().strftime('%Y-%m-%d %H:%M:%S')} "
                            f"ranges={scheduled_time_range_list} "
                            f"is_recording={recording.is_recording} active={active}"
                        )

                    setattr(
                        recording,
                        "_fnos_native7_in_scheduled",
                        False,
                    )

                    if active or recording.is_recording:
                        if active and not recording.is_recording:
                            # active_recorders 是真实录制的最终依据。
                            recording.is_recording = True

                        if active:
                            logger.info(
                                "[fnOS native7 schedule] REAL STOP "
                                f"rec_id={recording.rec_id} url={recording.url}"
                            )
                            self.stop_recording(
                                recording,
                                manually_stopped=False,
                            )
                        else:
                            # native6 可能留下假的 is_recording=True。
                            logger.warning(
                                "[fnOS native7 schedule] FAKE STATE outside window; "
                                f"reset rec_id={recording.rec_id} url={recording.url}"
                            )
                            recording.is_recording = False
                            recording.start_time = None
                            recording.stopping_in_progress = False
                            recording.manually_stopped = False

                    # 没有真实 recorder 时，不得残留 force_stop=True。
                    if not active:
                        recording.force_stop = False

                    recording.is_live = False
                    recording.is_checking = False
                    recording.status_info = (
                        RecordingStatus.NOT_IN_SCHEDULED_CHECK
                    )
                    continue

                # 进入/位于时间窗内。
                entered = previous_in_scheduled is not True

                if entered:
                    setattr(
                        recording,
                        "_fnos_native7_in_scheduled",
                        True,
                    )
                    recording.detection_time = None
                    recording.showed_checking_status = False
                    logger.info(
                        "[fnOS native7 schedule] ENTER window "
                        f"url={recording.url} "
                        f"now={utils.fnos_now().strftime('%Y-%m-%d %H:%M:%S')} "
                        f"ranges={scheduled_time_range_list} "
                        f"is_recording={recording.is_recording} active={active}"
                    )

                # 旧 force_stop 只能属于上一场/旧 fake state。
                if not active and recording.force_stop:
                    logger.warning(
                        "[fnOS native7 schedule] clear stale force_stop "
                        f"rec_id={recording.rec_id} url={recording.url}"
                    )
                    recording.force_stop = False

                # UI 可能已变成“录制中”，但真正 recorder 没建立。
                if recording.is_recording and not active:
                    logger.warning(
                        "[fnOS native7 schedule] FAKE STATE detected; "
                        f"is_recording=True but active recorder missing; "
                        f"reset and retry rec_id={recording.rec_id} url={recording.url}"
                    )
                    recording.is_recording = False
                    recording.is_live = False
                    recording.start_time = None
                    recording.stopping_in_progress = False
                    recording.manually_stopped = False
                    recording.force_stop = False
                    recording.detection_time = None
                    active = False

                if active:
                    if not recording.is_recording:
                        logger.warning(
                            "[fnOS native7 schedule] active recorder exists but "
                            "is_recording=False; reconcile state "
                            f"rec_id={recording.rec_id}"
                        )
                        recording.is_recording = True
                    continue

                is_exceeded = utils.is_time_interval_exceeded(
                    recording.detection_time,
                    recording.loop_time_seconds,
                )

                if entered or not recording.detection_time or is_exceeded:
                    logger.info(
                        "[fnOS native7 schedule] CHECK "
                        f"rec_id={recording.rec_id} url={recording.url} "
                        f"entered={entered}"
                    )
                    asyncio.create_task(
                        self.check_if_live(recording)
                    )
                continue

            # 非定时监听继续保留上游行为。
            if recording.is_recording or active:
                continue

            is_exceeded = utils.is_time_interval_exceeded(
                recording.detection_time,
                recording.loop_time_seconds,
            )

            if not recording.detection_time or is_exceeded:
                asyncio.create_task(
                    self.check_if_live(recording)
                )

'''

    text = text[:start] + replacement + text[end:]

write_if_changed(record_manager_path, old_text, text)


# ---- Stream manager: detach recording engine from Flet page/WebSocket ----
text = stream_manager_path.read_text(encoding="utf-8")
old_text = text

native7_stream_marker = "# fnOS native7: server-side recording engine"

if native7_stream_marker not in text:
    # Persist recording_dir without requiring a live Flet page.
    old_persist = "self.app.page.run_task(self.app.record_manager.persist_recordings)"
    if old_persist in text:
        text = text.replace(
            old_persist,
            "asyncio.create_task(self.app.record_manager.persist_recordings())",
            1,
        )

    direct_old = '''            self.app.page.run_task(
                self.start_direct_download,
                stream_info.anchor_name,
                self.live_url,
                record_url,
                save_path,
                self.save_format,
                self.user_config.get("custom_script_command"),
            )'''

    direct_new = '''            # fnOS native7: server-side recording engine
            logger.info(
                "[fnOS native7 recorder] dispatch direct downloader "
                f"rec_id={self.recording.rec_id} save_path={save_path}"
            )
            asyncio.create_task(
                self.start_direct_download(
                    stream_info.anchor_name,
                    self.live_url,
                    record_url,
                    save_path,
                    self.save_format,
                    self.user_config.get("custom_script_command"),
                )
            )'''

    if direct_old in text:
        text = text.replace(direct_old, direct_new, 1)

    ffmpeg_old = '''            self.app.page.run_task(
                self.start_ffmpeg,
                stream_info.anchor_name,
                self.live_url,
                record_url,
                ffmpeg_command,
                self.save_format,
                self.user_config.get("custom_script_command"),
            )'''

    ffmpeg_new = '''            # fnOS native7: server-side recording engine
            logger.info(
                "[fnOS native7 recorder] dispatch ffmpeg "
                f"rec_id={self.recording.rec_id} save_path={save_path}"
            )
            asyncio.create_task(
                self.start_ffmpeg(
                    stream_info.anchor_name,
                    self.live_url,
                    record_url,
                    ffmpeg_command,
                    self.save_format,
                    self.user_config.get("custom_script_command"),
                )
            )'''

    if ffmpeg_old in text:
        text = text.replace(ffmpeg_old, ffmpeg_new, 1)

    # native3 recovery used page.run_task; keep recovery alive after browser close.
    recovery_old = '''            self.app.page.run_task(
                self.app.record_manager.check_if_live,
                self.recording,
            )'''
    recovery_new = '''            asyncio.create_task(
                self.app.record_manager.check_if_live(self.recording)
            )'''
    text = text.replace(recovery_old, recovery_new)

    if native7_stream_marker not in text:
        raise SystemExit(
            "[fnOS native7] ERROR: cannot detach stream engine from page.run_task"
        )

write_if_changed(stream_manager_path, old_text, text)


# ================================================================
# 3) FFmpeg 异常后快速刷新直播源，并增加详细 stderr 日志。
# ================================================================
text = stream_manager_path.read_text(encoding="utf-8")
old_text = text

recheck_marker = "# fnOS native3: transient recording recovery"

if recheck_marker not in text:
    start = text.find("    async def recheck_live_status(self):")
    end = text.find("    async def start_ffmpeg(", start)

    if start < 0 or end < 0:
        print(
            "[fnOS native3] WARN: recheck_live_status changed upstream; "
            "skip recovery patch",
            flush=True,
        )
    else:
        replacement = """    # fnOS native3: transient recording recovery
    async def recheck_live_status(self):
        if self.should_stop or self.recording.manually_stopped:
            return

        if not self.app.recording_enabled or self.is_flv_preferred_platform:
            return

        recording_duration = max(
            0.0,
            time.time() - self.recording_start_time,
        )

        retry_count = int(
            getattr(self.recording, "_fnos_native3_retry_count", 0)
            or 0
        )

        if recording_duration <= self.min_valid_recording_duration:
            if retry_count >= 3:
                logger.error(
                    "[fnOS native3 recovery] "
                    f"{self.recording.url} failed quickly 3 times; "
                    "stop fast retry and wait for the normal monitor loop"
                )
                self.recording.status_info = RecordingStatus.RECORDING_ERROR
                setattr(self.recording, "_fnos_native3_retry_count", 0)
                return

            retry_count += 1
            setattr(
                self.recording,
                "_fnos_native3_retry_count",
                retry_count,
            )
            delay = 8
            logger.warning(
                "[fnOS native3 recovery] "
                f"recording ended after {recording_duration:.1f}s; "
                f"refresh stream URL in {delay}s "
                f"(fast retry {retry_count}/3)"
            )
        else:
            setattr(self.recording, "_fnos_native3_retry_count", 0)
            delay = 5
            logger.warning(
                "[fnOS native3 recovery] "
                f"recording ended after {recording_duration:.1f}s; "
                f"refresh stream URL in {delay}s"
            )

        self.recording.status_info = RecordingStatus.STATUS_CHECKING
        await asyncio.sleep(delay)

        if (
            not self.should_stop
            and not self.recording.manually_stopped
            and self.recording.monitor_status
            and self.app.recording_enabled
        ):
            self.app.page.run_task(
                self.app.record_manager.check_if_live,
                self.recording,
            )

"""
        text = text[:start] + replacement + text[end:]

stderr_old = (
    '                    logger.error('
    'f"FFmpeg Stderr Output: {str(stderr.decode()).splitlines()[0]}")'
)

if stderr_old in text:
    stderr_new = """                    error_text = stderr.decode(errors="replace")
                    error_lines = error_text.splitlines()
                    recording_duration = max(
                        0.0,
                        time.time() - self.recording_start_time,
                    )
                    logger.error(
                        "[fnOS native3 ffmpeg] "
                        f"return_code={return_code}, "
                        f"duration={recording_duration:.1f}s, "
                        f"url={live_url}"
                    )
                    for error_line in error_lines[-12:]:
                        logger.error(
                            f"[fnOS native3 ffmpeg] {error_line}"
                        )"""

    text = text.replace(stderr_old, stderr_new, 1)

retry_needle = """            if return_code in safe_return_code:
                self.recording.is_live = False
"""

retry_insert = """            # fnOS native3: a non-safe FFmpeg exit is usually recoverable.
            # Re-fetch a fresh stream URL instead of waiting several minutes.
            if (
                return_code not in safe_return_code
                and not self.recording.manually_stopped
            ):
                await self.recheck_live_status()

            if return_code in safe_return_code:
                self.recording.is_live = False
"""

if "# fnOS native3: a non-safe FFmpeg exit" not in text:
    if retry_needle in text:
        text = text.replace(retry_needle, retry_insert, 1)
    else:
        print(
            "[fnOS native3] WARN: FFmpeg return-code block changed upstream; "
            "immediate retry not injected",
            flush=True,
        )

write_if_changed(stream_manager_path, old_text, text)

for path in (
    utils_path,
    record_manager_path,
    stream_manager_path,
    recording_card_path,
    main_py_path,
):
    py_compile.compile(str(path), doraise=True)

print("[fnOS native7] runtime patch verified", flush=True)
PY
}

log_runtime_clock() {
  {
    echo "============================================================"
    echo "$(date '+%F %T') [fnOS native7] runtime diagnostics"
    echo "shell TZ=${TZ:-}"
    echo "shell date=$(date '+%F %T %z %Z' 2>/dev/null || date)"
    echo "ffmpeg=$(command -v ffmpeg 2>/dev/null || echo missing)"
    ffmpeg -version 2>/dev/null | head -n 1 || true

    "$VENV/bin/python" - <<'PY'
import os
import time
from datetime import datetime, timedelta, timezone

try:
    time.tzset()
except (AttributeError, OSError):
    pass

beijing = datetime.now(timezone(timedelta(hours=8)))

print("python datetime.now()=" + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
print("python UTC+8=" + beijing.strftime("%Y-%m-%d %H:%M:%S %z"))
print("python TZ env=" + str(os.environ.get("TZ")))
print("python time.tzname=" + str(time.tzname))
PY

    echo "============================================================"
  } >> "$LOG_FILE" 2>&1
}

start_app() {
  if is_running; then
    return 0
  fi

  if [ ! -x "$VENV/bin/python" ] || [ ! -f "$SOURCE/main.py" ]; then
    echo "StreamCap 原生运行环境不存在或不完整，请重新安装/升级应用。" > "${TRIM_TEMP_LOGFILE}"
    return 1
  fi

  if ! repair_download_link; then
    echo "录像目录不可用：${DOWNLOADS}。请在 StreamCap 应用设置中重新选择授权目录。" > "${TRIM_TEMP_LOGFILE}"
    return 1
  fi

  cd "$SOURCE" || return 1

  echo "$(date '+%F %T') applying StreamCap fnOS native7 runtime patch" >> "$LOG_FILE"

  if ! apply_native3_patch >> "$LOG_FILE" 2>&1; then
    echo "StreamCap native7 运行补丁失败，请查看 ${LOG_FILE}。" > "${TRIM_TEMP_LOGFILE}"
    return 1
  fi

  log_runtime_clock

  echo "$(date '+%F %T') [fnOS native7] visible_log=$LOG_FILE" >> "$LOG_FILE"
  echo "$(date '+%F %T') starting StreamCap native7 on port $PORT; recordings=$DOWNLOADS" >> "$LOG_FILE"

  if command -v setsid >/dev/null 2>&1; then
    setsid "$VENV/bin/python" main.py --web --host 0.0.0.0 --port "$PORT" >> "$LOG_FILE" 2>&1 &
  else
    "$VENV/bin/python" main.py --web --host 0.0.0.0 --port "$PORT" >> "$LOG_FILE" 2>&1 &
  fi

  pid=$!
  echo "$pid" > "$PID_FILE"
  sleep 2

  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$PID_FILE"
    echo "StreamCap 启动失败，请查看 ${LOG_FILE}。" > "${TRIM_TEMP_LOGFILE}"
    return 1
  fi

  return 0
}

stop_app() {
  if ! is_running; then
    return 0
  fi

  pid="$(head -n 1 "$PID_FILE" | tr -d '[:space:]')"
  echo "$(date '+%F %T') stopping StreamCap native7" >> "$LOG_FILE"

  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true

  n=0
  while kill -0 "$pid" 2>/dev/null && [ "$n" -lt 20 ]; do
    sleep 1
    n=$((n + 1))
  done

  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
  fi

  rm -f "$PID_FILE"
  return 0
}

case "${1:-}" in
  start) start_app ;;
  stop) stop_app ;;
  status) if is_running; then exit 0; else exit 3; fi ;;
  *) echo "Unknown command: ${1:-}" > "${TRIM_TEMP_LOGFILE}"; exit 1 ;;
esac
