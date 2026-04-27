"""Socket.IO events and inline admin panel — mirrors Node.js server"""
import uuid
from datetime import datetime, timezone
from flask import request
from app import app, socketio
from flask_socketio import join_room
import database
from routes_posts import messages_store

# ---- Socket.IO handlers ----
@socketio.on('connect')
def handle_connect():
    print(f"👤 User connected: {request.sid}")

@socketio.on('join-user-room')
def handle_join_user_room(username):
    join_room(username)
    request.sid_username = username
    print(f"📱 {username} joined their room")

@socketio.on('join-stream')
def handle_join_stream(stream_id):
    join_room(f"stream-{stream_id}")
    print(f"🔴 User joined stream: {stream_id}")

@socketio.on('stream-message')
def handle_stream_message(data):
    stream_id = data.get('streamId')
    socketio.emit('stream-chat', {
        'username': data.get('username'),
        'message': data.get('message'),
        'timestamp': datetime.now(timezone.utc).isoformat()
    }, room=f"stream-{stream_id}")

@socketio.on('send-dm')
def handle_send_dm(data):
    to = data.get('to'); frm = data.get('from')
    msg = {
        'id': str(uuid.uuid4()), 'from': frm, 'to': to,
        'content': data.get('content',''),
        'messageType': data.get('messageType','text'),
        'date': datetime.now(timezone.utc).isoformat(),
        'isRead': False, 'isDelivered': True
    }
    messages_store.append(msg)
    socketio.emit('receive-dm', msg, room=to)
    socketio.emit('dm-sent', msg, room=request.sid)

@socketio.on('typing-start')
def handle_typing_start(data):
    socketio.emit('user-typing', {'username': data.get('from')}, room=data.get('to'))

@socketio.on('typing-stop')
def handle_typing_stop(data):
    socketio.emit('user-stopped-typing', {'username': data.get('from')}, room=data.get('to'))

@socketio.on('set-online')
def handle_set_online(username):
    request.sid_username = username
    socketio.emit('user-online', {'username': username}, broadcast=True, include_self=False)

@socketio.on('notify')
def handle_notify(data):
    socketio.emit('notification', {
        'type': data.get('type'),
        'message': data.get('message'),
        'postId': data.get('postId'),
        'timestamp': datetime.now(timezone.utc).isoformat()
    }, room=data.get('targetUser'))

@socketio.on('disconnect')
def handle_disconnect():
    username = getattr(request, 'sid_username', None)
    if username:
        socketio.emit('user-offline', {'username': username}, broadcast=True)
        print(f"👋 {username} disconnected")
    else:
        print(f"👋 User disconnected: {request.sid}")

