import asyncio
import contextlib
import json
import os
import re
import shutil
import time
from app.core.config import settings
from custom_logger import logger_config as logger
from app.db import crud

worker_task = None
worker_running = False

def is_worker_running():
    return worker_running

async def start_worker():
    global worker_task, worker_running
    
    logger.info(f"start_worker called: worker_running={worker_running}")
    
    if not worker_running:
        worker_running = True
        worker_task = asyncio.create_task(worker_loop())
        logger.info("Worker task started")
    else:
        logger.info("Worker already running")

async def worker_loop():
    global worker_running
    logger.info("TTT Worker started. Monitoring for new tasks...")

    from ttt.runner import initiate
    loop = asyncio.get_event_loop()

    try:
        peek_row = await crud.get_next_not_started()
        peek_model = ((peek_row['model'] if 'model' in peek_row.keys() else None) if peek_row else None) or 'qwen'
        if peek_model != 'opencode':
            await loop.run_in_executor(None, lambda: initiate({'text': 'Hi', 'model': 'qwen', 'max_new_tokens': 1}))
            logger.info("✅ Qwen model ready. Monitoring for new tasks...")
        else:
            logger.info("⏭️ Skipping Qwen warmup (opencode task queued). Monitoring for new tasks...")
    except Exception as e:
        logger.warning(f"⚠️ Qwen model not available (opencode-only tasks will still work): {e}")

    while worker_running:
        logger.debug("Worker loop iteration, checking for files...", overwrite=True)
        await crud.cleanup_old_entries()
        
        try:
            row = await crud.get_next_not_started()
            
            if row:
                task_id = row['id']
                input_text = row['input_text']
                system_prompt = row['system_prompt'] or "You are a helpful assistant."
                model = row['model'] if 'model' in row.keys() else 'qwen'
                
                logger.info(f"\n{'='*60}\nProcessing task: {task_id} (model: {model})\n📌 Input: {input_text[:100]}...\n{'='*60}")
                
                await crud.update_status(task_id, 'processing')
                
                loop = asyncio.get_event_loop()

                def progress_cb(percent, text):
                    asyncio.run_coroutine_threadsafe(
                        crud.update_progress(task_id, percent, text),
                        loop
                    )

                try:
                    await crud.update_progress(task_id, 5, "Starting...")

                    if model == 'opencode':
                        await crud.update_progress(task_id, 10, "Running opencode...")
                        result = await _run_opencode(system_prompt, input_text, task_id)
                        logger.success(f"Successfully processed (opencode): {task_id}")
                        await crud.update_progress(task_id, 100, "Completed")
                        await crud.update_status(task_id, 'completed', result=json.dumps({"response": result}))
                    else:
                        result = await loop.run_in_executor(None, lambda: initiate(
                            {
                                'text': input_text,
                                'system_prompt': system_prompt,
                                'model': 'qwen',
                            },
                            progress_callback=progress_cb
                        ))

                        if result:
                            logger.success(f"Successfully processed: {task_id}")
                            await crud.update_status(task_id, 'completed', result=json.dumps(result))
                        else:
                            raise Exception("initiate() returned empty result")

                except Exception as e:
                    logger.error(f"Failed to process {task_id}: {str(e)}")
                    await crud.update_status(task_id, 'failed', error=str(e))
                    
            else:
                await asyncio.sleep(settings.POLL_INTERVAL)
                
        except Exception as e:
            logger.error(f"Worker error: {str(e)}")
            await asyncio.sleep(settings.POLL_INTERVAL)


