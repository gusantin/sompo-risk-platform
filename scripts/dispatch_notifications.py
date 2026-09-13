"""Run explicitly under a scheduler; no delivery occurs on application startup."""

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    if os.getenv("TELEGRAM_NOTIFICATIONS_ENABLED", "false").lower() != "true":
        raise SystemExit("Telegram notifications are disabled.")
    if not os.getenv("TELEGRAM_BOT_TOKEN") or not os.getenv("TELEGRAM_CHAT_ID"):
        raise SystemExit("Configure Telegram credentials in the worker environment.")
    from server import notifications
    try:
        from server import alerts
        # Explicit worker repair: a temporary outbox failure must not lose a persisted alert.
        for alert in alerts.list(limit=100):
            notifications.enqueue(alert)
        notifications.deliver_pending()
        # Covers a resolution that occurred while the original send was in flight.
        for alert in alerts.list({"status": "resolved"}, limit=100):
            notifications.enqueue(alert)
    except Exception:
        raise SystemExit("Notification worker unavailable; inspect safe persisted delivery state.") from None
