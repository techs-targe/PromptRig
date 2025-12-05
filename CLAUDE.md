# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ⚠️ CRITICAL: Specification Adherence

**ALWAYS refer to `docs/req.txt` before making ANY implementation decisions.**

The full Japanese specification in `docs/req.txt` is the authoritative source of truth. All implementation must strictly follow this specification without deviation. When in doubt:
1. Read the relevant section in `docs/req.txt`
2. Follow the specification exactly as written
3. Do not add features or change behavior not specified
4. Do not skip specified features, even if they seem minor

## Project Overview

**Prompt Evaluation System** - A local web application for evaluating and benchmarking prompts against LLMs (Large Language Models). This is currently a **specification-only project** with implementation pending.

The system allows users to:
- Execute prompts against LLMs (Azure OpenAI GPT-4.1, OpenAI gpt-4.1-nano)
- Record and analyze execution results with turnaround times
- Manage projects with prompt templates and custom parsers
- Run batch evaluations against datasets (Phase 2)

## Development Commands

### Setup and Installation
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Running the Application
```bash
# Start the web server (will run on port 9200)
python main.py

# Access at: http://localhost:9200
```

### Configuration
Create `.env` or `config/config.yaml` with:
```
AZURE_OPENAI_ENDPOINT=<your-endpoint>
AZURE_OPENAI_API_KEY=<your-key>
AZURE_OPENAI_DEPLOYMENT_NAME=<deployment-name>
AZURE_OPENAI_API_VERSION=<api-version>
DATABASE_PATH=database/app.db
ACTIVE_LLM_MODEL=azure-gpt-4.1
```

## Architecture

### Technology Stack
- **Backend**: Python 3.10-3.12 + FastAPI + uvicorn (port 9200)
- **Frontend**: HTML + CSS + minimal JavaScript with Jinja2 templates
- **Database**: SQLite with SQLAlchemy ORM
- **LLM Integration**: Azure OpenAI GPT-4.1, OpenAI gpt-4.1-nano

### Project Structure (Expected)
```
project_root/
├── main.py                    # Application entry point
├── requirements.txt           # Python dependencies
├── .env                       # Environment configuration
├── docs/
│   └── req.txt               # Full Japanese specification
├── app/
│   ├── routes/               # FastAPI endpoints
│   │   ├── main.py          # GET /
│   │   ├── config.py        # GET /api/config
│   │   └── run.py           # POST /api/run/single, /api/run/batch
│   ├── templates/            # Jinja2 HTML templates
│   └── schemas/              # Pydantic models
├── backend/
│   ├── llm/                  # LLM client modules
│   │   ├── base.py          # LLM interface
│   │   ├── azure_gpt_4_1.py
│   │   └── openai_gpt_4_nano.py
│   ├── database/
│   │   ├── models.py        # SQLAlchemy ORM models
│   │   └── schemas.py       # Pydantic schemas
│   ├── parser.py            # Response parsing logic
│   ├── prompt.py            # Template extraction and {{}} parsing
│   └── job.py               # Job management logic
└── database/
    └── app.db               # SQLite database
```

## Core Concepts

### Prompt Template Syntax
The system uses `{{}}` syntax for dynamic parameters in prompt templates:

```
{{PARAM_NAME}}              # Default: TEXT5 (5-line textarea)
{{PARAM_NAME:TEXT10}}       # 10-line text area
{{PARAM_NAME:NUM}}          # Number input
{{PARAM_NAME:DATE}}         # Date picker
{{PARAM_NAME:DATETIME}}     # DateTime picker
```

**Important behaviors:**
- Duplicate parameter names use the same value across all occurrences
- Input forms are auto-generated from template parsing
- Type specifications are optional (defaults to TEXT5)

### Database Schema

**Core tables:**
- `projects` - Project metadata
- `project_revisions` - Prompt/parser versions (Phase 2)
- `jobs` - Execution jobs (single/batch)
- `job_items` - Individual execution results with turnaround times
- `datasets` - Imported Excel data for batch execution (Phase 2)
- `system_settings` - Key-value configuration store

**Key relationships:**
- Jobs link to project_revisions (enables version tracking)
- Job_items link to jobs (one job has many items for repeat/batch execution)
- Datasets link to projects and are used by batch jobs

### Execution Flow

**Single Execution:**
1. User opens main page → `GET /`
2. Page loads initial config → `GET /api/config` (returns project info, prompt template, parameter definitions, recent history)
3. User fills form and clicks "1件送信" (send once) or "n回送信" (send n times)
4. Submit → `POST /api/run/single` with input params and repeat count
5. Server creates job + job_items, executes LLM calls sequentially
6. Results saved to DB and returned to client
7. UI updates history list and displays raw/parsed responses

**Batch Execution (Phase 2):**
1. Select project and dataset → `POST /api/run/batch`
2. Server creates batch job with job_items for each dataset row
3. Backend worker processes items sequentially
4. Client polls `GET /api/jobs/{job_id}` for progress updates

