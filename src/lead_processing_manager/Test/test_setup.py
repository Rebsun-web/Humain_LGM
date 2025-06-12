# test_setup.py
import os
from dotenv import load_dotenv
import pandas as pd
from sqlalchemy import create_engine
import openai
from google.oauth2.credentials import Credentials
import requests

load_dotenv()

print("🔍 Checking Configuration...\n")

# Check OpenAI
try:
    openai.api_key = os.getenv("OPENAI_API_KEY")
    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": "Say 'OpenAI connected!'"}],
        max_tokens=10
    )
    print("✅ OpenAI: Connected")
except Exception as e:
    print(f"❌ OpenAI: {e}")

# Check Email Config
email = os.getenv("EMAIL_ADDRESS")
password = os.getenv("EMAIL_PASSWORD")
if email and password:
    print(f"✅ Email: Configured for {email}")
else:
    print("❌ Email: Missing configuration")

# Check Telegram
telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
if telegram_token:
    try:
        url = f"https://api.telegram.org/bot{telegram_token}/getMe"
        response = requests.get(url)
        if response.status_code == 200:
            bot_info = response.json()
            print(f"✅ Telegram Bot: @{bot_info['result']['username']}")
        else:
            print("❌ Telegram: Invalid token")
    except:
        print("❌ Telegram: Connection error")
else:
    print("❌ Telegram: No token")

# Check Excel file
excel_path = os.getenv("EXCEL_FILE_PATH", "leads.xlsx")
if os.path.exists(excel_path):
    df = pd.read_excel(excel_path)
    print(f"✅ Excel: Found {len(df)} leads")
else:
    print(f"❌ Excel: File '{excel_path}' not found")

# Check Database
db_url = os.getenv("DATABASE_URL", "sqlite:///lead_automation.db")
try:
    engine = create_engine(db_url)
    conn = engine.connect()
    conn.close()
    print("✅ Database: Connected")
except:
    print("❌ Database: Connection failed")

# Check Google Calendar credentials
if os.path.exists("/Users/nikitavoronkin/Desktop/Pet Projects/Lead Processing Manager/Secrets/credentials.json"):
    print("✅ Google Calendar: Credentials found")
else:
    print("❌ Google Calendar: credentials.json not found")

print("\n📋 Summary: Check the above before starting the main script")