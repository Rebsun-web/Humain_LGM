import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")
    # Email Configuration
    EMAIL_ADDRESS: str = os.getenv("EMAIL_ADDRESS")
    EMAIL_PASSWORD: str = os.getenv("EMAIL_PASSWORD")
    EMAIL_SMTP_SERVER: str = os.getenv(
        "EMAIL_SMTP_SERVER",
        "smtp.gmail.com"
    )
    EMAIL_SMTP_PORT: int = int(os.getenv(
        "EMAIL_SMTP_PORT",
        "587")
    )
    EMAIL_IMAP_SERVER: str = os.getenv(
        "EMAIL_IMAP_SERVER",
        "imap.gmail.com"
    )

    # WhatsApp Business API
    WHATSAPP_API_URL: str = os.getenv("WHATSAPP_API_URL")
    WHATSAPP_API_TOKEN: str = os.getenv("WHATSAPP_API_TOKEN")
    WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    WHATSAPP_WEBHOOK_VERIFY_TOKEN: str = os.getenv(
        "WHATSAPP_WEBHOOK_VERIFY_TOKEN"
    )
    WHATSAPP_APP_SECRET: str = os.getenv("WHATSAPP_APP_SECRET")
    WHATSAPP_WEBHOOK_PORT: int = int(os.getenv(
        "WHATSAPP_WEBHOOK_PORT",
        "5000"
    ))

    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_GROUP_CHAT_ID: str = os.getenv("TELEGRAM_GROUP_CHAT_ID")

    # Google Calendar
    GOOGLE_CALENDAR_CREDENTIALS_PATH: str = os.getenv(
        "GOOGLE_CALENDAR_CREDENTIALS_PATH",
        "credentials.json"
    )

    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite:///lead_automation.db"
    )

    # Excel file path
    EXCEL_FILE_PATH: str = os.getenv(
        "EXCEL_FILE_PATH",
        "leads.xlsx"
    )

    # Business hours (Dubai time)
    BUSINESS_START_HOUR: int = 10
    BUSINESS_END_HOUR: int = 18
    TIMEZONE: str = "Asia/Dubai"


config = Config()
