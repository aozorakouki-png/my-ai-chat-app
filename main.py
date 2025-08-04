import os
import datetime
import json
import requests
from flask import Flask, request, render_template_string, redirect, url_for, Response, stream_with_context, session, abort

# --- 1. Initial Setup ---
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY')

# --- 2. Load Configuration from Environment Variables ---
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
REDIRECT_URI = os.environ.get('REDIRECT_URI')

# --- 3. Lazy Initializers ---
db_client = None
def get_db():
    global db_client
    if db_client is None:
        from google.cloud import firestore
        db_client = firestore.Client()
    return db_client

genai_client = None
def get_genai():
    global genai_client
    if genai_client is None:
        if GEMINI_API_KEY:
            try:
                import google.generativeai as genai
                genai.configure(api_key=GEMINI_API_KEY)
                genai_client = genai
            except ImportError:
                pass
    return genai_client

def get_oauth_flow():
    if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and REDIRECT_URI):
        return None
    from google_auth_oauthlib.flow import Flow
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    return Flow.from_client_config(
        client_config={ "web": {
            "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [REDIRECT_URI],
        }},
        scopes=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"],
        redirect_uri=REDIRECT_URI
    )

# --- 4. HTML Template ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ja"><head><title>AI Chat</title><meta name="viewport" content="width=device-width, initial-scale=1.0"><meta charset="UTF-8">
<style>
    :root { --bg-color: #f7f9fc; --text-color: #000; --sidebar-bg: #ffffff; --border-color: #ddd; --user-bubble-bg: #0b93f6; --model-bubble-bg: #e5e5ea; --input-area-bg: #f0f2f5; }
    body.dark-mode { --bg-color: #121212; --text-color: #e0e0e0; --sidebar-bg: #1e
