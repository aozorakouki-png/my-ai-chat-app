import os
import datetime
import json
from flask import Flask, request, render_template_string, make_response, redirect, url_for

# Firestore client
from google.cloud import firestore

# Generative AI client
try:
    import google.generativeai as genai
    from google.generativeai.types import HarmCategory, HarmBlockThreshold
except ImportError:
    genai = None

# Initialize Flask App and Firestore DB Client
app = Flask(__name__)
db = firestore.Client()

# --- HTMLテンプレート ---
# ログ削除ボタンを追加
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
        .history-item { position: relative; margin-bottom: 15px; padding: 10px; border-radius: 5px; background-color: #e8f0fe; }
        .history-item p { margin: 0 30px 0 0; white-space: pre-wrap; word-wrap: break-word; }
        .history-item .prompt { font-weight: bold; }
        .delete-btn { position: absolute; top: 5px; right: 5px; background: #ff4d4d; color: white; border: none; border-radius: 50%; width: 20px; height: 20px; cursor: pointer; font-size: 12px; line-height: 20px; text-align: center; }
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
                <form action="{{ url_for('delete_log', log_id=item.id) }}" method="post" onsubmit="return confirm('このログを削除しますか？');">
                    <button type="submit" class="delete-btn">×</button>
                </form>
            </div>
            {% else %}
            <p>まだ会話がありません。</p>
            {% endfor %}
        </div>
    </div>
</body>
</html>
"""

# --- 会話ログ削除のルート ---
@app.route('/delete/<log_id>', methods=['POST'])
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

        if not api_key:
            error_message = "サーバー側でAPIキーが設定されていません。"
        elif not genai:
             error_message = "サーバー側でGenerative AIライブラリの読み込みに失敗しました。"
        elif user_prompt:
            try:
                genai.configure(api_key=api_key)
                
                # --- Google検索ツールの設定 ---
                search_tool = genai.Tool(
                    function_declarations=[
                        genai.FunctionDeclaration(
                            name='Google Search',
                            description='最新の情報や専門的な知識を調べるためにGoogle検索を使用します。',
                            parameters={
                                'type': 'object',
                                'properties': { 'queries': {'type': 'array', 'items': {'type': 'string'}}}
                            }
                        )
                    ]
                )
                
                model = genai.GenerativeModel(
                    model_name=config['model_name'],
                    generation_config=genai.GenerationConfig(temperature=config['temperature']),
                    system_instruction=config['system_instruction'],
                    tools=[search_tool]
                )
                
                response = model.generate_content(user_prompt)
                
                # --- AIがツール（Google検索）を使おうとしたかチェック ---
                if response.candidates[0].content.parts[0].function_call:
                    function_call = response.candidates[0].content.parts[0].function_call
                    if function_call.name == 'Google Search':
                        # AIが指定したクエリで検索を実行
                        # (この部分は実際の検索ツールに置き換える必要がありますが、ここではダミーデータを使います)
                        # 例: search_results = real_Google Search(function_call.args['queries'])
                        search_results = "「日本の首都は東京です。」という検索結果が見つかりました。"

                        # 検索結果をAIに渡して、再度応答を生成させる
                        response = model.generate_content(
                            [user_prompt, genai.Part(function_response=genai.FunctionResponse(name='Google Search', response={'result': search_results}))]
                        )

                ai_response = response.text

                # Firestoreに会話ログを保存
                doc_ref = db.collection('conversations').document()
                doc_ref.set({
                    'prompt': user_prompt, 'response': ai_response,
                    'config': config, 'timestamp': datetime.datetime.now(datetime.timezone.utc)
                })

            except Exception as e:
                error_message = f"API呼び出し中にエラーが発生しました: {e}"

    # Firestoreから表示用の会話ログを取得
    display_history = []
    try:
        docs = db.collection('conversations').order_by('timestamp', direction=firestore.Query.DESCENDING).limit(10).stream()
        for doc in docs:
            log_data = doc.to_dict()
            log_data['id'] = doc.id  # 削除用にドキュメントIDを追加
            display_history.append(log_data)
    except Exception as e:
        print(f"Error fetching history: {e}")
        
    resp = make_response(render_template_string(HTML_TEMPLATE, prompt=user_prompt, response=ai_response, error=error_message, history=display_history, config=config))
    resp.set_cookie('ai_config', json.dumps(config), max_age=365*24*60*60)
    
    return resp

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=True)
