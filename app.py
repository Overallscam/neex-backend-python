"""NEEX Social Backend - Python/Flask (Railway-ready)"""
import os
from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('JWT_SECRET', 'your-secret-key')
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB

CORS(app, origins=[
    'http://localhost:3000', 'http://localhost:5001', 'http://localhost:8080',
    'https://neex-57c2e.web.app', 'https://neex-57c2e.firebaseapp.com',
    'https://neex.netlify.app'
], supports_credentials=True)

# Use threading for local dev; eventlet is used automatically on Railway via gunicorn
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(os.path.join(UPLOAD_DIR, 'stories'), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_DIR, 'videos'), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_DIR, 'avatars'), exist_ok=True)
