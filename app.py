import os
import shutil
import datetime
import sqlite3
import zipfile
import io
import secrets
import psutil
import platform
from flask import Flask, request, render_template, send_from_directory, send_file, redirect, url_for, session, flash, jsonify
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.secret_key = 'kunci_rahasia_multi_user'

# --- 2. INISIALISASI SOCKETIO ---
socketio = SocketIO(app, cors_allowed_origins="*")

# --- CONFIG ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GLOBAL_ROOT = os.path.join(BASE_DIR, 'myDrive_data')

if not os.path.exists(GLOBAL_ROOT): os.makedirs(GLOBAL_ROOT)
app.config['ROOT_DRIVE'] = GLOBAL_ROOT

# --- DATABASE ---
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS shares (token TEXT PRIMARY KEY, file_path TEXT, created_by TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- HELPERS ---
def notify_file_change():
    """Mengirim sinyal ke klien agar merefresh halaman"""
    socketio.emit('files_updated', {'message': 'Data changed'})

def get_user_root():
    if 'username' not in session: return None
    user_folder = os.path.join(GLOBAL_ROOT, session['username'])
    if not os.path.exists(user_folder): os.makedirs(user_folder)
    return user_folder

def get_safe_path(req_path):
    root = get_user_root()
    if not root: return None
    target = os.path.join(root, req_path)
    if not os.path.realpath(target).startswith(os.path.realpath(root)): return root
    return target

def get_file_info(path):
    try:
        stats = os.stat(path)
        b = stats.st_size
        if b < 1024: size = f"{b} B"
        elif b < 1024**2: size = f"{round(b/1024, 1)} KB"
        elif b < 1024**3: size = f"{round(b/1024**2, 1)} MB"
        else: size = f"{round(b/1024**3, 2)} GB"
        date = datetime.datetime.fromtimestamp(stats.st_mtime).strftime('%d %b %Y')
        return size, date
    except: return "-", "-"

def get_type(filename):
    ext = filename.lower().split('.')[-1]
    if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']: return 'image'
    if ext in ['mp4', 'webm', 'ogg', 'mov', 'mkv']: return 'video'
    return 'file'

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session: return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- API ROUTES (ADMIN & STORAGE) ---

@app.route('/api/storage_info')
def storage_info():
    disk = psutil.disk_usage(app.config['ROOT_DRIVE'])
    return jsonify({
        "total": round(disk.total / (1024**3), 2),
        "used": round(disk.used / (1024**3), 2),
        "free": round(disk.free / (1024**3), 2),
        "percent": disk.percent
    })

@app.route('/admin')
@login_required
def admin_dashboard():
    if session['username'] != 'admin': 
        return "Akses Ditolak: Hanya untuk Admin", 403

    disk = psutil.disk_usage(app.config['ROOT_DRIVE'])
    memory = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.5)
    
    system_info = {
        "os": platform.system(),
        "node": platform.node(),
        "cpu_usage": cpu,
        "ram_usage": memory.percent,
        "storage_total": round(disk.total / (1024**3), 2),
        "storage_used": round(disk.used / (1024**3), 2),
        "storage_free": round(disk.free / (1024**3), 2),
    }

    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT id, username FROM users")
    all_users = c.fetchall()
    conn.close()

    return render_template('admin.html', info=system_info, users=all_users)

# --- PUBLIC SHARE ROUTE ---
@app.route('/s/<token>')
def shared_access(token):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT file_path FROM shares WHERE token=?", (token,))
    result = c.fetchone()
    conn.close()

    if result:
        rel_path = result[0]
        abs_path = os.path.join(app.config['ROOT_DRIVE'], rel_path)
        if os.path.exists(abs_path):
            if os.path.isdir(abs_path):
                memory_file = io.BytesIO()
                with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for root, dirs, files in os.walk(abs_path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, os.path.dirname(abs_path))
                            zf.write(file_path, arcname)
                memory_file.seek(0)
                return send_file(memory_file, download_name=f"{os.path.basename(abs_path)}.zip", as_attachment=True)
            else:
                return send_file(abs_path, as_attachment=False)
    return "Link Expired or File Not Found", 404

@app.route('/api/share', methods=['POST'])
@login_required
def api_share():
    data = request.json
    req_path = data.get('path', '')
    abs_path = get_safe_path(req_path)
    if not abs_path or not os.path.exists(abs_path):
        return jsonify({'error': 'File not found'}), 404
    rel_path = os.path.relpath(abs_path, app.config['ROOT_DRIVE'])
    token = secrets.token_urlsafe(6)
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("INSERT INTO shares (token, file_path, created_by) VALUES (?, ?, ?)", 
              (token, rel_path, session['username']))
    conn.commit()
    conn.close()
    share_link = url_for('shared_access', token=token, _external=True)
    return jsonify({'link': share_link}), 200

