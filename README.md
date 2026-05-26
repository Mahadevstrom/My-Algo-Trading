# AlgoVyuh

AlgoVyuh is a paper-first trading research terminal for Indian index options. It brings together market-data dashboards, option-chain analysis, paper-trading diagnostics, replay, reports, risk visibility, and learning workflows in one local application.

The project is built for studying decisions, reviewing missed trades, and improving rule-based trading systems. It is not designed to place live broker orders.

## Safety Defaults

AlgoVyuh is configured for research and paper trading.

- `TRADING_MODE=PAPER`
- `ALLOW_LIVE_ORDERS=false`
- `ENABLE_DHAN_ORDER_PLACEMENT=false`
- Live broker execution remains blocked unless the code and environment are deliberately changed.

Do not commit real `.env` files, API keys, access tokens, local databases, generated market-data files, logs, or private trade notes.

## Project Structure

```text
backend/       FastAPI backend, signal engines, paper trading, reports, replay, risk, and data services
frontend-v2/   Angular terminal UI
```

Key backend areas:

- `app/api/` - HTTP route modules
- `app/engine/` - signal, option-chain, paper, risk, and specialist engine code
- `app/services/` - application service layer
- `app/models/` - SQLAlchemy models
- `app/agent_evolution/` - paper-trade learning and recommendation workflow
- `tests/` - backend regression tests

Key frontend areas:

- `src/app/features/` - terminal pages such as dashboard, market chart, market flow, signals, replay, reports, and agent evolution
- `src/app/layout/` - shell/navigation layout

## Requirements

- Windows PowerShell
- Python 3.10+
- Node.js 18+ or 20+
- npm

Optional, depending on your local configuration:

- PostgreSQL for persistent local storage
- Market-data provider credentials in a private `.env`

## Backend Setup

From the repository root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
copy env.template .env
```

Open `backend\.env` and fill only the private values you need, such as broker or AI-provider keys. Keep paper-trading safety flags disabled for live orders.

If you want a simple local SQLite database instead of PostgreSQL, set this in `backend\.env`:

```env
DATABASE_URL=sqlite:///./my_algo_trading.db
```

## Run The Backend

Recommended:

```powershell
cd backend
.\run_backend.ps1
```

The backend starts at:

```text
http://127.0.0.1:8000
```

Useful checks:

```text
http://127.0.0.1:8000/api/health
http://127.0.0.1:8000/docs
```

If port `8000` is already busy, run manually on another port:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
```

If you use a non-default backend port, update the Angular proxy or environment settings to match your local setup.

## Frontend Setup

Open a second PowerShell terminal from the repository root:

```powershell
cd frontend-v2
npm install
```

## Run The Frontend

```powershell
cd frontend-v2
npm start
```

Angular serves the UI at:

```text
http://127.0.0.1:4200
```

The frontend uses `frontend-v2/proxy.conf.json` and local environment configuration to reach the backend during development.

## Run Tests

Backend tests:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m pytest tests/ -v
```

Frontend build:

```powershell
cd frontend-v2
npm run build
```

## Data And Secrets Policy

The repository intentionally ignores:

- `.env` and local credential files
- local SQLite/PostgreSQL runtime data
- generated logs
- virtual environments
- `node_modules`
- Angular build output
- downloaded market-data CSV files
- local research notes and PDFs
- private project logs

Use `env.template` as a template only. Never paste real access tokens or passwords into tracked files.

## Disclaimer

This project is for software research, paper-trading analysis, and personal learning. It is not financial advice and does not guarantee trading performance.
