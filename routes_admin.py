"""Admin routes — mirrors all /admin/* endpoints from the Node.js server"""
import os
from datetime import datetime, timezone
import bcrypt
from flask import request, jsonify
from app import app, socketio
import database
from routes_auth import is_admin, safe_user

# Admin: Get all posts (including hidden)
@app.route('/admin/posts', methods=['GET'])
@is_admin
async def admin_get_posts():
    posts = await database.get_posts()
    return jsonify(posts=posts, totalPosts=len(posts),
                   adminUser=request.admin_user['username'], adminAction=True)

# Admin: Get detailed posts
@app.route('/admin/posts/detailed', methods=['GET'])
@is_admin
async def admin_get_detailed_posts():
    posts = await database.get_posts()
    detailed = []
    for p in posts:
        rxn = p.get('reactions') or {}
        likes = p.get('likes')
        like_count = len(likes) if isinstance(likes, list) else (sum(rxn.values()) if isinstance(rxn, dict) else 0)
        detailed.append({**p,
            'likeCount': like_count,
            'commentCount': len(p.get('comments') or []),
            'shareCount': p.get('shares', 0),
            'viewCount': p.get('views', 0),
            'isVisible': p.get('isVisible', True) and p.get('visible', True),
            'hasMedia': bool(p.get('media') or p.get('mediaUrl') or p.get('videoUrl') or p.get('imageUrl')),
            'mediaType': 'video' if p.get('videoUrl') else ('image' if (p.get('imageUrl') or p.get('mediaUrl')) else None),
        })
    return jsonify(posts=detailed, totalPosts=len(detailed),
                   adminUser=request.admin_user['username'], adminAction=True)

# Admin: Get individual post
@app.route('/admin/posts/<post_id>', methods=['GET'])
@is_admin
async def admin_get_post(post_id):
    posts = await database.get_posts()
    post = next((p for p in posts if str(p.get('id')) == str(post_id)), None)
    if not post: return jsonify(message='Post not found'), 404
    rxn = post.get('reactions') or {}
    like_count = sum(rxn.values()) if isinstance(rxn, dict) else 0
    result = {**post,
        'commentCount': len(post.get('comments') or []),
        'likeCount': like_count,
        'viewCount': post.get('views', 0),
        'adminInfo': {
            'adminUser': request.admin_user['username'],
            'accessTime': datetime.now(timezone.utc).isoformat(),
            'adminAction': True
        }
    }
    return jsonify(result)

# Admin: Delete post
@app.route('/admin/posts/<post_id>', methods=['DELETE'])
@is_admin
async def admin_delete_post(post_id):
    print(f"Admin {request.admin_user['username']} attempting to delete post {post_id}")
    result = await database.delete_post(post_id)
    if not result.get('success'):
        return jsonify(message=result.get('message', 'Post not found')), 404
    socketio.emit('post-deleted', {'postId': post_id, 'adminUser': request.admin_user['username']})
    print(f"Post {post_id} deleted successfully by admin {request.admin_user['username']}")
    return jsonify(message='Post deleted successfully',
                   deletedPost=result.get('deletedPost'), adminAction=True)

# Admin: Delete all posts
@app.route('/admin/posts', methods=['DELETE'])
@is_admin
async def admin_delete_all_posts():
    await database.delete_all_posts()
    return jsonify(message='All posts deleted successfully',
                   adminUser=request.admin_user['username'], action='delete_all_posts')

# Admin: Edit post
@app.route('/admin/posts/<post_id>', methods=['PUT'])
@is_admin
async def admin_edit_post(post_id):
    data = request.get_json(force=True, silent=True) or {}
    posts = await database.get_posts()
    post = next((p for p in posts if str(p.get('id')) == str(post_id)), None)
    if not post: return jsonify(message='Post not found'), 404
    if 'content' in data: post['content'] = data['content']
    if 'isAnonymous' in data:
        post['isAnonymous'] = data['isAnonymous']
        if data['isAnonymous']:
            post['originalUser'] = post.get('username')
            post['username'] = 'Anonymous'
        elif post.get('originalUser'):
            post['username'] = post['originalUser']
            post.pop('originalUser', None)
    if 'visible' in data: post['isVisible'] = data['visible']
    post['editedByAdmin'] = {'adminUser': request.admin_user['username'],
                              'editDate': datetime.now(timezone.utc).isoformat()}
    await database.update_post(post['id'], post)
    socketio.emit('post-updated', {'postId': post_id, 'post': post,
                                    'adminUser': request.admin_user['username']})
    return jsonify(message='Post updated successfully', post=post, adminAction=True)

