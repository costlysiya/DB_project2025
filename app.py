# app.py

from flask import Flask, jsonify, request
import psycopg2  # PostgreSQL 연결을 위한 DB API
from psycopg2 import extras  # 딕셔너리 형태로 데이터를 가져오기 위함

app = Flask(__name__)


# 💡 DB 접속 설정 함수
def get_db_connection():
    try:
        conn = psycopg2.connect(
            host="127.0.0.1",  # 예: "127.0.0.1" (로컬 테스트 시), 외부 접속 시 실제 IP
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


# 예시: 상품 목록을 DB에서 가져오는 API 구현 (SELECT 기능)
@app.route('/products', methods=['GET'])
def get_products():
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "데이터베이스 연결 실패"}), 500

    try:
        # CursorFactory를 사용하여 데이터를 딕셔너리 형태로 가져오도록 설정
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # SQL 쿼리 실행
        cur.execute("SELECT product_id, name, price, stock, status, rating FROM Product WHERE status = '판매중';")

        # 결과를 모두 가져와서 리스트로 변환
        products = [dict(row) for row in cur.fetchall()]

        cur.close()
        conn.close()

        return jsonify(products)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    # 디버그 모드를 켜고 실행 (개발 중에는 편리함)
    app.run(debug=True)


# 데이터베이스 연결 확인 코드
@app.route('/test_db_connection', methods=['GET'])
def test_db_connection():
    conn = get_db_connection()

    if conn is None:
        # get_db_connection 함수에서 이미 오류 메시지를 출력했지만,
        # API 응답으로도 실패를 명확히 알림
        return jsonify({
            "status": "FAIL",
            "message": "데이터베이스 연결에 실패했습니다. (host, port, user, password, dbname 확인 필요)"
        }), 500

    try:
        # 간단한 쿼리를 실행하여 실제 통신이 되는지 확인
        cur = conn.cursor()
        cur.execute("SELECT 1")
        result = cur.fetchone()

        if result and result[0] == 1:
            conn.close()
            return jsonify({
                "status": "SUCCESS",
                "message": "데이터베이스 연결 및 기본 쿼리 테스트 성공!"
            }), 200
        else:
            conn.close()
            return jsonify({
                "status": "FAIL",
                "message": "연결은 되었으나 기본 쿼리 실행에 문제가 있습니다."
            }), 500

    except Exception as e:
        # 쿼리 실행 중 발생한 예외 처리
        conn.close()
        return jsonify({
            "status": "ERROR",
            "message": f"DB 쿼리 실행 중 예외 발생: {str(e)}"
        }), 500