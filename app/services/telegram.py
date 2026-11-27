import logging

import httpx

from app.config import settings


logger = logging.getLogger("infrapulse.telegram")


def send_message(message: str) -> bool:

    if not settings.telegram_enabled:
        return False

    if (
        not settings.telegram_bot_token
        or not settings.telegram_chat_id
    ):
        logger.warning(
            "Telegram configuration is incomplete"
        )
        return False

    token = settings.telegram_bot_token.get_secret_value()

    url = (
        f"https://api.telegram.org/"
        f"bot{token}/sendMessage"
    )

    try:
        with httpx.Client(timeout=15.0) as client:

            response = client.post(
                url,
                json={
                    "chat_id": settings.telegram_chat_id,
                    "text": message
                }
            )

            if response.status_code != 200:
                logger.warning(
                    "Telegram HTTP status: %s",
                    response.status_code
                )
                return False

            if not response.json().get("ok"):
                logger.warning(
                    "Telegram rejected message"
                )
                return False

        logger.info("Telegram message sent")
        return True

    except Exception as exc:
        logger.warning(
            "Telegram delivery failed: %s",
            type(exc).__name__
        )

        return False
