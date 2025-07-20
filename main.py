import os
import datetime
from flask import Flask, request, render_template_string

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

# --- HTMLテンプレートに設定項目と会話ログ表示を追加 ---
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
        .history-item { margin-bottom: 15px; padding: 10px; border-radius: 5px; background-color: #e8f0fe; }
        .history-item p { margin: 0; white-space: pre-wrap; word-wrap: break-word; }
        .history-item .prompt { font-weight: bold; }
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
        <div class="main-content">
            <form method="post">
                
                <div class="settings-grid">
                    <div>
                        <label for="model_name">モデル:</label>
                        <select id="model_name" name="model_name">
                            <option value="gemini-1.5-flash" {% if config.model_name == 'gemini-1.5-flash' %}selected{% endif %}>Gemini 1.5 Flash</option>
                            <option value="gemini-1.5-pro" {% if config.model_name == 'gemini-1.5-pro' %}selected{% endif %}>Gemini 1.5 Pro</option>
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
            </form>

            {% if error %}
            <div class="response" style="color: red;"><h2>エラー:</h2><p>{{ error }}</p></div>
            {% elif response %}
            <div class="response"><h2>AIの応答:</h2><p>{{ response }}</p></div>
            {% endif %}
        </div>

        <div class="history">
            <h2>会話ログ</h2>
            {% for item in history %}
            <div class="history-item">
                <p class="prompt">You: {{ item.prompt }}</p>
                <p class="response">AI: {{ item.response }}</p>
            </div>
            {% else %}
            <p>まだ会話がありません。</p>
            {% endfor %}
        </div>
    </div>
</body>
</html>
"""

@app.route('/', methods=['GET', 'POST'])
def home():
    user_prompt = ""
    ai_response = ""
    error_message = ""
    
    # デフォルト設定
    config = {
        "model_name": "gemini-1.5-flash",
        "temperature": 1.0,
        "system_instruction": "あなたは親切で優秀なAIアシスタントです。"
    }
    
    api_key = os.environ.get('GEMINI_API_KEY')

    if request.method == 'POST':
        # フォームから設定値を取得し、configを更新
        user_prompt = request.form.get('prompt', "")
        config['model_name'] = request.form.get('model_name', 'gemini-1.5-flash')
        config['system_instruction'] = request.form.get('system_instruction', "")
        try:
            config['temperature'] = float(request.form.get('temperature', 1.0))
        except (ValueError, TypeError):
            config['temperature'] = 1.0

        if not api_key:
            error_message = "サーバー側でAPIキーが設定されていません。"
        elif not genai:
             error_message = "サーバー側でGenerative AIライブラリの読み込みに失敗しました。"
        elif user_prompt:
            try:
                genai.configure(api_key=api_key)

                # --- Geminiの設定オブジェクトを作成 ---
                generation_config = genai.GenerationConfig(
                    temperature=config['temperature']
                )
                
                model = genai.GenerativeModel(
                    model_name=config['model_name'],
                    generation_config=generation_config,
                    system_instruction=config['system_instruction']
                )
                # --- 設定コードここまで ---

                response = model.generate_content(user_prompt)
                ai_response = response.text

                # --- Firestoreに会話ログを保存 ---
                doc_ref = db.collection('conversations').document()
                doc_ref.set({
                    'prompt': user_prompt,
                    'response': ai_response,
                    'config': config, # 設定も一緒に保存
                    'timestamp': datetime.datetime.now(datetime.timezone.utc)
                })
                # --- 保存コードここまで ---

            except Exception as e:
                error_message = f"API呼び出し中にエラーが発生しました: {e}"

    # --- Firestoreから会話ログを取得 ---
    history = []
    try:
        # 最新10件のログを取得
        docs = db.collection('conversations').order_by('timestamp', direction=firestore.Query.DESCENDING).limit(10).stream()
        for doc in docs:
            history.append(doc.to_dict())
    except Exception as e:
        print(f"Error fetching history: {e}")
    # --- 取得コードここまで ---
        
    return render_template_string(HTML_TEMPLATE, prompt=user_prompt, response=ai_response, error=error_message, history=history, config=config)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=True)
