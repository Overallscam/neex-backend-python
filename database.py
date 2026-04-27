"""
Database module for NEEX Social Backend (Python)
Supports Firebase Realtime Database with local JSON file fallback.
Direct port of the Node.js database.js module.
"""

import os
import json
import threading

# ---------------------------------------------------------------------------
# Firebase initialisation
# ---------------------------------------------------------------------------
firebase_initialized = False
firebase_db = None

try:
    import firebase_admin
    from firebase_admin import credentials, db as firebase_database

    if not firebase_admin._apps:
        service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
        if service_account_json:
            import tempfile
            sa_dict = json.loads(service_account_json)
            cred = credentials.Certificate(sa_dict)
        else:
            sa_path = os.path.join(os.path.dirname(__file__), "firebase-service-account.json")
            cred = credentials.Certificate(sa_path)

        database_url = os.environ.get(
            "FIREBASE_DATABASE_URL",
            "https://neex-57c2e-default-rtdb.firebaseio.com"
        )
        firebase_admin.initialize_app(cred, {"databaseURL": database_url})
        firebase_initialized = True
        firebase_db = firebase_database
        print("[OK] Firebase Admin initialized")
except Exception as e:
    print(f"[WARN] Firebase Admin not initialized: {e}")

# ---------------------------------------------------------------------------
# Local JSON file paths (fallback)
# ---------------------------------------------------------------------------
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
USERS_DB = os.path.join(DATA_DIR, "users.json")
POSTS_DB = os.path.join(DATA_DIR, "posts.json")
MESSAGES_DB = os.path.join(DATA_DIR, "messages.json")
CHATS_DB = os.path.join(DATA_DIR, "chats.json")

_file_lock = threading.Lock()

