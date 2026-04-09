"""
One-time script to authenticate with Charles Schwab API.
Run this once to generate token.json, then the dashboard will use it automatically.

Usage:
    python setup_schwab_auth.py

Requirements:
    - SCHWAB_APP_KEY and SCHWAB_APP_SECRET set in your .env file
    - Your Schwab app's callback URL must be set to https://127.0.0.1
"""

import os
from dotenv import load_dotenv
import schwab

load_dotenv()

APP_KEY = os.getenv("SCHWAB_APP_KEY")
APP_SECRET = os.getenv("SCHWAB_APP_SECRET")
CALLBACK_URL = "https://127.0.0.1"
TOKEN_PATH = "token.json"

if not APP_KEY or not APP_SECRET:
    print("ERROR: Set SCHWAB_APP_KEY and SCHWAB_APP_SECRET in your .env file first.")
    exit(1)

print("Opening browser for Schwab login...")
print("After logging in, you'll be redirected to a URL starting with https://127.0.0.1")
print("Copy and paste that full URL back here when prompted.\n")

client = schwab.auth.client_from_login_flow(
    api_key=APP_KEY,
    app_secret=APP_SECRET,
    callback_url=CALLBACK_URL,
    token_path=TOKEN_PATH,
)

print(f"\nSuccess! Token saved to {TOKEN_PATH}")
print("You can now run the dashboard — it will use this token automatically.")
