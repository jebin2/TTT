# Text-to-Text Generator

A Python-based text generation service powered by Qwen/Qwen3.5-4B with a neobrutalist web interface. Submit prompts via API or UI, process them through the model, and view results with full task tracking.

## Features

- 📝 Text prompt submission via REST API
- 🤖 Automatic generation using Qwen/Qwen3.5-4B
- 💾 SQLite database for queue management
- 🎨 Neobrutalist UI with smooth animations
- 🔄 Real-time progress updates and token streaming
- 📱 Fully responsive design

## Project Structure

```
hf_backend/
├── app.py              # Flask API server + embedded worker
├── index.html          # Frontend UI
├── requirements.txt    # Python dependencies
├── text_tasks.db       # SQLite database (auto-created)
└── temp_dir/           # Temporary generation output (auto-created)
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/submit` | POST | Submit a text task |
| `/api/tasks` | GET | Get all tasks |
| `/api/tasks/<id>` | GET | Get specific task (includes full result) |
| `/health` | GET | Health check |

---

### `POST /api/submit`

Submit a text prompt for generation.

**Request:**
- **Content-Type:** `application/json`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `text` | string | Yes | Input prompt |
| `system_prompt` | string | No | System message (default: "You are a helpful assistant.") |
| `hide_from_ui` | boolean | No | Hide task from web UI (default: false) |

**Response (201 Created):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "not_started",
  "message": "Task submitted successfully"
}
```

**Error Responses:**

| Status | Response |
|--------|----------|
| 400 | `{"error": "No input text provided"}` |

---

### `GET /api/tasks`

Retrieve all tasks with their status.

**Response (200 OK):**
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "input_text": "Explain quantum computing in simple terms...",
    "status": "completed",
    "result": "HIDDEN_IN_LIST_VIEW",
    "created_at": "2024-01-15T10:30:00.000000",
    "processed_at": "2024-01-15T10:31:20.000000",
    "progress": 100,
    "progress_text": "Completed",
    "queue_position": null,
    "estimated_start_seconds": null
  },
  {
    "id": "660e8400-e29b-41d4-a716-446655440001",
    "input_text": "Write a poem about...",
    "status": "not_started",
    "result": "HIDDEN_IN_LIST_VIEW",
    "created_at": "2024-01-15T10:35:00.000000",
    "processed_at": null,
    "progress": 0,
    "progress_text": null,
    "queue_position": 1,
    "estimated_start_seconds": 80
  }
]
```

---

### `GET /api/tasks/<task_id>`

Retrieve a specific task including its full result.

**Response (200 OK):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "input_text": "Explain quantum computing in simple terms",
  "status": "completed",
  "result": "{\"text\": \"Quantum computing uses quantum bits...\", \"model\": \"Qwen/Qwen3.5-4B\", \"input_tokens\": 42, \"output_tokens\": 318}",
  "created_at": "2024-01-15T10:30:00.000000",
  "processed_at": "2024-01-15T10:31:20.000000",
  "progress": 100,
  "progress_text": "Completed",
  "queue_position": null,
  "estimated_start_seconds": null
}
```

**Error Responses:**

| Status | Response |
|--------|----------|
| 404 | `{"error": "Task not found"}` |

---

### `GET /health`

**Response (200 OK):**
```json
{
  "status": "healthy",
  "service": "text-to-text-generator",
  "worker_running": true
}
```

## Database Schema

```sql
CREATE TABLE text_tasks (
    id TEXT PRIMARY KEY,
    input_text TEXT NOT NULL,
    system_prompt TEXT,
    status TEXT NOT NULL,
    result TEXT,
    created_at TEXT NOT NULL,
    processed_at TEXT,
    progress INTEGER DEFAULT 0,
    progress_text TEXT,
    hide_from_ui INTEGER DEFAULT 0
);
```

## Status Values

| Status | Description | `queue_position` | `estimated_start_seconds` |
|--------|-------------|------------------|---------------------------|
| `not_started` | Queued, waiting for worker | Integer (1-based) | Estimated seconds until start |
| `processing` | Currently being generated | `null` | `null` |
| `completed` | Generation successful | `null` | `null` |
| `failed` | Error during generation | `null` | `null` |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `7860` | Flask server port |
| `MAX_NEW_TOKENS` | `2048` | Maximum tokens to generate |
| `USE_CPU_IF_POSSIBLE` | unset | Force CPU inference |

## Tech Stack

- **Backend:** Flask (Python)
- **Database:** SQLite
- **Frontend:** Vanilla HTML/CSS/JavaScript
- **Model:** Qwen/Qwen3.5-4B (via HuggingFace Transformers)
- **Design:** Neobrutalism with neon accents

## License

MIT
