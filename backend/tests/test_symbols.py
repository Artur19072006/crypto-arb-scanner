import unittest

from app.services.symbols import (
    SUPPORTED_NORMALIZED_SYMBOLS,
    is_supported_normalized_symbol,
    normalize_symbol,
    symbol_format_examples,
)


class SymbolNormalizationTests(unittest.TestCase):
    def test_normalizes_current_mock_symbols(self) -> None:
        self.assertEqual(normalize_symbol("BTCUSDT"), "BTCUSDT")
        self.assertEqual(normalize_symbol(" ethusdt "), "ETHUSDT")
        self.assertEqual(normalize_symbol("SOLUSDT"), "SOLUSDT")

    def test_documents_future_exchange_symbol_formats(self) -> None:
        examples = symbol_format_examples()

        self.assertEqual(examples["Binance"], "BTCUSDT")
        self.assertEqual(examples["Bybit"], "BTCUSDT")
        self.assertEqual(examples["OKX"], "BTC-USDT-SWAP")
        self.assertEqual(examples["Gate"], "BTC_USDT")
        self.assertEqual(normalize_symbol(examples["Bybit"]), "BTCUSDT")
        self.assertEqual(normalize_symbol(examples["OKX"]), "BTCUSDT")
        self.assertEqual(normalize_symbol(examples["Gate"]), "BTCUSDT")

    def test_supported_symbols_are_limited_to_current_mock_set(self) -> None:
        self.assertEqual(SUPPORTED_NORMALIZED_SYMBOLS, ("BTCUSDT", "ETHUSDT", "SOLUSDT"))
        self.assertTrue(is_supported_normalized_symbol("BTC-USDT-SWAP"))
        self.assertFalse(is_supported_normalized_symbol("DOGEUSDT"))


if __name__ == "__main__":
    unittest.main()
