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
# ログ選択用のチェックボックスを追加
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
        .delete-btn { background: #ff4d4d; color: white; border: none; border-radius: 50%; width: 20px; height: 20px; cursor: pointer; font-size: 12px; line-height: 20px; text-align: center; }
        textarea, select, input[type=number] { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 5px; box-sizing: border-box; }
        .response { background-color: #ffffff; border: 1px solid #ddd; padding: 15px; border-radius: 5px; margin-top: 20px; white-space: pre-wrap; }
        input[type=submit] { background-color: #1a73e8; color: white; padding: 10px 15px; border: none; border-radius: 5px; cursor: pointer; margin-top: 10px;}
        .settings-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 15px;}
        label { font-weight: bold; margin-bottom: 5px; display: block; }
    </style>
</head>
<body>
    <h1>Advanced AI Chat</h1>
    <div class="container">
        <form method="post" style="display: contents;">
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
                        <textarea id="system_instruction" name="system_instruction" rows="4" placeholder="あなたは優秀なアシスタントです。簡潔に答えてください。">{{ config.system_instruction }}</textarea>
                    </div>
                    <br>
                    <div>
                        <label for="prompt">プロンプト:</label>
                        <textarea id="prompt" name="prompt" rows="5" placeholder="ここにプロンプトを入力...">{{ prompt }}</textarea>
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

# --- 会話ログ削除のルート ---
@app.route('/delete/<log_id>')
def delete_log(log_id):
    try:
        db.collection('conversations').document(log_id).delete()
    except Exception as e:
        print(f"Error deleting log: {e}")
    return redirect(url_for('home'))

@app.route('/', methods=['GET', 'POST'])
def home():
    user_prompt = ""
    ai_response = ""
    error_message = ""
    locked_log_ids = []
    
    # --- 設定の読み込み (Cookie優先) ---
    saved_config = request.cookies.get('ai_config')
    if saved_config:
        try:
            config = json.loads(saved_config)
        except (json.JSONDecodeError, TypeError):
            saved_config = None

    if not saved_config:
        config = {
            "model_name": "gemini-1.5-flash", "temperature": 1.0,
            "system_instruction": "あなたは親切で優秀なAIアシスタントです。"
        }
    
    api_key = os.environ.get('GEMINI_API_KEY')

    if request.method == 'POST':
        user_prompt = request.form.get('prompt', "")
        config['model_name'] = request.form.get('model_name', 'gemini-1.5-flash')
        config['system_instruction'] = request.form.get('system_instruction', "")
        try:
            config['temperature'] = float(request.form.get('temperature', 1.0))
        except (ValueError, TypeError):
            config['temperature'] = 1.0

        # --- ▼▼▼ ここからが変更点 ▼▼▼ ---
        # チェックされたログのIDリストを取得
        locked_log_ids = request.form.getlist('locked_logs')
        # --- ▲▲▲ ここまでが変更点 ▲▲▲ ---

        if not api_key:
            error_message = "サーバー側でAPIキーが設定されていません。"
        elif not genai:
             error_message = "サーバー側でGenerative AIライブラリの読み込みに失敗しました。"
        elif user_prompt:
            try:
                genai.configure(api_key=api_key)
                
                model = genai.GenerativeModel(
                    model_name=config['model_name'],
                    generation_config=genai.GenerationConfig(temperature=config['temperature']),
                    system_instruction=config['system_instruction'],
                )

                # --- ▼▼▼ ここからが変更点 ▼▼▼ ---
                # チェックされたログだけを読み込んでコンテキストを作成
                chat_history = []
                if locked_log_ids:
                    # Firestoreから個別にドキュメントを取得
                    selected_docs = [db.collection('conversations').document(log_id).get() for log_id in locked_log_ids]
                    # タイムスタンプでソートして時系列を維持
                    selected_docs.sort(key=lambda x: x.to_dict().get('timestamp'))
                    
                    for doc in selected_docs:
                        if doc.exists:
                            log = doc.to_dict()
                            chat_history.append({'role': 'user', 'parts': [log.get('prompt', '')]})
                            chat_history.append({'role': 'model', 'parts': [log.get('response', '')]})
                # --- ▲▲▲ ここまでが変更点 ▲▲▲ ---

                chat = model.start_chat(history=chat_history)
                response = chat.send_message(user_prompt)
                ai_response = response.text

                # Firestoreに会話ログを保存
                doc_ref = db.collection('conversations').document()
                doc_ref.set({
                    'prompt': user_prompt, 'response': ai_response,
                    'config': config, 'timestamp': datetime.datetime.now(datetime.timezone.utc)
                })

            except Exception as e:
                error_message = f"API呼び出し中にエラーが発生しました: {e}"

    # 表示用の会話ログを全件取得
    display_history = []
    try:
        docs = db.collection('conversations').order_by('timestamp', direction=firestore.Query.DESCENDING).stream()
        for doc in docs:
            log_data = doc.to_dict()
            log_data['id'] = doc.id
            display_history.append(log_data)
    except Exception as e:
        print(f"Error fetching history: {e}")
        
    resp = make_response(render_template_string(HTML_TEMPLATE, prompt=user_prompt, response=ai_response, error=error_message, history=display_history, config=config, locked_log_ids=locked_log_ids))
    resp.set_cookie('ai_config', json.dumps(config), max_age=365*24*60*60)
    
    return resp

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=True)
