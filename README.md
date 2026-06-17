# Crypto Perpetual Futures Arbitrage Scanner

Local-first scanner skeleton for USDT perpetual futures arbitrage opportunities.

This version defaults to mock bid/ask data. Optional live mode uses Binance, Bybit, and OKX public market-data endpoints only. It does not place trades, use exchange API keys, or call private/account endpoints. Telegram notifications are optional and only send Alert Engine candidates.

## Current Scope

- FastAPI backend with an `/api/opportunities` endpoint
- Mock opportunity generation from bid/ask snapshots
- React + Vite frontend with a table view
- SQLite-ready folder and database placeholder
- Config example for fees, filters, blacklist, alert rules, and Telegram settings
- Optional Telegram notifier for active Alert Engine candidates
- Connector registry with fake connector in mock mode and optional Binance/Bybit/OKX public connectors in live mode
- Optional public REST order book depth validation for top opportunities
- Internal Alert Engine v1 for selecting notification-worthy opportunities without sending messages

## Project Structure

```text
backend/
  app/
    api/              FastAPI routes
    connectors/       Exchange connector interface, registry, and fake connector
    core/             Settings placeholder
    db/               SQLite placeholder
    models/           API response models
    notifications/    Telegram notifier
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

## Local Development Scripts

After the backend virtual environment and frontend dependencies are installed, these PowerShell helpers can start the app from the repository root:

```powershell
.\scripts\start-backend.ps1
```

```powershell
.\scripts\start-frontend.ps1
```

```powershell
.\scripts\start-dev.ps1
```

To stop local dev servers listening on the default backend/frontend ports:

```powershell
.\scripts\stop-dev.ps1
```

You can also pass explicit ports:

```powershell
.\scripts\stop-dev.ps1 -Ports 8000,5173,5174
```

`start-backend.ps1` loads environment variables from a local `.env` file when it exists, without printing the values. Keep real Telegram credentials only in `.env` or your shell environment. `.env.example` should contain safe placeholders only:

```text
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

`start-dev.ps1` opens the backend and frontend in separate PowerShell windows.

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

Telegram settings use environment variable names only. Do not commit real bot tokens or chat IDs.

The backend reads `config/config.yaml` when it exists. If it does not exist, it falls back to `config/config.example.yaml`, then to built-in safe defaults.

`data_source_mode` defaults to `mock`. Live mode currently supports Binance, Bybit, and OKX public market-data connectors.
`depth_check.enabled` defaults to `false`, so the scanner avoids extra REST calls unless you explicitly enable depth validation.
`alerts.enabled` defaults to `false`, so no alert candidates are generated unless you explicitly enable the internal alert engine.

Frontend-safe settings are exposed at:

```text
http://127.0.0.1:8000/api/settings
```

The backend starts a mock in-memory scanner loop on startup. It refreshes fake market snapshots every few seconds, recalculates opportunities, and exposes scanner state at:

```text
http://127.0.0.1:8000/api/status
```

## Connector Architecture

- `ExchangeConnector` defines `name`, `data_source`, and `fetch_snapshots()`.
- `ConnectorRegistry` registers available connectors.
- Current active mock connector: `FakeExchangeConnector`.
- Optional live connectors: `BinancePublicConnector`, `BybitPublicConnector`, and `OKXPublicConnector` for public REST market data.
- Future real connectors such as Bitget, Gate, and KuCoin should be registered through the registry after they exist.
- Symbol normalization currently supports mock symbols such as `BTCUSDT`, `ETHUSDT`, and `SOLUSDT`.
- Exchange format examples: Binance `BTCUSDT`, Bybit `BTCUSDT`, OKX `BTC-USDT-SWAP`, Gate `BTC_USDT`.

Private/account endpoints, exchange API keys, order execution, and automatic trading are intentionally not implemented.

## Public Live Mode

To test Binance and Bybit public market data with the manual allowlist, edit `config/config.yaml`:

```yaml
data_source_mode: live
enabled_connectors:
  - binance
  - bybit
max_symbols: 3
symbol_allowlist:
  - BTCUSDT
  - ETHUSDT
  - SOLUSDT
symbol_selection:
  mode: manual
```

To let the scanner build the Binance/Bybit symbol universe automatically:

```yaml
data_source_mode: live
enabled_connectors:
  - binance
  - bybit
symbol_selection:
  mode: auto
  min_volume_24h_usd: 400000
  max_volume_24h_usd: 50000000
  max_symbols: 100
  min_exchanges_required: 2
  include_symbols: []
  exclude_symbols:
    - BTCUSDT
    - ETHUSDT
```

To include OKX public USDT swaps as a third scanner source:

```yaml
data_source_mode: live
enabled_connectors:
  - binance
  - bybit
  - okx
symbol_selection:
  mode: auto
  min_volume_24h_usd: 400000
  max_volume_24h_usd: 50000000
  max_symbols: 100
  min_exchanges_required: 2
  include_symbols: []
  exclude_symbols:
    - BTCUSDT
    - ETHUSDT
```

Restart the backend after changing config. Live mode uses public REST market data by default.

## Market Data Mode

REST polling remains the default and safest mode:

```yaml
market_data:
  mode: rest
  websocket:
    enabled: false
```

To test public WebSocket top-of-book updates for Binance and Bybit, keep `data_source_mode: live` and enable:

```yaml
market_data:
  mode: websocket
  websocket:
    enabled: true
    exchanges:
      - binance
      - bybit
    reconnect_seconds: 5
    stale_after_seconds: 20
```

