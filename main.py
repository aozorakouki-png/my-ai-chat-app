import os
from flask import Flask, request, render_template_string

# google-generativeai ���C���X�g�[������Ă��Ȃ��ꍇ�̃G���[��h��
try:
    import google.generativeai as genai
except ImportError:
    # Cloud Run���ł� requirements.txt ����C���X�g�[�������̂ŁA
    # ���̃G���[�͎�Ƀ��[�J���ł̎��s���ɔ������܂��B
    print("�K�v�ȃ��C�u����������܂���B'pip install google-generativeai' �����s���Ă��������B")
    genai = None

app = Flask(__name__)

# --- HTML�e���v���[�g ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Cloud Run AI Chat</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: sans-serif; max-width: 600px; margin: auto; padding: 20px; background-color: #f7f9fc; }
        h1 { color: #1a73e8; }
        textarea { width: 100%; height: 100px; border: 1px solid #ddd; border-radius: 5px; padding: 10px; }
        .response { background-color: #ffffff; border: 1px solid #ddd; padding: 15px; border-radius: 5px; margin-top: 20px; white-space: pre-wrap; }
        input[type=submit] { background-color: #1a73e8; color: white; padding: 10px 15px; border: none; border-radius: 5px; cursor: pointer; }
    </style>
</head>
<body>
    <h1>Cloud Run AI Chat</h1>
    <form method="post">
        <textarea name="prompt" placeholder="�����Ƀv�����v�g�����...">{{ prompt }}</textarea><br><br>
        <input type="submit" value="���M">
    </form>
    {% if error %}
    <div class="response" style="color: red;">
        <h2>�G���[:</h2>
        <p>{{ error }}</p>
    </div>
    {% elif response %}
    <div class="response">
        <h2>AI�̉���:</h2>
        <p>{{ response }}</p>
    </div>
    {% endif %}
</body>
</html>
"""

@app.route('/', methods=['GET', 'POST'])
def home():
    user_prompt = ""
    ai_response = ""
    error_message = ""

    # ���ϐ�����API�L�[��ǂݍ��ށi�C�Őݒ�j
    api_key = os.environ.get('GEMINI_API_KEY')

    if not api_key:
        error_message = "�T�[�o�[����API�L�[���ݒ肳��Ă��܂���B"
    elif not genai:
         error_message = "�T�[�o�[����Generative AI���C�u�����̓ǂݍ��݂Ɏ��s���܂����B"
    elif request.method == 'POST':
        user_prompt = request.form['prompt']
        if user_prompt:
            try:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel('gemini-1.5-flash')
                response = model.generate_content(user_prompt)
                ai_response = response.text
            except Exception as e:
                error_message = f"API�Ăяo�����ɃG���[���������܂���: {e}"

    return render_template_string(HTML_TEMPLATE, prompt=user_prompt, response=ai_response, error=error_message)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=True)