# --- AUTH ROUTES ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        u = request.form['username'].lower().strip()
        p = request.form['password']
        if not u or not p: return render_template('register.html')
        try:
            conn = sqlite3.connect('users.db')
            c = conn.cursor()
            c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (u, generate_password_hash(p)))
            conn.commit()
            conn.close()
            os.makedirs(os.path.join(GLOBAL_ROOT, u), exist_ok=True)
            return redirect(url_for('login'))
        except: flash('Username taken', 'error')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form['username'].lower().strip()
        p = request.form['password']
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute("SELECT password FROM users WHERE username=?", (u,))
        user = c.fetchone()
        conn.close()
        if user and check_password_hash(user[0], p):
            session['username'] = u
            return redirect(url_for('index'))
        else: flash('Login Failed', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- MAIN DRIVE ROUTES ---
@app.route('/')
@login_required
def index():
    current_path = request.args.get('path', '')
    abs_path = get_safe_path(current_path)
    files = []
    try:
        items = os.listdir(abs_path)
        for item in items:
            full_path = os.path.join(abs_path, item)
            is_folder = os.path.isdir(full_path)
            size, date = "-", "-"
            if not is_folder: size, date = get_file_info(full_path)
            files.append({
                'name': item, 'path': os.path.join(current_path, item).replace("\\", "/"),
                'is_folder': is_folder, 'type': 'folder' if is_folder else get_type(item),
                'size': size, 'date': date
            })
        files.sort(key=lambda x: (not x['is_folder'], x['name'].lower()))
    except: return redirect(url_for('index'))

    try:
        total, used, free = shutil.disk_usage(app.config['ROOT_DRIVE'])
        storage = {'used_gb': round(used/1024**3, 2), 'total_gb': round(total/1024**3, 2), 'percent': round((used/total)*100, 1)}
    except: storage = {'used_gb': 0, 'total_gb': 0, 'percent': 0}

    return render_template('dashboard.html', files=files, current_path=current_path, parent_path=os.path.dirname(current_path), storage=storage, username=session['username'])

@app.route('/upload', methods=['POST'])
@login_required
def upload():
    path = request.form.get('current_path', '')
    files = request.files.getlist('file') 
    base_target = get_safe_path(path)
    for f in files:
        if f.filename:
            target_path = os.path.join(base_target, f.filename)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            f.save(target_path)
    
    notify_file_change() 
    return "OK", 200

@app.route('/create_folder', methods=['POST'])
@login_required
def create_folder():
    path = request.form.get('current_path', '')
    name = request.form.get('folder_name')
    if name:
        t = os.path.join(get_safe_path(path), "".join([c for c in name if c.isalnum() or c in " ._-"]))
        if not os.path.exists(t): os.makedirs(t)
        notify_file_change() 
    return redirect(url_for('index', path=path))

@app.route('/rename', methods=['POST'])
@login_required
def rename():
    path = request.form.get('current_path', '')
    old = request.form.get('old_name')
    new = request.form.get('new_name')
    if old and new:
        try: os.rename(os.path.join(get_safe_path(path), old), os.path.join(get_safe_path(path), "".join([c for c in new if c.isalnum() or c in " ._-"])))
        except: pass
        notify_file_change() # 3. Trigger Real-Time
    return redirect(url_for('index', path=path))

@app.route('/action/<act>')
@login_required
def action(act):
    path = request.args.get('path', '')
    target = get_safe_path(path)
    try:
        if act == 'download': return send_from_directory(os.path.dirname(target), os.path.basename(target), as_attachment=True)
        if act == 'view': return send_from_directory(os.path.dirname(target), os.path.basename(target), as_attachment=False)
        if act == 'delete': 
            if os.path.isdir(target): shutil.rmtree(target)
            else: os.remove(target)
            notify_file_change() # 3. Trigger Real-Time
    except: pass
    return redirect(url_for('index', path=os.path.dirname(path)))

@app.route('/api/folders', methods=['GET'])
@login_required
def api_folders():
    req_path = request.args.get('path', '')
    abs_path = get_safe_path(req_path)
    folders = []
    try:
        if req_path: folders.append({'name': '.. (Back)', 'path': os.path.dirname(req_path), 'type': 'parent'})
        for item in os.listdir(abs_path):
            if os.path.isdir(os.path.join(abs_path, item)): folders.append({'name': item, 'path': os.path.join(req_path, item).replace("\\", "/"), 'type': 'folder'})
    except: pass
    return {'folders': folders}

@app.route('/api/move', methods=['POST'])
@login_required
def api_move():
    data = request.json
    dest = get_safe_path(data.get('destination', ''))
    count = 0
    for item in data.get('items', []):
        src = get_safe_path(item)
        if src and os.path.exists(src):
            try: shutil.move(src, os.path.join(dest, os.path.basename(src))); count += 1
            except: pass
    
    if count > 0: notify_file_change() # 3. Trigger Real-Time
    return f"Moved {count}", 200

@app.route('/api/delete_batch', methods=['POST'])
@login_required
def api_delete_batch():
    for item in request.json.get('items', []):
        p = get_safe_path(item)
        try: 
            if os.path.isdir(p): shutil.rmtree(p)
            else: os.remove(p)
        except: pass
    
    notify_file_change() 
    return "Deleted", 200

if __name__ == '__main__':
    import socket
    try: ip = socket.gethostbyname(socket.gethostname())
    except: ip = "127.0.0.1"
    print(f"\n--- myDrive Cloud Server---")
    print(f"Local: http://{ip}:5000")
    print(f"Tailscale IP: http://100.86.93.30:5000 Windows")
    print(f"Tailscale IP: http://100.95.26.39:5001 MacOS")
    
    socketio.run(app, host='0.0.0.0', port=5001, debug=True)