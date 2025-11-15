# app.py

from flask import Flask, jsonify, request, render_template, session
import psycopg2  # PostgreSQL 연결을 위한 DB API
from psycopg2 import extras  # 딕셔너리 형태로 데이터를 가져오기 위함
import os


app = Flask(__name__)
#세션 secret_key 설정
app.secret_key = os.urandom(24)

#  DB 접속 설정 함수
def get_db_connection():
    try:
        conn = psycopg2.connect(
            host="127.0.0.1",  #로컬 테스트, (외부 접속 시 실제 IP)
            database="project2025",
            user="db2025",
            password="db!2025",
            port="5432",
            client_encoding='UTF8'
        )
        return conn
    except Exception as e:
        print(f"DB 연결 오류: {e}")
        return None

# app.py 파일 상단 (기존 get_db_connection 함수 바로 아래에 추가)

# DB 연결 상태를 확인하는 함수
def check_db_connection():
    """ 데이터베이스 연결을 시도하고 성공 여부를 반환합니다. """
    conn = get_db_connection()
    if conn:
        try:
            # 연결이 성공하면 닫고 True 반환
            conn.close()
            return True
        except Exception as e:
            # 연결은 되었지만, 닫는 과정에서 문제 발생 시 (거의 없음)
            print(f"DB 연결 테스트 중 오류 발생: {e}")
            return False
    # get_db_connection에서 이미 오류 출력
    return False

# ----------------------------------------------------------------------
# 테스트용 API 엔드포인트
# ----------------------------------------------------------------------
@app.route('/')
def home():
    return "Goods Sales and Resale System API is Running!"


# 기존 '/' 라우트 아래에 추가

@app.route('/api/db-check')
def db_check():
    """ 웹 브라우저에서 DB 연결 상태를 확인하는 라우트 """
    if check_db_connection():
        # 연결 성공 시
        return jsonify({
            "status": "success",
            "message": "데이터베이스 연결이 정상적으로 확인되었습니다.",
            "db_info": {
                "user": "db2025",
                "database": "project2025"
            }
        }), 200
    else:
        # 연결 실패 시
        return jsonify({
            "status": "failure",
            "message": "데이터베이스 연결에 실패했습니다. (HOST, PORT, USER, PASSWORD, 권한 확인 필요)",
            "error_detail": "DB 연결 오류 로그를 콘솔에서 확인하세요."
        }), 500


# ... (나머지 기존 라우팅 코드)


# 테스트용 API 엔드포인트


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
            #세션에 사용자 정보 저장
            session['user_id'] = user_info['user_id']
            session['user_name'] = user_info['name']
            session['user_role'] = user_info['role']
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

# 로그아웃 기능
@app.route('/api/logout', methods=['POST'])
def logout_user():
    session.pop('user_id', None)
    session.pop('user_name', None)
    session.pop('user_role', None)
    return jsonify({"message": "로그아웃되었습니다."}), 200
#세션 확인
@app.route('/api/check_session', methods=['GET'])
def check_session():
    if 'user_id' in session:
        return jsonify({
            "logged_in": True,
            "user_id": session['user_id'],
            "user_name": session['user_name'],
            "user_role": session['user_role']
        }), 200
    else:
        return jsonify({"logged_in": False}), 200

