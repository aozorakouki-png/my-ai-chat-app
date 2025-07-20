import os
import datetime
import json
from flask import Flask, request, render_template_string, make_response, redirect, url_for

# (他のimport文は変更なし)
from google.cloud import firestore
try:
    import google.generativeai as genai
except ImportError:
    genai = None

app = Flask(__name__)
db = firestore.Client()

# --- ▼▼▼ HTMLとCSSをチャット形式に全面的に変更 ▼▼▼ ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>AI Chat</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        html, body { height: 100%; margin: 0; font-family: sans-serif; }
        .chat-wrapper { display: flex; flex-direction: column; height: 100%; max-width: 800px; margin: auto; }
        .chat-history { flex-grow: 1; overflow-y: auto; padding: 20px; }
        .message { display: flex; margin-bottom: 15px; }
        .message-bubble { max-width: 70%; padding: 10px 15px; border-radius: 18px; }
        .user-message { justify-content: flex-end; }
        .user-message .message-bubble { background-color: #0b93f6; color: white; }
        .model-message { justify-content: flex-start; }
        .model-message .message-bubble { background-color: #e5e5ea; color: black; }
        .input-area { padding: 15px; border-top: 1px solid #ddd; background-color: #f7f9fc; }
        .input-area form { display: flex; gap: 10px; }
        .input-area textarea { flex-grow: 1; border: 1px solid #ddd; border-radius: 18px; padding: 10px 15px; resize: none; font-size: 16px; max-height: 100px;}
        .input-area button { background: #0b93f6; color: white; border: none; border-radius: 50%; width: 40px; height: 40px; font-size: 20px; cursor: pointer; }
    </style>
</head>
<body>
    <div class="chat-wrapper">
        <div class="chat-history" id="chat-history">
            {% for item in history %}
            <div class="message {% if item.role == 'user' %}user-message{% else %}model-message{% endif %}">
                <div class="message-bubble">
                    <p style="white-space: pre-wrap;">{{ item.text }}</p>
                </div>
            </div>
            {% endfor %}
        </div>
        <div class="input-area">
            <form method="post">
                <textarea name="prompt" placeholder="メッセージを入力..." oninput="this.style.height = 'auto'; this.style.height = this.scrollHeight + 'px';"></textarea>
                <button type="submit">↑</button>
            </form>
        </div>
    </div>
    <script>
        // ページ読み込み時に一番下までスクロール
        const chatHistory = document.getElementById('chat-history');
        chatHistory.scrollTop = chatHistory.scrollHeight;
    </script>
</body>
</html>
"""

# (Pythonのロジック部分は簡略化のため、一部機能を削除・変更)
@app.route('/', methods=['GET', 'POST'])
def home():
    ai_response = ""
    error_message = ""
    api_key = os.environ.get('GEMINI_API_KEY')

    if request.method == 'POST':
        user_prompt = request.form.get('prompt', "")
        
        if not api_key:
            error_message = "サーバー側でAPIキーが設定されていません。"
        elif not genai:
             error_message = "サーバー側でGenerative AIライブラリの読み込みに失敗しました。"
        elif user_prompt:
            try:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel('gemini-1.5-flash')

                # DBから全履歴を取得
                docs = db.collection('conversations').order_by('timestamp').stream()
                chat_history = []
                for doc in docs:
                    log = doc.to_dict()
                    chat_history.append({'role': 'user', 'parts': [log.get('prompt')]})
                    chat_history.append({'role': 'model', 'parts': [log.get('response')]})

                chat = model.start_chat(history=chat_history)
                response = chat.send_message(user_prompt)
                ai_response = response.text

                # ユーザーのプロンプトとAIの応答を両方保存
                db.collection('conversations').add({'role': 'user', 'text': user_prompt, 'timestamp': datetime.datetime.now(datetime.timezone.utc)})
                db.collection('conversations').add({'role': 'model', 'text': ai_response, 'timestamp': datetime.datetime.now(datetime.timezone.utc)})

            except Exception as e:
                error_message = f"API呼び出し中にエラーが発生しました: {e}"

    # 表示用の会話ログを全件取得
    display_history = []
    try:
        docs = db.collection('conversations').order_by('timestamp').stream()
        for doc in docs:
            log_data = doc.to_dict()
            display_history.append(log_data)
    except Exception as e:
        print(f"Error fetching history: {e}")
        
    # エラーがあればそれも履歴として表示
    if error_message:
        display_history.append({'role': 'model', 'text': error_message})

    return render_template_string(HTML_TEMPLATE, history=display_history)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=True)
