import asyncio
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
        logger.debug("Worker loop iteration, checking for files...")
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


# opencode reports nothing about how far along it is — the Qwen path has a real
# progress_callback, but here the task would sit at 10% for minutes and then
# jump to 100. This is an estimate, not a measurement: progress approaches but
# never reaches 90%, hitting the halfway mark at _PROGRESS_BASELINE seconds, so
# a run that takes longer than usual keeps moving instead of stalling or lying
# about being nearly done. The elapsed time in the text is the honest part.
_PROGRESS_BASELINE = 300  # seconds; a typical whole-book run
_PROGRESS_INTERVAL = 10   # seconds between updates


async def _report_progress(task_id):
    started = time.monotonic()
    while True:
        await asyncio.sleep(_PROGRESS_INTERVAL)
        elapsed = time.monotonic() - started
        percent = 10 + int(80 * elapsed / (elapsed + _PROGRESS_BASELINE))
        await crud.update_progress(
            task_id, percent, f"Running opencode… {_format_elapsed(elapsed)}"
        )


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
    proc = await asyncio.create_subprocess_exec(
        'opencode', 'run', '--print-logs', '--log-level', 'WARN',
        '--model', 'opencode/big-pickle', full_prompt,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=2 ** 24,  # 16 MB
    )

    stdout_lines = []
    stderr_lines = []

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
    # around five minutes; 300s killed those just as they were finishing. Give
    # it real headroom — the client waits longer than this on purpose.
    OPENCODE_TIMEOUT = 600
    ticker = asyncio.create_task(_report_progress(task_id)) if task_id else None
    try:
        await asyncio.wait_for(
            asyncio.gather(
                _read_stream(proc.stdout, stdout_lines, "stdout"),
                _read_stream(proc.stderr, stderr_lines, "stderr"),
            ),
            timeout=OPENCODE_TIMEOUT
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise TimeoutError(f"opencode timed out after {OPENCODE_TIMEOUT}s")
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
    return stdout
