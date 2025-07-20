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
<html>
<head>
    <title>AI Chat (Full-Featured)</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: sans-serif; background-color: #f7f9fc; margin: 0; }
        .wrapper { display: flex; height: 100vh; }
        .sidebar { width: 320px; padding: 20px; border-right: 1px solid #ddd; background-color: #ffffff; display: flex; flex-direction: column; overflow-y: auto;}
        .chat-wrapper { flex-grow: 1; display: flex; flex-direction: column; height: 100vh; }
        .chat-history { flex-grow: 1; overflow-y: auto; padding: 20px; }
        .message { display: flex; margin-bottom: 20px; max-width: 90%; }
        .message-bubble { padding: 10px 15px; border-radius: 18px; line-height: 1.5; }
        .user-message { align-self: flex-end; }
        .user-message .message-bubble { background-color: #0b93f6; color: white; }
        .model-message { align-self: flex-start; }
        .model-message .message-bubble { background-color: #e5e5ea; color: black; }
        .input-area { padding: 15px; border-top: 1px solid #ddd; background-color: #f0f2f5; }
        .input-area form { display: flex; gap: 10px; align-items: center; }
        .input-area textarea { flex-grow: 1; border: 1px solid #ddd; border-radius: 18px; padding: 10px 15px; resize: none; font-size: 16px; max-height: 120px; }
        .input-area button { background: #0b93f6; color: white; border: none; border-radius: 50%; width: 40px; height: 40px; font-size: 20px; cursor: pointer; flex-shrink: 0; }
        label { font-weight: bold; margin-top: 15px; margin-bottom: 5px; display: block; }
        select, input[type=number], input[type=file], textarea { width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 5px; box-sizing: border-box; }
        .file-info { display: flex; align-items: center; justify-content: space-between; font-size: 12px; color: green; margin-top: 5px; }
        .clear-file-btn { background: #6c757d; color: white; border-radius: 4px; padding: 2px 8px; font-size: 12px; cursor: pointer; text-decoration: none; }
    </style>
</head>
<body>
    <div class="wrapper">
        <div class="sidebar">
            <h2>設定</h2>
            <form id="config-form">
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
                
                <label for="knowledge_file">知識ファイル (TXT):</label>
                <input type="file" id="knowledge_file" name="knowledge_file" accept=".txt">
                {% if file_name %}
                <div class="file-info">
                    <span>{{ file_name }}</span>
                    <a href="{{ url_for('clear_file') }}" class="clear-file-btn">クリア</a>
                </div>
                {% endif %}
            </form>
        </div>
        <div class="chat-wrapper">
            <div class="chat-history" id="chat-history">
                {% for item in history %}
                <div class="message {% if item.role == 'user' %}user-message{% else %}model-message{% endif %}">
                    <div class="message-bubble"><p style="white-space: pre-wrap;">{{ item.text }}</p></div>
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
        let uploadedFileContent = "";
        let uploadedFileName = "";

        configForm.querySelector('#knowledge_file').addEventListener('change', function(event) {
            const file = event.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = function(e) {
                    uploadedFileContent = e.target.result;
                    uploadedFileName = file.name;
                    saveConfigToCookie(); 
                    document.querySelector('.file-info span').innerText = uploadedFileName;
                };
                reader.readAsText(file);
            }
        });

        chatForm.addEventListener('submit', async function(event) {
            event.preventDefault();
            const userPrompt = promptInput.value.trim();
            if (!userPrompt) return;

            appendMessage(userPrompt, 'user');
            promptInput.value = '';
            promptInput.style.height = 'auto';

            const modelBubble = appendMessage('', 'model');
            
            const formData = new FormData(configForm);
            formData.append('prompt', userPrompt);
            formData.append('file_content', uploadedFileContent);
            
            saveConfigToCookie();
            
            try {
                const response = await fetch('/stream_chat', {
                    method: 'POST',
                    body: formData
                });

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let fullResponse = "";
                while (true) {
                    const { value, done } = await reader.read();
                    if (done) break;
                    const chunk = decoder.decode(value, {stream: true});
                    fullResponse += chunk;
                    modelBubble.querySelector('p').innerText = fullResponse;
                    chatHistory.scrollTop = chatHistory.scrollHeight;
                }
                 // チャット完了後、3秒待ってからリロードして履歴をDBから再読み込み
                setTimeout(() => window.location.reload(), 3000);
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
            p.style.whiteSpace = 'pre-wrap';
            p.innerText = text;
            
            bubbleDiv.appendChild(p);
            messageDiv.appendChild(bubbleDiv);
            chatHistory.appendChild(messageDiv);
            chatHistory.scrollTop = chatHistory.scrollHeight;
            return bubbleDiv;
        }
        
        function saveConfigToCookie() {
            const config = {
                model_name: document.getElementById('model_name').value,
                temperature: document.getElementById('temperature').value,
                system_instruction: document.getElementById('system_instruction').value,
                file_name: uploadedFileName
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
    resp = make_response(redirect(url_for('home')))
    saved_config = request.cookies.get('ai_config')
    if saved_config:
        try:
            config = json.loads(saved_config)
            config['file_name'] = ""
            resp.set_cookie('ai_config', json.dumps(config), max_age=365*24*60*60)
        except (json.JSONDecodeError, TypeError):
            resp.delete_cookie('ai_config')
    return resp

# (ログ削除機能は一旦コメントアウト。必要に応じて復活させてください)
# @app.route('/delete/<log_id>')
# def delete_log(log_id):
#     try:
#         db.collection('conversations').document(log_id).delete()
#     except Exception as e:
#         print(f"Error deleting log: {e}")
#     return redirect(url_for('home'))

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
    config.setdefault('file_name', "")

    display_history = []
    try:
        docs = db.collection('conversations').order_by('timestamp').stream()
        for doc in docs:
            display_history.append(doc.to_dict())
    except Exception as e:
        print(f"Error fetching history: {e}")
        
    return render_template_string(HTML_TEMPLATE, history=display_history, config=config, file_name=config.get('file_name'))

# --- AIとの対話（ストリーミング）専門のルート ---
@app.route('/stream_chat', methods=['POST'])
def stream_chat():
    def generate():
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
        try:
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
            
            utc_now = datetime.datetime.now(datetime.timezone.utc)
            db.collection('conversations').add({'role': 'user', 'text': user_prompt, 'timestamp': utc_now})
            db.collection('conversations').add({'role': 'model', 'text': full_ai_response, 'timestamp': utc_now + datetime.timedelta(microseconds=1)})
        except Exception as e:
            print(f"Error during generation: {e}")
            yield f"API呼び出し中にエラーが発生しました: {e}"

    return Response(stream_with_context(generate()), mimetype='text/plain')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=True)