WebSocket mode still uses REST for symbol selection, funding context, depth checks, OKX live data, and fallback when a WebSocket snapshot is missing or stale.

## Optional Depth Check

The scanner normally calculates spreads from public best bid/ask ticker data. The optional depth check fetches public REST order book levels for only the top configured opportunities and estimates whether a target USD notional can be filled on both legs:

- Long side: consume asks from cheapest to higher prices.
- Short side: consume bids from highest to lower prices.
- Effective prices are weighted averages across the consumed levels.
- Depth-adjusted spread uses those effective prices and subtracts the existing fee estimate for depth-adjusted net spread.

This is still only an estimate. Public books can change before any manual action, REST snapshots can be stale by the time they are displayed, and the scanner still does not place orders, reserve liquidity, use account data, or know your actual execution fees/slippage.

Depth checks are disabled by default to avoid extra REST traffic:

```yaml
depth_check:
  enabled: true
  target_notional_usd: 1000
  max_opportunities_to_check: 10
  order_book_limit: 50
  max_allowed_slippage_percent: 0.3
```

When enabled, rows with depth data show status `OK`, `Thin`, `Insufficient`, or `Unknown`. `Unknown` means the opportunity is kept but at least one public depth request failed or no public depth connector was available.

## Alert Engine

Alert Engine v1 is an internal scanner-only layer. It evaluates the latest arbitrage opportunities and selects candidates that are worth notifying about. It does not place trades, use exchange API keys, or call private/account endpoints.

Alert filtering uses:

- Estimated net spread when no depth result exists.
- Depth-adjusted net spread when depth data exists.
- Required depth status, usually `OK` or `Thin`.
- Minimum 24h volume.
- Funding and liquidity context as score adjustments.
- Cooldown per `symbol + long_exchange + short_exchange`.
- A maximum number of active alert candidates per scan.

Cooldown prevents repeated candidates for the same opportunity key during repeated scanner refreshes. Suppressed candidates are kept in in-memory history for debugging, while `/api/alerts` returns only currently active candidates.

Enable alerts in `config/config.yaml`:

```yaml
alerts:
  enabled: true
  min_net_spread_percent: 0.15
  min_depth_adjusted_net_spread_percent: 0.05
  require_depth_status:
    - OK
    - Thin
  max_allowed_slippage_percent: 0.3
  min_volume_24h_usd: 400000
  cooldown_seconds: 300
  max_alerts_per_scan: 5
```

Alert endpoints:

```text
http://127.0.0.1:8000/api/alerts
http://127.0.0.1:8000/api/alerts/history
http://127.0.0.1:8000/api/alerts/status
```

## Telegram Notifications

Telegram Notifier v1 sends messages only for active Alert Engine candidates. It never sends raw opportunities directly and never sends suppressed alerts.

Telegram deduplication uses the stable alert key:

```text
symbol + long_exchange + short_exchange
```

The notifier tracks the last send time for each alert key in memory and respects `alerts.cooldown_seconds`. If the same opportunity remains active across repeated scanner refreshes, Telegram sends it once during the cooldown window. After the cooldown expires, the same still-active alert may be sent again. This in-memory state resets when the backend restarts.

Set credentials as environment variables. For PowerShell:

```powershell
$env:TELEGRAM_BOT_TOKEN="123456:replace-with-your-token"
$env:TELEGRAM_CHAT_ID="123456789"
```

You can also copy `.env.example` to `.env` for local development and fill in local values. Do not commit `.env`.

Enable Telegram in `config/config.yaml`:

```yaml
telegram:
  enabled: true
  bot_token_env: TELEGRAM_BOT_TOKEN
  chat_id_env: TELEGRAM_CHAT_ID
  parse_mode: HTML
  timeout_seconds: 10
```

Telegram status is available at:

```text
http://127.0.0.1:8000/api/telegram/status
```

The status endpoint reports whether Telegram is enabled/configured, last send time, sent count, tracked alert-key count, and last error. It never returns the bot token or chat ID.

Safety note: Telegram is notification-only. It does not create orders, execute trades, or access exchange account/private APIs.

Binance USD-M Futures public endpoints:

- Exchange metadata: `/fapi/v1/exchangeInfo`
- Best bid/ask: `/fapi/v1/ticker/bookTicker`
- Order book depth: `/fapi/v1/depth`
- 24h quote volume: `/fapi/v1/ticker/24hr`
- Funding context: `/fapi/v1/premiumIndex`

Bybit V5 public endpoints:

- Linear contract metadata: `/v5/market/instruments-info`
- Linear ticker bid/ask, turnover, and funding context: `/v5/market/tickers`
- Linear order book depth: `/v5/market/orderbook`

OKX public endpoints:

- Swap metadata: `/api/v5/public/instruments?instType=SWAP`
- Swap ticker bid/ask and 24h volume context: `/api/v5/market/tickers?instType=SWAP`
- Swap order book depth: `/api/v5/market/books`
- Funding context: `/api/v5/public/funding-rate`

With only one live connector active, cross-exchange arbitrage opportunities will usually be empty because the spread engine needs at least two exchanges for the same symbol.

## Development Notes

- Spread logic must use bid/ask data, not last traded price.
- Long side is the lowest ask.
- Short side is the highest bid.
- Raw spread is `(highest_bid - lowest_ask) / lowest_ask * 100`.
- Net spread currently uses a conservative mock taker-fee estimate.
- Depth-adjusted spread is an optional public-book estimate for a configured notional, not execution logic.
- Additional real exchange market-data connectors should be added later, starting with Bitget.
