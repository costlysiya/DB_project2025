# test_db_connection.py
import psycopg2
import sys

# ----------------------------------------------------------------------
# DB 접속 설정 (app.py의 정보를 사용합니다)
# ----------------------------------------------------------------------
DB_HOST = "127.0.0.1"
DB_NAME = "project2025"
DB_USER = "db2025"
DB_PASS = "db!2025"  # ⚠️ 이 비밀번호가 PostgreSQL에 등록된 비밀번호와 일치하는지 확인!
DB_PORT = "5432"


def test_db_connection():
    """ PostgreSQL 데이터베이스 연결을 테스트하고 결과를 출력합니다. """
    print("=" * 40)
    print(f"PostgreSQL 연결 테스트 시작 (User: {DB_USER}, DB: {DB_NAME})")
    print("-" * 40)

    conn = None
    try:
        # 1. DB 연결 시도
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            port=DB_PORT,
            client_encoding = 'UTF8'
        )

        # 2. 연결 성공 확인
        print("✅ 연결 성공: 데이터베이스에 성공적으로 접속했습니다.")

        # 3. 간단한 쿼리 실행 (DB 권한 테스트)
        cur = conn.cursor()
        cur.execute("SELECT version();")
        db_version = cur.fetchone()[0]
        print(f"   - DB 버전: {db_version.split(',')[0]}")

        # 4. Users 테이블 접근 권한 테스트 (가장 중요한 부분)
        try:
            cur.execute("SELECT COUNT(*) FROM Users;")
            user_count = cur.fetchone()[0]
            print(f"   - Users 테이블 접근 성공 (현재 사용자 수: {user_count})")
        except psycopg2.ProgrammingError as e:
            # 권한이 없을 경우 발생하는 오류
            print("❌ 권한 오류: Users 테이블에 접근할 권한이 없습니다.")
            print("   - 조치: 'postgres' 슈퍼유저로 접속하여 'db2025' 사용자에게 GRANT 권한을 부여하세요.")
            print(f"   - 상세 오류: {e}")
            sys.exit(1)


    except psycopg2.OperationalError as e:
        # 5. 연결 실패 처리 (서버 꺼짐, 비밀번호 오류 등)
        print("❌ 연결 실패: 데이터베이스에 접속할 수 없습니다.")
        if "Connection refused" in str(e):
            print("   - 원인: PostgreSQL 서버가 실행 중인지, 포트가 열려 있는지 확인하세요.")
            print("   - 조치: 서비스 관리자에서 PostgreSQL 서비스를 시작해야 합니다.")
        elif "password authentication failed" in str(e):
            print("   - 원인: 비밀번호가 잘못되었습니다. 'db!2025' 비밀번호를 확인하세요.")
        else:
            print(f"   - 상세 오류: {e}")
        sys.exit(1)

    except Exception as e:
        print(f"⚠️ 예측하지 못한 오류 발생: {e}")
        sys.exit(1)

    finally:
        if conn:
            conn.close()
            print("-" * 40)
            print("연결이 안전하게 종료되었습니다.")
        print("=" * 40)


if __name__ == '__main__':
    # 'pip install psycopg2-binary'가 먼저 설치되어 있어야 합니다.
    test_db_connection()