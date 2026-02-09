from datetime import timedelta
from flask import Flask, render_template, request, redirect, session, url_for, jsonify
import sqlite3
import hashlib
import os
import time
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'
app.permanent_session_lifetime = timedelta(days=30)

UPLOAD_FOLDER = 'static/profiles'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# 접속 상태를 확인하기 위한 메모리 저장소
user_last_pulse = {}

def get_db_connection():
    conn = sqlite3.connect('workout.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY, password TEXT NOT NULL, nickname TEXT NOT NULL, 
        role TEXT NOT NULL, profile_img TEXT, is_working_out INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, date TEXT,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS routines (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, routine_name TEXT NOT NULL, 
        is_hj_mode INTEGER DEFAULT 0, FOREIGN KEY (user_id) REFERENCES users (user_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS exercises (
        id INTEGER PRIMARY KEY AUTOINCREMENT, routine_id INTEGER, name TEXT NOT NULL, 
        sets INTEGER, reps INTEGER, rest_time INTEGER, FOREIGN KEY (routine_id) REFERENCES routines (id)
    )''')
    try:
        admin_pw = hashlib.sha256("1234".encode()).hexdigest()
        c.execute("INSERT OR IGNORE INTO users (user_id, password, nickname, role) VALUES (?, ?, ?, ?)", 
                  ("admin", admin_pw, "Master", "admin"))
        conn.commit()
    except: pass
    conn.close()

init_db()

# [중요] 접속 유지를 위한 전역 감지기
@app.before_request
def update_last_seen():
    if 'user_id' in session:
        user_last_pulse[session['user_id']] = time.time()

# ================= 라우트 시작 =================

@app.route('/', methods=['GET', 'POST'])
def login():
    if 'user_id' in session: return redirect(url_for('main_dashboard'))
    if request.method == 'POST':
        user_id = request.form['user_id']
        password = request.form['password']
        hashed_pw = hashlib.sha256(password.encode()).hexdigest()
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE user_id = ? AND password = ?', (user_id, hashed_pw)).fetchone()
        conn.close()
        if user:
            session.permanent = True if request.form.get('remember_me') else False
            session['user_id'] = user['user_id']
            session['nickname'] = user['nickname']
            session['role'] = user['role']
            session['profile_img'] = user['profile_img']
            return redirect(url_for('main_dashboard'))
        return render_template('login.html', error='아이디 또는 비밀번호가 잘못되었습니다.')
    return render_template('login.html')

@app.route('/main')
def main_dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    routines = conn.execute('SELECT * FROM routines WHERE user_id = ?', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('main.html', routines=routines, session=session)

@app.route('/add_routine', methods=['GET', 'POST'])
def add_routine():
    if 'user_id' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        routine_name = request.form.get('routine_name', '새 루틴')
        conn = get_db_connection()
        conn.execute('INSERT INTO routines (user_id, routine_name, is_hj_mode) VALUES (?, ?, 0)', 
                     (session['user_id'], routine_name))
        conn.commit(); conn.close()
    return redirect(url_for('main_dashboard'))

@app.route('/delete_routine/<int:routine_id>', methods=['GET', 'POST']) # [수리] POST 메서드 명시 (삭제 버튼 폼 전송용)
def delete_routine(routine_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    conn.execute('DELETE FROM exercises WHERE routine_id = ?', (routine_id,))
    conn.execute('DELETE FROM routines WHERE id = ? AND user_id = ?', (routine_id, session['user_id']))
    conn.commit(); conn.close()
    return redirect(url_for('main_dashboard'))

@app.route('/edit_routine/<int:routine_id>', methods=['GET', 'POST'])
def edit_routine(routine_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    if request.method == 'POST':
        new_name = request.form['routine_name']
        is_hj = 1 if request.form.get('is_hj_mode') else 0
        conn.execute('UPDATE routines SET routine_name = ?, is_hj_mode = ? WHERE id = ? AND user_id = ?', 
                     (new_name, is_hj, routine_id, session['user_id']))
        conn.execute('DELETE FROM exercises WHERE routine_id = ?', (routine_id,))
        names, sets, reps, rests = request.form.getlist('ex_name'), request.form.getlist('ex_sets'), request.form.getlist('ex_reps'), request.form.getlist('ex_rest')
        for i in range(len(names)):
            if names[i].strip():
                conn.execute('INSERT INTO exercises (routine_id, name, sets, reps, rest_time) VALUES (?, ?, ?, ?, ?)', 
                             (routine_id, names[i], int(sets[i]), int(reps[i]), int(rests[i])))
        conn.commit(); conn.close()
        return redirect(url_for('main_dashboard'))
    routine = conn.execute('SELECT * FROM routines WHERE id = ? AND user_id = ?', (routine_id, session['user_id'])).fetchone()
    exercises = conn.execute('SELECT * FROM exercises WHERE routine_id = ?', (routine_id,)).fetchall()
    conn.close()
    return render_template('edit_routine.html', routine=routine, exercises=exercises)

@app.route('/run_routine/<int:routine_id>')
def run_routine(routine_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    routine = conn.execute('SELECT * FROM routines WHERE id = ?', (routine_id,)).fetchone()
    exercises_rows = conn.execute('SELECT * FROM exercises WHERE routine_id = ?', (routine_id,)).fetchall()
    exercises_list = [dict(row) for row in exercises_rows] 
    conn.close()
    return render_template('run_routine.html', routine=routine, exercises=exercises_list)

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    
    if request.method == 'POST':
        new_id = request.form.get('new_id')
        new_nickname = request.form.get('nickname')
        old_id = session['user_id']
        
        if new_id and new_id != old_id:
            try:
                conn.execute('UPDATE users SET user_id = ? WHERE user_id = ?', (new_id, old_id))
                conn.execute('UPDATE routines SET user_id = ? WHERE user_id = ?', (new_id, old_id))
                conn.execute('UPDATE history SET user_id = ? WHERE user_id = ?', (new_id, old_id))
                session['user_id'] = new_id
            except: pass

        if new_nickname:
            conn.execute('UPDATE users SET nickname = ? WHERE user_id = ?', (new_nickname, session['user_id']))
            session['nickname'] = new_nickname
            
        if 'profile_img' in request.files:
            file = request.files['profile_img']
            if file.filename != '':
                ext = os.path.splitext(file.filename)[1]
                filename = f"{session['user_id']}_{int(time.time())}{ext}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                conn.execute('UPDATE users SET profile_img = ? WHERE user_id = ?', (filename, session['user_id']))
                session['profile_img'] = filename
        
        conn.commit(); conn.close()
        return redirect(url_for('main_dashboard'))

    user = conn.execute('SELECT * FROM users WHERE user_id = ?', (session['user_id'],)).fetchone()
    conn.close()
    return render_template('profile.html', user=user)

@app.route('/calendar')
def calendar_page():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('calendar.html')

# ================= 관리자 및 API =================

@app.route('/admin')
def admin_panel():
    if 'user_id' not in session or session.get('role') != 'admin': return redirect(url_for('main_dashboard'))
    conn = get_db_connection()
    users = conn.execute('SELECT * FROM users').fetchall()
    conn.close()
    return render_template('admin.html', users=users)

@app.route('/admin/create_user', methods=['POST'])
def admin_create_user():
    if session.get('role') != 'admin': return redirect(url_for('login'))
    new_id = request.form['new_id']
    new_pw = hashlib.sha256(request.form['new_pw'].encode()).hexdigest()
    new_nick = request.form['new_nickname']
    conn = get_db_connection()
    try: conn.execute("INSERT INTO users (user_id, password, nickname, role) VALUES (?, ?, ?, 'user')", (new_id, new_pw, new_nick)); conn.commit()
    except: pass
    conn.close(); return redirect(url_for('admin_panel'))

@app.route('/admin/update_user', methods=['POST'])
def admin_update_user():
    if session.get('role') != 'admin': return redirect(url_for('login'))
    target_id = request.form['target_id']
    new_nick = request.form['new_nickname']
    new_pw = request.form.get('new_pw')
    
    conn = get_db_connection()
    conn.execute("UPDATE users SET nickname = ? WHERE user_id = ?", (new_nick, target_id))
    
    if new_pw and new_pw.strip():
        hashed_pw = hashlib.sha256(new_pw.encode()).hexdigest()
        conn.execute("UPDATE users SET password = ? WHERE user_id = ?", (hashed_pw, target_id))
        
    if 'profile_img' in request.files:
        file = request.files['profile_img']
        if file.filename != '':
            ext = os.path.splitext(file.filename)[1]
            filename = f"{target_id}_{int(time.time())}{ext}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            conn.execute('UPDATE users SET profile_img = ? WHERE user_id = ?', (filename, target_id))
            
    conn.commit(); conn.close(); return redirect(url_for('admin_panel'))

@app.route('/admin/delete_user/<user_id>')
def admin_delete_user(user_id):
    if session.get('role') != 'admin': return redirect(url_for('login'))
    conn = get_db_connection()
    conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM routines WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM history WHERE user_id = ?", (user_id,))
    conn.commit(); conn.close(); return redirect(url_for('admin_panel'))

# [수리] 달력 기록 조회 API (타입 안전성 강화)
@app.route('/api/get_history/<year>/<month>')
def get_history(year, month):
    if 'user_id' not in session: return jsonify([])
    # month가 숫자여도, 문자여도 2자리 문자열로 변환 (예: 2 -> "02")
    safe_month = str(month).zfill(2)
    date_prefix = f"{year}-{safe_month}%"
    conn = get_db_connection()
    rows = conn.execute("SELECT date FROM history WHERE user_id=? AND date LIKE ?", (session['user_id'], date_prefix)).fetchall()
    conn.close()
    return jsonify([r['date'] for r in rows])

# [수리] 달력 기록 토글 API
@app.route('/api/toggle_history', methods=['POST'])
def toggle_history():
    if 'user_id' not in session: return "Unauthorized", 401
    date_str = request.json.get('date')
    conn = get_db_connection()
    exists = conn.execute("SELECT id FROM history WHERE user_id=? AND date=?", (session['user_id'], date_str)).fetchone()
    if exists: conn.execute("DELETE FROM history WHERE id=?", (exists['id'],))
    else: conn.execute("INSERT INTO history (user_id, date) VALUES (?, ?)", (session['user_id'], date_str))
    conn.commit(); conn.close(); return "OK", 200

@app.route('/api/record_workout_done', methods=['POST'])
def record_workout_done():
    if 'user_id' not in session: return "Unauthorized", 401
    today = datetime.now().strftime('%Y-%m-%d')
    conn = get_db_connection()
    if not conn.execute('SELECT * FROM history WHERE user_id = ? AND date = ?', (session['user_id'], today)).fetchone():
        conn.execute('INSERT INTO history (user_id, date) VALUES (?, ?)', (session['user_id'], today))
    conn.commit(); conn.close(); return "OK", 200

@app.route('/update_status', methods=['POST'])
def update_status():
    if 'user_id' not in session: return "Unauthorized", 401
    status = request.json.get('status', 1)
    user_last_pulse[session['user_id']] = time.time()
    conn = get_db_connection()
    conn.execute('UPDATE users SET is_working_out = ? WHERE user_id = ?', (status, session['user_id']))
    conn.commit(); conn.close(); return "OK", 200

@app.route('/get_friends_status')
def get_friends_status():
    if 'user_id' not in session: return jsonify({"friends": []}), 401
    conn = get_db_connection()
    friends = [dict(f) for f in conn.execute('SELECT user_id, nickname, profile_img, is_working_out FROM users').fetchall()]
    conn.close()
    curr = time.time()
    for f in friends:
        if curr - user_last_pulse.get(f['user_id'], 0) > 8: f['is_working_out'] = 0 # 8초 미응답시 오프라인
        if f['profile_img']: f['profile_img'] = f"/static/profiles/{f['profile_img']}?v={int(curr)}"
    return jsonify({"friends": friends})

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)