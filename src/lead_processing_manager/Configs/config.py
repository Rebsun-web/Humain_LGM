import os
from dataclasses import dataclass
from dotenv import load_dotenv
from typing import Optional

load_dotenv(override=True)

print(f"DEBUG CONFIG: WHATSAPP_API_TOKEN from env: {os.getenv('WHATSAPP_API_TOKEN', 'NOT FOUND')[:20]}...")


def get_env_bool(key: str, default: bool = False) -> bool:
    """Safely get a boolean from environment variables."""
    value = os.getenv(key)
    if value is None or value == '':
        return default
    return value.lower() in ('true', '1', 'yes', 'on')


def get_env_int(key: str, default: int) -> int:
    """Safely get an integer from environment variables."""
    value = os.getenv(key)
    if value is None or value == '':
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass
class Config:
    
    # Use templates for speed vs GPT for personalization
    USE_TEMPLATES: bool = False

    # Feature flags
    WHATSAPP_ENABLED: bool = True
    EMAIL_ENABLED: bool = True
    TELEGRAM_ENABLED: bool = True
    
    # WhatsApp test mode
    WHATSAPP_TEST_MODE: bool = get_env_bool("WHATSAPP_TEST_MODE", False)
    WHATSAPP_RATE_LIMITER: Optional[object] = None

    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    
    # Email Configuration
    EMAIL_TEST_MODE: bool = get_env_bool("EMAIL_TEST_MODE", False)
    EMAIL_ADDRESS: str = os.getenv("EMAIL_ADDRESS", "")
    EMAIL_PASSWORD: str = os.getenv("EMAIL_PASSWORD", "")
    EMAIL_SMTP_SERVER: str = os.getenv("EMAIL_SMTP_SERVER", "smtp.gmail.com")
    EMAIL_SMTP_PORT: int = get_env_int("EMAIL_SMTP_PORT", 587)
    EMAIL_IMAP_SERVER: str = os.getenv("EMAIL_IMAP_SERVER", "imap.gmail.com")

    # WhatsApp Business API
    WHATSAPP_API_URL: str = os.getenv("WHATSAPP_API_URL", "")
    WHATSAPP_API_TOKEN: str = os.getenv("WHATSAPP_API_TOKEN", "")
    WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    WHATSAPP_WEBHOOK_VERIFY_TOKEN: str = os.getenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "")
    WHATSAPP_APP_SECRET: str = os.getenv("WHATSAPP_APP_SECRET", "")
    WHATSAPP_WEBHOOK_PORT: int = get_env_int("WHATSAPP_WEBHOOK_PORT", 8090)

    # WhatsApp Rate Limits
    WHATSAPP_DAILY_LIMIT = int(os.getenv("WHATSAPP_DAILY_LIMIT", "200"))
    WHATSAPP_HOURLY_LIMIT = int(os.getenv("WHATSAPP_HOURLY_LIMIT", "20"))

    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_GROUP_CHAT_ID: str = os.getenv("TELEGRAM_GROUP_CHAT_ID", "")

    # Google Calendar
    GOOGLE_CALENDAR_CREDENTIALS_PATH: str = os.getenv(
        "GOOGLE_CALENDAR_CREDENTIALS_PATH",
        "Secrets/credentials_desktop.json"
    )

    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite:///leads_automation.db"
    )

    # Excel file path
    LEADS_FILE: str = os.path.join('Secrets', 'leads.xlsx')

    # Business hours (Dubai time)
    BUSINESS_START_HOUR: int = 0
    BUSINESS_END_HOUR: int = 24
    TIMEZONE: str = "Europe/Amsterdam"


config = Config()
