from app.services.alert_engine import AlertEngine
from app.notifications.telegram import TelegramNotifier
from app.services.market_data_cache import MarketDataCache
from app.services.opportunity_store import OpportunityStore
from app.services.symbol_universe import SymbolUniverseBuilder
from app.services.websocket_market_data import WebSocketMarketDataManager


alert_engine = AlertEngine()
market_data_cache = MarketDataCache()
opportunity_store = OpportunityStore()
symbol_universe_builder = SymbolUniverseBuilder()
telegram_notifier = TelegramNotifier()
websocket_market_data_manager = WebSocketMarketDataManager(market_data_cache)
