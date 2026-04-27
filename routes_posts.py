"""Posts, comments, stories, search, hashtags, live-stream routes"""
import os, re, uuid
from datetime import datetime, timedelta, timezone
from flask import request, jsonify, send_from_directory
from app import app, socketio, UPLOAD_DIR
import database

# In-memory stores (same as Node.js)
comments = []
messages_store = []
stories = []
live_streams = []
hashtags = {}  # tag -> {count, posts}
mentions = {}  # user -> [postIds]

def extract_hashtags(text):
    return re.findall(r'#[a-zA-Z0-9_]+', text or '')

def extract_mentions(text):
    return re.findall(r'@[a-zA-Z0-9_]+', text or '')

def _save_upload(file_obj, subfolder=''):
    fname = f"{uuid.uuid4()}{os.path.splitext(file_obj.filename)[1]}"
    dest = os.path.join(UPLOAD_DIR, subfolder, fname) if subfolder else os.path.join(UPLOAD_DIR, fname)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    file_obj.save(dest)
    return f'/uploads/{subfolder}/{fname}' if subfolder else f'/uploads/{fname}'

# ---- Posts ----
@app.route('/posts', methods=['POST'])
async def create_post():
    username = request.form.get('username') or (request.get_json(silent=True) or {}).get('username')
    content = request.form.get('content') or (request.get_json(silent=True) or {}).get('content')
    is_anon = request.form.get('isAnonymous','false')
    location = request.form.get('location')
    allow_comments = request.form.get('allowComments','true')

    if not username or not username.strip():
        return jsonify(message='🔐 Authentication required. Please login to post.', requireLogin=True), 401
    if not content or not content.strip():
        return jsonify(message='Post content cannot be empty'), 400
    if len(content) > 500:
        return jsonify(message='Post content cannot exceed 500 characters'), 400

    media_url = None; media_type = None
    if 'media' in request.files:
        f = request.files['media']
        media_url = _save_upload(f)
        media_type = 'video' if f.content_type and f.content_type.startswith('video/') else 'image'

    htags = extract_hashtags(content.strip())
    ments = extract_mentions(content.strip())

    new_post = {
        'id': str(uuid.uuid4()),
        'username': 'Anonymous' if is_anon == 'true' else (username or 'Guest'),
        'content': content.strip(),
        'media': media_url, 'mediaType': media_type,
        'location': location,
        'date': datetime.now(timezone.utc).isoformat(),
        'likes': [], 'shares': 0, 'comments': [],
        'reactions': {'like':0,'heart':0,'laugh':0,'angry':0,'sad':0},
        'hashtags': htags, 'mentions': ments,
        'isAnonymous': is_anon == 'true',
        'originalUser': username if is_anon == 'true' else None,
        'allowComments': allow_comments in ('true', True),
        'views': 0
    }

    for tag in htags:
        tl = tag.lower()
        if tl in hashtags:
            hashtags[tl]['count'] += 1; hashtags[tl]['posts'].append(new_post['id'])
        else:
            hashtags[tl] = {'count':1, 'posts':[new_post['id']]}
    for m in ments:
        mu = m[1:]
        mentions.setdefault(mu, []).append(new_post['id'])

    saved = await database.add_post(new_post)
    if saved:
        socketio.emit('new-post', saved)
        print(f'📝 New post by {"Anonymous" if is_anon=="true" else username}: "{content[:50]}..."')
        return jsonify(message='Post created successfully', post=saved)
    return jsonify(message='Failed to create post'), 500

