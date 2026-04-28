from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse
import uuid
from app.core.config import settings
from app.db import crud
from app.services.worker import start_worker, is_worker_running
from custom_logger import logger_config as logger

router = APIRouter()

@router.get("/")
async def index():
    return FileResponse('index.html')

@router.post("/api/tasks/upload")
async def submit_task(request: Request):
    data = await request.json()
    if not data or not data.get('text', '').strip():
        raise HTTPException(status_code=400, detail="No input text provided")

    task_id = str(uuid.uuid4())
    input_text = data['text'].strip()
    system_prompt = data.get('system_prompt', '').strip() or None
    hide_from_ui = 1 if data.get('hide_from_ui') else 0

    await crud.insert_task(task_id, input_text, system_prompt, 'not_started', hide_from_ui)
    
    await start_worker()

    return JSONResponse(status_code=201, content={
        'id': task_id,
        'filename': input_text[:50] + ("..." if len(input_text) > 50 else ""),
        'status': 'not_started',
        'message': 'Task submitted successfully'
    })

@router.get("/api/tasks")
async def get_tasks():
    rows, queue_ids, processing_count, avg_time = await crud.get_all_tasks()
    
    tasks = []
    for row in rows:
        queue_position = None
        estimated_start_seconds = None

        if row['status'] == 'not_started' and row['id'] in queue_ids:
            queue_position = queue_ids.index(row['id']) + 1
            tasks_ahead = queue_position - 1 + processing_count
            estimated_start_seconds = round(tasks_ahead * avg_time)

        tasks.append({
            'id': row['id'],
            'filename': row['input_text'][:200] + ('...' if len(row['input_text']) > 200 else ''),
            'status': row['status'],
            'result': "HIDDEN_IN_LIST_VIEW",
            'created_at': row['created_at'],
            'processed_at': row['processed_at'],
            'progress': row['progress'] or 0,
            'progress_text': row['progress_text'],
            'queue_position': queue_position,
            'estimated_start_seconds': estimated_start_seconds
        })

    return tasks

@router.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    result = await crud.get_task_by_id(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="Task not found")
        
    row, queue_position, estimated_start_seconds = result

    return {
        'id': row['id'],
        'filename': row['input_text'],
        'status': row['status'],
        'result': row['result'],
        'created_at': row['created_at'],
        'processed_at': row['processed_at'],
        'progress': row['progress'] or 0,
        'progress_text': row['progress_text'],
        'queue_position': queue_position,
        'estimated_start_seconds': estimated_start_seconds
    }

@router.get("/health")
async def health():
    return {
        'status': 'healthy',
        'service': 'ttt-runner',
        'worker_running': is_worker_running()
    }
