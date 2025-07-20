import os
import datetime
import json
import requests
from flask import Flask, request, render_template_string, redirect, url_for, Response, stream_with_context, session, abort
from google.cloud import firestore, secretmanager
from google_auth_oauthlib.flow import Flow

# --- Initial Setup ---
app = Flask(__name__)

# --- Secret Managerから秘密情報を読み込む ---
try:
    project_id = os.environ.get('GOOGLE_CLOUD_PROJECT')
    secret_client = secretmanager.SecretManagerServiceClient()

    def get_secret(secret_name):
        path = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
        response = secret_client.access_secret_version(request={"name": path})
        return response.payload.data.decode("UTF-8")

    app.secret_key = get_secret('FLASK_SECRET_KEY')
    GEMINI_API_KEY = get_secret('gemini-api-key')
    GOOGLE_CLIENT_ID = get_secret('GOOGLE_CLIENT_ID')
    GOOGLE_CLIENT_SECRET = get_secret('GOOGLE_CLIENT_SECRET')
    
    # Cloud RunのURLを自動取得し、リダイレクトURIを設定
    # この環境変数はCloud Runによって自動的に設定されます
    service_url = os.environ.get('SERVICE_URL', 'http://localhost:8080')
    REDIRECT_URI = f"{service_url}/callback"

except Exception as e:
    print(f"Warning: Could not load secrets from Secret Manager. Using local fallbacks. Error: {e}")
    app.secret_key = 'a-strong-dev-secret-key'
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY') # ローカルテスト用に環境変数を設定可能
    GOOGLE_CLIENT_ID = None
    GOOGLE_CLIENT_SECRET = None
    REDIRECT_URI = "http://localhost:8080/callback"

# --- Firestore & Gemini Client ---
db = firestore.Client()
genai = None
if GEMINI_API_KEY:
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
    except ImportError:
        pass

# --- OAuth 2.0 Flow Configuration ---
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1' # HTTPでのローカルテストを許可
flow = None
if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    flow = Flow.from_client_config(
        client_config={ "web": {
                "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [REDIRECT_URI],
        }},
        scopes=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"],
        redirect_uri=REDIRECT_URI
    )

