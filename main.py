import os
import datetime
import json
from flask import Flask, request, render_template_string, redirect, url_for, Response, stream_with_context, session, abort

# --- 1. Initial Setup ---
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'a-very-secret-key-for-local-dev')

# --- 2. Load Configuration from Environment Variables ---
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

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
    .deep-think-toggle { margin-top: 15px; display: flex; align-items: center; }
</style></head>
<body>
    <div class="theme-toggle" id="theme-toggle">🌓</div>
    <div class="wrapper">
        <div class="sidebar">
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
                <div id="file-list"></div>
            </div>
        </div>
        <div class="chat-wrapper">
            <div class="chat-history" id="chat-history">
                </div>
            <div class="input-area">
                <form id="chat-form"><textarea name="prompt" placeholder="メッセージを入力..." required></textarea><button type="submit">↑</button></form>
            </div>
        </div>
    </div>
    <script>
        document.addEventListener('DOMContentLoaded', () => {
            const chatForm = document.getElementById('chat-form');
            const promptInput = chatForm.querySelector('textarea[name="prompt"]');
            const chatHistory = document.getElementById('chat-history');
            const fileInput = document.getElementById('knowledge_file');
            const fileListDiv = document.getElementById('file-list');
            const themeToggle = document.getElementById('theme-toggle');
            let knowledgeFiles = [];
            let conversationHistory = []; // 会話履歴を保持する配列

            // --- Theme Management ---
            themeToggle.addEventListener('click', () => {
                document.body.classList.toggle('dark-mode');
                localStorage.setItem('theme', document.body.classList.contains('dark-mode') ? 'dark' : 'light');
            });
            if (localStorage.getItem('theme') === 'dark') {
                document.body.classList.add('dark-mode');
            }

            // --- Settings Management ---
            function saveState() {
                const settings = {
                    model_name: document.getElementById('model_name').value,
                    temperature: document.getElementById('temperature').value,
                    system_instruction: document.getElementById('system_instruction').value,
                    deep_think_mode: document.getElementById('deep_think_mode').checked
                };
                localStorage.setItem('ai_settings', JSON.stringify(settings));
                localStorage.setItem('knowledge_files', JSON.stringify(knowledgeFiles));
                localStorage.setItem('conversation_history', JSON.stringify(conversationHistory));
            }

            function loadState() {
                const savedSettings = JSON.parse(localStorage.getItem('ai_settings')) || {};
                const savedFiles = JSON.parse(localStorage.getItem('knowledge_files')) || [];
                const savedHistory = JSON.parse(localStorage.getItem('conversation_history')) || [];
                
                const models = ['gemini-1.5-flash', 'gemini-2.5-pro', 'gemini-1.0-pro'];
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
                
                conversationHistory = savedHistory;
                renderHistory();
            }
            
            function renderHistory() {
                chatHistory.innerHTML = '';
                conversationHistory.forEach(msg => appendMessage(msg.text, msg.role, false));
            }

            ['model_name', 'temperature', 'system_instruction', 'deep_think_mode'].forEach(id => {
                const el = document.getElementById(id);
                el.addEventListener('change', saveState);
                el.addEventListener('input', saveState);
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
                            saveState();
                        };
                        reader.readAsText(file, 'UTF-8');
                    }
                });
                event.target.value = '';
            });

            function renderFileList() {
                fileListDiv.innerHTML = '';
                knowledgeFiles.forEach((file, index) => {
                    const fileItem = document.createElement('div'); fileItem.className = 'file-item';
                    const fileNameSpan = document.createElement('span'); fileNameSpan.innerText = file.name;
                    const deleteBtn = document.createElement('button'); deleteBtn.innerText = '×';
                    deleteBtn.onclick = () => { knowledgeFiles.splice(index, 1); renderFileList(); saveState(); };
                    fileItem.appendChild(fileNameSpan); fileItem.appendChild(deleteBtn); fileListDiv.appendChild(fileItem);
                });
            }
            
            // --- Chat Submission ---
            chatForm.addEventListener('submit', async function(event) {
                event.preventDefault();
                const userPrompt = promptInput.value.trim();
                if (!userPrompt) return;
                
                appendMessage(userPrompt, 'user', true); // Add to UI and history array
                promptInput.value = ''; promptInput.style.height = 'auto';
                const modelBubble = appendMessage('...', 'model', false); // Add placeholder to UI only
                
                const payload = {
                    prompt: userPrompt,
                    model_name: document.getElementById('model_name').value,
                    temperature: document.getElementById('temperature').value,
                    system_instruction: document.getElementById('system_instruction').value,
                    knowledge_files: knowledgeFiles,
                    deep_think_mode: document.getElementById('deep_think_mode').checked,
                    history: conversationHistory.slice(0, -1) // Send all history except the current user prompt
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
                    // Add final AI response to history array and save
                    conversationHistory.push({ role: 'model', text: fullResponse });
                    saveState();
                } catch (error) { modelBubble.querySelector('p').innerText = "エラーが発生しました: " + error; }
            });

            function appendMessage(text, role, addToHistoryArray) {
                if(addToHistoryArray) {
                    conversationHistory.push({ role: role, text: text });
                    saveState();
                }
                const messageDiv = document.createElement('div'); messageDiv.className = `message ${role}-message`;
                const bubbleDiv = document.createElement('div'); bubbleDiv.className = 'message-bubble';
                const p = document.createElement('p'); p.innerText = text;
                bubbleDiv.appendChild(p); messageDiv.appendChild(bubbleDiv); chatHistory.appendChild(messageDiv);
                chatHistory.scrollTop = chatHistory.scrollHeight;
                return bubbleDiv;
            }

            // --- Initial Load ---
            loadState();
        });
    </script>
