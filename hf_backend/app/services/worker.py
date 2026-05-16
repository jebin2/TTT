import asyncio
import json
import shutil
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
                        result = await _run_opencode(input_text)
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


async def _run_opencode(text: str) -> str:
    if not shutil.which('opencode'):
        raise FileNotFoundError(
            "opencode CLI not found. Install it from https://opencode.ai"
        )

    proc = await asyncio.create_subprocess_exec(
        'opencode', 'run', '--print-logs', '--model', 'opencode/big-pickle', text,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout_lines = []
    stderr_lines = []

    async def _read_stream(stream, lines, label):
        while True:
            line = await stream.readline()
            if not line:
                break
            decoded = line.decode(errors='replace').rstrip()
            lines.append(decoded)
            logger.info(f"opencode {label}: {decoded}")

    try:
        await asyncio.wait_for(
            asyncio.gather(
                _read_stream(proc.stdout, stdout_lines, "stdout"),
                _read_stream(proc.stderr, stderr_lines, "stderr"),
            ),
            timeout=120
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise TimeoutError("opencode timed out after 120s")

    await proc.wait()

    stdout = '\n'.join(stdout_lines)
    stderr = '\n'.join(stderr_lines)

    if proc.returncode != 0:
        raise RuntimeError(f"opencode failed ({proc.returncode}): {stderr or 'unknown error'}")
    return stdout
