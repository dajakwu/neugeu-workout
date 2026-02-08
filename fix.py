import sqlite3
import os

def final_db_patch():
    # 현재 실행 중인 파일의 경로를 기준으로 DB 파일 탐색
    db_path = os.path.join(os.path.dirname(__file__), 'workout.db')
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    try:
        # routines 테이블에 is_hj_mode 컬럼 추가
        cur.execute('ALTER TABLE routines ADD COLUMN is_hj_mode INTEGER DEFAULT 0')
        conn.commit()
        print(f"✅ DB 수리 완료: {db_path} 에 'is_hj_mode' 컬럼이 추가되었습니다.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print("ℹ️ 이미 컬럼이 존재합니다. 다음 단계를 진행하세요.")
        else:
            print(f"❌ 오류 발생: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    final_db_patch()