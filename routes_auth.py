"""Auth & User routes"""
import os, re, uuid, hashlib, secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
import bcrypt, jwt
from flask import request, jsonify
from app import app, socketio
import database

JWT_SECRET = os.environ.get('JWT_SECRET', 'your-secret-key')

# ---------- helpers ----------
def make_token(payload, hours=24):
    payload['exp'] = datetime.now(timezone.utc) + timedelta(hours=hours)
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')

def safe_user(u):
    if not u: return u
    u = dict(u)
    for k in ('password','verificationToken','passwordResetToken'): u.pop(k, None)
    return u

def is_admin(f):
    @wraps(f)
    async def wrapper(*a, **kw):
        auth = request.headers.get('Authorization','')
        if not auth.startswith('Bearer '):
            return jsonify(message='Authorization token required'), 401
        try:
            decoded = jwt.decode(auth.split(' ')[1], JWT_SECRET, algorithms=['HS256'])
        except Exception:
            return jsonify(message='Invalid or expired token'), 401
        user = await database.get_user_by_username(decoded.get('username',''))
        if not user:
            return jsonify(message='User not found'), 401
        if user.get('username') not in ('Administrator','john'):
            return jsonify(message='Administrator access required - Invalid user'), 403
        if not user.get('isAdmin'):
            return jsonify(message='Administrator access denied - Not an admin'), 403
        request.admin_user = user
        return await f(*a, **kw)
    wrapper.__name__ = f.__name__
    return wrapper

# ---------- init admin ----------
async def init_admin():
    for uname, pwd, name, email in [
        ('Administrator','bi+jJZ9t','System Administrator','admin@neex.app'),
        ('john','john123','John Admin','john@neex.app')
    ]:
        u = await database.get_user_by_username(uname)
        hashed = bcrypt.hashpw(pwd.encode(), bcrypt.gensalt()).decode()
        if not u:
            await database.add_user({
                'username':uname,'password':hashed,'name':name,'email':email,
                'avatar':uname[:2].upper(),'bio':f'{name} - Full Access Control 🔧⚡',
                'verified':True,'isAdmin':True,'role':'admin',
                'permissions':{'deleteAnyPost':True,'editAnyPost':True,'makePostAnonymous':True,
                    'togglePostVisibility':True,'manageUsers':True,'viewAllData':True,'moderateContent':True},
                'followers':0,'following':0,'joinDate':datetime.now(timezone.utc).isoformat()
            })
            print(f'✅ {uname} account created')
        else:
            try:
                if not bcrypt.checkpw(pwd.encode(), u['password'].encode()):
                    await database.update_user(uname, {'password':hashed})
                    print(f'✅ {uname} password updated')
                else:
                    print(f'✅ {uname} account ready')
            except Exception:
                await database.update_user(uname, {'password':hashed})
                print(f'✅ {uname} password updated')

# ---------- registration disabled ----------
@app.route('/register', methods=['POST'])
def register():
    return jsonify(message='Registration is disabled. Only existing users can sign in.',
                   registrationDisabled=True), 403

# ---------- email verification ----------
@app.route('/verify-email', methods=['GET'])
async def verify_email():
    token = request.args.get('token')
    if not token: return jsonify(message='Verification token is required'), 400
    users = await database.get_users()
    user = next((u for u in users if u.get('verificationToken')==token), None)
    if not user: return jsonify(message='Invalid or expired verification token'), 400
    await database.update_user(user['username'], {'emailVerified':True,'verificationToken':None})
    return jsonify(message='Email verified successfully!')

# ---------- forgot / reset password ----------
@app.route('/forgot-password', methods=['POST'])
async def forgot_password():
    data = request.get_json(force=True, silent=True) or {}
    email = data.get('email')
    if not email: return jsonify(message='Email is required'), 400
    user = await database.get_user_by_email(email)
    if not user: return jsonify(message='No account found with this email address'), 404
    reset_token = secrets.token_hex(32)
    await database.update_user(user['username'], {
        'passwordResetToken': reset_token,
        'passwordResetExpiry': (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
    })
    return jsonify(message='Password reset email sent successfully', emailSent=False)

@app.route('/reset-password', methods=['POST'])
async def reset_password():
    data = request.get_json(force=True, silent=True) or {}
    token, new_pw = data.get('token'), data.get('newPassword')
    if not token or not new_pw: return jsonify(message='Token and new password are required'), 400
    if len(new_pw) < 6: return jsonify(message='Password must be at least 6 characters long'), 400
    users = await database.get_users()
    user = next((u for u in users if u.get('passwordResetToken')==token
                 and datetime.fromisoformat(u.get('passwordResetExpiry','2000-01-01')) > datetime.now(timezone.utc)), None)
    if not user: return jsonify(message='Invalid or expired reset token'), 400
    hashed = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()).decode()
    await database.update_user(user['username'], {'password':hashed,'passwordResetToken':None,'passwordResetExpiry':None})
    return jsonify(message='Password reset successfully!')

