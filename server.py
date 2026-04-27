"""
NEEX Social Backend - Python/Flask
Railway-ready entry point. Drop-in replacement for the Node.js backend.
"""
import sys
import io
import os

# Fix Windows encoding for emoji output
if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

from app import app, socketio

# Register all route modules
import routes_auth
import routes_posts
import routes_admin
import routes_sockets

PORT = int(os.environ.get('PORT', 5001))

@app.before_request
async def _ensure_admin_init():
    if not getattr(app, '_admin_initialized', False):
        await routes_auth.init_admin()
        app._admin_initialized = True

if __name__ == '__main__':
    env = os.environ.get('NODE_ENV', 'development')
    print(f"[ROCKET] NEEX Backend (Python) running on port {PORT}")
    print(f"[FIRE] Database: FIREBASE-REALTIME (Global Cloud)")
    print(f"[GLOBE] Environment: {env}")
    print(f"[ART] UI: Enhanced Social Media Platform")
    print(f"[SATELLITE] Real-time sync: ENABLED")
    print(f"[SPARKLE] Features: Posts, Stories, Live Streaming, Enhanced Messaging")
    print(f"[TARGET] Advanced: Video/Image uploads, Hashtags, Search, Comments")
    print(f"[LINK] Socket.IO: Real-time messaging and notifications")

    socketio.run(app, host='0.0.0.0', port=PORT, debug=(env != 'production'),
                 allow_unsafe_werkzeug=True)