# --- HTML Template ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ja"><head><title>AI Chat Final</title><meta name="viewport" content="width=device-width, initial-scale=1.0"><meta charset="UTF-8">
<style>
    :root { --bg-color: #f7f9fc; --text-color: #000; --sidebar-bg: #ffffff; --border-color: #ddd; --user-bubble-bg: #0b93f6; --model-bubble-bg: #e5e5ea; --input-area-bg: #f0f2f5; }
    body.dark-mode { --bg-color: #121212; --text-color: #e0e0e0; --sidebar-bg: #1e1e1e; --border-color: #444; --user-bubble-bg: #377dff; --model-bubble-bg: #333333; --input-area-bg: #2a2a2a; }
    html, body { height: 100%; margin: 0; font-family: sans-serif; background-color: var(--bg-color); color: var(--text-color); }
    .wrapper { display: flex; height: 100vh; }
    .sidebar { width: 320px; padding: 20px; border-right: 1px solid var(--border-color); background-color: var(--sidebar-bg); display: flex; flex-direction: column; overflow-y: auto; flex-shrink: 0;}
    .chat-wrapper { flex-grow: 1; display: flex; flex-direction: column; height: 100vh; }
    .chat-history { flex-grow: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; }
    .message { display: flex; margin-bottom: 20px; max-width: 80%; }
    .message-bubble { padding: 10px 15px; border-radius: 18px; line-height: 1.5; white-space: pre-wrap; word-wrap: break-word;}
    .user-message { align-self: flex-end; } .user-message .message-bubble { background-color: var(--user-bubble-bg); color: white; }
    .model-message { align-self: flex-start; } .model-message .message-bubble { background-color: var(--model-bubble-bg); color: var(--text-color); }
    .input-area { padding: 15px; border-top: 1px solid var(--border-color); background-color: var(--input-area-bg); }
    .input-area form { display: flex; gap: 10px; align-items: center; }
    .input-area textarea { flex-grow: 1; border: 1px solid var(--border-color); border-radius: 18px; padding: 10px 15px; resize: none; font-size: 16px; max-height: 120px; background-color: var(--sidebar-bg); color: var(--text-color); }
    .input-area button { background: #0b93f6; color: white; border: none; border-radius: 50%; width: 40px; height: 40px; font-size: 20px; cursor: pointer; flex-shrink: 0; }
    label { font-weight: bold; margin-top: 15px; margin-bottom: 5px; display: block; }
    select, input[type=number], input[type=file], .sidebar textarea { width: 100%; padding: 8px; border: 1px solid var(--border-color); border-radius: 5px; box-sizing: border-box; background-color: var(--bg-color); color: var(--text-color);}
    #file-list { font-size: 12px; margin-top: 5px; }
    .file-item { display: flex; justify-content: space-between; align-items: center; margin-bottom: 3px; }
    .file-item span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding-right: 5px;}
    .file-item button { background: #dc3545; color: white; border: none; border-radius: 4px; padding: 1px 6px; font-size: 12px; cursor: pointer; }
    .theme-toggle { position: fixed; top: 10px; right: 10px; cursor: pointer; font-size: 24px; z-index: 100; }
    .login-container { text-align: center; padding-top: 50px; }
    .login-btn { background-color: #4285F4; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; }
    .user-info { padding: 10px; text-align: center; border-bottom: 1px solid var(--border-color); font-size: 12px;}
</style></head>
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
            <div id="config-form">
                <label for="model_name">モデル:</label>
                <select id="model_name" name="model_name"></select>
                <label for="temperature">Temperature:</label>
                <input type="number" id="temperature" name="temperature" min="0" max="2" step="0.1">
                <label for="system_instruction">System Instruction:</label>
                <textarea id="system_instruction" name="system_instruction" rows="6"></textarea>
                <label for="knowledge_file">知識ファイル (最大10件):</label>
                <input type="file" id="knowledge_file" name="knowledge_file" accept=".txt" multiple>
                <div id="file-list"></div>
            </div>
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
                    {% for item in history %}
                    <div class="message {% if item.role == 'user' %}user-message{% else %}model-message{% endif %}">
                        <div class="message-bubble"><p>{{ item.text }}</p></div>
                    </div>
                    {% endfor %}
                </div>
                <div class="input-area">
                    <form id="chat-form"><textarea name="prompt" placeholder="メッセージを入力..." required></textarea><button type="submit">↑</button></form>
                </div>
             {% endif %}
        </div>
    </div>
    <script>
        const isLoggedIn = {{ 'true' if user else 'false' }};
        if (isLoggedIn) {
            // --- State Management & Initialization ---
            const chatForm = document.getElementById('chat-form');
            const promptInput = chatForm.querySelector('textarea[name="prompt"]');
            const chatHistory = document.getElementById('chat-history');
            const fileInput = document.getElementById('knowledge_file');
            const fileListDiv = document.getElementById('file-list');
            let knowledgeFiles = [];

            // --- Settings Management (using server) ---
            async function saveSettings() {
                const settings = {
                    model_name: document.getElementById('model_name').value,
                    temperature: document.getElementById('temperature').value,
                    system_instruction: document.getElementById('system_instruction').value,
                    knowledgeFiles: knowledgeFiles
                };
                await fetch('/save_settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(settings)
                });
            }

            function loadSettings() {
                const config = JSON.parse('{{ config|tojson|safe }}');
                const models = ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-1.0-pro'];
                const modelSelect = document.getElementById('model_name');
                models.forEach(model => {
                    const option = document.createElement('option');
                    option.value = model;
                    option.text = model.replace(/gemini-|-pro|-flash/g, m => ({'gemini-': 'Gemini ', '-pro': ' Pro', '-flash': ' Flash'})[m]);
                    if (model === (config.model_name || 'gemini-1.5-flash')) { option.selected = true; }
                    modelSelect.appendChild(option);
                });
                document.getElementById('temperature').value = config.temperature || 1.0;
                document.getElementById('system_instruction').value = config.system_instruction || 'あなたは親切で優秀なAIアシスタントです。';
                knowledgeFiles = config.knowledgeFiles || [];
                renderFileList();
            }

            ['model_name', 'temperature', 'system_instruction'].forEach(id => {
                const el = document.getElementById(id);
                el.addEventListener('change', saveSettings);
                if (id === 'system_instruction') el.addEventListener('input', saveSettings);
            });

            // --- File Management ---
            fileInput.addEventListener('change', (event) => {
                const newFiles = Array.from(event.target.files);
                if (knowledgeFiles.length + newFiles.length > 10) { alert("ファイルは合計10個までです。"); return; }
                newFiles.forEach(file => {
                    if (!knowledgeFiles.some(f => f.name === file.name)) {
                        const reader = new FileReader();
                        reader.onload = (e) => {
                            knowledgeFiles.push({ name: file.name, content: e.target.result });
                            renderFileList();
                            saveSettings();
                        };
                        reader.readAsText(file, 'UTF-8');
                    }
                });
                event.target.value = '';
            });

            function renderFileList() {
                fileListDiv.innerHTML = '';
                knowledgeFiles.forEach((file, index) => {
                    const fileItem = document.createElement('div');
                    fileItem.className = 'file-item';
                    const fileNameSpan = document.createElement('span');
                    fileNameSpan.innerText = file.name;
                    const deleteBtn = document.createElement('button');
                    deleteBtn.innerText = '×';
                    deleteBtn.onclick = () => { knowledgeFiles.splice(index, 1); renderFileList(); saveSettings(); };
                    fileItem.appendChild(fileNameSpan);
                    fileItem.appendChild(deleteBtn);
                    fileListDiv.appendChild(fileItem);
                });
            }
            
            // --- Chat Submission ---
            chatForm.addEventListener('submit', async function(event) {
                event.preventDefault();
                const userPrompt = promptInput.value.trim();
                if (!userPrompt) return;
                appendMessage(userPrompt, 'user');
                promptInput.value = ''; promptInput.style.height = 'auto';
                const modelBubble = appendMessage('...', 'model');
                
                const payload = {
                    prompt: userPrompt,
                    model_name: document.getElementById('model_name').value,
                    temperature: document.getElementById('temperature').value,
                    system_instruction: document.getElementById('system_instruction').value,
                    knowledge_files: knowledgeFiles
                };
                
                try {
                    const response = await fetch('/stream_chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
                    if (!response.ok) throw new Error(`Server error: ${response.status} ${await response.text()}`);
                    const reader = response.body.getReader();
                    const decoder = new TextDecoder();
                    let fullResponse = "";
                    modelBubble.querySelector('p').innerText = "";
                    while (true) {
                        const { value, done } = await reader.read();
                        if (done) break;
                        const chunk = decoder.decode(value, {stream: true});
                        fullResponse += chunk;
                        modelBubble.querySelector('p').innerText = fullResponse;
                        chatHistory.scrollTop = chatHistory.scrollHeight;
                    }
                } catch (error) { modelBubble.querySelector('p').innerText = "エラーが発生しました: " + error; }
            });

            function appendMessage(text, role) {
                const messageDiv = document.createElement('div');
                messageDiv.className = `message ${role}-message`;
                const bubbleDiv = document.createElement('div');
                bubbleDiv.className = 'message-bubble';
                const p = document.createElement('p');
                p.innerText = text;
                bubbleDiv.appendChild(p);
                messageDiv.appendChild(bubbleDiv);
                chatHistory.appendChild(messageDiv);
                chatHistory.scrollTop = chatHistory.scrollHeight;
                return bubbleDiv;
            }
        }
        // --- Theme Management ---
        const themeToggle = document.getElementById('theme-toggle');
        themeToggle.addEventListener('click', () => {
            document.body.classList.toggle('dark-mode');
            localStorage.setItem('theme', document.body.classList.contains('dark-mode') ? 'dark' : 'light');
        });
        document.addEventListener('DOMContentLoaded', () => {
            if (localStorage.getItem('theme') === 'dark') { document.body.classList.add('dark-mode'); }
            if(isLoggedIn) loadSettings();
            chatHistory.scrollTop = chatHistory.scrollHeight;
        });
    </script>
</body>
</html>
"""

# --- Google OAuth Routes ---
@app.route('/login')
def login():
    if not flow: return "OAuth 2.0 is not configured.", 500
    authorization_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true')
    session['state'] = state
    return redirect(authorization_url)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/callback')
def callback():
    if not flow: return "OAuth 2.0 is not configured.", 500
    try:
        flow.fetch_token(authorization_response=request.url)
        creds = flow.credentials
        user_info_response = requests.get(
            'https://www.googleapis.com/oauth2/v1/userinfo',
            headers={'Authorization': f'Bearer {creds.token}'}
        )
        user_info = user_info_response.json()
        session['google_id'] = user_info['id']
        session['name'] = user_info['name']
    except Exception as e:
        print(f"Error during callback: {e}")
        return redirect(url_for('home'))
    return redirect(url_for('home'))

# --- Main App Routes ---
@app.route('/', methods=['GET'])
def home():
    user_data = session.get('name')
    config = {}
    history = []
    if 'google_id' in session:
        user_id = session['google_id']
        settings_doc = db.collection('users').document(user_id).get()
        if settings_doc.exists:
            config = settings_doc.to_dict()
        
        # (会話履歴の読み込みは、必要に応じて後で追加できます)
    return render_template_string(HTML_TEMPLATE, user=user_data, history=history, config=config)

# --- API Routes for JavaScript ---
@app.route('/save_settings', methods=['POST'])
def save_settings():
    if 'google_id' not in session: return abort(401)
    settings = request.get_json()
    user_id = session['google_id']
    db.collection('users').document(user_id).set(settings, merge=True)
    return {"status": "success"}
    
@app.route('/stream_chat', methods=['POST'])
def stream_chat():
    if 'google_id' not in session: return abort(401)
    
    def generate():
        try:
            data = request.get_json()
            user_prompt = data.get('prompt', "")
            model_name = data.get('model_name', 'gemini-1.5-flash')
            system_instruction = data.get('system_instruction', "")
            temperature = float(data.get('temperature', 1.0))
            knowledge_files = data.get('knowledge_files', [])
            
            if not (genai and user_prompt):
                yield "エラー: 設定が不十分か、プロンプトが空です。"
                return

            model = genai.GenerativeModel(
                model_name=model_name,
                generation_config=genai.GenerationConfig(temperature=temperature),
                system_instruction=system_instruction,
            )
            final_prompt = user_prompt
            if knowledge_files:
                combined_content = "\\n\\n".join([f"--- File: {f['name']} ---\\n{f['content']}" for f in knowledge_files])
                final_prompt = f"以下の知識ファイルを元に回答してください。\\n---知識ファイル---\\n{combined_content}\\n--------------\\nユーザーの質問: {user_prompt}"
            
            response_stream = model.generate_content(final_prompt, stream=True)
            for chunk in response_stream:
                if chunk.text: yield chunk.text
        except Exception as e:
            print(f"Error during generation: {e}")
            yield f"API呼び出し中にエラーが発生しました: {e}"

    return Response(stream_with_context(generate()), mimetype='text/plain; charset=utf-8')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=True)