# 상품 등록
@app.route('/api/product_register', methods=['POST'])
def product_register():
    data = request.json

    # 1. 필수 데이터 추출
    if 'user_id' not in session or 'user_role' not in session:
        return jsonify({"error": "로그인이 필요합니다."}), 401

    seller_id = session.get('user_id')
    seller_role = session.get('user_role')
    product_name = data.get('product_name')
    category = data.get('category')
    price = data.get('price')
    stock = data.get('stock')

    # 2. 선택적/역할별 데이터 추출
    description = data.get('description')
    master_image_url = data.get('master_image_url')  # Product 마스터 이미지
    listing_status = data.get('listing_status', '판매중')  # 기본값 '판매중'
    condition = data.get('condition')  # Reseller 필수

    # Reseller 전용
    resale_images = data.get('resale_images', [])  # 리셀러 실물 사진 (list)
    is_auction = data.get('is_auction', False)
    auction_start_price = data.get('auction_start_price')
    auction_start_date = data.get('auction_start_date')
    auction_end_date = data.get('auction_end_date')

    # 3. 유효성 검증
    if not all([seller_id, seller_role, product_name, category, price, stock]):
        return jsonify({"error": "필수 상품 정보(판매자ID, 역할, 상품명, 카테고리, 가격, 재고)가 누락되었습니다."}), 400

    if seller_role not in ['PrimarySeller', 'Reseller']:
        return jsonify({"error": "상품 등록 권한이 없는 역할입니다."}), 403

    listing_type = None
    if seller_role == 'PrimarySeller':
        listing_type = 'Primary'
        if is_auction:
            return jsonify({"error": "1차 판매자는 경매를 등록할 수 없습니다."}), 400

    elif seller_role == 'Reseller':
        listing_type = 'Resale'
        if not condition:
            return jsonify({"error": "2차 판매자는 상품 상태(condition)를 필수로 입력해야 합니다."}), 400
        if is_auction and not all([auction_start_price, auction_start_date, auction_end_date]):
            return jsonify({"error": "경매 등록 시 시작가, 시작일, 종료일이 모두 필요합니다."}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "데이터베이스 연결 실패"}), 500

    conn.autocommit = False

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # 4. (트랜잭션)
        # Step 1: Product 테이블 확인 및 등록
        # 1차/2차 판매자 모두 동일 이름, 동일 카테고리 상품은 Product 마스터에 1개만 존재하도록 처리
        cur.execute(
            "SELECT product_id FROM Product WHERE name = %s AND category = %s",
            (product_name, category)
        )
        existing_product = cur.fetchone()

        product_id = None
        if existing_product:
            product_id = existing_product[0]
            # (선택) 1차 판매자가 기존 상품 정보를 업데이트하는 로직 추가 가능
            if seller_role == 'PrimarySeller' and (description or master_image_url):
                cur.execute(
                    """
                    UPDATE Product 
                    SET 
                        description = COALESCE(%s, description), 
                        image_url = COALESCE(%s, image_url)
                    WHERE product_id = %s
                    """,
                    (description, master_image_url, product_id)
                )
        else:
            # 새 상품 마스터 등록
            cur.execute(
                """
                INSERT INTO Product (name, category, description, image_url) 
                VALUES (%s, %s, %s, %s) 
                RETURNING product_id
                """,
                (product_name, category, description, master_image_url)
            )
            product_id = cur.fetchone()[0] #상품 번호 부여

        # Step 1.5: (Reseller Auction) 경매 등록 조건 검증
        if seller_role == 'Reseller' and is_auction:
            # 1. 상품 등급(Rating) B 이상 (S, A, B)인지 확인
            cur.execute("SELECT rating FROM Product WHERE product_id = %s", (product_id,))
            product_rating_row = cur.fetchone()
            product_rating = product_rating_row[0] if product_rating_row else None

            if product_rating not in ('S', 'A', 'B'):
                conn.rollback()
                return jsonify({"error": f"경매 등록 실패: 상품 등급({product_rating})이 B등급 이상(S, A, B)이어야 합니다."}), 403

            # 2. 동일 상품의 1차 판매자가 '판매중'/'경매' 상태가 아닌지 확인
            cur.execute(
                """
                SELECT 1 FROM Listing
                WHERE product_id = %s
                  AND listing_type = 'Primary'
                  AND status IN ('판매중', '경매 예정', '경매 중')
                """,
                (product_id,)
            )
            if cur.fetchone():
                conn.rollback()
                return jsonify({"error": "경매 등록 실패: 해당 상품의 1차 판매자가 여전히 판매/경매 중입니다."}), 403

        # Step 2: Listing 테이블 등록
        cur.execute(
            """
            INSERT INTO Listing (product_id, seller_id, listing_type, price, stock, status, condition) 
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING listing_id
            """,
            (product_id, seller_id, listing_type, price, stock, listing_status, condition)
        )
        listing_id = cur.fetchone()[0]

        # Step 3: (Reseller) ListingImage 등록
        if seller_role == 'Reseller' and resale_images:
            for i, img_url in enumerate(resale_images):
                is_main = (i == 0)  # 첫 번째 이미지를 메인 이미지로 설정
                cur.execute(
                    "INSERT INTO ListingImage (listing_id, image_url, is_main) VALUES (%s, %s, %s)",
                    (listing_id, img_url, is_main)
                )

        # Step 4: (Reseller) Auction 등록
        if seller_role == 'Reseller' and is_auction:
            # Auction 테이블에 최고 입찰자 ID(current_highest_bidder_id)를 포함하여 INSERT
            cur.execute(
                """
                INSERT INTO Auction (listing_id, start_price, current_price, start_date, end_date, current_highest_bidder_id)
                VALUES (%s, %s, %s, %s, %s, NULL)
                """,
                (listing_id, auction_start_price, auction_start_price, auction_start_date, auction_end_date)
            )

            if listing_status not in ['경매 예정', '경매 중']:
                # 현재 시간에 따른 상태 변경
                cur.execute("SELECT NOW() > %s::timestamp", (auction_end_date,))
                is_ended = cur.fetchone()[0]
                cur.execute("SELECT NOW() < %s::timestamp", (auction_start_date,))
                is_scheduled = cur.fetchone()[0]

                new_status = '판매중'  # 기본값

                if is_ended:
                    # 등록 시점부터 이미 종료된 경매는 '판매 종료'로 처리
                    new_status = '판매 종료'
                elif is_scheduled:
                    new_status = '경매 예정'
                else:
                    # 현재 시간이 시작일과 종료일 사이
                    new_status = '경매 중'

                if listing_status != new_status:
                    cur.execute(
                        "UPDATE Listing SET status = %s WHERE listing_id = %s",
                        (new_status, listing_id)
                    )
                    # 만약 '판매 종료'로 바로 상태가 변경되면 재고도 0으로 변경
                    if new_status == '판매 종료':
                        cur.execute(
                            "UPDATE Listing SET stock = 0 WHERE listing_id = %s",
                            (listing_id,)
                        )

        # 5. 모든 작업 성공 시 커밋
        conn.commit()
        return jsonify({
            "message": "상품 등록에 성공했습니다.",
            "product_id": product_id,
            "listing_id": listing_id,
            "listing_type": listing_type
        }), 201

    except Exception as e:
        # 6. 오류 발생 시 롤백
        conn.rollback()
        return jsonify({"error": f"상품 등록 트랜잭션 실패: {str(e)}"}), 500
    finally:
        cur.close()
        conn.close()