# ---------- login ----------
@app.route('/login', methods=['POST'])
async def login():
    data = request.get_json(force=True, silent=True) or {}
    username, password = data.get('username'), data.get('password')
    if not username or not password: return jsonify(message='Username and password are required'), 400
    user = await database.get_user_by_username(username)
    if not user: return jsonify(message='Invalid username or password'), 401
    try:
        valid = bcrypt.checkpw(password.encode(), user['password'].encode())
    except Exception:
        valid = (password == user.get('password'))
    if not valid: return jsonify(message='Invalid username or password'), 401
    token = make_token({'username':user['username'],'email':user.get('email','')})
    return jsonify(message='Login successful', user=safe_user(user), token=token)

# ---------- admin login ----------
@app.route('/admin/login', methods=['POST'])
async def admin_login():
    data = request.get_json(force=True, silent=True) or {}
    username, password = data.get('username'), data.get('password')
    if not username or not password: return jsonify(message='Username and password are required'), 400
    user = await database.get_user_by_username(username)
    if not user: return jsonify(message='Invalid admin credentials'), 401
    if not user.get('isAdmin') and user.get('role')!='admin' and username!='Administrator':
        return jsonify(message='Admin access required'), 403
    try:
        valid = bcrypt.checkpw(password.encode(), user['password'].encode())
    except Exception:
        valid = (password == user.get('password'))
    if not valid: return jsonify(message='Invalid admin credentials'), 401
    token = make_token({'username':user['username'],'email':user.get('email',''),
                        'isAdmin':True,'role':'admin','permissions':user.get('permissions',{})}, hours=8)
    su = safe_user(user)
    su['isAdmin'] = True; su['role'] = 'admin'
    print(f"🔧 Admin login successful: {username}")
    return jsonify(message='Admin login successful', user=su, token=token, adminAccess=True)

# ---------- signup ----------
@app.route('/signup', methods=['POST'])
async def signup():
    data = request.get_json(force=True, silent=True) or {}
    username = data.get('username'); password = data.get('password'); email = data.get('email')
    if not username or not password or not email:
        return jsonify(message='Username, password, and email are required'), 400
    if len(password) < 3: return jsonify(message='Password must be at least 3 characters'), 400
    if await database.get_user_by_username(username):
        return jsonify(message='Username already exists'), 400
    if await database.get_user_by_email(email):
        return jsonify(message='Email already registered'), 400
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    new_user = {
        'username':username,'password':hashed,
        'name':data.get('name', username[0].upper()+username[1:]),
        'email':email,'avatar':username[:2].upper(),
        'bio':data.get('bio', f"Hello! I'm {username} 👋"),
        'verified':False,'isAdmin':False,'role':'user',
        'followers':0,'following':0,'joinDate':datetime.now(timezone.utc).isoformat()
    }
    saved = await database.add_user(new_user)
    print(f"✅ New user registered: {username}")
    return jsonify(message='Account created successfully', user=safe_user(saved)), 201

# ---------- user profile ----------
@app.route('/users/<username>', methods=['GET'])
async def get_user(username):
    user = await database.get_user_by_username(username)
    if not user: return jsonify(message='User not found'), 404
    return jsonify(safe_user(user))

@app.route('/users/<username>', methods=['PUT'])
async def update_user_profile(username):
    data = request.get_json(force=True, silent=True) or {}
    user = await database.get_user_by_username(username)
    if not user: return jsonify(message='User not found'), 404
    updates = {}
    if data.get('name'): updates['name'] = data['name']
    if data.get('bio'): updates['bio'] = data['bio']
    if data.get('email'): updates['email'] = data['email']
    updated = {**user, **updates}
    await database.update_user(username, updated)
    return jsonify(message='Profile updated successfully', user=safe_user(updated))

@app.route('/users', methods=['GET'])
async def get_all_users():
    users = await database.get_users()
    return jsonify([safe_user(u) for u in users])

