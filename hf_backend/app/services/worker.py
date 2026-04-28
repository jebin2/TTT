import asyncio
import json
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
    
    try:
        from ttt.runner import initiate
        # Warm up: load the engine
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: initiate({'text': 'Hi', 'model': 'qwen', 'max_new_tokens': 1}))
        logger.info("✅ Qwen model ready. Monitoring for new tasks...")
    except Exception as e:
        logger.error(f"❌ Failed to load model: {e}")
        worker_running = False
        return

    while worker_running:
        logger.debug("Worker loop iteration, checking for files...")
        await crud.cleanup_old_entries()
        
        try:
            row = await crud.get_next_not_started()
            
            if row:
                task_id = row['id']
                input_text = row['input_text']
                system_prompt = row['system_prompt'] or "You are a helpful assistant."
                
                logger.info(f"\n{'='*60}\nProcessing task: {task_id}\n📌 Input: {input_text[:100]}...\n{'='*60}")
                
                await crud.update_status(task_id, 'processing')
                
                loop = asyncio.get_event_loop()

                def progress_cb(percent, text):
                    asyncio.run_coroutine_threadsafe(
                        crud.update_progress(task_id, percent, text),
                        loop
                    )

                try:
                    await crud.update_progress(task_id, 5, "Starting...")
                    
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