# 경매 입찰 기능
@app.route('/api/auction/bid', methods=['POST'])
def auction_bid():
    data = request.json
    auction_id = data.get('auction_id')

    if 'user_id' not in session or session.get('user_role') != 'Buyer':
        return jsonify({"error": "구매자로 로그인해야 입찰할 수 있습니다."}), 401
    buyer_id = data.get('buyer_id')
    bid_price = data.get('bid_price')

    if not all([auction_id, buyer_id, bid_price]):
        return jsonify({"error": "경매ID, 입찰가가 모두 필요합니다."}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "데이터베이스 연결 실패"}), 500

    conn.autocommit = False #트랜잭션 시작
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        # 1. 현재 경매 상태 및 가격 확인 (FOR UPDATE로 레코드 잠금)
        cur.execute(
            """
            SELECT A.current_price, A.start_date, A.end_date, L.status
            FROM Auction A
            JOIN Listing L ON A.listing_id = L.listing_id
            WHERE A.auction_id = %s
            FOR UPDATE 
            """,
            (auction_id,)
        )
        auction_info = cur.fetchone()

        if not auction_info:
            conn.rollback()
            return jsonify({"error": "존재하지 않는 경매입니다."}), 404

        # 2. 경매 상태 검증
        if auction_info['status'] != '경매 중':
            conn.rollback()
            return jsonify({"error": f"현재 '경매 중' 상태가 아닙니다. (현재 상태: {auction_info['status']})"}), 403

        # 3. 시간 검증
        cur.execute("SELECT NOW()")
        now = cur.fetchone()[0]
        if not (auction_info['start_date'] <= now <= auction_info['end_date']):
            conn.rollback()
            return jsonify({"error": "경매 시간이 종료되었습니다."}), 403

        # 4. 입찰 가격 검증
        if bid_price <= auction_info['current_price']:
            conn.rollback()
            return jsonify({"error": f"입찰가는 현재 최고가({auction_info['current_price']})보다 높아야 합니다."}), 400

        # 5. 입찰 기록 (AuctionBid)
        cur.execute(
            "INSERT INTO AuctionBid (auction_id, buyer_id, bid_price, bid_time) VALUES (%s, %s, %s, NOW())",
            (auction_id, buyer_id, bid_price)
        )

        # 6. 경매 정보 업데이트 (Auction)
        cur.execute(
            "UPDATE Auction SET current_price = %s, current_highest_bidder_id = %s WHERE auction_id = %s",
            (bid_price, buyer_id, auction_id)
        )

        conn.commit()
        return jsonify({"message": "입찰에 성공했습니다.", "new_price": bid_price, "bidder_id": buyer_id}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": f"입찰 처리 중 오류 발생: {str(e)}"}), 500
    finally:
        cur.close()
        conn.close()


#  경매 종료 및 자동 주문 기능
@app.route('/api/auction/finalize', methods=['POST'])
def finalize_auction():
    data = request.json
    auction_id = data.get('auction_id')

    if not auction_id:
        return jsonify({"error": "경매ID가 필요합니다."}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "데이터베이스 연결 실패"}), 500

    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        # 1. 경매 정보 및 최고 입찰자 확인 (FOR UPDATE로 레코드 잠금)
        cur.execute(
            """
            SELECT A.listing_id, A.current_price, A.current_highest_bidder_id, A.end_date, L.status
            FROM Auction A
            JOIN Listing L ON A.listing_id = L.listing_id
            WHERE A.auction_id = %s
            FOR UPDATE
            """,
            (auction_id,)
        )
        auction_info = cur.fetchone()

        if not auction_info:
            conn.rollback()
            return jsonify({"error": "존재하지 않는 경매입니다."}), 404

        listing_id = auction_info['listing_id']

        # 2. 경매 종료 시간 확인
        cur.execute("SELECT NOW()")
        now = cur.fetchone()[0]

        if now <= auction_info['end_date'] and auction_info['status'] != '판매 종료':
            conn.rollback()
            return jsonify({"error": "아직 경매가 종료되지 않았습니다."}), 400

        # 3. 이미 처리된 경매인지 확인
        if auction_info['status'] == '판매 종료':
            conn.rollback()
            # 이미 '판매 종료' 상태라면, 추가 작업 없이 성공 메시지 반환
            return jsonify({"message": "이미 처리가 완료된 경매입니다."}), 200

        winner_id = auction_info['current_highest_bidder_id']
        final_price = auction_info['current_price']

        # 4. Listing 상태 '판매 종료'로 변경
        cur.execute(
            "UPDATE Listing SET status = '판매 종료', stock = 0 WHERE listing_id = %s",
            (listing_id,)
        )

        # 5. 최고 입찰자가 있는 경우, Orderb 테이블에 자동 추가
        if winner_id:
            cur.execute(
                """
                INSERT INTO Orderb (buyer_id, listing_id, quantity, total_price, status)
                VALUES (%s, %s, 1, %s, '상품 준비중')
                RETURNING order_id
                """,
                (winner_id, listing_id, final_price)
            )
            order_id = cur.fetchone()[0]
            conn.commit()
            return jsonify({
                "message": "경매가 종료되었습니다. 최고 입찰자에게 주문이 자동 생성되었습니다.",
                "auction_id": auction_id,
                "winner_id": winner_id,
                "final_price": final_price,
                "order_id": order_id
            }), 200
        else:
            # 유찰된 경우 (입찰자가 없음)
            conn.commit()
            return jsonify({
                "message": "경매가 종료되었습니다. (입찰자 없음)",
                "auction_id": auction_id,
                "status": "판매 종료"
            }), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": f"경매 종료 처리 중 오류 발생: {str(e)}"}), 500
    finally:
        cur.close()
        conn.close()

