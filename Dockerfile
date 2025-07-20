# ベースとなるPythonの環境を指定
FROM python:3.11-slim

# 環境変数（文字化け防止）
ENV PYTHONUNBUFFERED True
ENV APP_HOME /app
WORKDIR $APP_HOME

# 必要なファイルをコピー
COPY requirements.txt .

# ライブラリをインストール
RUN pip install -r requirements.txt

# アプリケーションの全ファイルをコピー
COPY . .

# アプリケーションを実行するコマンド（ポート8080でgunicornを起動）
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 main:app
