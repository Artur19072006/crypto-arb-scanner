from app.models.opportunity import Opportunity


class TelegramNotifier:
    def __init__(self, bot_token: str | None, chat_id: str | None) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id

    async def send_opportunity_alert(self, opportunity: Opportunity) -> bool:
        # TODO: Implement Telegram Bot API call after alert filtering is in place.
        # Keep this optional so local development works without secrets.
        if not self.bot_token or not self.chat_id:
            return False

        _ = opportunity
        return False
