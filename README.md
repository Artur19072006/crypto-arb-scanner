# Crypto Perpetual Futures Arbitrage Scanner

Local-first scanner skeleton for USDT perpetual futures arbitrage opportunities.

This version uses mock bid/ask data only. It does not connect to real exchanges, place trades, use API keys, or send Telegram messages.

## Current Scope

- FastAPI backend with an `/api/opportunities` endpoint
- Mock opportunity generation from bid/ask snapshots
- React + Vite frontend with a table view
- SQLite-ready folder and database placeholder
- Config example for fees, filters, blacklist, and Telegram settings
- Placeholder Telegram notifier that does nothing without future implementation
- TODO comments for future exchange connectors

## Project Structure

```text
backend/
  app/
    api/              FastAPI routes
    connectors/       Exchange connector interfaces and fake connector
    core/             Settings placeholder
    db/               SQLite placeholder
    models/           API response models
    notifications/    Telegram placeholder
    services/         Mock scanner logic
frontend/
  src/                React app
config/
  config.example.yaml Fees, filters, blacklist, Telegram settings
data/                 Local SQLite data directory
```

## Backend Startup

From the repository root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Backend URL:

```text
http://127.0.0.1:8000
```

Mock opportunities endpoint:

```text
http://127.0.0.1:8000/api/opportunities
```

## Frontend Startup

Open a second terminal from the repository root:

```powershell
cd frontend
npm install
npm run dev
```

If PowerShell blocks `npm.ps1`, use:

```powershell
npm.cmd install
npm.cmd run dev
```

Frontend URL:

```text
http://127.0.0.1:5173
```

Vite proxies `/api` requests to the backend at `http://127.0.0.1:8000`.

## Configuration

Copy the examples before adding local secrets or custom settings:

```powershell
Copy-Item .env.example .env
Copy-Item config\config.example.yaml config\config.yaml
```

Telegram settings are placeholders for now. Do not commit real bot tokens or chat IDs.

The backend reads `config/config.yaml` when it exists. If it does not exist, it falls back to `config/config.example.yaml`, then to built-in safe defaults.

Frontend-safe settings are exposed at:

```text
http://127.0.0.1:8000/api/settings
```

## Development Notes

- Spread logic must use bid/ask data, not last traded price.
- Long side is the lowest ask.
- Short side is the highest bid.
- Raw spread is `(highest_bid - lowest_ask) / lowest_ask * 100`.
- Net spread currently uses a conservative mock taker-fee estimate.
- Real exchange WebSocket connectors should be added later, starting with Binance and then Bybit.