os.makedirs(DATA_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_json(filepath):
    with _file_lock:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []


def _write_json(filepath, data):
    with _file_lock:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True


# ---------------------------------------------------------------------------
# Database initialisation (seed data)
# ---------------------------------------------------------------------------

def initialize_database():
    """Create local JSON files with seed data if they don't exist."""
    if not os.path.exists(USERS_DB):
        initial_users = [
            {
                "id": 1,
                "username": "john",
                "password": "123",
                "name": "John Doe",
                "email": "john@example.com",
                "avatar": "JD",
                "bio": "Hello! I'm John 👋",
                "verified": True,
                "followers": 1234,
                "following": 567,
                "joinDate": "2025-08-20T00:00:00.000Z",
            },
            {
                "id": 2,
                "username": "alice",
                "password": "123",
                "name": "Alice Johnson",
                "email": "alice@example.com",
                "avatar": "AJ",
                "bio": "Love coffee and books ☕📚",
                "verified": True,
                "followers": 987,
                "following": 432,
                "joinDate": "2025-08-21T00:00:00.000Z",
            },
            {
                "id": 3,
                "username": "bob",
                "password": "123",
                "name": "Bob Chen",
                "email": "bob@example.com",
                "avatar": "BC",
                "bio": "Tech enthusiast 💻",
                "verified": False,
                "followers": 543,
                "following": 789,
                "joinDate": "2025-08-22T00:00:00.000Z",
            },
            {
                "id": 4,
                "username": "sarah",
                "password": "123",
                "name": "Sarah Garcia",
                "email": "sarah@example.com",
                "avatar": "SG",
                "bio": "Designer & creator 🎨",
                "verified": True,
                "followers": 2156,
                "following": 234,
                "joinDate": "2025-08-23T00:00:00.000Z",
            },
        ]
        _write_json(USERS_DB, initial_users)

    if not os.path.exists(POSTS_DB):
        initial_posts = [
            {
                "id": 1,
                "username": "john",
                "content": "Hello everyone! This is my first post 👋",
                "date": "2025-08-25T10:00:00.000Z",
                "image": None,
                "likes": ["alice"],
                "reactions": {"like": 1, "heart": 0, "laugh": 0},
                "isAnonymous": False,
            },
            {
                "id": 2,
                "username": "alice",
                "content": "Beautiful day today! ☀️",
                "date": "2025-08-25T11:30:00.000Z",
                "image": None,
                "likes": ["john", "bob"],
                "reactions": {"like": 2, "heart": 0, "laugh": 0},
                "isAnonymous": False,
            },
            {
                "id": 3,
                "username": "bob",
                "content": "Just finished reading a great book 📚",
                "date": "2025-08-25T12:15:00.000Z",
                "image": None,
                "likes": ["sarah"],
                "reactions": {"like": 1, "heart": 0, "laugh": 0},
                "isAnonymous": False,
            },
        ]
        _write_json(POSTS_DB, initial_posts)

    if not os.path.exists(MESSAGES_DB):
        initial_messages = [
            {
                "from": "john",
                "to": "alice",
                "content": "Hey Alice, how are you?",
                "date": "2025-08-25T09:00:00.000Z",
            },
            {
                "from": "alice",
                "to": "john",
                "content": "Hi John! I'm doing great, thanks for asking!",
                "date": "2025-08-25T09:05:00.000Z",
            },
        ]
        _write_json(MESSAGES_DB, initial_messages)


# ---------------------------------------------------------------------------
# User operations
# ---------------------------------------------------------------------------

async def get_users():
    if firebase_initialized:
        snap = firebase_db.reference("users").get() or {}
        return list(snap.values())
    return _read_json(USERS_DB)


async def get_user_by_username(username):
    if firebase_initialized:
        snap = firebase_db.reference(f"users/{username}").get()
        return snap
    users = _read_json(USERS_DB)
    return next((u for u in users if u.get("username") == username), None)


async def get_user_by_email(email):
    if firebase_initialized:
        snap = firebase_db.reference("users").order_by_child("email").equal_to(email).get() or {}
        vals = list(snap.values())
        return vals[0] if vals else None
    users = _read_json(USERS_DB)
    return next((u for u in users if u.get("email") == email), None)


async def add_user(user):
    if firebase_initialized:
        firebase_db.reference(f"users/{user['username']}").set(user)
        return user
    users = _read_json(USERS_DB)
    max_id = max((u.get("id", 0) for u in users), default=0)
    user["id"] = max_id + 1
    users.append(user)
    _write_json(USERS_DB, users)
    return user


async def update_user(username, updated_fields):
    if firebase_initialized:
        firebase_db.reference(f"users/{username}").update(updated_fields)
        snap = firebase_db.reference(f"users/{username}").get()
        return snap
    users = _read_json(USERS_DB)
    for i, u in enumerate(users):
        if u.get("username") == username:
            users[i] = {**u, **updated_fields}
            _write_json(USERS_DB, users)
            return users[i]
    return None


async def delete_user(username):
    if firebase_initialized:
        firebase_db.reference(f"users/{username}").delete()
        return {"success": True, "message": "User deleted"}
    users = _read_json(USERS_DB)
    filtered = [u for u in users if u.get("username") != username]
    if len(filtered) == len(users):
        return {"success": False, "message": "User not found"}
    _write_json(USERS_DB, filtered)
    return {"success": True, "message": "User deleted"}


# ---------------------------------------------------------------------------
# Post operations
# ---------------------------------------------------------------------------

async def get_posts():
    if firebase_initialized:
        snap = firebase_db.reference("posts").get() or {}
        return list(snap.values())
    return _read_json(POSTS_DB)


async def add_post(post):
    if firebase_initialized:
        snap = firebase_db.reference("posts").get() or {}
        max_id = max((p.get("id", 0) for p in snap.values()), default=0) if snap else 0
        post["id"] = max_id + 1
        firebase_db.reference(f"posts/{post['id']}").set(post)
        return post
    posts = _read_json(POSTS_DB)
    max_id = max((p.get("id", 0) for p in posts), default=0)
    post["id"] = max_id + 1
    posts.insert(0, post)
    _write_json(POSTS_DB, posts)
    return post


async def update_post(post_id, updated_post):
    if firebase_initialized:
        firebase_db.reference(f"posts/{post_id}").update(updated_post)
        snap = firebase_db.reference(f"posts/{post_id}").get()
        return snap
    posts = _read_json(POSTS_DB)
    for i, p in enumerate(posts):
        if p.get("id") == post_id:
            posts[i] = {**p, **updated_post}
            _write_json(POSTS_DB, posts)
            return posts[i]
    return None


async def delete_post(post_id):
    if firebase_initialized:
        firebase_db.reference(f"posts/{post_id}").delete()
        return {"success": True, "message": "Post deleted successfully"}
    posts = _read_json(POSTS_DB)
    # post_id may be int or str
    idx = None
    for i, p in enumerate(posts):
        pid = p.get("id")
        if str(pid) == str(post_id):
            idx = i
            break
    if idx is None:
        return {"success": False, "message": "Post not found"}
    deleted = posts.pop(idx)
    _write_json(POSTS_DB, posts)
    return {"success": True, "message": "Post deleted successfully", "deletedPost": deleted}


async def delete_all_posts():
    if firebase_initialized:
        firebase_db.reference("posts").delete()
        return True
    _write_json(POSTS_DB, [])
    return True


async def make_all_posts_anonymous():
    posts = await get_posts()
    for p in posts:
        if p.get("username") and p["username"] != "Anonymous":
            p["originalUser"] = p["username"]
            p["username"] = "Anonymous"
            p["isAnonymous"] = True
    if firebase_initialized:
        mapping = {str(p["id"]): p for p in posts}
        firebase_db.reference("posts").set(mapping)
    else:
        _write_json(POSTS_DB, posts)
    return True


# ---------------------------------------------------------------------------
# Chat operations (file-based only, same as Node.js)
# ---------------------------------------------------------------------------

def get_chats():
    return _read_json(CHATS_DB)


# ---------------------------------------------------------------------------
# Initialise on import
# ---------------------------------------------------------------------------
initialize_database()
