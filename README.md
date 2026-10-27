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

## Paths

Defaults assume you run commands from `backend/`:

- Data: `backend/data/` (`VEA_DATA_DIR`)
- Study config: `backend/config/studies/`
- Prompts: `backend/prompts/`

Override with environment variables (see `backend/.env.example`).