## Implementation Phases

### Phase 1 (MVP) - Current Target
- Single project (fixed, no multi-project UI)
- Single execution mode only
- Template-based form generation from `{{}}` syntax
- Azure OpenAI GPT-4.1 and OpenAI gpt-4.1-nano fixed
- Execution history storage
- No system/project settings UI (config file only)

### Phase 2 (Extensions)
- Multiple project management
- Prompt/parser revision tracking
- Excel dataset import (.xlsx with named ranges, default: "DSRange")
- Batch execution with progress tracking
- LLM plugin architecture (config/llm/*.py modules)
- System settings UI
- Background job execution

## API Endpoints

### Core Endpoints (Phase 1)
- `GET /` - Main UI page with single execution interface
- `GET /api/config` - Initial configuration and prompt template
- `POST /api/run/single` - Execute single/repeated prompt
  - Body: `{input_params: {}, repeat: int}`
  - Returns: job_id and latest execution results

### Phase 2 Endpoints
- `POST /api/run/batch` - Start batch execution
- `GET /api/jobs/{job_id}` - Job progress/status polling
- Project/dataset/settings management endpoints

## LLM Plugin System (Phase 2)

Plugins are Python modules in `config/llm/` with a `ModelConfig` class:

```python
class ModelConfig:
    name = "azure-gpt-4.1"
    provider = "azure_openai"
    parameters = {
        "temperature": {"type": "float", "default": 0.2, "min": 0.0, "max": 2.0},
        "top_p": {"type": "float", "default": 1.0},
    }

    def call(self, prompt: str, **kwargs) -> str:
        # Implementation
        pass
```

The application scans this directory at startup to discover available models.

## Job Execution and Parallelism

### Parallelism Configuration

The system supports parallel job execution for faster batch processing. This is configured in System Settings:

- **Setting**: `job_parallelism` (range: 1-99, default: 1)
- **UI**: System Settings tab → "並列実行数 / Job Parallelism" picker
- **API**:
  - `GET /api/settings/job-parallelism` - Get current setting
  - `PUT /api/settings/job-parallelism?parallelism=N` - Set parallelism

**Implementation**: When `parallelism=1`, jobs execute serially. When `parallelism>1`, the system uses `ThreadPoolExecutor` with `max_workers=parallelism` to process job items concurrently.

### Thread Safety

Each parallel worker thread creates its own database session to ensure thread safety:

```python
def execute_single_item(item_id: int, raw_prompt: str, parser_config: str) -> int:
    db = SessionLocal()  # New session per thread
    try:
        # ... process item
    finally:
        db.close()  # Always close session
```

**Important**: Never share SQLAlchemy sessions across threads as SQLite is not thread-safe for concurrent writes.

### Azure OpenAI Rate Limits

When using Azure OpenAI GPT-5 models (mini, nano), be aware of API rate limits:

**Common Symptoms of Rate Limiting:**
- Empty responses with no error message
- 429 HTTP errors
- Slow response times
- Finish reason: `content_filter` or `length`

**Recommended Parallelism Settings:**
- **Testing/Development**: Start with parallelism=1
- **Production with Standard Tier**: parallelism=3-5
- **Production with Premium Tier**: parallelism=10-20
- **If experiencing errors**: Reduce by 50% and monitor

**Best Practices:**
1. Monitor server logs for `[RATE_LIMIT]` and `[TIMEOUT]` tags in error messages
2. Check Azure Portal for quota utilization and throttling metrics
3. Start with low parallelism and gradually increase while monitoring success rate
4. Consider implementing retry logic with exponential backoff for rate-limited requests

**Enhanced Error Logging:**
The GPT-5 clients now log detailed information for troubleshooting:
- Completion ID and model name for all requests
- Finish reason for empty responses
- Automatic detection of rate limit and timeout errors
- Response turnaround time tracking

### Job Cancellation

Users can stop running jobs using the stop button (⏹ 停止). This cancels all **pending** items in the job queue:

- **Single Execution**: Stop button appears during execution
- **Batch Execution**: Stop button appears during batch processing
- **Limitation**: Only pending items can be cancelled. Items currently executing (LLM API calls in progress) cannot be interrupted.

**API**: `POST /api/jobs/{job_id}/cancel` - Cancels all pending items, returns count of cancelled items.

## Important Notes

- **Target OS**: Windows 10/11 (64-bit) and Linux (x86_64)
- **Single user**: System designed for local use by one user
- **Repeat limit**: `repeat` parameter capped at ~10 executions for MVP
- **Error handling**: LLM API errors stored in job_items with `status=error` and `error_message`
- **Logging**: INFO-level logging for all LLM calls with turnaround time tracking
- **Specification**: Full Japanese specification available in `docs/req.txt`
