import os
import datetime
import json
import requests
from flask import Flask, request, render_template_string, redirect, url_for, Response, stream_with_context, session, abort
from google.cloud import firestore, secretmanager
from google.oauth2 import credentials
from google_auth_oauthlib.flow import Flow

# --- Initial Setup ---
app = Flask(__name__)

# --- Secret Managerから秘密情報を読み込む ---
# この部分はCloud Run環境でのみ動作します
if os.environ.get('GAE_ENV', '').startswith('standard'):
    project_id = os.environ.get('GOOGLE_CLOUD_PROJECT')
    secret_client = secretmanager.SecretManagerServiceClient()

    def get_secret(secret_name):
        path = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
        response = secret_client.access_secret_version(request={"name": path})
        return response.payload.data.decode("UTF-8")

    app.secret_key = get_secret('flask-secret-key')
    GEMINI_API_KEY = get_secret('gemini-api-key')
    GOOGLE_CLIENT_ID = get_secret('google-oauth-client-id')
    GOOGLE_CLIENT_SECRET = get_secret('google-oauth-client-secret')
    # あなたのCloud RunのURL + /callback
    REDIRECT_URI = f"{os.environ.get('SERVICE_URL')}/callback" 
else:
    # ローカル開発用のダミー設定
    app.secret_key = 'dev-secret-key'
    GEMINI_API_KEY = "YOUR_LOCAL_API_KEY" # 必要に応じて設定
    GOOGLE_CLIENT_ID = "YOUR_LOCAL_CLIENT_ID"
    GOOGLE_CLIENT_SECRET = "YOUR_LOCAL_CLIENT_SECRET"
    REDIRECT_URI = "http://localhost:8080/callback"

# --- Firestore Client ---
db = firestore.Client()
genai = None
if GEMINI_API_KEY and GEMINI_API_KEY != "YOUR_LOCAL_API_KEY":
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
    except ImportError:
        pass

# --- OAuth 2.0 Flow Configuration ---
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1' # HTTPでのローカルテストを許可
flow = Flow.from_client_config(
    client_config={
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [REDIRECT_URI],
        }
    },
    scopes=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"],
    redirect_uri=REDIRECT_URI
)

# --- HTML Template ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <title>AI Chat Final</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta charset="UTF-8">
    <style>
        body { font-family: sans-serif; margin: 0; }
        /* (CSSは前回のものをそのまま利用するため省略) */
        .login-container { text-align: center; padding-top: 50px; }
        .login-btn { background-color: #4285F4; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; }
        .user-info { padding: 10px; text-align: center; border-bottom: 1px solid var(--border-color); font-size: 12px;}
    </style>
</head>
<body>
    <div class="theme-toggle" id="theme-toggle">🌓</div>
    <div class="wrapper">
        <div class="sidebar">
            {% if user %}
                <div class="user-info">
                    <p>{{ user.name }}としてログイン中</p>
                    <a href="/logout">ログアウト</a>
                </div>
            {% endif %}
            <h2>設定</h2>
            </div>
        <div class="chat-wrapper">
             {% if not user %}
                <div class="login-container">
                    <h2>ようこそ</h2>
                    <p>全ての機能を利用するには、Googleアカウントでログインしてください。</p>
                    <a href="/login" class="login-btn">Googleでログイン</a>
                </div>
             {% else %}
                <div class="chat-history" id="chat-history">
                    </div>
                <div class="input-area">
                    </div>
             {% endif %}
        </div>
    </div>
    <script>
        // (JavaScriptは大幅に変更)
        document.addEventListener('DOMContentLoaded', () => {
            const isLoggedIn = {{ 'true' if user else 'false' }};
            if (!isLoggedIn) return; // ログインしていない場合は何もしない

            // (前回と同様のJavaScriptの全機能をここに記述)
            // ... loadSettings, saveSettings, chatForm submission etc. ...
            // saveSettingsは/save_settingsエンドポイントをfetchするよう変更
        });
    </script>
</body>
</html>
"""
# (注：上記のHTMLとJSは主要な構造のみを示しています。実際のコードでは前回の完全版が利用されます)

# --- Google OAuth Routes ---
@app.route('/login')
def login():
    authorization_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true')
    session['state'] = state
    return redirect(authorization_url)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/callback')
def callback():
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials
    
    # ユーザー情報を取得
    user_info_response = requests.get(
        'https://www.googleapis.com/oauth2/v1/userinfo',
        headers={'Authorization': f'Bearer {creds.token}'}
    )
    user_info = user_info_response.json()

    session['google_id'] = user_info['id']
    session['name'] = user_info['name']
    session['credentials'] = {
        'token': creds.token, 'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri, 'client_id': creds.client_id,
        'client_secret': creds.client_secret, 'scopes': creds.scopes
    }
    return redirect(url_for('home'))

# --- Main App Routes ---
@app.route('/', methods=['GET'])
def home():
    if 'google_id' not in session:
        # ログインしていない場合は、ログインを促すシンプルなページを表示
        return render_template_string(HTML_TEMPLATE.replace("", "").replace("", ""), user=None)
    
    user_id = session['google_id']
    user_settings_ref = db.collection('users').document(user_id)
    settings_doc = user_settings_ref.get()
    
    if settings_doc.exists:
        config = settings_doc.to_dict()
    else:
        config = {} # デフォルト値はJS側で設定

    # (表示用の履歴読み込みロジックは前回同様)
    history = []
    
    return render_template_string(HTML_TEMPLATE, user=session, history=history, config=config)

# --- API Routes for JavaScript ---
@app.route('/save_settings', methods=['POST'])
def save_settings():
    if 'google_id' not in session:
        return abort(401) # Unauthorized
    
    settings = request.get_json()
    user_id = session['google_id']
    db.collection('users').document(user_id).set(settings, merge=True)
    return {"status": "success"}
    
@app.route('/stream_chat', methods=['POST'])
def stream_chat():
    if 'google_id' not in session:
        return abort(401)
    
    # (ストリーミングのロジックは前回と同様)
    # ...
    # DBへの保存先をユーザーごとのサブコレクションに変更
    # user_id = session['google_id']
    # db.collection('users').document(user_id).collection('conversations').add(...)
    pass # ダミー
