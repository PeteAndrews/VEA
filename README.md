# VEA prototype

Monorepo layout:

- **`backend/`** — Python API, graph, study, CLI (`app/`)
- **`frontend/`** — React marking UI (Vite)

## Backend environment

```powershell
cd backend
conda create -n vea python=3.11 -y
conda activate vea
pip install torch torchvision torchaudio
pip install -r requirements.txt
copy .env.example .env
```

Optional: graph export (`networkx`, `pydot`) and [Graphviz](https://graphviz.org/) on `PATH`:

```powershell
pip install -r requirements-viz.txt
```

Editable install (optional):

```powershell
pip install -e ".[dev]"
```

## Run

**API** (from `backend/`):

```powershell
uvicorn app.api:app --reload --host 127.0.0.1 --port 8000
```

**UI** (from `frontend/`):

```powershell
npm install
npm run dev
```

Open http://localhost:5173

## Tests

From `backend/`:

```powershell
pytest
```

## Recording walkthrough interactions

Set `VEA_RECORD_INTERACTIONS=1` in `backend/.env` (see `.env.example`). Each evidence check, level check, assistant launch, and assistant message is written to `backend/data/recordings/recording_001.json`, `recording_002.json`, and so on. Clear that directory before a capture run, then use the marking UI as usual and edit the JSON by hand.

A recording stores the request and the AI fields the UI renders: intervention type and message, nuance items, suggested evidence, level-review summary, and the new chat messages with their citations. It does not store graph context, earlier conversation history, or tool traces.

These files are git-ignored. Copy any you want to keep into a tracked location before building the walkthrough. One walkthrough step may produce several recordings, or none.

## Paths

Defaults assume you run commands from `backend/`:

- Data: `backend/data/` (`VEA_DATA_DIR`)
- Study config: `backend/config/studies/`
- Prompts: `backend/prompts/`

Override with environment variables (see `backend/.env.example`).