#상품 조회
@app.route('/api/products', methods=['GET'])
def get_products():
    # 1. URL 쿼리 파라미터에서 필터값 가져오기
    category = request.args.get('category')
    search_term = request.args.get('search')
    listing_type = request.args.get('type') # 'Primary' or 'Resale'
    seller_name = request.args.get('seller') # 판매자 이름 (V_All_Products.seller_name)
    min_price = request.args.get('min_price')
    max_price = request.args.get('max_price')
    listing_status = request.args.get('status') # '판매중', '경매 중', '경매 예정', '품절'

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "데이터베이스 연결 실패"}), 500

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # 2. 기본 SQL 쿼리 (V_All_Products 뷰 사용)
        # V_All_Products 뷰는 이미 '판매 종료'를 제외함
        sql_query = "SELECT * FROM V_All_Products"

        conditions = []
        params = []

        # 3. 동적으로 WHERE 조건 추가
        if category:
            conditions.append("category = %s")
            params.append(category)

        if search_term:
            # product_name (상품명)에서 검색
            conditions.append("product_name LIKE %s")
            params.append(f"%{search_term}%")  # %는 SQL의 와일드카드

        if listing_type:
            conditions.append("listing_type = %s")
            params.append(listing_type)

        if seller_name:
            # 판매자 이름(seller_name)에서 LIKE 검색
            conditions.append("seller_name LIKE %s")
            params.append(f"%{seller_name}%")

        if min_price:
            try:
                # 가격 비교 (크거나 같음)
                conditions.append("price >= %s")
                params.append(int(min_price))
            except ValueError:
                pass  # 숫자가 아니면 무시

        if max_price:
            try:
                # 가격 비교 (작거나 같음)
                conditions.append("price <= %s")
                params.append(int(max_price))
            except ValueError:
                pass  # 숫자가 아니면 무시

        if listing_status:
            conditions.append("listing_status = %s")
            params.append(listing_status)

        # 4. 조건 조합
        if conditions:
            sql_query += " WHERE " + " AND ".join(conditions)

        # 5. 최신순 정렬
        sql_query += " ORDER BY listing_id DESC"

        cur.execute(sql_query, tuple(params))
        products_raw = cur.fetchall()

        # 6. JSON으로 변환 가능한 딕셔너리 리스트로 변경
        products = [dict(product) for product in products_raw]

        cur.close()
        conn.close()

        return jsonify(products), 200

    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"error": f"상품 조회 중 오류 발생: {str(e)}"}), 500


if __name__ == '__main__':
    # 디버그 모드를 켜고 실행
    app.run(debug=True)