# Admin: Update post content
@app.route('/admin/posts/<post_id>/content', methods=['PUT'])
@is_admin
async def admin_update_content(post_id):
    data = request.get_json(force=True, silent=True) or {}
    content = data.get('content')
    if not content: return jsonify(message='Content is required'), 400
    posts = await database.get_posts()
    post = next((p for p in posts if str(p.get('id')) == str(post_id)), None)
    if not post: return jsonify(message='Post not found'), 404
    original = post.get('content')
    post['content'] = content
    post['editedByAdmin'] = {'adminUser': request.admin_user['username'],
                              'editDate': datetime.now(timezone.utc).isoformat(),
                              'originalContent': original}
    await database.update_post(post['id'], post)
    return jsonify(message='Post content updated successfully', post=post,
                   adminUser=request.admin_user['username'], action='update_content')

# Admin: Toggle anonymity
@app.route('/admin/posts/<post_id>/anonymity', methods=['PATCH'])
@is_admin
async def admin_toggle_anonymity(post_id):
    data = request.get_json(force=True, silent=True) or {}
    make_anon = data.get('makeAnonymous', False)
    posts = await database.get_posts()
    post = next((p for p in posts if str(p.get('id')) == str(post_id)), None)
    if not post: return jsonify(message='Post not found'), 404
    if make_anon:
        post['originalUser'] = post.get('username')
        post['username'] = 'Anonymous'; post['isAnonymous'] = True
    else:
        if post.get('originalUser'):
            post['username'] = post['originalUser']
            post.pop('originalUser', None)
        post['isAnonymous'] = False
    actions = post.setdefault('adminActions', [])
    actions.append({'action': 'made_anonymous' if make_anon else 'revealed_identity',
                    'adminUser': request.admin_user['username'],
                    'timestamp': datetime.now(timezone.utc).isoformat()})
    socketio.emit('post-anonymity-changed', {'postId': post_id, 'post': post,
                                              'adminUser': request.admin_user['username']})
    return jsonify(message=f"Post {'made anonymous' if make_anon else 'identity revealed'}",
                   post=post, adminAction=True)

# Admin: Toggle visibility
@app.route('/admin/posts/<post_id>/visibility', methods=['PATCH'])
@is_admin
async def admin_toggle_visibility(post_id):
    data = request.get_json(force=True, silent=True) or {}
    visible = data.get('visible', True)
    posts = await database.get_posts()
    post = next((p for p in posts if str(p.get('id')) == str(post_id)), None)
    if not post: return jsonify(message='Post not found'), 404
    post['visible'] = visible
    post['hiddenByAdmin'] = None if visible else {
        'adminUser': request.admin_user['username'],
        'hiddenDate': datetime.now(timezone.utc).isoformat()
    }
    socketio.emit('post-visibility-changed', {'postId': post_id, 'visible': visible,
                                               'adminUser': request.admin_user['username']})
    return jsonify(message=f"Post {'made visible' if visible else 'hidden'}",
                   post=post, adminAction=True)

# Admin: Make all posts anonymous
@app.route('/admin/posts/make-anonymous', methods=['POST'])
@is_admin
async def admin_make_all_anonymous():
    await database.make_all_posts_anonymous()
    return jsonify(message='All posts made anonymous successfully',
                   adminUser=request.admin_user['username'], action='make_anonymous')

# Admin: Get all users
@app.route('/admin/users', methods=['GET'])
@is_admin
async def admin_get_users():
    users = await database.get_users()
    return jsonify([safe_user(u) for u in users])

# Admin: Get user details
@app.route('/admin/users/<username>', methods=['GET'])
@is_admin
async def admin_get_user(username):
    user = await database.get_user_by_username(username)
    if not user: return jsonify(message='User not found'), 404
    posts = await database.get_posts()
    user_posts = [p for p in posts if p.get('username') == username]
    total_likes = sum(p.get('likes', 0) if isinstance(p.get('likes'), int) else len(p.get('likes', [])) for p in user_posts)
    total_comments = sum(len(p.get('comments') or []) for p in user_posts)
    su = safe_user(user)
    su['stats'] = {'totalPosts': len(user_posts), 'totalLikes': total_likes,
                   'totalComments': total_comments,
                   'joinDate': user.get('createdAt', datetime.now(timezone.utc).isoformat())}
    su['recentPosts'] = user_posts[-5:]
    return jsonify(su)

