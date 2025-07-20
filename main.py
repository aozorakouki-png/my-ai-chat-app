import os
import datetime
import json
from flask import Flask, request, render_template_string, make_response, redirect, url_for, Response, stream_with_context

# Firestore client
from google.cloud import firestore

# Generative AI client
try:
    import google.generativeai as genai
except ImportError:
    genai = None

# Initialize Flask App and Firestore DB Client
app = Flask(__name__)
db = firestore.Client()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <title>AI Chat Final</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta charset="UTF-8">
    <style>
        :root {
            --bg-color: #f7f9fc; --text-color: #000; --sidebar-bg: #ffffff;
            --border-color: #ddd; --user-bubble-bg: #0b93f6; --model-bubble-bg: #e5e5ea;
            --input-area-bg: #f0f2f5;
        }
        body.dark-mode {
            --bg-color: #121212; --text-color: #e0e0e0; --sidebar-bg: #1e1e1e;
            --border-color: #444; --user-bubble-bg: #377dff; --model-bubble-bg: #333333;
            --input-area-bg: #2a2a2a;
        }
        html, body { height: 100%; margin: 0; font-family: sans-serif; background-color: var(--bg-color); color: var(--text-color); transition: background-color 0.3s, color 0.3s; }
        .wrapper { display: flex; height: 100vh; }
        .sidebar { width: 320px; padding: 20px; border-right: 1px solid var(--border-color); background-color: var(--sidebar-bg); display: flex; flex-direction: column; overflow-y: auto; flex-shrink: 0;}
        .chat-wrapper { flex-grow: 1; display: flex; flex-direction: column; height: 100vh; }
        .chat-history { flex-grow: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; }
        .message { display: flex; margin-bottom: 20px; max-width: 80%; }
        .message-bubble { padding: 10px 15px; border-radius: 18px; line-height: 1.5; white-space: pre-wrap; word-wrap: break-word;}
        /* ▼▼▼ チャット表示修正：ユーザーメッセージを右寄せ ▼▼▼ */
        .user-message { align-self: flex-end; }
        .user-message .message-bubble { background-color: var(--user-bubble-bg); color: white; }
        .model-message { align-self: flex-start; }
        .model-message .message-bubble { background-color: var(--model-bubble-bg); color: var(--text-color); }
        .input-area { padding: 15px; border-top: 1px solid var(--border-color); background-color: var(--input-area-bg); }
        .input-area form { display: flex; gap: 10px; align-items: center; }
        .input-area textarea { flex-grow: 1; border: 1px solid var(--border-color); border-radius: 18px; padding: 10px 15px; resize: none; font-size: 16px; max-height: 120px; background-color: var(--sidebar-bg); color: var(--text-color); }
        .input-area button { background: #0b93f6; color: white; border: none; border-radius: 50%; width: 40px; height: 40px; font-size: 20px; cursor: pointer; flex-shrink: 0; }
        label { font-weight: bold; margin-top: 15px; margin-bottom: 5px; display: block; }
        select, input[type=number], input[type=file], .sidebar textarea { width: 100%; padding: 8px; border: 1px solid var(--border-color); border-radius: 5px; box-sizing: border-box; background-color: var(--bg-color); color: var(--text-color);}
        #file-list { font-size: 12px; margin-top: 5px; }
        .file-item { display: flex; justify-content: space-between; align-items: center; margin-bottom: 3px; }
        .file-item span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .file-item button { background: #dc3545; color: white; border: none; border-radius: 4px; padding: 1px 6px; font-size: 12px; cursor: pointer; }
        .theme-toggle { position: fixed; top: 10px; right: 10px; cursor: pointer; font-size: 24px; z-index: 100; }
    </style>
</head>
<body>
    <div class="theme-toggle" id="theme-toggle">🌓</div>
    <div class="wrapper">
        <div class="sidebar">
            <h2>設定</h2>
            <div id="config-form">
                <label for="model_name">モデル:</label>
                <select id="model_name" name="model_name">
                    <option value="gemini-1.5-flash" {% if config.model_name == 'gemini-1.5-flash' %}selected{% endif %}>Gemini 1.5 Flash</option>
                    <option value="gemini-1.5-pro" {% if config.model_name == 'gemini-1.5-pro' %}selected{% endif %}>Gemini 1.5 Pro</option>
                    <option value="gemini-1.0-pro" {% if config.model_name == 'gemini-1.0-pro' %}selected{% endif %}>Gemini 1.0 Pro</option>
                </select>
                <label for="temperature">Temperature:</label>
                <input type="number" id="temperature" name="temperature" min="0" max="2" step="0.1" value="{{ config.temperature }}">
                <label for="system_instruction">System Instruction:</label>
                <textarea id="system_instruction" name="system_instruction" rows="6">{{ config.system_instruction }}</textarea>
                <label for="knowledge_file">知識ファイル (最大10件):</label>
                <input type="file" id="knowledge_file" name="knowledge_file" accept=".txt" multiple>
                <div id="file-list"></div>
            </div>
        </div>
        <div class="chat-wrapper">
            <div class="chat-history" id="chat-history">
                {% for item in history %}
                <div class="message {% if item.role == 'user' %}user-message{% else %}model-message{% endif %}">
                    <div class="message-bubble"><p>{{ item.text }}</p></div>
                </div>
                {% endfor %}
            </div>
            <div class="input-area">
                <form id="chat-form">
                    <textarea name="prompt" placeholder="メッセージを入力..." required></textarea>
                    <button type="submit">↑</button>
                </form>
            </div>
        </div>
    </div>
    
    <script>
        const chatForm = document.getElementById('chat-form');
        const configForm = document.getElementById('config-form');
        const promptInput = chatForm.querySelector('textarea[name="prompt"]');
        const chatHistory = document.getElementById('chat-history');
        const fileInput = document.getElementById('knowledge_file');
        const fileListDiv = document.getElementById('file-list');
        const themeToggle = document.getElementById('theme-toggle');
        let knowledgeFiles = [];

        themeToggle.addEventListener('click', () => {
            document.body.classList.toggle('dark-mode');
            localStorage.setItem('theme', document.body.classList.contains('dark-mode') ? 'dark' : 'light');
        });
        document.addEventListener('DOMContentLoaded', () => {
            if (localStorage.getItem('theme') === 'dark') {
                document.body.classList.add('dark-mode');
            }
            chatHistory.scrollTop = chatHistory.scrollHeight;
        });

        fileInput.addEventListener('change', (event) => {
            if (event.target.files.length > 10) {
                alert("ファイルは最大10個までです。");
                event.target.value = '';
                return;
            }
            knowledgeFiles = [];
            const files = Array.from(event.target.files);
            let filesRead = 0;
            if (files.length === 0) { renderFileList(); return; }
            files.forEach(file => {
                const reader = new FileReader();
                reader.onload = (e) => {
                    knowledgeFiles.push({ name: file.name, content: e.target.result });
                    filesRead++;
                    if (filesRead === files.length) renderFileList();
                };
                reader.readAsText(file, 'UTF-8');
            });
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
                deleteBtn.onclick = () => {
                    knowledgeFiles.splice(index, 1);
                    renderFileList();
                };
                fileItem.appendChild(fileNameSpan);
                fileItem.appendChild(deleteBtn);
                fileListDiv.appendChild(fileItem);
            });
        }
        
        chatForm.addEventListener('submit', async function(event) {
            event.preventDefault();
            const userPrompt = promptInput.value.trim();
            if (!userPrompt) return;

            appendMessage(userPrompt, 'user');
            promptInput.value = '';
            promptInput.style.height = 'auto';

            const modelBubble = appendMessage('...', 'model');
            
            const formData = new FormData();
            formData.append('prompt', userPrompt);
            formData.append('model_name', document.getElementById('model_name').value);
            formData.append('temperature', document.getElementById('temperature').value);
            formData.append('system_instruction', document.getElementById('system_instruction').value);
            const combinedFileContent = knowledgeFiles.map(f => `--- File: ${f.name} ---\n${f.content}`).join('\\n\\n');
            formData.append('file_content', combinedFileContent);
            
            saveConfigToCookie();
            
            try {
                const response = await fetch('/stream_chat', { method: 'POST', body: formData });
                if (!response.ok) throw new Error(`Server error: ${response.status}`);

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
            } catch (error) {
                modelBubble.querySelector('p').innerText = "エラーが発生しました: " + error;
            }
        });

        function appendMessage(text, role) {
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${role}-message`;
            const bubbleDiv = document.createElement('div');
            bubbleDiv.className = 'message-bubble';
            const p = document.createElement('p');
            p.innerText = text;
            bubbleDiv.appendChild(p);
            messageDiv.appendChild(messageDiv);
            chatHistory.appendChild(messageDiv);
            chatHistory.scrollTop = chatHistory.scrollHeight;
            return bubbleDiv;
        }
        
        function saveConfigToCookie() {
            const config = {
                model_name: document.getElementById('model_name').value,
                temperature: document.getElementById('temperature').value,
                system_instruction: document.getElementById('system_instruction').value,
            };
            document.cookie = `ai_config=${JSON.stringify(config)}; max-age=31536000; path=/`;
        }
    </script>
</body>
</html>
"""

# --- ▼▼▼ ここに削除したルートを復活させます ▼▼▼ ---
@app.route('/clear_file')
def clear_file():
    # この機能は現在JavaScriptで処理されるため、サーバー側では不要ですが、
    # エラー防止のために空のリダイレクトを残しておきます。
    return redirect(url_for('home'))

@app.route('/delete/<log_id>')
def delete_log(log_id):
    # この機能は現在JavaScriptで処理されるため、サーバー側では不要ですが、
    # ページのリロードで履歴を再表示するために残しておきます。
    try:
        db.collection('conversations').document(log_id).delete()
    except Exception as e:
        print(f"Error deleting log: {e}")
    return redirect(url_for('home'))

# --- メインページ表示用のルート ---
@app.route('/', methods=['GET'])
def home():
    saved_config = request.cookies.get('ai_config')
    config = {}
    if saved_config:
        try: config = json.loads(saved_config)
        except (json.JSONDecodeError, TypeError): pass
    
    config.setdefault('model_name', 'gemini-1.5-flash')
    config.setdefault('temperature', 1.0)
    config.setdefault('system_instruction', "あなたは親切で優秀なAIアシスタントです。")

    display_history = []
    try:
        docs = db.collection('conversations').order_by('timestamp').stream()
        for doc in docs:
            display_history.append(doc.to_dict())
    except Exception as e:
        print(f"Error fetching history: {e}")
        
    return render_template_string(HTML_TEMPLATE, history=display_history, config=config)

# --- AIとの対話（ストリーミング）専門のルート ---
@app.route('/stream_chat', methods=['POST'])
def stream_chat():
    def generate():
        try:
            user_prompt = request.form.get('prompt', "")
            model_name = request.form.get('model_name', 'gemini-1.5-flash')
            system_instruction = request.form.get('system_instruction', "")
            temperature = float(request.form.get('temperature', 1.0))
            file_content = request.form.get('file_content', '')
            
            api_key = os.environ.get('GEMINI_API_KEY')
            if not (api_key and genai and user_prompt):
                yield "エラー: サーバー設定が不十分か、プロンプトが空です。"
                return

            full_ai_response = ""
            
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(
                model_name=model_name,
                generation_config=genai.GenerationConfig(temperature=temperature),
                system_instruction=system_instruction,
            )

            final_prompt = user_prompt
            if file_content:
                final_prompt = f"以下の知識ファイルを元に回答してください。\n---知識ファイル---\n{file_content}\n--------------\nユーザーの質問: {user_prompt}"

            response_stream = model.generate_content(final_prompt, stream=True)
            
            for chunk in response_stream:
                if chunk.text:
                    full_ai_response += chunk.text
                    yield chunk.text
            
            # 応答が完了してからDBに保存
            utc_now = datetime.datetime.now(datetime.timezone.utc)
            db.collection('conversations').add({'role': 'user', 'text': user_prompt, 'timestamp': utc_now})
            db.collection('conversations').add({'role': 'model', 'text': full_ai_response, 'timestamp': utc_now + datetime.timedelta(microseconds=1)})
        except Exception as e:
            print(f"Error during generation: {e}")
            yield f"API呼び出し中にエラーが発生しました: {e}"

    # 文字化け対策としてcharset=utf-8をレスポンスに含める
    return Response(stream_with_context(generate()), mimetype='text/plain; charset=utf-8')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=True)
