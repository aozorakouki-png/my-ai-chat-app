import os
import datetime
import json
from flask import Flask, request, render_template_string, Response, stream_with_context
from urllib.parse import unquote

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
        .file-item span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding-right: 5px;}
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
                    <option value="gemini-1.5-flash">Gemini 1.5 Flash</option>
                    <option value="gemini-1.5-pro">Gemini 1.5 Pro</option>
                    <option value="gemini-1.0-pro">Gemini 1.0 Pro</option>
                </select>
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
        // --- State Management & Initialization ---
        const chatForm = document.getElementById('chat-form');
        const promptInput = chatForm.querySelector('textarea[name="prompt"]');
        const chatHistory = document.getElementById('chat-history');
        const fileInput = document