# ---------- follow/unfollow ----------
@app.route('/users/<username>/follow', methods=['POST'])
async def follow_user(username):
    data = request.get_json(force=True, silent=True) or {}
    follower_username = data.get('followerUsername')
    if not follower_username: return jsonify(message='Follower username is required'), 400
    if username == follower_username: return jsonify(message='Cannot follow yourself'), 400
    user_to_follow = await database.get_user_by_username(username)
    follower = await database.get_user_by_username(follower_username)
    if not user_to_follow or not follower: return jsonify(message='User not found'), 404
    ps = user_to_follow.get('privacySettings') or {}
    if ps.get('profileVisibility') == 'private':
        return jsonify(message='This user has a private profile'), 403
    followers_list = user_to_follow.get('followers') or []
    if isinstance(followers_list, list) and follower_username in followers_list:
        return jsonify(message='Already following this user'), 400
    following_list = follower.get('following') or []
    if isinstance(following_list, list):
        following_list = following_list + [username]
    await database.update_user(follower_username, {'following': following_list,
        'followingCount': (follower.get('followingCount',0) or 0)+1})
    if isinstance(followers_list, list):
        followers_list = followers_list + [follower_username]
    await database.update_user(username, {'followers': followers_list,
        'followerCount': (user_to_follow.get('followerCount',0) or 0)+1})
    return jsonify(message=f"Now following {user_to_follow.get('name','')}", following=True)

@app.route('/users/<username>/unfollow', methods=['POST'])
async def unfollow_user(username):
    data = request.get_json(force=True, silent=True) or {}
    follower_username = data.get('followerUsername')
    if not follower_username: return jsonify(message='Follower username is required'), 400
    user_to_unfollow = await database.get_user_by_username(username)
    follower = await database.get_user_by_username(follower_username)
    if not user_to_unfollow or not follower: return jsonify(message='User not found'), 404
    followers_list = user_to_unfollow.get('followers') or []
    if isinstance(followers_list, list) and follower_username not in followers_list:
        return jsonify(message='Not following this user'), 400
    following_list = [u for u in (follower.get('following') or []) if u != username]
    await database.update_user(follower_username, {'following': following_list,
        'followingCount': max(0, (follower.get('followingCount',0) or 0)-1)})
    new_followers = [u for u in followers_list if u != follower_username]
    await database.update_user(username, {'followers': new_followers,
        'followerCount': max(0, (user_to_unfollow.get('followerCount',0) or 0)-1)})
    return jsonify(message=f"Unfollowed {user_to_unfollow.get('name','')}", following=False)

@app.route('/users/<username>/followers', methods=['GET'])
async def get_followers(username):
    user = await database.get_user_by_username(username)
    if not user: return jsonify(message='User not found'), 404
    ps = user.get('privacySettings') or {}
    if ps.get('followersVisible') is False:
        return jsonify(message='Followers list is private'), 403
    followers = user.get('followers') or []
    details = []
    if isinstance(followers, list):
        for fu in followers:
            fu_data = await database.get_user_by_username(fu)
            if fu_data: details.append(safe_user(fu_data))
    return jsonify(count=len(followers), followers=details)

@app.route('/users/<username>/following', methods=['GET'])
async def get_following(username):
    user = await database.get_user_by_username(username)
    if not user: return jsonify(message='User not found'), 404
    following = user.get('following') or []
    details = []
    if isinstance(following, list):
        for fu in following:
            fu_data = await database.get_user_by_username(fu)
            if fu_data: details.append(safe_user(fu_data))
    return jsonify(count=len(following), following=details)

@app.route('/users/<username>/privacy', methods=['PUT'])
async def update_privacy(username):
    data = request.get_json(force=True, silent=True) or {}
    ps = data.get('privacySettings')
    if not ps: return jsonify(message='Privacy settings are required'), 400
    user = await database.get_user_by_username(username)
    if not user: return jsonify(message='User not found'), 404
    merged = {**(user.get('privacySettings') or {}), **ps}
    updated = {**user, 'privacySettings': merged}
    await database.update_user(username, updated)
    return jsonify(message='Privacy settings updated', user=safe_user(updated))

@app.route('/users/<username>/avatar', methods=['PUT'])
async def update_avatar(username):
    user = await database.get_user_by_username(username)
    if not user: return jsonify(message='User not found'), 404
    if 'avatar' not in request.files: return jsonify(message='No avatar file provided'), 400
    f = request.files['avatar']
    fname = f"{uuid.uuid4()}{os.path.splitext(f.filename)[1]}"
    from app import UPLOAD_DIR
    f.save(os.path.join(UPLOAD_DIR, fname))
    avatar_url = f'/uploads/{fname}'
    updated = {**user, 'avatar': avatar_url}
    await database.update_user(username, updated)
    return jsonify(message='Avatar updated successfully', user=safe_user(updated))
