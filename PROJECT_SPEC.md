# PROJECT_SPEC.md — Crypto Arbitrage Scanner

## Project idea

A local web application and Telegram alert bot for monitoring arbitrage opportunities between USDT perpetual futures markets on multiple crypto exchanges.

The app is for personal use and runs locally on localhost.

## Core strategy

The scanner looks for price differences between the same perpetual futures contract on different exchanges.

Example:

* Buy / long on the exchange with the lower ask price
* Sell / short on the exchange with the higher bid price
* Potential profit appears if the spread later narrows or prices converge

The scanner does not execute trades automatically. It only detects and displays potential opportunities.

## Main market type

Only USDT perpetual futures for the first version.

Quarterly futures, spot-futures, DEX/CEX arbitrage, and triangular arbitrage are not part of the first version.

## Spread calculation

The scanner should use bid/ask data, not last price.

Long side:

* Use the lowest ask price among selected exchanges

Short side:

* Use the highest bid price among selected exchanges

Raw spread formula:
raw_spread_percent = (highest_bid - lowest_ask) / lowest_ask * 100

## Net spread calculation

Net spread should estimate the spread after trading fees.

Fees must include:

* Long open fee
* Short open fee
* Long close fee
* Short close fee

Fees should be configurable per exchange and should support maker and taker values.

For Telegram alerts, the conservative taker/taker estimate should be preferred.

## Liquidity logic

The scanner should show liquidity information but should not be too restrictive in MVP.

Important values:

* 24h volume
* Best bid size
* Best ask size
* Approximate depth near current price
* Liquidity status: OK / Thin / Holey

For the first version, slippage should not be used as a strict filter.

Later versions may calculate effective execution price for a selected position size.

## User situation and default filter ideas

The user has around 3000 USD trading capital and wants to start testing with very small positions, around 100 USD first.

The app should allow filtering medium-risk tokens.

Default ideas:

* Minimum 24h volume: 400,000 USD
* Position check reference: up to 1,500 USD
* Depth reference: around 2,000 USD
* Minimum raw spread: configurable
* Minimum net spread: configurable

These values must be editable in the UI or config.

## Funding rate

Funding rate should be displayed in the first version.

For each opportunity, show:

* Funding on long exchange
* Funding on short exchange
* Funding difference
* Next funding time, if available
* Funding impact label: Good / Neutral / Bad

Funding impact should not automatically block signals in MVP.

## Telegram alerts

Telegram bot should send alerts only when an opportunity passes filters.

Alert message should include:

* Pair
* Long exchange
* Short exchange
* Ask price
* Bid price
* Raw spread
* Estimated net spread
* 24h volume
* Funding data
* Liquidity status
* Timestamp

Add cooldown per pair/opportunity to avoid spam.

## Frontend

Local web UI should include:

* Main opportunities table
* Exchange filter
* Min volume filter
* Min raw spread filter
* Min net spread filter
* Blacklist
* Funding display
* Liquidity display
* Spread history chart

Design can be minimal. Functionality is more important than visual design.

## Database

Use SQLite for MVP.

Store:

* Spread history
* Alert history
* User settings
* Blacklist
* Fees configuration if needed

History target:

* At least 7 days of spread history

## Development roadmap

1. Create project skeleton
2. Add backend API with fake opportunities
3. Add frontend table with fake data
4. Add settings and filters
5. Add SQLite storage
6. Add Telegram test notification
7. Add Binance connector
8. Add Bybit connector
9. Implement real Binance ↔ Bybit spread calculation
10. Add fees and net spread
11. Add funding display
12. Add spread history chart
13. Add OKX
14. Add Bitget
15. Add Gate
16. Add KuCoin
17. Improve order book depth and liquidity quality
