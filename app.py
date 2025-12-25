import os
import shutil
from flask import Flask, request, render_template, send_from_directory, redirect, url_for

app = Flask(__name__)

# --- CONFIG ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DRIVE = os.path.join(BASE_DIR, 'myDrive_data')

if not os.path.exists(ROOT_DRIVE): os.makedirs(ROOT_DRIVE)
app.config['ROOT_DRIVE'] = ROOT_DRIVE

# --- HELPERS ---
def get_safe_path(req_path):
    target = os.path.join(app.config['ROOT_DRIVE'], req_path)
    if not os.path.realpath(target).startswith(os.path.realpath(app.config['ROOT_DRIVE'])):
        return app.config['ROOT_DRIVE']
    return target

def get_file_type(filename):
    ext = filename.lower().split('.')[-1]
    if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']: return 'image'
    if ext in ['mp4', 'webm', 'ogg', 'mov', 'mkv']: return 'video'
    return 'file'

# --- ROUTES ---
@app.route('/')
def index():
    current_path = request.args.get('path', '')
    abs_path = get_safe_path(current_path)
    
    items_data = []
    try:
        items = os.listdir(abs_path)
        for item in items:
            full_path = os.path.join(abs_path, item)
            rel_path = os.path.join(current_path, item).replace("\\", "/")
            is_folder = os.path.isdir(full_path)
            items_data.append({
                'name': item,
                'path': rel_path,
                'is_folder': is_folder,
                'type': 'folder' if is_folder else get_file_type(item)
            })
        items_data.sort(key=lambda x: (not x['is_folder'], x['name'].lower()))
    except:
        return redirect(url_for('index'))

    parent_path = os.path.dirname(current_path)
    
    # --- PERBAIKAN DI SINI (Penamaan Variabel) ---
    try:
        total, used, free = shutil.disk_usage(app.config['ROOT_DRIVE'])
        storage = {
            'total_gb': round(total / (2**30), 2),  # GB Total
            'used_gb': round(used / (2**30), 2),    # GB Terpakai
            'free_gb': round(free / (2**30), 2),    # GB Sisa (Fix error disini)
            'percent': round((used / total) * 100, 1)
        }
    except:
        storage = {'total_gb': 0, 'used_gb': 0, 'free_gb': 0, 'percent': 0}

    return render_template('dashboard.html', files=items_data, current_path=current_path, parent_path=parent_path, storage=storage)

@app.route('/upload', methods=['POST'])
def upload_file():
    current_path = request.form.get('current_path', '')
    if 'file' not in request.files: return "No file part", 400
    file = request.files['file']
    if file.filename == '': return "No selected file", 400
    if file:
        file.save(os.path.join(get_safe_path(current_path), file.filename))
        return redirect(url_for('index', path=current_path))

@app.route('/create_folder', methods=['POST'])
def create_folder():
    folder_name = request.form.get('folder_name')
    current_path = request.form.get('current_path', '')
    if folder_name:
        safe_name = "".join([c for c in folder_name if c.isalnum() or c in " ._-"])
        target = os.path.join(get_safe_path(current_path), safe_name)
        if not os.path.exists(target): os.makedirs(target)
    return redirect(url_for('index', path=current_path))

@app.route('/rename', methods=['POST'])
def rename_item():
    current_path = request.form.get('current_path', '')
    old_name = request.form.get('old_name')
    new_name = request.form.get('new_name')
    
    if old_name and new_name:
        safe_new_name = "".join([c for c in new_name if c.isalnum() or c in " ._-"])
        old_path = os.path.join(get_safe_path(current_path), old_name)
        new_path = os.path.join(get_safe_path(current_path), safe_new_name)
        try: os.rename(old_path, new_path)
        except: pass
            
    return redirect(url_for('index', path=current_path))

@app.route('/action/<action_type>')
def file_action(action_type):
    req_path = request.args.get('path', '')
    abs_path = get_safe_path(req_path)
    directory = os.path.dirname(abs_path)
    filename = os.path.basename(abs_path)

    try:
        if action_type == 'download': return send_from_directory(directory, filename, as_attachment=True)
        if action_type == 'view': return send_from_directory(directory, filename, as_attachment=False)
        if action_type == 'delete':
            if os.path.isdir(abs_path): os.rmdir(abs_path)
            else: os.remove(abs_path)
    except: pass
    return redirect(url_for('index', path=os.path.dirname(req_path)))

if __name__ == '__main__':
    import socket
    try: ip = socket.gethostbyname(socket.gethostname())
    except: ip = "127.0.0.1"
    print(f"\n--- myDrive v4.1 (Fix Storage) ---\nhttp://{ip}:5000\n")
    app.run(host='0.0.0.0', port=5000, debug=True)