async def _install_opencode():
    logger.info("opencode CLI not found. Installing via https://opencode.ai/install ...")
    proc = await asyncio.create_subprocess_shell(
        "curl -fsSL https://opencode.ai/install | bash",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    async for line in proc.stdout:
        logger.info(f"opencode install: {line.decode(errors='replace').rstrip()}")
    await proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("opencode installation failed")

    # Always prepend common install locations so this process can find the binary
    candidates = [
        os.path.expanduser("~/.local/bin"),
        os.path.expanduser("~/.bin"),
        "/usr/local/bin",
    ]
    os.environ["PATH"] = ":".join(candidates) + ":" + os.environ.get("PATH", "")

    # Fallback: locate the binary directly on disk
    if not shutil.which('opencode'):
        result = await asyncio.create_subprocess_shell(
            "find /home /root /usr/local/bin -name opencode -type f 2>/dev/null | head -1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await result.communicate()
        found = stdout.decode().strip()
        if found:
            os.environ["PATH"] = os.path.dirname(found) + ":" + os.environ["PATH"]
        else:
            raise RuntimeError("opencode installed but binary not found anywhere on disk")

    logger.info("✅ opencode installed successfully")


# opencode's `--print-logs` emits one structured line per internal event, e.g.
#   INFO  2026-07-22T17:23:10 +37ms service=bus type=message.part.delta publishing
# A single answer produces thousands of these, one per streamed token, which
# buried every other worker log. Parse them instead of echoing: real problems
# (WARN/ERROR) get their own line, the token firehose collapses into a single
# overwriting heartbeat, and a persistent summary is written at the end.
_OPENCODE_LOG_RE = re.compile(
    r'^(?P<level>DEBUG|INFO|WARN|ERROR)\s+\S+\s+\S+\s+(?P<rest>.*)$'
)
_HEARTBEAT_INTERVAL = 1.0  # seconds between heartbeat repaints


class _OpencodeLog:
    def __init__(self, label):
        self.label = label
        self.count = 0
        self.started = time.monotonic()
        self.last_beat = 0.0

    def emit(self, line):
        if not line:
            return
        self.count += 1

        match = _OPENCODE_LOG_RE.match(line)
        level = match.group('level') if match else None
        detail = match.group('rest') if match else line

        if level == 'ERROR':
            logger.error(f"opencode {self.label}: {detail}")
            return
        if level == 'WARN':
            logger.warning(f"opencode {self.label}: {detail}")
            return

        now = time.monotonic()
        if now - self.last_beat < _HEARTBEAT_INTERVAL:
            return
        self.last_beat = now
        elapsed = int(now - self.started)
        logger.info(
            f"opencode {self.label}: {self.count} lines / {elapsed}s | {_shorten(detail)}",
            overwrite=True,
        )

    def flush(self):
        elapsed = int(time.monotonic() - self.started)
        logger.info(f"opencode {self.label}: done — {self.count} lines in {elapsed}s")


def _shorten(text, width=100):
    text = text.strip()
    return text if len(text) <= width else f"{text[:width - 1]}…"


def _format_elapsed(seconds):
    seconds = int(seconds)
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}m{seconds:02d}s" if minutes else f"{seconds}s"


# opencode reports nothing about how far along it is, so both the progress
# percentage and the kill deadline are estimates. They have to be estimates of
# the *same* thing: they used to be two unrelated literals — a 300s baseline
# for the curve and a 600s deadline — which is how a run could report 59% while
# it was 80% through its budget and then die at the timeout with nothing in the
# log to warn anyone. One estimate now drives both.
_OPENCODE_CHARS_PER_SECOND = settings.OPENCODE_CHARS_PER_SECOND
_OPENCODE_MIN_SECONDS = settings.OPENCODE_MIN_SECONDS
_OPENCODE_MAX_SECONDS = settings.OPENCODE_MAX_SECONDS
_OPENCODE_TIMEOUT_SLACK = settings.OPENCODE_TIMEOUT_SLACK
_PROGRESS_INTERVAL = settings.OPENCODE_PROGRESS_INTERVAL
# opencode streams nothing useful until it finishes, so the top of the range is
# reserved for "still going, don't read this as nearly done".
_PROGRESS_CEILING = 95
# Inside this many seconds of the estimate, the text says so out loud.
_OVERRUN_WARNING = 60


def _estimate_seconds(prompt: str) -> int:
    """Seconds big-pickle is expected to need for a prompt this size."""
    seconds = int(len(prompt) / _OPENCODE_CHARS_PER_SECOND)
    return max(_OPENCODE_MIN_SECONDS, min(_OPENCODE_MAX_SECONDS, seconds))


async def _report_progress(task_id: str, started: float, estimate: int):
    """Advance the progress estimate, and survive a failed DB write.

    Nothing awaits this task, so an exception used to kill the ticker silently:
    one `database is locked` while the API touched text_tasks.db and the task
    sat frozen on one number until opencode finished or timed out, with nothing
    in the log explaining the stall.
    """
    while True:
        await asyncio.sleep(_PROGRESS_INTERVAL)
        elapsed = time.monotonic() - started
        percent = 10 + int(
            (_PROGRESS_CEILING - 10) * min(1.0, elapsed / estimate)
        )

        text = f"Running opencode… {_format_elapsed(elapsed)}"
        if elapsed > estimate:
            text += f" — past {_format_elapsed(estimate)} estimate, overrunning"
        elif estimate - elapsed < _OVERRUN_WARNING:
            text += f" — near {_format_elapsed(estimate)} estimate"

        try:
            await crud.update_progress(task_id, percent, text)
        except Exception as e:
            logger.warning(f"Progress update failed for {task_id}: {e}")


async def _run_opencode(system_prompt: str, text: str, task_id: str = None) -> str:
    if not shutil.which('opencode'):
        await _install_opencode()

    full_prompt = f"{system_prompt}\n\n{text}" if system_prompt else text

    # --log-level WARN keeps the logs we care about (something went wrong) and
    # drops the INFO firehose: one `message.part.delta publishing` line per
    # streamed token, plus the whole-prompt echo on startup.
    #
    # That echo is why the streams get a raised limit. The readers below use
    # StreamReader.readline(), whose buffer defaults to 64KB (2**16), and a
    # prompt larger than that — a character-dense reconcile pass, say —
    # overflowed on the very first line with "Separator is found, but chunk is
    # longer than limit", failing the task before opencode did any work. WARN
    # should suppress the echo, but the headroom stays as insurance.
    #
    # stdin must be DEVNULL. `opencode run` reads stdin to EOF whenever it is
    # not a TTY, and under pm2 the inherited stdin is a pipe that never closes,
    # so opencode blocked before sending anything and every task — even a
    # 1.3k-char prompt that takes ~7s — sat there until the timeout killed it.
    proc = await asyncio.create_subprocess_exec(
        'opencode', 'run', '--print-logs', '--log-level', 'WARN',
        '--model', 'opencode/big-pickle', full_prompt,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=2 ** 24,  # 16 MB
    )

    stdout_lines = []
    stderr_lines = []

    estimate = _estimate_seconds(full_prompt)
    timeout = int(estimate * _OPENCODE_TIMEOUT_SLACK)
    logger.info(
        f"opencode: {len(full_prompt)} chars, expecting ~{_format_elapsed(estimate)}, "
        f"killing at {_format_elapsed(timeout)}"
    )

    async def _read_stream(stream, lines, label):
        log = _OpencodeLog(label)
        while True:
            line = await stream.readline()
            if not line:
                break
            decoded = line.decode(errors='replace').rstrip()
            lines.append(decoded)
            log.emit(decoded)
        log.flush()

    # A whole-book prompt (reconcile, the director pass) runs big-pickle for
    # minutes at a time, so the deadline scales with the prompt rather than
    # being a fixed cap — see _estimate_seconds. The client waits longer than
    # this on purpose.
    started = time.monotonic()
    ticker = (
        asyncio.create_task(_report_progress(task_id, started, estimate))
        if task_id else None
    )
    try:
        await asyncio.wait_for(
            asyncio.gather(
                _read_stream(proc.stdout, stdout_lines, "stdout"),
                _read_stream(proc.stderr, stderr_lines, "stderr"),
            ),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        # Reap the child: kill() alone leaves a zombie until the next wait().
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()
        raise TimeoutError(
            f"opencode timed out after {timeout}s "
            f"(prompt {len(full_prompt)} chars, expected ~{_format_elapsed(estimate)})"
        )
    finally:
        if ticker:
            ticker.cancel()

    await proc.wait()

    stdout = '\n'.join(stdout_lines)
    stderr = '\n'.join(stderr_lines)

    if proc.returncode != 0:
        # stderr can be thousands of suppressed event lines; the tail is where
        # the actual failure is.
        tail = '\n'.join(stderr.splitlines()[-20:])
        raise RuntimeError(f"opencode failed ({proc.returncode}): {tail or 'unknown error'}")
    # opencode exits 0 even when the model call itself failed (e.g. a 426
    # "OpenCode 1.18.0 or newer is required"), leaving stdout empty. Without
    # this check the task was marked successful with no answer.
    if not stdout.strip():
        raise RuntimeError(f"opencode produced no output: {_opencode_error(stderr_lines)}")
    return stdout


def _opencode_error(stderr_lines):
    """The most useful one-line reason from opencode's stderr."""
    for line in reversed(stderr_lines):
        if 'service=session.processor' in line and 'error=' in line:
            return line.split('error=', 1)[1].split(' stack=', 1)[0]
    errors = [line for line in stderr_lines if line.startswith('ERROR')]
    return _shorten(errors[-1], 300) if errors else 'unknown error'