</body>
</html>
"""

# --- 5. Python Backend ---
@app.route('/', methods=['GET'])
def home():
    # サーバー側は単純にHTMLを返すだけ。ログイン機能は削除。
    return render_template_string(HTML_TEMPLATE)
    
@app.route('/stream_chat', methods=['POST'])
def stream_chat():
    def generate():
        try:
            data = request.get_json()
            user_prompt = data.get('prompt', "")
            
            is_deep_think = data.get('deep_think_mode', False)
            if is_deep_think:
                model_name = 'gemini-2.5-pro'
                temperature = 0.5
                system_instruction = "あなたは非常に慎重で論理的な専門家です。ユーザーの質問に対して、まず背景、複数の視点、そして段階的な思考プロセスを内部で整理してください。その上で、最も論理的で包括的な回答を生成してください。"
            else:
                model_name = data.get('model_name', 'gemini-1.5-flash')
                temperature = float(data.get('temperature', 1.0))
                system_instruction = data.get('system_instruction', "")

            knowledge_files = data.get('knowledge_files', [])
            history = data.get('history', []) # Get history from payload
            
            genai_client = get_genai()
            if not (genai_client and user_prompt):
                yield "エラー: GEMINI_API_KEYが設定されていないか、プロンプトが空です。"
                return

            model = genai_client.GenerativeModel(
                model_name=model_name,
                generation_config=genai.GenerativeModel.GenerationConfig(temperature=temperature),
                system_instruction=system_instruction,
            )
            
            # Format history for the API
            api_history = []
            for item in history:
                role = 'user' if item['role'] == 'user' else 'model'
                api_history.append({'role': role, 'parts': [{'text': item['text']}]})

            chat = model.start_chat(history=api_history)
            
            final_prompt = user_prompt
            if knowledge_files:
                combined_content = "\\n\\n".join([f"--- File: {f['name']} ---\\n{f['content']}" for f in knowledge_files])
                final_prompt = f"以下の知識ファイルを元に回答してください。\\n---知識ファイル---\\n{combined_content}\\n--------------\\nユーザーの質問: {user_prompt}"
            
            response_stream = chat.send_message(final_prompt, stream=True)
            
            for chunk in response_stream:
                if chunk.text:
                    yield chunk.text
            
        except Exception as e:
            print(f"Error during generation: {e}")
            yield f"API呼び出し中にエラーが発生しました: {e}"

    return Response(stream_with_context(generate()), mimetype='text/plain; charset=utf-8')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