@app.route('/posts', methods=['GET'])
async def get_posts():
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    hashtag = request.args.get('hashtag')
    user = request.args.get('user')
    search = request.args.get('search')

    posts = await database.get_posts()
    if hashtag:
        posts = [p for p in posts if p.get('hashtags') and f'#{hashtag}' in p['hashtags']]
    if user:
        posts = [p for p in posts if p.get('username') == user]
    if search:
        sl = search.lower()
        posts = [p for p in posts if sl in (p.get('content','').lower())]

    start = (page - 1) * limit
    end = start + limit
    return jsonify(posts=list(reversed(posts[start:end])), totalPosts=len(posts),
                   currentPage=page, totalPages=-(-len(posts)//limit) if posts else 0)

@app.route('/posts/<post_id>', methods=['GET'])
async def get_post_detail(post_id):
    posts = await database.get_posts()
    post = None
    for p in posts:
        if str(p.get('id')) == str(post_id):
            post = p; break
    if not post: return jsonify(message='Post not found'), 404
    rxn = post.get('reactions') or {}
    like_count = sum(rxn.values()) if isinstance(rxn, dict) else 0
    result = {**post,
        'commentCount': len(post.get('comments') or []),
        'likeCount': like_count,
        'viewCount': post.get('views', 0),
        'hasMedia': bool(post.get('mediaUrl') or post.get('videoUrl') or post.get('imageUrl')),
        'engagementRate': f"{(like_count/post['views']*100):.1f}" if post.get('views') else '0.0'
    }
    return jsonify(result)

# ---- Reactions ----
@app.route('/posts/<post_id>/react', methods=['POST'])
async def react_post(post_id):
    data = request.get_json(force=True, silent=True) or {}
    username = data.get('username'); reaction = data.get('reaction')
    if not username or not reaction: return jsonify(message='Username and reaction are required'), 400
    posts = await database.get_posts()
    post = next((p for p in posts if str(p.get('id'))==str(post_id)), None)
    if not post: return jsonify(message='Post not found'), 404
    ur = post.setdefault('userReactions', {})
    if username in ur:
        prev = ur[username]
        post['reactions'][prev] = max(0, post['reactions'].get(prev, 0) - 1)
    ur[username] = reaction
    post['reactions'][reaction] = post['reactions'].get(reaction, 0) + 1
    socketio.emit('post-reaction', {'postId': post_id, 'reactions': post['reactions']})
    return jsonify(message='Reaction added', reactions=post['reactions'])

# ---- Share ----
@app.route('/posts/<post_id>/share', methods=['POST'])
async def share_post(post_id):
    data = request.get_json(force=True, silent=True) or {}
    username = data.get('username'); comment = data.get('comment','')
    if not username: return jsonify(message='Username is required'), 400
    posts = await database.get_posts()
    orig = next((p for p in posts if str(p.get('id'))==str(post_id)), None)
    if not orig: return jsonify(message='Post not found'), 404
    shared = {
        'id': str(uuid.uuid4()), 'username': username, 'content': comment,
        'sharedPost': {'id':orig['id'],'username':orig['username'],'content':orig['content'],
                       'media':orig.get('media'),'mediaType':orig.get('mediaType'),'date':orig['date']},
        'date': datetime.now(timezone.utc).isoformat(),
        'likes':[],'shares':0,'comments':[],'reactions':{'like':0,'heart':0,'laugh':0,'angry':0,'sad':0},
        'hashtags':extract_hashtags(comment),'mentions':extract_mentions(comment),
        'isShared':True,'allowComments':True,'views':0
    }
    orig['shares'] = (orig.get('shares') or 0) + 1
    saved = await database.add_post(shared)
    if saved:
        socketio.emit('new-post', saved)
        socketio.emit('post-shared', {'postId':post_id,'shares':orig['shares']})
        return jsonify(message='Post shared successfully', post=saved)
    return jsonify(message='Failed to share post'), 500

# ---- Comments ----
@app.route('/posts/<post_id>/comments', methods=['POST'])
async def add_comment(post_id):
    data = request.get_json(force=True, silent=True) or {}
    username = data.get('username'); content = data.get('content')
    if not username or not content: return jsonify(message='Username and content are required'), 400
    posts = await database.get_posts()
    post = next((p for p in posts if str(p.get('id'))==str(post_id)), None)
    if not post: return jsonify(message='Post not found'), 404
    if not post.get('allowComments', True):
        return jsonify(message='Comments are disabled for this post'), 403
    parent_id = data.get('parentCommentId')
    new_comment = {
        'id': str(uuid.uuid4()), 'postId': post_id, 'username': username,
        'content': content.strip(), 'parentCommentId': parent_id,
        'date': datetime.now(timezone.utc).isoformat(),
        'likes': [], 'replies': [],
        'hashtags': extract_hashtags(content), 'mentions': extract_mentions(content)
    }
    comments.append(new_comment)
    if parent_id:
        pc = next((c for c in comments if c['id']==parent_id), None)
        if pc: pc['replies'].append(new_comment['id'])
    socketio.emit('new-comment', {'postId': post_id, 'comment': new_comment})
    return jsonify(message='Comment added', comment=new_comment)

@app.route('/posts/<post_id>/comments', methods=['GET'])
def get_comments(post_id):
    page = int(request.args.get('page', 1)); limit = int(request.args.get('limit', 10))
    top = sorted([c for c in comments if c.get('postId')==post_id and not c.get('parentCommentId')],
                 key=lambda x: x['date'], reverse=True)
    with_replies = []
    for c in top:
        replies = sorted([r for r in comments if r.get('parentCommentId')==c['id']],
                         key=lambda x: x['date'])
        with_replies.append({**c, 'replies': replies})
    start = (page-1)*limit; end = start+limit
    return jsonify(comments=with_replies[start:end], totalComments=len(top),
                   currentPage=page, totalPages=-(-len(top)//limit) if top else 0)

# ---- Stories ----
@app.route('/stories', methods=['POST'])
async def create_story():
    username = request.form.get('username')
    if not username: return jsonify(message='Authentication required'), 401
    if 'story' not in request.files: return jsonify(message='Story media is required'), 400
    f = request.files['story']
    media_url = _save_upload(f, 'stories')
    mt = 'video' if f.content_type and f.content_type.startswith('video/') else 'image'
    dur = int(request.form.get('duration', 24))
    story = {
        'id': str(uuid.uuid4()), 'username': username,
        'content': request.form.get('content',''), 'media': media_url, 'mediaType': mt,
        'date': datetime.now(timezone.utc).isoformat(),
        'expiresAt': (datetime.now(timezone.utc)+timedelta(hours=dur)).isoformat(),
        'viewers': [], 'isActive': True
    }
    stories.append(story)
    socketio.emit('new-story', story)
    return jsonify(message='Story created successfully', story=story)

@app.route('/stories', methods=['GET'])
def get_stories():
    username = request.args.get('username')
    now = datetime.now(timezone.utc)
    global stories
    stories = [s for s in stories if datetime.fromisoformat(s['expiresAt'].replace('Z','+00:00')) > now]
    active = [s for s in stories if s.get('isActive')]
    if username: active = [s for s in active if s['username']==username]
    by_user = {}
    for s in active: by_user.setdefault(s['username'], []).append(s)
    return jsonify(by_user)

@app.route('/stories/<story_id>/view', methods=['POST'])
def view_story(story_id):
    data = request.get_json(force=True, silent=True) or {}
    username = data.get('username')
    if not username: return jsonify(message='Username is required'), 400
    story = next((s for s in stories if s['id']==story_id), None)
    if not story: return jsonify(message='Story not found'), 404
    if username not in story['viewers']: story['viewers'].append(username)
    return jsonify(message='Story viewed', viewers=len(story['viewers']))

# ---- Search ----
@app.route('/search', methods=['GET'])
async def search():
    q = request.args.get('q',''); stype = request.args.get('type','all')
    page = int(request.args.get('page',1)); limit = int(request.args.get('limit',20))
    if len(q) < 2: return jsonify(message='Search query must be at least 2 characters'), 400
    results = {'posts':[],'users':[],'hashtags':[]}
    ql = q.lower()
    if stype in ('all','posts'):
        posts = await database.get_posts()
        results['posts'] = [p for p in posts if ql in p.get('content','').lower()]
    if stype in ('all','users'):
        from routes_auth import safe_user
        users = await database.get_users()
        results['users'] = [safe_user(u) for u in users
            if ql in u.get('username','').lower() or ql in u.get('name','').lower()
            or ql in (u.get('bio') or '').lower()]
    if stype in ('all','hashtags'):
        results['hashtags'] = [{'tag':t,'count':d['count'],'posts':d['posts']}
            for t,d in hashtags.items() if ql in t.lower()]
    if stype != 'all':
        start = (page-1)*limit; results[stype] = results[stype][start:start+limit]
    return jsonify(query=q, results=results, page=page, limit=limit)

# ---- Hashtags ----
@app.route('/hashtags/trending', methods=['GET'])
def trending_hashtags():
    trending = sorted(hashtags.items(), key=lambda x: x[1]['count'], reverse=True)[:20]
    return jsonify([{'hashtag':t,'count':d['count'],'posts':len(d['posts'])} for t,d in trending])

@app.route('/hashtags/<hashtag>/posts', methods=['GET'])
async def hashtag_posts(hashtag):
    page = int(request.args.get('page',1)); limit = int(request.args.get('limit',20))
    posts = await database.get_posts()
    filtered = [p for p in posts if p.get('hashtags') and f'#{hashtag}' in p['hashtags']]
    start = (page-1)*limit; end = start+limit
    return jsonify(hashtag=f'#{hashtag}', posts=list(reversed(filtered[start:end])),
                   totalPosts=len(filtered), currentPage=page,
                   totalPages=-(-len(filtered)//limit) if filtered else 0)

# ---- Live Streaming ----
@app.route('/live/start', methods=['POST'])
def start_live():
    data = request.get_json(force=True, silent=True) or {}
    username = data.get('username')
    if not username: return jsonify(message='Authentication required'), 401
    import secrets
    stream = {
        'id': str(uuid.uuid4()), 'username': username,
        'title': data.get('title', f"{username}'s Live Stream"),
        'description': data.get('description',''),
        'startTime': datetime.now(timezone.utc).isoformat(),
        'viewers': [], 'isActive': True, 'streamKey': secrets.token_hex(16)
    }
    live_streams.append(stream)
    socketio.emit('live-stream-started', {'streamId':stream['id'],'username':username,'title':stream['title']})
    return jsonify(message='Live stream started', streamId=stream['id'], streamKey=stream['streamKey'])

@app.route('/live', methods=['GET'])
def get_live():
    return jsonify([s for s in live_streams if s.get('isActive')])

@app.route('/live/<stream_id>/join', methods=['POST'])
def join_live(stream_id):
    data = request.get_json(force=True, silent=True) or {}
    username = data.get('username','')
    stream = next((s for s in live_streams if s['id']==stream_id), None)
    if not stream: return jsonify(message='Live stream not found'), 404
    if username and username not in stream['viewers']: stream['viewers'].append(username)
    return jsonify(message='Joined live stream', stream={'id':stream['id'],'title':stream['title'],
        'username':stream['username'],'viewers':len(stream['viewers'])})

@app.route('/live/<stream_id>/end', methods=['POST'])
def end_live(stream_id):
    data = request.get_json(force=True, silent=True) or {}
    username = data.get('username','')
    stream = next((s for s in live_streams if s['id']==stream_id), None)
    if not stream: return jsonify(message='Live stream not found'), 404
    if stream['username'] != username:
        return jsonify(message='Only the stream owner can end the stream'), 403
    stream['isActive'] = False; stream['endTime'] = datetime.now(timezone.utc).isoformat()
    socketio.emit('live-stream-ended', {'streamId': stream_id})
    return jsonify(message='Live stream ended')

# ---- Messages ----
@app.route('/messages', methods=['POST'])
def send_message():
    frm = request.form.get('from') or (request.get_json(silent=True) or {}).get('from')
    to = request.form.get('to') or (request.get_json(silent=True) or {}).get('to')
    content = request.form.get('content') or (request.get_json(silent=True) or {}).get('content','')
    msg_type = request.form.get('messageType','text')
    if not frm or not to: return jsonify(message='Sender and recipient are required'), 400
    if not content and 'media' not in request.files:
        return jsonify(message='Message content or media is required'), 400
    media_url = None; media_type_val = None
    if 'media' in request.files:
        f = request.files['media']
        media_url = _save_upload(f)
        media_type_val = 'video' if f.content_type and f.content_type.startswith('video/') else 'image'
    msg = {
        'id': str(uuid.uuid4()), 'from': frm, 'to': to, 'content': content,
        'media': media_url, 'mediaType': media_type_val, 'messageType': msg_type,
        'date': datetime.now(timezone.utc).isoformat(),
        'isRead': False, 'isDelivered': False, 'reactions': [],
        'replyTo': request.form.get('replyTo') or (request.get_json(silent=True) or {}).get('replyTo')
    }
    messages_store.append(msg)
    socketio.emit('new-message', msg, room=to)
    socketio.emit('message-sent', msg, room=frm)
    return jsonify(message='Message sent', data=msg)

@app.route('/messages/<user1>/<user2>', methods=['GET'])
def get_messages(user1, user2):
    page = int(request.args.get('page',1)); limit = int(request.args.get('limit',50))
    conv = sorted([m for m in messages_store
        if (m['from']==user1 and m['to']==user2) or (m['from']==user2 and m['to']==user1)],
        key=lambda x: x['date'], reverse=True)
    start = (page-1)*limit; end = start+limit
    return jsonify(messages=list(reversed(conv[start:end])), totalMessages=len(conv),
                   currentPage=page, totalPages=-(-len(conv)//limit) if conv else 0)

@app.route('/conversations/<username>', methods=['GET'])
def get_conversations(username):
    user_msgs = [m for m in messages_store if m['from']==username or m['to']==username]
    convs = {}
    for m in user_msgs:
        partner = m['to'] if m['from']==username else m['from']
        if partner not in convs:
            convs[partner] = {'partner':partner,'lastMessage':m,'unreadCount':0,'messages':[]}
        if m['date'] > convs[partner]['lastMessage']['date']:
            convs[partner]['lastMessage'] = m
        if not m.get('isRead') and m['to']==username:
            convs[partner]['unreadCount'] += 1
    return jsonify(list(convs.values()))

@app.route('/messages/read', methods=['PUT'])
def mark_read():
    data = request.get_json(force=True, silent=True) or {}
    ids = data.get('messageIds',[]); username = data.get('username')
    if not isinstance(ids, list): return jsonify(message='Message IDs array is required'), 400
    for mid in ids:
        m = next((x for x in messages_store if x['id']==mid and x['to']==username), None)
        if m: m['isRead'] = True
    return jsonify(message='Messages marked as read')

@app.route('/messages/<message_id>/react', methods=['POST'])
def react_message(message_id):
    data = request.get_json(force=True, silent=True) or {}
    username = data.get('username'); reaction = data.get('reaction')
    msg = next((m for m in messages_store if m['id']==message_id), None)
    if not msg: return jsonify(message='Message not found'), 404
    if not isinstance(msg.get('reactions'), list): msg['reactions'] = []
    msg['reactions'] = [r for r in msg['reactions'] if r.get('username')!=username]
    if reaction:
        msg['reactions'].append({'username':username,'reaction':reaction,'date':datetime.now(timezone.utc).isoformat()})
    socketio.emit('message-reaction', {'messageId':message_id,'reactions':msg['reactions']}, room=msg['from'])
    socketio.emit('message-reaction', {'messageId':message_id,'reactions':msg['reactions']}, room=msg['to'])
    return jsonify(message='Reaction updated', reactions=msg['reactions'])

# ---- Chats ----
@app.route('/chats', methods=['GET'])
def get_chats():
    return jsonify(database.get_chats())

# ---- Static uploads ----
@app.route('/uploads/<path:filename>', methods=['GET'])
def serve_upload(filename):
    return send_from_directory(UPLOAD_DIR, filename)
