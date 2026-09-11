# Customer Support & Autonomous Resolution Engine

An enterprise-grade, agentic AI customer support system that automates ticket processing from **issue understanding to verified resolution**. Built with **FastAPI**, **PostgreSQL (Neon)**, **LangGraph**, **Groq (Llama-3.3-70B / Qwen-2.5)**, and **Model Context Protocol (MCP)** tool execution.

---

## Key Features

1. **Immediate Asynchronous Ingestion (`FastAPI BackgroundTasks`)**
   - When a customer submits a ticket via `POST /api/system/tickets` or the Customer Portal, the server immediately persists the ticket with status `in_progress` and returns an immediate HTTP response.
   - The AI reasoning workflow executes autonomously in the background without blocking the client.
   - For multi-worker distributed clusters, the background dispatch layer is structured for drop-in migration to Redis/Celery queue workers.

2. **Deterministic Guardrails & Zero-Hallucination Policy**
   - Financial operations (refunds, subscription credits) and shipping policies are governed by a deterministic `BusinessRulesEngine`.
   - Strictly enforces the 30-day return policy and 24-hour duplicate billing detection.

3. **Human-in-the-Loop (HITL) Safety Checkpoints**
   - Consequential actions (such as initiating refunds or account modifications) pause execution at state checkpoints (`is_waiting_human_approval`).
   - The Support Operations Dashboard alerts operators with a real-time review card allowing `Approve`, `Modify`, or `Reject`.

4. **Dual Interface Frontend**
   - **Customer Portal (`/`)**: Submit tickets, track live resolution status with auto-polling every 3s, and view resolution communications.
   - **Support Operations Dashboard (`/agent/`)**: Full visibility into active tickets, execution traces, real-time MCP tool invocations, and supervisor approval controls.

5. **Built-in Benchmark & Evaluation Suite (`POST /api/workflow/evaluate`)**
   - Automated evaluation harness with 7 diverse test cases validating deterministic compliance, routing accuracy, and safety gating.

---

## Architecture Overview

```text
Customer Portal / API Request
          │
          ▼
   POST /api/system/tickets
          │
          ├──► [Persist Ticket in PostgreSQL (status: in_progress)]
          └──► [Return HTTP 200 Immediately to Customer]
          │
          ▼ (FastAPI Background Task)
   WorkflowRunner (LangGraph Engine)
          │
          ├── 1. Information Extraction & Entity Disambiguation (LLM)
          ├── 2. Customer & System of Record Lookup (MCP Tools)
          ├── 3. Deterministic Policy Evaluation (BusinessRulesEngine)
          │        ├── 30-Day Return Window Check
          │        ├── 24-Hour Duplicate Charge Detection
          │        └── Escalation Triggers (VIP / High-Risk / Lost Goods)
          │
          ├── 4. Action Decision
          │        ├── Consequential (Refund/Cancel) ──► Pause at HITL Checkpoint (pending_approval)
          │        ├── Direct Resolve (Policy Explanation) ──► Send Resolution Email ──► status: resolved
          │        └── Urgent/Complex ──► Route to Specialist ──► status: escalated
          │
          └── 5. Supervisor Sign-Off (Support Dashboard)
                   └── POST /api/workflow/approve/{ticket_id} ──► Execute MCP Action & Send Email
```

---

## Setup & Running

### 1. Environment Variables
Create a `.env` file in the root directory:
```ini
DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>/<dbname>?sslmode=require
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile
```

### 2. Install Dependencies
```bash
python -m venv venv
venv\Scripts\activate  # On Linux: source venv/bin/activate
pip install -r requirements.txt
```

### 3. Start the Server
```bash
uvicorn app.main:app --reload --port 8000
```
- **Customer Portal**: `http://localhost:8000/`
- **Support Operations Dashboard**: `http://localhost:8000/agent/`
- **Interactive API Docs**: `http://localhost:8000/docs`

---

## Running the Automated Test Suite

Run unit, integration, and benchmark tests with `pytest`:
```bash
pytest -vv
```
