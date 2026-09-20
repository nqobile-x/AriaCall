"""Run once locally to get your Gmail OAuth refresh token.
Usage: python scripts/get_gmail_token.py path/to/credentials.json
"""
import json
import sys
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

creds_file = sys.argv[1] if len(sys.argv) > 1 else "credentials.json"
flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
creds = flow.run_local_server(port=0)

print("\n--- Copy these into your Render env vars ---")
print(f"GMAIL_CLIENT_ID={creds.client_id}")
print(f"GMAIL_CLIENT_SECRET={creds.client_secret}")
print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
print(f"GMAIL_USER=ariaagentsa@gmail.com")