# ---- Inline admin panel (same as Node.js) ----
ADMIN_HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NEEX Admin - Working Delete</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: Arial, sans-serif; background: #0a0a0a; color: #fff; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 { color: #f59e0b; margin-bottom: 30px; text-align: center; }
        .section { background: #1a1a1a; padding: 20px; margin: 20px 0; border-radius: 8px; border: 1px solid #333; }
        .btn { padding: 10px 15px; margin: 5px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; }
        .btn-primary { background: #3b82f6; color: white; }
        .btn-danger { background: #ef4444; color: white; }
        .btn-success { background: #10b981; color: white; }
        .posts-container { max-height: 400px; overflow-y: auto; }
        .post-item { padding: 15px; border-bottom: 1px solid #333; display: flex; justify-content: space-between; align-items: center; }
        .post-item:hover { background: #2a2a2a; }
        .login-form { max-width: 400px; margin: 0 auto; }
        .form-group { margin: 15px 0; }
        .form-group input { width: 100%; padding: 10px; background: #2a2a2a; border: 1px solid #444; color: white; border-radius: 5px; }
        .alert { padding: 15px; margin: 15px 0; border-radius: 5px; }
        .alert-success { background: #065f46; color: #10b981; }
        .alert-error { background: #7f1d1d; color: #ef4444; }
        .alert-info { background: #164e63; color: #06b6d4; }
        #loginSection { display: block; }
        #adminSection { display: none; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🛡️ NEEX Admin Panel (Python Backend)</h1>
        <div id="loginSection">
            <div class="section">
                <h2>🔐 Admin Login</h2>
                <div class="login-form">
                    <div id="loginAlert"></div>
                    <div class="form-group"><input type="text" id="username" placeholder="Username" value="john"></div>
                    <div class="form-group"><input type="password" id="password" placeholder="Password" value="john123"></div>
                    <button class="btn btn-primary" onclick="login()" style="width: 100%;">Login as Admin</button>
                </div>
            </div>
        </div>
        <div id="adminSection">
            <div class="section">
                <div style="text-align: right; margin-bottom: 20px;">
                    Logged in as: <strong id="currentUser"></strong> |
                    <button class="btn btn-danger" onclick="logout()">Logout</button>
                </div>
                <div id="alertArea"></div>
                <h2>📋 Post Management</h2>
                <button class="btn btn-success" onclick="loadPosts()">Refresh Posts</button>
                <button class="btn btn-danger" onclick="deleteAllPosts()">Delete ALL Posts</button>
                <div id="postsContainer" class="posts-container">
                    <div style="padding: 20px; text-align: center; color: #666;">Click "Refresh Posts" to load posts</div>
                </div>
            </div>
        </div>
    </div>
    <script>
        const API_BASE_URL = window.location.origin;
        let authToken = '', currentUser = '', allPosts = [];
        function showAlert(message, type, containerId) {
            containerId = containerId || 'alertArea';
            const c = document.getElementById(containerId);
            c.innerHTML = '<div class="alert alert-' + type + '">' + message + '</div>';
            setTimeout(() => { c.innerHTML = ''; }, 5000);
        }
        async function login() {
            const u = document.getElementById('username').value, p = document.getElementById('password').value;
            try {
                showAlert('🔐 Logging in...', 'info', 'loginAlert');
                const r = await fetch('/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: u, password: p }) });
                const d = await r.json();
                if (r.ok && d.token && d.user.isAdmin) {
                    authToken = d.token; currentUser = d.user.username;
                    document.getElementById('loginSection').style.display = 'none';
                    document.getElementById('adminSection').style.display = 'block';
                    document.getElementById('currentUser').textContent = currentUser;
                    showAlert('✅ Login successful!', 'success'); loadPosts();
                } else { showAlert('❌ Login failed: ' + (d.message || 'Invalid credentials'), 'error', 'loginAlert'); }
            } catch (e) { showAlert('❌ Login error: ' + e.message, 'error', 'loginAlert'); }
        }
        function logout() { authToken = ''; document.getElementById('loginSection').style.display = 'block'; document.getElementById('adminSection').style.display = 'none'; }
        async function loadPosts() {
            try {
                showAlert('📥 Loading posts...', 'info');
                const r = await fetch('/posts'); const d = await r.json();
                allPosts = d.posts || d; displayPosts();
                showAlert('✅ Loaded ' + allPosts.length + ' posts', 'success');
            } catch (e) { showAlert('❌ Error: ' + e.message, 'error'); }
        }
        function displayPosts() {
            const c = document.getElementById('postsContainer');
            if (!allPosts || !allPosts.length) { c.innerHTML = '<div style="padding:20px;text-align:center;color:#666">No posts</div>'; return; }
            c.innerHTML = allPosts.map(p => '<div class="post-item" id="post-' + p.id + '"><div><strong>#' + p.id + '</strong> by ' + (p.username||'Anon') + '<br><small>' + (p.content||'').substring(0,80) + '...</small></div><button class="btn btn-danger" onclick="deletePost(\'' + p.id + '\')">🗑️ DELETE</button></div>').join('');
        }
        async function deletePost(pid) {
            if (!confirm('DELETE POST #' + pid + '?')) return;
            try {
                const r = await fetch('/admin/posts/' + pid, { method: 'DELETE', headers: { 'Authorization': 'Bearer ' + authToken, 'Content-Type': 'application/json' } });
                if (r.ok) { showAlert('✅ Post ' + pid + ' deleted!', 'success'); const el = document.getElementById('post-' + pid); if (el) el.remove(); allPosts = allPosts.filter(p => p.id != pid); }
                else { const d = await r.json(); throw new Error(d.message); }
            } catch (e) { showAlert('❌ ' + e.message, 'error'); }
        }
        async function deleteAllPosts() {
            if (!confirm('DELETE ALL POSTS?')) return;
            if (prompt('Type "DELETE ALL" to confirm:') !== 'DELETE ALL') return;
            try {
                const r = await fetch('/admin/posts', { method: 'DELETE', headers: { 'Authorization': 'Bearer ' + authToken } });
                if (r.ok) { showAlert('✅ All posts deleted!', 'success'); allPosts = []; displayPosts(); }
            } catch (e) { showAlert('❌ ' + e.message, 'error'); }
        }
    </script>
</body>
</html>'''

@app.route('/admin', methods=['GET'])
def admin_panel():
    return ADMIN_HTML
