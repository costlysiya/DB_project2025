# app.py

from flask import Flask, jsonify, request, render_template
import psycopg2  # PostgreSQL 연결을 위한 DB API
from psycopg2 import extras  # 딕셔너리 형태로 데이터를 가져오기 위함

app = Flask(__name__)

#  DB 접속 설정 함수
def get_db_connection():
    try:
        conn = psycopg2.connect(
            host="127.0.0.1",  #로컬 테스트, (외부 접속 시 실제 IP)
            database="project2025",
            user="db2025",
            password="db!2025",
            port="5432"
        )
        return conn
    except Exception as e:
        print(f"DB 연결 오류: {e}")
        return None


# 테스트용 API 엔드포인트
@app.route('/')
def home():
    return "Goods Sales and Resale System API is Running!"

#로그인 페이지 라우터
@app.route('/login', methods=['GET'])
def show_login_page():
    """ 로그인 페이지 (login.html)를 보여줍니다. """
    return render_template('login.html') # templates 폴더의 login.html 파일을 찾아서 반환
#회원가입 페이지 라우터
@app.route('/signup', methods=['GET'])
def show_signup_page():
    """ 회원가입 페이지 (signup.html)를 보여줍니다. """
    return render_template('signup.html') # templates 폴더의 signup.html 파일을 찾아서 반환


# 회원가입 기능 구현
# 임시 관리자 인증 번호 (실제 환경에서는 환경 변수 등으로 관리해야 합니다.)
ADMIN_AUTH_CODE = "ADMIN4567"

@app.route('/api/signup', methods=['POST'])
def signup_user():
    data = request.json #http요청에 대한 정보 담음

    # 1. JSON 데이터 받아서 필수 입력값 검증
    user_uid = data.get('user_uid')
    password = data.get('password')
    name = data.get('name')
    role = data.get('role')
    address = data.get('address')
    admin_code = data.get('admin_code')
    store_name = data.get('store_name')

    if not all([user_uid, password, name, role]):
        return jsonify({"error": "필수 입력 항목이 누락되었습니다."}), 400

    if role not in ['Administrator', 'PrimarySeller', 'Reseller', 'Buyer']:
        return jsonify({"error": "유효하지 않은 역할입니다."}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "데이터베이스 연결 실패"}), 500

    # 트랜잭션 시작 (Users 테이블과 Profile 테이블에 동시에 성공해야 함)
    conn.autocommit = False
    try:
        cur = conn.cursor()

        # 1-1. 관리자 인증 번호 확인
        if role == 'Administrator' and admin_code != ADMIN_AUTH_CODE:
            conn.rollback()
            return jsonify({"message": "관리자 인증 번호가 올바르지 않습니다."}), 403

        # 1-2. user_uid 중복 확인
        cur.execute("SELECT user_id FROM Users WHERE user_uid = %s", (user_uid,))
        if cur.fetchone():
            conn.rollback()
            return jsonify({"message": "이미 사용 중인 ID입니다."}), 409

        # 2. Users 테이블에 기본 정보 INSERT
        cur.execute(
            "INSERT INTO Users (user_uid, password, name, role) VALUES (%s, %s, %s, %s) RETURNING user_id",
            (user_uid, password, name, role)
        )
        user_id = cur.fetchone()[0]  # 새로 생성된 user_id 가져오기

        # 3. 역할에 따른 프로필 테이블 INSERT
        if role == 'Administrator':
            cur.execute("INSERT INTO AdminProfile (user_id) VALUES (%s)", (user_id,))
        elif role in ['PrimarySeller', 'Reseller']:
            cur.execute("INSERT INTO SellerProfile (user_id, store_name, grade) VALUES (%s, %s, NULL)",
                        (user_id, store_name))

        elif role == 'Buyer':
            # 구매자는 주소가 필수 (제안서 기반)
            if not address:
                conn.rollback()
                return jsonify({"message": "구매자는 주소를 입력해야 합니다."}), 400
            cur.execute("INSERT INTO BuyerProfile (user_id, address) VALUES (%s, %s)", (user_id, address))

        # 4. 모든 작업 성공 시 커밋
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"message": f"{role} 회원가입 성공", "user_id": user_id}), 201

    except Exception as e:
        # 오류 발생 시 롤백 (Users, Profile 모두 취소)
        conn.rollback()
        return jsonify({"error": f"회원가입 트랜잭션 실패: {str(e)}"}), 500

#로그인 기능
@app.route('/api/login', methods=['POST'])
def login_user():
    data = request.json

    # 1. 사용자 입력 받기
    user_uid = data.get('user_uid')
    password = data.get('password')

    if not all([user_uid, password]):
        return jsonify({"error": "ID와 비밀번호를 모두 입력해야 합니다."}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "데이터베이스 연결 실패"}), 500

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # 2. Users 테이블에서 사용자 정보 조회
        # 실제 환경에서는 'password = %s' 대신 해시된 비밀번호를 비교해야 함. -->나중에 구현해보기
        sql_query = """
            SELECT 
                user_id, 
                name, 
                role 
            FROM 
                Users 
            WHERE 
                user_uid = %s AND password = %s
        """
        cur.execute(sql_query, (user_uid, password))
        user = cur.fetchone()

        cur.close()
        conn.close()

        # 3. 로그인 성공 또는 실패 처리
        if user:
            # 딕셔너리 형태로 반환
            user_info = dict(user)
            return jsonify({
                "message": f"{user_info['name']}님, 로그인에 성공했습니다.",
                "user_id": user_info['user_id'],
                "user_name": user_info['name'],
                "user_role": user_info['role']
            }), 200
        else:
            return jsonify({"message": "ID 또는 비밀번호가 올바르지 않습니다."}), 401

    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"error": f"로그인 중 오류 발생: {str(e)}"}), 500


if __name__ == '__main__':
    # 디버그 모드를 켜고 실행
    app.run(debug=True)