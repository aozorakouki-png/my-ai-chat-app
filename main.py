import os
import datetime
import json
from flask import Flask, request, render_template_string, make_response, redirect, url_for

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

# --- HTMLテンプレート ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Advanced AI Chat</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: sans-serif; max-width: 900px; margin: auto; padding: 20px; background-color: #f7f9fc; }
        h1 { color: #1a73e8; }
        .container { display: flex; gap: 20px; }
        .main-content { flex: 2; }
        .history { flex: 1; border-left: 1px solid #ddd; padding-left: 20px; height: 80vh; overflow-y: auto; }
        .history-item { display: flex; align-items: flex-start; gap: 10px; margin-bottom: 15px; padding: 10px; border-radius: 5px; background-color: #e8f0fe; }
        .history-item .content { flex-grow: 1; }
        .history-item p { margin: 0; white-space: pre-wrap; word-wrap: break-word; }
        .history-item .prompt { font-weight: bold; }
        .delete-btn { background: #ff4d4d; color: white; border: none; border-radius: 50%; width: 20px; height: 20px; cursor: pointer; font-size: 12px; line-height: 20px; text-align: center; text-decoration: none; display: inline-block;}
        textarea, select, input[type=number], input[type=file] { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 5px; box-sizing: border-box; margin-top: 5px; }
        .response { background-color: #ffffff; border: 1px solid #ddd; padding: 15px; border-radius: 5px; margin-top: 20px; white-space: pre-wrap; }
        input[type=submit] { background-color: #1a73e8; color: white; padding: 10px 15px; border: none; border-radius: 5px; cursor: pointer; margin-top: 10px;}
        .settings-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 15px;}
        label { font-weight: bold; margin-bottom: 5px; display: block; }
        .file-info { display: flex; align-items: center; justify-content: space-between; font-size: 12px; color: green; }
        .clear-file-btn { background: #6c757d; color: white; border: none; border-radius: 4px; padding: 2px 8px; font-size: 12px; cursor: pointer; text-decoration: none;}
    </style>
</head>
<body>
    <h1>Advanced AI Chat</h1>
    <div class="container">
        <form method="post" enctype="multipart/form-data" style="display: contents;">
            <div class="main-content">
                <div class="settings-grid">
                    <div>
                        <label for="model_name">モデル:</label>
                        <select id="model_name" name="model_name">
                            <option value="gemini-1.5-flash" {% if config.model_name == 'gemini-1.5-flash' %}selected{% endif %}>Gemini 1.5 Flash</option>
                            <option value="gemini-1.5-pro" {% if config.model_name == 'gemini-1.5-pro' %}selected{% endif %}>Gemini 1.5 Pro</option>
                            <option value="gemini-1.0-pro" {% if config.model_name == 'gemini-1.0-pro' %}selected{% endif %}>Gemini 1.0 Pro</option>
                        </select>
                    </div>
                    <div>
                        <label for="temperature">Temperature (0-2):</label>
                        <input type="number" id="temperature" name="temperature" min="0" max="2" step="0.1" value="{{ config.temperature }}">
                    </div>
                </div>
                <div>
                    <label for="system_instruction">System Instruction (AIへの指示):</label>
                    <textarea id="system_instruction" name="system_instruction" rows="4">{{ config.system_instruction }}</textarea>
                </div>
                <br>
                <div>
                    <label for="knowledge_file">知識ファイル (TXT):</label>
                    <input type="file" id="knowledge_file" name="knowledge_file" accept=".txt">
                    {% if file_content %}
                    <div class="file-info">
                        <span>現在、ファイル「{{ file_name }}」が知識として読み込まれています。</span>
                        <a href="{{ url_for('clear_file') }}" class="clear-file-btn">ファイルをクリア</a>
                    </div>
                    {% endif %}
                </div>

                <input type="hidden" name="file_content" value="{{ file_content }}">
                <input type="hidden" name="file_name" value="{{ file_name }}">
                <br>
                <div>
                    <label for="prompt">プロンプト:</label>
                    <textarea id="prompt" name="prompt" rows="5" placeholder="ここにプロンプトを入力..."></textarea>
                </div>
                <input type="submit" value="送信">

                {% if error %}
                <div class="response" style="color: red;"><h2>エラー:</h2><p>{{ error }}</p></div>
                {% elif response %}
                <div class="response"><h2>AIの応答:</h2><p>{{ response }}</p></div>
                {% endif %}
            </div>

            <div class="history">
                <h2>会話ログ (ロックして記憶させる)</h2>
                {% for item in history %}
                <div class="history-item">
                    <input type="checkbox" name="locked_logs" value="{{ item.id }}" {% if item.id in locked_log_ids %}checked{% endif %}>
                    <div class="content">
                        <p class="prompt">You: {{ item.prompt }}</p>
                        <p class="response">AI: {{ item.response }}</p>
                    </div>
                    <a href="{{ url_for('delete_log', log_id=item.id) }}" class="delete-btn" onclick="return confirm('このログを削除しますか？');">×</a>
                </div>
                {% else %}
                <p>まだ会話がありません。</p>
                {% endfor %}
            </div>
        </form>
    </div>
</body>
</html>
"""

# --- ファイルクリア用のルート ---
@app.route('/clear_file')
def clear_file():
    saved_config = request.cookies.get('ai_config')
    if saved_config:
        try:
            config = json.loads(saved_config)
            config['file_content'] = ""
            config['file_name'] = ""
            resp = make_response(redirect(url_for('home')))
            resp.set_cookie('ai_config', json.dumps(config), max_age=365*24*60*60)
            return resp
        except (json.JSONDecodeError, TypeError):
            pass
    return redirect(url_for('home'))

# --- ログ削除用のルート ---
@app.route('/delete/<log_id>')
def delete_log(log_id):
    try:
        db.collection('conversations').document(log_id).delete()
    except Exception as e:
        print(f"Error deleting log: {e}")
    return redirect(url_for('home'))

# --- メインの処理 ---
@app.route('/', methods=['GET', 'POST'])
def home():
    user_prompt = ""
    ai_response = ""
    error_message = ""
    locked_log_ids = []
    
    # --- ▼▼▼ ここでCookieから全設定を読み込みます ▼▼▼ ---
    saved_config = request.cookies.get('ai_config')
    if saved_config:
        try:
            config = json.loads(saved_config)
        except (json.JSONDecodeError, TypeError):
            saved_config = None
    
    if not saved_config:
        # Cookieがない場合のデフォルト設定
        config = {
            "model_name": "gemini-1.5-flash", "temperature": 1.0, "system_instruction": "",
            "file_content": "", "file_name": ""
        }
    
    file_content = config.get('file_content', '')
    file_name = config.get('file_name', '')
    
    api_key = os.environ.get('GEMINI_API_KEY')

    if request.method == 'POST':
        # --- ▼▼▼ ここでフォームから送信された全設定をconfigに保存します ▼▼▼ ---
        user_prompt = request.form.get('prompt', "")
        config['model_name'] = request.form.get('model_name')
        config['system_instruction'] = request.form.get('system_instruction')
        config['temperature'] = float(request.form.get('temperature', 1.0))
        locked_log_ids = request.form.getlist('locked_logs')

        uploaded_file = request.files.get('knowledge_file')
        if uploaded_file and uploaded_file.filename != '':
            file_name = uploaded_file.filename
            try:
                file_content = uploaded_file.read().decode('utf-8')
            except Exception as e:
                error_message = f"ファイルの読み込みに失敗しました: {e}"
        
        config['file_content'] = file_content
        config['file_name'] = file_name
        
        # (AIへの送信処理は省略)
        # ...

    # (DBからの履歴取得処理は省略)
    # ...
        
    # --- ▼▼▼ ここで更新された全設定をCookieに書き込みます ▼▼▼ ---
    resp = make_response(render_template_string(HTML_TEMPLATE, prompt=user_prompt, response=ai_response, error=error_message, history=[], config=config, locked_log_ids=locked_log_ids, file_content=file_content, file_name=file_name))
    resp.set_cookie('ai_config', json.dumps(config), max_age=365*24*60*60)
    
    return resp

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=True)
