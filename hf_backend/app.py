from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3
import os
import uuid
from datetime import datetime, timedelta
import threading
import time

app = Flask(__name__)
CORS(app)

# Worker state
worker_thread = None
worker_running = False

def init_db():
    conn = sqlite3.connect('text_tasks.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS text_tasks
                 (id TEXT PRIMARY KEY,
                  input_text TEXT NOT NULL,
                  system_prompt TEXT,
                  status TEXT NOT NULL,
                  result TEXT,
                  created_at TEXT NOT NULL,
                  processed_at TEXT,
                  progress INTEGER DEFAULT 0,
                  progress_text TEXT,
                  hide_from_ui INTEGER DEFAULT 0)'''
    )
    conn.commit()
    conn.close()

def start_worker():
    global worker_thread, worker_running
    if not worker_running:
        worker_running = True
        worker_thread = threading.Thread(target=worker_loop, daemon=True)
        worker_thread.start()
        print("✅ Worker thread started")

def cleanup_old_entries():
    try:
        conn = sqlite3.connect('text_tasks.db')
        c = conn.cursor()
        cutoff_date = (datetime.now() - timedelta(days=10)).isoformat()
        c.execute('DELETE FROM text_tasks WHERE created_at < ?', (cutoff_date,))
        deleted = c.rowcount
        conn.commit()
        conn.close()
        if deleted > 0:
            print(f"🧹 Cleanup: Deleted {deleted} old task entries")
    except Exception as e:
        print(f"⚠️  Cleanup error: {e}")

def update_progress(task_id, progress, progress_text=None):
    conn = sqlite3.connect('text_tasks.db')
    c = conn.cursor()
    c.execute('UPDATE text_tasks SET progress = ?, progress_text = ? WHERE id = ?',
              (progress, progress_text, task_id))
    conn.commit()
    conn.close()

def update_status(task_id, status, result=None, error=None):
    conn = sqlite3.connect('text_tasks.db')
    c = conn.cursor()
    if status == 'completed':
        c.execute('''UPDATE text_tasks
                     SET status = ?, result = ?, processed_at = ?, progress = 100, progress_text = 'Completed'
                     WHERE id = ?''',
                  (status, result, datetime.now().isoformat(), task_id))
    elif status == 'failed':
        c.execute('''UPDATE text_tasks
                     SET status = ?, result = ?, processed_at = ?, progress_text = 'Failed'
                     WHERE id = ?''',
                  (status, f"Error: {error}", datetime.now().isoformat(), task_id))
    else:
        c.execute('UPDATE text_tasks SET status = ? WHERE id = ?', (status, task_id))
    conn.commit()
    conn.close()

def worker_loop():
    """Worker loop: loads Qwen model once, then processes queued tasks."""
    print("🤖 TTT Worker starting — importing ttt package...")

    POLL_INTERVAL = 3

    try:
        from ttt.runner import initiate
        # Warm up: load the engine by doing a tiny call (model load happens inside initiate)
        print("📥 Loading Qwen model (this may take a few minutes)...")
        initiate({'text': 'Hi', 'model': 'qwen', 'max_new_tokens': 1})
        print("✅ Qwen model ready")
    except Exception as e:
        print(f"❌ Failed to load model: {e}")
        return

    from ttt.runner import initiate

    print("🤖 TTT Worker ready. Monitoring for new tasks...")

    while worker_running:
        cleanup_old_entries()
        try:
            conn = sqlite3.connect('text_tasks.db')
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute('''SELECT * FROM text_tasks
                         WHERE status = 'not_started'
                         ORDER BY created_at ASC
                         LIMIT 1''')
            row = c.fetchone()
            conn.close()

            if row:
                task_id = row['id']
                input_text = row['input_text']
                system_prompt = row['system_prompt'] or "You are a helpful assistant."

                print(f"\n{'='*60}")
                print(f"📝 Processing task: {task_id}")
                print(f"📌 Input: {input_text[:100]}{'...' if len(input_text) > 100 else ''}")
                print(f"{'='*60}")

                update_status(task_id, 'processing')

                def make_progress_cb(tid):
                    def cb(percent, text):
                        update_progress(tid, percent, text)
                    return cb

                try:
                    result = initiate(
                        {
                            'text': input_text,
                            'system_prompt': system_prompt,
                            'model': 'qwen',
                        },
                        progress_callback=make_progress_cb(task_id)
                    )

                    if result:
                        import json
                        print(f"✅ Task completed: {task_id}")
                        print(f"📄 Output preview: {result.get('text', '')[:100]}...")
                        update_status(task_id, 'completed', result=json.dumps(result))
                    else:
                        raise Exception("initiate() returned empty result")

                except Exception as e:
                    print(f"❌ Task failed: {task_id} — {e}")
                    update_status(task_id, 'failed', error=str(e))
            else:
                time.sleep(POLL_INTERVAL)

        except Exception as e:
            print(f"⚠️  Worker error: {e}")
            time.sleep(POLL_INTERVAL)

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/api/submit', methods=['POST'])
def submit_task():
    data = request.get_json()
    if not data or not data.get('text', '').strip():
        return jsonify({'error': 'No input text provided'}), 400

    task_id = str(uuid.uuid4())
    input_text = data['text'].strip()
    system_prompt = data.get('system_prompt', '').strip() or None
    hide_from_ui = 1 if data.get('hide_from_ui') else 0

    conn = sqlite3.connect('text_tasks.db')
    c = conn.cursor()
    c.execute('''INSERT INTO text_tasks
                 (id, input_text, system_prompt, status, created_at, hide_from_ui)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (task_id, input_text, system_prompt, 'not_started', datetime.now().isoformat(), hide_from_ui))
    conn.commit()
    conn.close()

    start_worker()

    return jsonify({
        'id': task_id,
        'status': 'not_started',
        'message': 'Task submitted successfully'
    }), 201

