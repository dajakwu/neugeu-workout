from datetime import timedelta
from flask import Flask, render_template, request, redirect, session, url_for, jsonify
import sqlite3
import hashlib
import os
import time
from datetime import datetime
from werkzeug.utils import secure_filename
import re

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'
app.permanent_session_lifetime = timedelta(days=30)

UPLOAD_FOLDER = 'static/profiles'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

user_last_pulse = {}

def get_db_connection():
    conn = sqlite3.connect('workout.db')
    conn.row_factory = sqlite3.Row
    return conn

def export_users_to_txt():
    conn = get_db_connection()
    users = conn.execute('SELECT nickname, user_id, role FROM users').fetchall()
    conn.close()
    with open('user_list.txt', 'w', encoding='utf-8') as f:
        f.write("=== 느그운동 유저 명단 ===\n")
        for user in users:
            f.write(f"{user['nickname']} | {user['user_id']} | {user['role']}\n")

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY, password TEXT NOT NULL, nickname TEXT NOT NULL, 
        role TEXT NOT NULL, profile_img TEXT, is_working_out INTEGER DEFAULT 0
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        date TEXT,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS routines (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        user_id TEXT, 
        routine_name TEXT NOT NULL, 
        is_hj_mode INTEGER DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS exercises (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        routine_id INTEGER, 
        name TEXT NOT NULL, 
        sets INTEGER, 
        reps INTEGER, 
        rest_time INTEGER, 
        FOREIGN KEY (routine_id) REFERENCES routines (id)
    )''')

    # 컬럼 누락 방지 보수 로직
    cols = [row['name'] for row in c.execute("PRAGMA table_info(routines)").fetchall()]
    if 'is_hj_mode' not in cols:
        c.execute('ALTER TABLE routines ADD COLUMN is_hj_mode INTEGER DEFAULT 0')

    try:
        admin_pw = hashlib.sha256("1234".encode()).hexdigest()
        c.execute("INSERT INTO users (user_id, password, nickname, role) VALUES (?, ?, ?, ?)", ("admin", admin_pw, "Master", "admin"))
        conn.commit()
    except: pass
    conn.close()
    export_users_to_txt()

init_db()

@app.route('/', methods=['GET', 'POST'])
def login():
    if 'user_id' in session: return redirect(url_for('main_dashboard'))
    
    if request.method == 'POST':
        user_id = request.form['user_id']
        password = request.form['password']
        # 기존 hashlib 방식 그대로 유지
        hashed_pw = hashlib.sha256(password.encode()).hexdigest()
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE user_id = ? AND password = ?', (user_id, hashed_pw)).fetchone()
        conn.close()
        
        if user:
            # 3. 자동 로그인 체크 여부에 따라 세션 수명 결정
            if request.form.get('remember_me'):
                session.permanent = True  # 브라우저 꺼도 30일간 유지
            else:
                session.permanent = False # 브라우저 끄면 바로 로그아웃
                
            session['user_id'] = user['user_id']
            session['nickname'] = user['nickname']
            session['role'] = user['role']
            return redirect(url_for('main_dashboard'))
        else:
            # 에러 메시지를 flash 대신 기존처럼 변수로 전달 (디자인 고수)
            return render_template('login.html', error='아이디 또는 비밀번호가 잘못되었습니다.')
            
    return render_template('login.html')

@app.route('/main')
def main_dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    routines = conn.execute('SELECT * FROM routines WHERE user_id = ?', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('main.html', routines=routines)

@app.route('/calendar')
def calendar_page():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('calendar.html')

@app.route('/api/get_history/<year>/<month>')
def get_history(year, month):
    if 'user_id' not in session: return jsonify([])
    search_date = f"{year}-{str(month).zfill(2)}-%"
    conn = get_db_connection()
    records = conn.execute('SELECT date FROM history WHERE user_id = ? AND date LIKE ?', (session['user_id'], search_date)).fetchall()
    conn.close()
    return jsonify([row['date'] for row in records])

@app.route('/api/record_workout_done', methods=['POST'])
def record_workout_done():
    if 'user_id' not in session: return "Unauthorized", 401
    today = datetime.now().strftime('%Y-%m-%d')
    conn = get_db_connection()
    existing = conn.execute('SELECT * FROM history WHERE user_id = ? AND date = ?', (session['user_id'], today)).fetchone()
    if not existing:
        conn.execute('INSERT INTO history (user_id, date) VALUES (?, ?)', (session['user_id'], today))
    conn.commit(); conn.close()
    return "OK", 200

@app.route('/update_status', methods=['POST'])
def update_status():
    if 'user_id' not in session: return "Unauthorized", 401
    status = request.json.get('status', 0)
    user_last_pulse[session['user_id']] = time.time()
    conn = get_db_connection()
    conn.execute('UPDATE users SET is_working_out = ? WHERE user_id = ?', (status, session['user_id']))
    conn.commit(); conn.close()
    return "OK", 200

@app.route('/get_friends_status')
def get_friends_status():
    if 'user_id' not in session: return jsonify({"friends": []}), 401
    conn = get_db_connection()
    friends_raw = conn.execute('SELECT user_id, nickname, profile_img, is_working_out FROM users').fetchall()
    conn.close()
    current_time = time.time()
    friend_list = []
    for f in friends_raw:
        f_dict = dict(f)
        last_seen = user_last_pulse.get(f_dict['user_id'], 0)
        if current_time - last_seen > 7: f_dict['is_working_out'] = 0
        friend_list.append(f_dict)
    return jsonify({"friends": friend_list})
@app.route('/delete_routine/<int:routine_id>', methods=['POST'])
def delete_routine(routine_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # 1. routines.txt에서 해당 루틴 삭제 로직
    # (기존에 파일 시스템을 사용 중이라면 아래와 유사한 로직이 필요합니다)
    try:
        with open('routines.txt', 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        with open('routines.txt', 'w', encoding='utf-8') as f:
            for line in lines:
                if not line.startswith(f"{routine_id}|"):
                    f.write(line)
                    
        return redirect(url_for('main'))
    except Exception as e:
        print(f"삭제 오류: {e}")
        return redirect(url_for('main'))
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
        names = request.form.getlist('ex_name')
        sets = request.form.getlist('ex_sets')
        reps = request.form.getlist('ex_reps')
        rests = request.form.getlist('ex_rest')
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
    exercises = conn.execute('SELECT * FROM exercises WHERE routine_id = ?', (routine_id,)).fetchall()
    conn.close()
    return render_template('run_routine.html', routine=routine, exercises=[dict(ex) for ex in exercises])

@app.route('/admin')
def admin_panel():
    if 'user_id' not in session or session.get('role') != 'admin': return redirect(url_for('main_dashboard'))
    conn = get_db_connection()
    users = conn.execute('SELECT * FROM users').fetchall()
    conn.close()
    return render_template('admin.html', users=users)

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)