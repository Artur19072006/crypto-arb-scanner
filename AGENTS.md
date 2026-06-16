# AGENTS.md — Project Instructions for Codex

## Project name

Crypto Perpetual Futures Arbitrage Scanner

## Main goal

Build a local-first arbitrage scanner for USDT perpetual futures. The app monitors selected crypto exchanges, compares bid/ask prices between exchanges, calculates raw and net spreads, applies user-defined filters, shows opportunities in a local web UI, and sends Telegram alerts when a valid spread appears.

## Important trading logic

This project must NOT compare last traded prices as the main spread source.

The scanner must use order book / ticker bid-ask data:

* Long side: cheapest ask price
* Short side: highest bid price
* Raw spread = (highest_bid - lowest_ask) / lowest_ask * 100

The scanner should focus on realistic opportunities, not just the biggest displayed spread.

## Supported exchanges for MVP roadmap

Initial target exchanges:

* Binance USDT perpetual futures
* Bybit USDT perpetual futures
* OKX USDT perpetual futures
* Bitget USDT perpetual futures
* Gate USDT perpetual futures
* KuCoin USDT perpetual futures

Do not implement all exchanges at once. Start with fake data, then Binance, then Bybit, then add more exchanges one by one.

## MVP scope

The first real MVP should include:

* Local backend
* Local frontend
* Real-time bid/ask data
* Raw spread calculation
* Estimated net spread after fees
* Configurable fees per exchange
* Funding rate display
* 24h volume filter
* Exchange filter
* Spread filter
* Blacklist
* Telegram alerts
* Spread history storage
* Basic chart for spread history

## Out of scope for MVP

Do not implement:

* Automatic trading
* API key trading
* Order execution
* User authentication
* Deposits/withdrawals
* DEX/CEX arbitrage
* Triangular arbitrage
* Complex strategy optimization

## Safety and design principles

* This is a scanner, not an auto-trading bot.
* Never add real trading execution unless explicitly requested later.
* Keep architecture modular.
* Each exchange should have its own connector.
* Do not hardcode secrets or Telegram tokens.
* Use environment variables for secrets.
* Prefer simple, maintainable code over over-engineered solutions.
* Add clear comments where logic is trading-specific.
* Keep the UI minimal but useful.

## Preferred tech stack

Backend:

* Python
* FastAPI
* asyncio
* websockets / aiohttp
* SQLite for MVP

Frontend:

* React + Vite
* Simple table-based UI
* Basic charts for spread history

Config:

* .env for secrets
* config.yaml or JSON for fees, filters, and app settings

## Development style

Work in small steps.
Before implementing a large feature, explain the plan briefly.
After changes, summarize:

* What was changed
* Which files were modified
* How to run/test it
* Any known limitations

Do not rewrite the whole project unless necessary.
Prefer small, high-confidence changes.
