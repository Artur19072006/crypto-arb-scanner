import json
import unittest

from app.connectors.websocket import (
    BinanceBookTickerWebSocketConnector,
    BitgetTickerWebSocketConnector,
    BybitTickerWebSocketConnector,
    GateBookTickerWebSocketConnector,
    OKXTickerWebSocketConnector,
    build_public_websocket_connectors,
    parse_binance_book_ticker_message,
    parse_bitget_ticker_message,
    parse_bybit_ticker_message,
    parse_gate_book_ticker_message,
    parse_okx_ticker_message,
)


class WebSocketConnectorParsingTests(unittest.TestCase):
    def test_binance_book_ticker_message_maps_top_of_book_snapshot(self) -> None:
        snapshot = parse_binance_book_ticker_message(
            json.dumps(
                {
                    "e": "bookTicker",
                    "E": 1710000000000,
                    "s": "btcusdt",
                    "b": "65000.10",
                    "B": "1.25",
                    "a": "65001.20",
                    "A": "0.75",
                    "st": 1,
                }
            )
        )

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.exchange, "Binance")
        self.assertEqual(snapshot.symbol, "BTCUSDT")
        self.assertEqual(snapshot.best_bid, 65000.10)
        self.assertEqual(snapshot.best_bid_size, 1.25)
        self.assertEqual(snapshot.best_ask, 65001.20)
        self.assertEqual(snapshot.best_ask_size, 0.75)
        self.assertEqual(snapshot.source, "websocket")

    def test_binance_book_ticker_ignores_coin_m_symbol_type(self) -> None:
        snapshot = parse_binance_book_ticker_message(
            json.dumps(
                {
                    "s": "BTCUSD_PERP",
                    "b": "65000.10",
                    "B": "1.25",
                    "a": "65001.20",
                    "A": "0.75",
                    "st": 2,
                }
            )
        )

        self.assertIsNone(snapshot)

    def test_binance_stream_url_uses_lowercase_book_ticker_topics(self) -> None:
        connector = BinanceBookTickerWebSocketConnector(
            base_url="wss://example.invalid/public/ws"
        )

        self.assertEqual(
            connector._stream_url(("BTCUSDT", "ETHUSDT")),
            "wss://example.invalid/public/ws/btcusdt@bookTicker/ethusdt@bookTicker",
        )

    def test_bybit_ticker_message_maps_top_of_book_snapshot(self) -> None:
        snapshot = parse_bybit_ticker_message(
            json.dumps(
                {
                    "topic": "tickers.BTCUSDT",
                    "type": "snapshot",
                    "ts": 1710000000000,
                    "data": {
                        "symbol": "BTCUSDT",
                        "bid1Price": "65010.50",
                        "bid1Size": "1.20",
                        "ask1Price": "65011.00",
                        "ask1Size": "0.80",
                        "turnover24h": "123456789.10",
                        "fundingRate": "0.00010000",
                        "nextFundingTime": "1710003600000",
                    },
                }
            )
        )

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.exchange, "Bybit")
        self.assertEqual(snapshot.symbol, "BTCUSDT")
        self.assertEqual(snapshot.best_bid, 65010.50)
        self.assertEqual(snapshot.best_bid_size, 1.20)
        self.assertEqual(snapshot.best_ask, 65011.00)
        self.assertEqual(snapshot.best_ask_size, 0.80)
        self.assertEqual(snapshot.volume_24h_usd, 123456789.10)
        self.assertEqual(snapshot.funding_rate_percent, 0.01)
        self.assertEqual(snapshot.source, "websocket")

    def test_bybit_ticker_delta_uses_previous_snapshot_fields(self) -> None:
        state: dict[str, dict[str, object]] = {}
        first = parse_bybit_ticker_message(
            json.dumps(
                {
                    "topic": "tickers.BTCUSDT",
                    "type": "snapshot",
                    "data": {
                        "symbol": "BTCUSDT",
                        "bid1Price": "65010.50",
                        "bid1Size": "1.20",
                        "ask1Price": "65011.00",
                        "ask1Size": "0.80",
                    },
                }
            ),
            state,
        )
        second = parse_bybit_ticker_message(
            json.dumps(
                {
                    "topic": "tickers.BTCUSDT",
                    "type": "delta",
                    "data": {
                        "symbol": "BTCUSDT",
                        "bid1Price": "65012.00",
                    },
                }
            ),
            state,
        )

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(second.best_bid, 65012.00)
        self.assertEqual(second.best_ask, 65011.00)

    def test_bybit_connector_parse_message_keeps_delta_state(self) -> None:
        connector = BybitTickerWebSocketConnector()
        first = connector.parse_message(
            json.dumps(
                {
                    "topic": "tickers.ETHUSDT",
                    "type": "snapshot",
                    "data": {
                        "symbol": "ETHUSDT",
                        "bid1Price": "3500.00",
                        "ask1Price": "3501.00",
                    },
                }
            )
        )
        second = connector.parse_message(
            json.dumps(
                {
                    "topic": "tickers.ETHUSDT",
                    "type": "delta",
                    "data": {
                        "symbol": "ETHUSDT",
                        "ask1Price": "3502.00",
                    },
                }
            )
        )

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(second.best_bid, 3500.00)
        self.assertEqual(second.best_ask, 3502.00)

    def test_bybit_subscription_ack_is_ignored(self) -> None:
        snapshot = parse_bybit_ticker_message(
            json.dumps({"op": "subscribe", "success": True})
        )

        self.assertIsNone(snapshot)

    def test_okx_ticker_message_maps_top_of_book_snapshot(self) -> None:
        snapshot = parse_okx_ticker_message(
            json.dumps(
                {
                    "arg": {
                        "channel": "tickers",
                        "instId": "BTC-USDT-SWAP",
                    },
                    "data": [
                        {
                            "instType": "SWAP",
                            "instId": "BTC-USDT-SWAP",
                            "last": "65012.00",
                            "bidPx": "65010.50",
                            "bidSz": "1.20",
                            "askPx": "65011.00",
                            "askSz": "0.80",
                            "volCcy24h": "10.5",
                            "ts": "1710000000000",
                        }
                    ],
                }
            )
        )

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.exchange, "OKX")
        self.assertEqual(snapshot.symbol, "BTCUSDT")
        self.assertEqual(snapshot.best_bid, 65010.50)
        self.assertEqual(snapshot.best_bid_size, 1.20)
        self.assertEqual(snapshot.best_ask, 65011.00)
        self.assertEqual(snapshot.best_ask_size, 0.80)
        self.assertEqual(snapshot.volume_24h_usd, 682626.0)
        self.assertEqual(snapshot.source, "websocket")

    def test_okx_ticker_message_normalizes_swap_symbol(self) -> None:
        snapshot = parse_okx_ticker_message(
            json.dumps(
                {
                    "data": [
                        {
                            "instId": "ETH-USDT-SWAP",
                            "bidPx": "3500.00",
                            "bidSz": "2.0",
                            "askPx": "3501.00",
                            "askSz": "3.0",
                            "ts": "1710000000000",
                        }
                    ],
                }
            )
        )

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.symbol, "ETHUSDT")

    def test_okx_ticker_ignores_non_usdt_swap_symbol(self) -> None:
        snapshot = parse_okx_ticker_message(
            json.dumps(
                {
                    "data": [
                        {
                            "instType": "SWAP",
                            "instId": "BTC-USD-SWAP",
                            "bidPx": "65010.50",
                            "askPx": "65011.00",
                        }
                    ],
                }
            )
        )

        self.assertIsNone(snapshot)

    def test_okx_subscription_ack_is_ignored(self) -> None:
        snapshot = parse_okx_ticker_message(
            json.dumps(
                {
                    "event": "subscribe",
                    "arg": {
                        "channel": "tickers",
                        "instId": "BTC-USDT-SWAP",
                    },
                }
            )
        )

        self.assertIsNone(snapshot)

    def test_okx_inst_ids_use_swap_symbol_format(self) -> None:
        connector = OKXTickerWebSocketConnector()

        self.assertEqual(
            connector._subscription_args(("BTCUSDT", "ETH-USDT-SWAP")),
            [
                {"channel": "tickers", "instId": "BTC-USDT-SWAP"},
                {"channel": "tickers", "instId": "ETH-USDT-SWAP"},
            ],
        )

    def test_bitget_ticker_message_maps_top_of_book_snapshot(self) -> None:
        snapshot = parse_bitget_ticker_message(
            json.dumps(
                {
                    "arg": {
                        "instType": "USDT-FUTURES",
                        "channel": "ticker",
                        "instId": "BTCUSDT",
                    },
                    "action": "snapshot",
                    "data": [
                        {
                            "instId": "BTCUSDT",
                            "symbol": "btcusdt",
                            "bidPr": "65010.50",
                            "bidSz": "1.20",
                            "askPr": "65011.00",
                            "askSz": "0.80",
                            "quoteVolume": "123456789.10",
                            "usdtVolume": "123456790.20",
                            "fundingRate": "0.00010000",
                            "nextFundingTime": "1710003600000",
                            "symbolType": "1",
                            "ts": "1710000000000",
                        }
                    ],
                    "ts": 1710000000001,
                }
            )
        )

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.exchange, "Bitget")
        self.assertEqual(snapshot.symbol, "BTCUSDT")
        self.assertEqual(snapshot.best_bid, 65010.50)
        self.assertEqual(snapshot.best_bid_size, 1.20)
        self.assertEqual(snapshot.best_ask, 65011.00)
        self.assertEqual(snapshot.best_ask_size, 0.80)
        self.assertEqual(snapshot.volume_24h_usd, 123456790.20)
        self.assertEqual(snapshot.funding_rate_percent, 0.01)
        self.assertIsNotNone(snapshot.next_funding_time)
        self.assertEqual(snapshot.source, "websocket")

    def test_bitget_ticker_message_normalizes_symbol_from_arg_inst_id(self) -> None:
        snapshot = parse_bitget_ticker_message(
            json.dumps(
                {
                    "arg": {
                        "instType": "USDT-FUTURES",
                        "channel": "ticker",
                        "instId": "ETHUSDT",
                    },
                    "data": [
                        {
                            "bidPr": "3500.00",
                            "askPr": "3501.00",
                            "bidSz": "2.0",
                            "askSz": "3.0",
                            "ts": "1710000000000",
                        }
                    ],
                }
            )
        )

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.symbol, "ETHUSDT")

    def test_bitget_ticker_ignores_delivery_symbol_type(self) -> None:
        snapshot = parse_bitget_ticker_message(
            json.dumps(
                {
                    "arg": {
                        "instType": "USDT-FUTURES",
                        "channel": "ticker",
                        "instId": "BTCUSDT_260327",
                    },
                    "data": [
                        {
                            "instId": "BTCUSDT_260327",
                            "bidPr": "65010.50",
                            "askPr": "65011.00",
                            "symbolType": "2",
                        }
                    ],
                }
            )
        )

        self.assertIsNone(snapshot)

    def test_bitget_subscription_ack_and_pong_are_ignored(self) -> None:
        self.assertIsNone(parse_bitget_ticker_message("pong"))
        self.assertIsNone(
            parse_bitget_ticker_message(
                json.dumps(
                    {
                        "event": "subscribe",
                        "arg": {
                            "instType": "USDT-FUTURES",
                            "channel": "ticker",
                            "instId": "BTCUSDT",
                        },
                    }
                )
            )
        )

    def test_bitget_subscription_args_use_public_futures_ticker_channel(self) -> None:
        connector = BitgetTickerWebSocketConnector()

        self.assertEqual(
            connector._subscription_args(("btcusdt", "ETHUSDT", "BTCUSDC", "BTCUSDT_260327")),
            [
                {
                    "instType": "USDT-FUTURES",
                    "channel": "ticker",
                    "instId": "BTCUSDT",
                },
                {
                    "instType": "USDT-FUTURES",
                    "channel": "ticker",
                    "instId": "ETHUSDT",
                },
            ],
        )

    def test_gate_book_ticker_message_maps_top_of_book_snapshot(self) -> None:
        snapshot = parse_gate_book_ticker_message(
            json.dumps(
                {
                    "time": 1615366379,
                    "time_ms": 1615366379123,
                    "channel": "futures.book_ticker",
                    "event": "update",
                    "result": {
                        "t": 1615366379123,
                        "u": 2517661076,
                        "s": "BTC_USDT",
                        "b": "54696.6",
                        "B": "37000",
                        "a": "54696.7",
                        "A": "47061",
                    },
                }
            )
        )

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.exchange, "Gate")
        self.assertEqual(snapshot.symbol, "BTCUSDT")
        self.assertEqual(snapshot.best_bid, 54696.6)
        self.assertEqual(snapshot.best_bid_size, 37000.0)
        self.assertEqual(snapshot.best_ask, 54696.7)
        self.assertEqual(snapshot.best_ask_size, 47061.0)
        self.assertEqual(snapshot.volume_24h_usd, 0)
        self.assertEqual(snapshot.funding_rate_percent, 0)
        self.assertEqual(snapshot.source, "websocket")

    def test_gate_book_ticker_message_normalizes_symbol(self) -> None:
        snapshot = parse_gate_book_ticker_message(
            json.dumps(
                {
                    "channel": "futures.book_ticker",
                    "event": "update",
                    "result": {
                        "s": "ETH_USDT",
                        "b": "3500.00",
                        "B": "2.0",
                        "a": "3501.00",
                        "A": "3.0",
                    },
                }
            )
        )

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.symbol, "ETHUSDT")

    def test_gate_book_ticker_ignores_empty_or_non_usdt_book_ticker(self) -> None:
        self.assertIsNone(
            parse_gate_book_ticker_message(
                json.dumps(
                    {
                        "channel": "futures.book_ticker",
                        "event": "update",
                        "result": {
                            "s": "BTC_USDT",
                            "b": "",
                            "B": "0",
                            "a": "54696.7",
                            "A": "47061",
                        },
                    }
                )
            )
        )
        self.assertIsNone(
            parse_gate_book_ticker_message(
                json.dumps(
                    {
                        "channel": "futures.book_ticker",
                        "event": "update",
                        "result": {
                            "s": "BTC_USD",
                            "b": "54696.6",
                            "a": "54696.7",
                        },
                    }
                )
            )
        )

    def test_gate_subscription_ack_is_ignored(self) -> None:
        snapshot = parse_gate_book_ticker_message(
            json.dumps(
                {
                    "channel": "futures.book_ticker",
                    "event": "subscribe",
                    "result": {"status": "success"},
                }
            )
        )

        self.assertIsNone(snapshot)

    def test_gate_subscription_payload_uses_public_futures_book_ticker_contracts(self) -> None:
        connector = GateBookTickerWebSocketConnector()

        self.assertEqual(
            connector._subscription_payload(
                ("btcusdt", "ETH_USDT", "BTCUSDC", "BTC_USDT_260327")
            ),
            ("BTC_USDT", "ETH_USDT"),
        )

    def test_build_public_websocket_connectors_includes_gate_when_enabled(self) -> None:
        connectors = build_public_websocket_connectors(
            ("gate",),
            reconnect_seconds=5,
        )

        self.assertEqual([connector.name for connector in connectors], ["gate"])
        self.assertIsInstance(connectors[0], GateBookTickerWebSocketConnector)


if __name__ == "__main__":
    unittest.main()