# Admin: Delete user
@app.route('/admin/users/<username>', methods=['DELETE'])
@is_admin
async def admin_delete_user(username):
    if username in ('Administrator', 'john'):
        return jsonify(message='Cannot delete admin users'), 403
    result = await database.delete_user(username)
    if result.get('success'):
        return jsonify(message=f'User {username} deleted successfully',
                       adminUser=request.admin_user['username'], action='delete_user')
    return jsonify(message='User not found'), 404

# Admin: Update user
@app.route('/admin/users/<username>', methods=['PUT'])
@is_admin
async def admin_update_user(username):
    data = request.get_json(force=True, silent=True) or {}
    user = await database.get_user_by_username(username)
    if not user: return jsonify(message='User not found'), 404
    updated = dict(user)
    if 'email' in data: updated['email'] = data['email']
    if 'name' in data: updated['name'] = data['name']
    if 'role' in data: updated['role'] = data['role']
    if 'isAdmin' in data: updated['isAdmin'] = data['isAdmin']
    if data.get('password', '').strip():
        updated['password'] = bcrypt.hashpw(data['password'].encode(), bcrypt.gensalt()).decode()
    updated['updatedAt'] = datetime.now(timezone.utc).isoformat()
    updated['updatedBy'] = request.admin_user['username']
    await database.update_user(username, updated)
    return jsonify(message=f'User {username} updated successfully',
                   user=safe_user(updated), adminUser=request.admin_user['username'])

# Admin: Create user
@app.route('/admin/users', methods=['POST'])
@is_admin
async def admin_create_user():
    data = request.get_json(force=True, silent=True) or {}
    username = data.get('username'); password = data.get('password'); email = data.get('email')
    if not username or not password or not email:
        return jsonify(message='Username, password, and email are required'), 400
    if await database.get_user_by_username(username):
        return jsonify(message='Username already exists'), 400
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    name = data.get('name', username[0].upper()+username[1:])
    new_user = {
        'username': username, 'password': hashed, 'name': name, 'email': email,
        'avatar': username[:2].upper(), 'bio': f"Hello! I'm {name} 👋",
        'verified': True, 'isAdmin': data.get('isAdmin', False),
        'role': data.get('role', 'user'),
        'followers': 0, 'following': 0,
        'joinDate': datetime.now(timezone.utc).isoformat()
    }
    saved = await database.add_user(new_user)
    return jsonify(message='User created successfully', user=safe_user(saved),
                   adminUser=request.admin_user['username'], action='create_user'), 201

# Admin: Update user role
@app.route('/admin/users/<username>/role', methods=['PATCH'])
@is_admin
async def admin_update_role(username):
    data = request.get_json(force=True, silent=True) or {}
    role = data.get('role')
    if not role: return jsonify(message='Role is required'), 400
    user = await database.get_user_by_username(username)
    if not user: return jsonify(message='User not found'), 404
    updated = {**user, 'role': role, 'isAdmin': data.get('isAdmin', False)}
    await database.update_user(username, updated)
    return jsonify(message=f'User {username} role updated to {role}',
                   user=safe_user(updated), adminUser=request.admin_user['username'], action='update_role')

# Admin: Get chats
@app.route('/admin/chats', methods=['GET'])
@is_admin
async def admin_get_chats():
    chats = database.get_chats()
    return jsonify(chats=chats, totalChats=len(chats),
                   adminUser=request.admin_user['username'], adminAction=True)

# Admin: Get chat detail
@app.route('/admin/chats/<int:chat_id>', methods=['GET'])
@is_admin
async def admin_get_chat(chat_id):
    chats = database.get_chats()
    chat = next((c for c in chats if c.get('id') == chat_id), None)
    if not chat: return jsonify(message='Chat not found'), 404
    return jsonify(chat=chat, adminUser=request.admin_user['username'], adminAction=True,
                   messageCount=len(chat.get('messages', [])),
                   lastActivity=chat.get('timestamp'),
                   participants=chat.get('name'),
                   status='Active' if chat.get('online') else 'Inactive')
