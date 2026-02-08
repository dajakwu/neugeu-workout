from datetime import timedelta
from flask import Flask, render_template, request, redirect, session, url_for, jsonify
import sqlite3
import hashlib
import os
import time
from datetime import datetime
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'your_secret_key_here' # 배포 시에는 복잡한 키로 변경 추천
app.permanent_session_lifetime = timedelta(days=30)

# 프로필 사진 저장 경로
UPLOAD_FOLDER = 'static/profiles'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# 실시간 접속 확인용 딕셔너리
user_last_pulse = {}

# DB 연결 헬퍼 함수
def get_db_connection():
    conn = sqlite3.connect('workout.db')
    conn.row_factory = sqlite3.Row
    return conn

# DB 초기화 함수
def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    # 1. 유저 테이블
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY, password TEXT NOT NULL, nickname TEXT NOT NULL, 
        role TEXT NOT NULL, profile_img TEXT, is_working_out INTEGER DEFAULT 0
    )''')
    
    # 2. 운동 기록 테이블
    c.execute('''CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT, date TEXT,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )''')

    # 3. 루틴 테이블
    c.execute('''CREATE TABLE IF NOT EXISTS routines (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        user_id TEXT, routine_name TEXT NOT NULL, 
        is_hj_mode INTEGER DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )''')

    # 4. 운동 상세 정보 테이블
    c.execute('''CREATE TABLE IF NOT EXISTS exercises (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        routine_id INTEGER, name TEXT NOT NULL, 
        sets INTEGER, reps INTEGER, rest_time INTEGER, 
        FOREIGN KEY (routine_id) REFERENCES routines (id)
    )''')

    # 관리자 계정 생성
    try:
        admin_pw = hashlib.sha256("1234".encode()).hexdigest()
        c.execute("INSERT OR IGNORE INTO users (user_id, password, nickname, role) VALUES (?, ?, ?, ?)", 
                  ("admin", admin_pw, "Master", "admin"))
        conn.commit()
    except: pass
    conn.close()

init_db()

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
            if request.form.get('remember_me'):
                session.permanent = True
            else:
                session.permanent = False
                
            session['user_id'] = user['user_id']
            session['nickname'] = user['nickname']
            session['role'] = user['role']
            session['profile_img'] = user['profile_img'] # 세션에 이미지 정보 추가
            return redirect(url_for('main_dashboard'))
        else:
            return render_template('login.html', error='아이디 또는 비밀번호가 잘못되었습니다.')
            
    return render_template('login.html')

@app.route('/main')
def main_dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    routines = conn.execute('SELECT * FROM routines WHERE user_id = ?', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('main.html', routines=routines)

# [수리 완료] 루틴 추가 기능 (404 원인 해결)
@app.route('/add_routine', methods=['POST'])
def add_routine():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    routine_name = request.form.get('routine_name', '새 루틴')
    conn = get_db_connection()
    conn.execute('INSERT INTO routines (user_id, routine_name, is_hj_mode) VALUES (?, ?, 0)', 
                 (session['user_id'], routine_name))
    conn.commit()
    conn.close()
    return redirect(url_for('main_dashboard'))

# [수리 완료] 루틴 삭제 기능 (DB 연동 방식으로 변경)
@app.route('/delete_routine/<int:routine_id>', methods=['POST'])
def delete_routine(routine_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    
    conn = get_db_connection()
    # 루틴에 속한 운동들 먼저 삭제 (참조 무결성)
    conn.execute('DELETE FROM exercises WHERE routine_id = ?', (routine_id,))
    # 루틴 본체 삭제 (본인 것인지 확인)
    conn.execute('DELETE FROM routines WHERE id = ? AND user_id = ?', (routine_id, session['user_id']))
    conn.commit()
    conn.close()
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
        
        # 기존 운동 싹 지우고 새로 등록
        conn.execute('DELETE FROM exercises WHERE routine_id = ?', (routine_id,))
        names = request.form.getlist('ex_name')
        sets = request.form.getlist('ex_sets')
        reps = request.form.getlist('ex_reps')
        rests = request.form.getlist('ex_rest')
        
        for i in range(len(names)):
            if names[i].strip():
                conn.execute('INSERT INTO exercises (routine_id, name, sets, reps, rest_time) VALUES (?, ?, ?, ?, ?)', 
                             (routine_id, names[i], int(sets[i]), int(reps[i]), int(rests[i])))
        conn.commit()
        conn.close()
        return redirect(url_for('main_dashboard'))
    
    routine = conn.execute('SELECT * FROM routines WHERE id = ? AND user_id = ?', (routine_id, session['user_id'])).fetchone()
    # 남의 루틴 수정 방지
    if not routine:
        conn.close()
        return redirect(url_for('main_dashboard'))
        
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

# [신규 추가] 내 계정 관리 페이지 (404 원인 해결)
@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    
    if request.method == 'POST':
        # 1. 닉네임 변경
        new_nickname = request.form.get('nickname')
        if new_nickname:
            conn.execute('UPDATE users SET nickname = ? WHERE user_id = ?', (new_nickname, session['user_id']))
            session['nickname'] = new_nickname
            
        # 2. 프로필 사진 업로드
        if 'profile_img' in request.files:
            file = request.files['profile_img']
            if file and file.filename != '':
                filename = secure_filename(f"{session['user_id']}_{int(time.time())}.jpg")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                conn.execute('UPDATE users SET profile_img = ? WHERE user_id = ?', (filename, session['user_id']))
                session['profile_img'] = filename
        
        conn.commit()
        conn.close()
        return redirect(url_for('profile'))

    user = conn.execute('SELECT * FROM users WHERE user_id = ?', (session['user_id'],)).fetchone()
    conn.close()
    return render_template('profile.html', user=user)

@app.route('/calendar')
def calendar_page():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('calendar.html')

# ================= API 영역 =================

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
        # 7초 이상 응답 없으면 오프라인 처리
        if current_time - last_seen > 7: 
            f_dict['is_working_out'] = 0
            
        # DB 상태도 최신화 (선택사항)
        if f_dict['is_working_out'] != f['is_working_out']:
             pass 

        friend_list.append(f_dict)
    return jsonify({"friends": friend_list})

@app.route('/admin')
def admin_panel():
    if 'user_id' not in session or session.get('role') != 'admin': return redirect(url_for('main_dashboard'))
    conn = get_db_connection()
    users = conn.execute('SELECT * FROM users').fetchall()
    conn.close()
    return render_template('admin.html', users=users)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)