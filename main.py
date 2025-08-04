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
    .deep-think-toggle { margin-top: 15px; display: flex; align-items: center; }
    /* ▼▼▼ New Button Style ▼▼▼ */
    .action-btn { background-color: #28a745; color: white; border: none; border-radius: 5px; padding: 8px; margin-top: 10px; cursor: pointer; width: 100%; }
</style></head>
<body>
    <div class="theme-toggle" id="theme-toggle">🌓</div>
    <div class="wrapper">
        <div class="sidebar">
            <div class="user-info">
                {% if user %}
                    <p>{{ user.name }}としてログイン中</p>
                    <a href="/logout">ログアウト</a>
                {% else %}
                    <a href="/login" class="login-btn">Googleでログイン</a>
                {% endif %}
            </div>
            <h2>設定</h2>
            <div id="config-form">
                <div class="deep-think-toggle">
                    <input type="checkbox" id="deep_think_mode" name="deep_think_mode" style="width: auto;">
                    <label for="deep_think_mode" style="margin: 0 0 0 5px;">Deep Thinkモード</label>
                </div>
                <label for="model_name">モデル:</label>
                <select id="model_name" name="model_name"></select>
                <label for="temperature">Temperature:</label>
                <input type="number" id="temperature" name="temperature" min="0" max="2" step="0.1">
                <label for="system_instruction">System Instruction:</label>
                <textarea id="system_instruction" name="system_instruction" rows="6"></textarea>
                <label for="knowledge_file">知識ファイル (最大10件):</label>
                <input type="file" id="knowledge_file" name="knowledge_file" accept=".txt" multiple>
                <button type="button" id="log-to-knowledge-btn" class="action-btn">現在の会話を知識化</button>
                <div id="file-list"></div>
            </div>
        </div>
        <div class="chat-wrapper">
             {% if not user %}
                <div class="login-container">
                    <h2>ようこそ</h2>
                    <p>全ての機能を利用するには、Googleアカウントでログインしてください。</p>
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
        document.addEventListener('DOMContentLoaded', () => {
            const isLoggedIn = {{ 'true' if user else 'false' }};
            const themeToggle = document.getElementById('theme-toggle');

            themeToggle.addEventListener('click', () => {
                document.body.classList.toggle('dark-mode');
                localStorage.setItem('theme', document.body.classList.contains('dark-mode') ? 'dark' : 'light');
            });
            if (localStorage.getItem('theme') === 'dark') {
                document.body.classList.add('dark-mode');
            }

            if (isLoggedIn) {
                const chatForm = document.getElementById('chat-form');
                const promptInput = chatForm.querySelector('textarea[name="prompt"]');
                const chatHistory = document.getElementById('chat-history');
                const fileInput = document.getElementById('knowledge_file');
                const fileListDiv = document.getElementById('file-list');
                const logToKnowledgeBtn = document.getElementById('log-to-knowledge-btn');
                let knowledgeFiles = [];

                function saveSettings() {
                    const settings = {
                        model_name: document.getElementById('model_name').value,
                        temperature: document.getElementById('temperature').value,
                        system_instruction: document.getElementById('system_instruction').value,
                        deep_think_mode: document.getElementById('deep_think_mode').checked
                    };
                    localStorage.setItem('ai_settings', JSON.stringify(settings));
                    localStorage.setItem('knowledge_files', JSON.stringify(knowledgeFiles));
                }

                function loadSettings() {
                    const savedSettings = JSON.parse(localStorage.getItem('ai_settings')) || {};
                    const savedFiles = JSON.parse(localStorage.getItem('knowledge_files')) || [];
                    
                    const models = ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-1.0-pro'];
                    const modelSelect = document.getElementById('model_name');
                    modelSelect.innerHTML = '';
                    models.forEach(model => {
                        const option = document.createElement('option');
                        option.value = model;
                        option.text = model.replace(/gemini-|-pro|-flash/g, m => ({'gemini-': 'Gemini ', '-pro': ' Pro', '-flash': ' Flash'})[m]);
                        if (model === (savedSettings.model_name || 'gemini-1.5-flash')) { option.selected = true; }
                        modelSelect.appendChild(option);
                    });
                    document.getElementById('temperature').value = savedSettings.temperature || 1.0;
                    document.getElementById('system_instruction').value = savedSettings.system_instruction || 'あなたは親切で優秀なAIアシスタントです。';
                    document.getElementById('deep_think_mode').checked = savedSettings.deep_think_mode || false;
                    
                    knowledgeFiles = savedFiles;
                    renderFileList();
                }

                ['model_name', 'temperature', 'system_instruction', 'deep_think_mode'].forEach(id => {
                    document.getElementById(id).addEventListener('change', saveSettings);
                    document.getElementById(id).addEventListener('input', saveSettings);
                });
                
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

                // ▼▼▼ New Function: Log to Knowledge ▼▼▼
                logToKnowledgeBtn.addEventListener('click', () => {
                    if (knowledgeFiles.length >= 10) {
                        alert("知識ファイルが上限の10個に達しています。");
                        return;
                    }
                    let logText = "以下は、これまでの会話の記録です。\\n\\n";
                    const messages = document.querySelectorAll('.chat-history .message');
                    messages.forEach(msg => {
                        const role = msg.classList.contains('user-message') ? 'User' : 'AI';
                        const text = msg.querySelector('p').innerText;
                        logText += `${role}: ${text}\\n`;
                    });

                    const logFileName = `conversation_log_${new Date().getTime()}.txt`;
                    knowledgeFiles.push({ name: logFileName, content: logText });
                    renderFileList();
                    saveSettings();
                    alert(`「${logFileName}」として会話ログを知識ファイルに追加しました。`);
                });

                function renderFileList() {
                    fileListDiv.innerHTML = '';
                    knowledgeFiles.forEach((file, index) => {
                        const fileItem = document.createElement('div'); fileItem.className = 'file-item';
                        const fileNameSpan = document.createElement('span'); fileNameSpan.innerText = file.name;
                        const deleteBtn = document.createElement('button'); deleteBtn.innerText = '×';
                        deleteBtn.onclick = () => { knowledgeFiles.splice(index, 1); renderFileList(); saveSettings(); };
                        fileItem.appendChild(fileNameSpan); fileItem.appendChild(deleteBtn); fileListDiv.appendChild(fileItem);
                    });
                }
                
                chatForm.addEventListener('submit', async function(event) {
                    event.preventDefault();
                    const userPrompt = promptInput.value.trim();
                    if (!userPrompt) return;
                    appendMessage(userPrompt, 'user');
                    promptInput.value = ''; promptInput.style.height = 'auto';
                    const modelBubble = appendMessage('...', 'model');
                    
                    saveSettings();
                    
                    const payload = {
                        prompt: userPrompt,
                        model_name: document.getElementById('model_name').value,
                        temperature: document.getElementById('temperature').value,
                        system_instruction: document.getElementById('system_instruction').value,
                        knowledge_files: knowledgeFiles,
                        deep_think_mode: document.getElementById('deep_think_mode').checked
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
                    const messageDiv = document.createElement('div'); messageDiv.className = `message ${role}-message`;
                    const bubbleDiv = document.createElement('div'); bubbleDiv.className = 'message-bubble';
                    const p = document.createElement('p'); p.innerText = text;
                    bubbleDiv.appendChild(p); messageDiv.appendChild(bubbleDiv); chatHistory.appendChild(messageDiv);
                    chatHistory.scrollTop = chatHistory.scrollHeight;
                    return bubbleDiv;
                }

                loadSettings();
                chatHistory.scrollTop = chatHistory.scrollHeight;
            }
        });
    </script>
</body>
</html>
"""

# --- 5. Python Backend Routes ---
@app.route('/login')
def login():
    flow = get_oauth_flow()
    if not flow: return "OAuth is not configured.", 500
    authorization_url, state = flow.authorization_url()
    session['state'] = state
    return redirect(authorization_url)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/callback')
def callback():
    flow = get_oauth_flow()
    if not flow: return "OAuth is not configured.", 500
    try:
        flow.fetch_token(authorization_response=request.url, state=session["state"])
        creds = flow.credentials
        user_info_response = requests.get('https://www.googleapis.com/oauth2/v1/userinfo', headers={'Authorization': f'Bearer {creds.token}'})
        user_info = user_info_response.json()
        session['google_id'] = user_info['id']
        session['name'] = user_info['name']
    except Exception as e:
        print(f"Error during OAuth callback: {e}")
    return redirect(url_for('home'))

@app.route('/', methods=['GET'])
def home():
    user_data = session.get('name')
    history = []
    if 'google_id' in session:
        try:
            user_id = session['google_id']
            db = get_db()
            docs = db.collection('users').document(user_id).collection('conversations').order_by('timestamp').limit(50).stream()
            for doc in docs:
                history.append(doc.to_dict())
        except Exception as e:
            print(f"Error fetching history for user {session.get('google_id')}: {e}")
    return render_template_string(HTML_TEMPLATE, user=user_data, history=history)
    
@app.route('/stream_chat', methods=['POST'])
def stream_chat():
    def generate():
        try:
            data = request.get_json()
            user_prompt = data.get('prompt', "")
            
            is_deep_think = data.get('deep_think_mode', False)
            if is_deep_think:
                model_name = 'gemini-1.5-pro'
                temperature = 0.5
                system_instruction = "あなたは非常に慎重で論理的な専門家です。ユーザーの質問に対して、まず背景、複数の視点、そして段階的な思考プロセスを内部で整理してください。その上で、最も論理的で包括的な回答を生成してください。"
            else:
                model_name = data.get('model_name', 'gemini-1.5-flash')
                temperature = float(data.get('temperature', 1.0))
                system_instruction = data.get('system_instruction', "")

            knowledge_files = data.get('knowledge_files', [])
            genai_client = get_genai()
            if not (genai_client and user_prompt):
                yield "エラー: GEMINI_API_KEYが設定されていないか、プロンプトが空です。"
                return

            model = genai_client.GenerativeModel(
                model_name=model_name,
                generation_config=genai.GenerativeModel.GenerationConfig(temperature=temperature),
                system_instruction=system_instruction,
            )
            final_prompt = user_prompt
            if knowledge_files:
                combined_content = "\\n\\n".join([f"--- File: {f['name']} ---\\n{f['content']}" for f in knowledge_files])
                final_prompt = f"以下の知識ファイルを元に回答してください。\\n---知識ファイル---\\n{combined_content}\\n--------------\\nユーザーの質問: {user_prompt}"
            
            chat = model.start_chat(history=[])
            response_stream = chat.send_message(final_prompt, stream=True)
            
            full_ai_response = ""
            for chunk in response_stream:
                if chunk.text:
                    full_ai_response += chunk.text
                    yield chunk.text
            
            if 'google_id' in session:
                user_id = session['google_id']
                db = get_db()
                convo_ref = db.collection('users').document(user_id).collection('conversations')
                utc_now = datetime.datetime.now(datetime.timezone.utc)
                convo_ref.add({'role': 'user', 'text': user_prompt, 'timestamp': utc_now})
                convo_ref.add({'role': 'model', 'text': full_ai_response, 'timestamp': utc_now + datetime.timedelta(microseconds=1)})
        except Exception as e:
            print(f"Error during generation: {e}")
            yield f"API呼び出し中にエラーが発生しました: {e}"

    return Response(stream_with_context(generate()), mimetype='text/plain; charset=utf-8')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