def get_average_processing_time(cursor):
    cursor.execute('''SELECT created_at, processed_at FROM text_tasks
                      WHERE status = 'completed' AND processed_at IS NOT NULL
                      ORDER BY processed_at DESC LIMIT 20''')
    rows = cursor.fetchall()
    if not rows:
        return 120.0  # default: 2 min per task

    total, count = 0, 0
    for r in rows:
        try:
            duration = (datetime.fromisoformat(r['processed_at']) -
                        datetime.fromisoformat(r['created_at'])).total_seconds()
            if duration > 0:
                total += duration
                count += 1
        except:
            continue
    return total / count if count else 120.0

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    conn = sqlite3.connect('text_tasks.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    avg_time = get_average_processing_time(c)

    c.execute("SELECT id FROM text_tasks WHERE status = 'not_started' ORDER BY created_at ASC")
    queue_ids = [r['id'] for r in c.fetchall()]

    c.execute("SELECT COUNT(*) as cnt FROM text_tasks WHERE status = 'processing'")
    processing_count = c.fetchone()['cnt']

    c.execute('SELECT * FROM text_tasks WHERE hide_from_ui = 0 OR hide_from_ui IS NULL ORDER BY created_at DESC')
    rows = c.fetchall()
    conn.close()

    tasks = []
    for row in rows:
        queue_position = None
        estimated_start_seconds = None

        if row['status'] == 'not_started' and row['id'] in queue_ids:
            queue_position = queue_ids.index(row['id']) + 1
            files_ahead = queue_position - 1 + processing_count
            estimated_start_seconds = round(files_ahead * avg_time)

        tasks.append({
            'id': row['id'],
            'input_text': row['input_text'][:200] + ('...' if len(row['input_text']) > 200 else ''),
            'status': row['status'],
            'result': "HIDDEN_IN_LIST_VIEW",
            'created_at': row['created_at'],
            'processed_at': row['processed_at'],
            'progress': row['progress'] or 0,
            'progress_text': row['progress_text'],
            'queue_position': queue_position,
            'estimated_start_seconds': estimated_start_seconds
        })

    return jsonify(tasks)

@app.route('/api/tasks/<task_id>', methods=['GET'])
def get_task(task_id):
    conn = sqlite3.connect('text_tasks.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM text_tasks WHERE id = ?', (task_id,))
    row = c.fetchone()

    if row is None:
        conn.close()
        return jsonify({'error': 'Task not found'}), 404

    queue_position = None
    estimated_start_seconds = None

    if row['status'] == 'not_started':
        avg_time = get_average_processing_time(c)
        c.execute("SELECT COUNT(*) as pos FROM text_tasks WHERE status = 'not_started' AND created_at < ?",
                  (row['created_at'],))
        queue_position = c.fetchone()['pos'] + 1
        c.execute("SELECT COUNT(*) as cnt FROM text_tasks WHERE status = 'processing'")
        processing_count = c.fetchone()['cnt']
        estimated_start_seconds = round((queue_position - 1 + processing_count) * avg_time)

    conn.close()

    return jsonify({
        'id': row['id'],
        'input_text': row['input_text'],
        'status': row['status'],
        'result': row['result'],
        'created_at': row['created_at'],
        'processed_at': row['processed_at'],
        'progress': row['progress'] or 0,
        'progress_text': row['progress_text'],
        'queue_position': queue_position,
        'estimated_start_seconds': estimated_start_seconds
    })

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'healthy',
        'service': 'text-to-text-generator',
        'worker_running': worker_running
    })

if __name__ == '__main__':
    init_db()
    print("\n" + "="*60)
    print("🚀 Text-to-Text Generator API Server (Qwen/Qwen3.5-4B)")
    print("="*60)
    print("📌 Worker + model load on first task submission")
    print("="*60 + "\n")

    port = int(os.environ.get('PORT', 7860))
    app.run(debug=False, host='0.0.0.0', port=port)
