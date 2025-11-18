from flask import Flask, jsonify, request, render_template, session, redirect, url_for
import psycopg2
from psycopg2 import extras
import os
import datetime
from decimal import Decimal

app = Flask(__name__)

# --- 세션 사용을 위한 secret_key 설정 ---
app.secret_key = os.urandom(24)

# --- 임시 관리자 인증 번호 ---
ADMIN_AUTH_CODE = "ADMIN4567"


#  DB 접속 설정 함수
def get_db_connection():
    try:
        conn = psycopg2.connect(
            host="127.0.0.1",
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


# DB 연결 상태를 확인하는 함수
def check_db_connection():
    conn = get_db_connection()
    if conn:
        try:
            conn.close()
            return True
        except Exception as e:
            print(f"DB 연결 테스트 중 오류 발생: {e}")
            return False
    return False


def format_datetime(value, format='%Y-%m-%d %H:%M:%S'):
    """ datetime 객체를 지정된 포맷의 문자열로 변환하는 필터 """
    if value is None:
        return ""
    if isinstance(value, datetime.datetime):
        # 파이썬 datetime 객체일 경우 포맷팅
        return value.strftime(format)
    # 문자열 등 다른 타입일 경우 그대로 반환
    return str(value)


# Flask 앱에 필터 등록
app.jinja_env.filters['datetime_format'] = format_datetime


def format_number(value):
    """ 숫자를 천 단위 쉼표로 포맷팅하는 필터 """
    if value is None:
        return "0"
    try:
        # Python의 내장 format 함수를 사용하여 쉼표 포맷팅을 적용
        return "{:,.0f}".format(float(value))
    except (ValueError, TypeError):
        # 숫자가 아닌 경우 그대로 반환
        return str(value)


# Flask 앱에 필터 등록
app.jinja_env.filters['number_format'] = format_number


# DB에서 상품을 조회하는 공통 함수
# app.py 파일 내 get_products_from_db 함수

# DB에서 상품을 조회하는 공통 함수
def get_products_from_db(category=None, search_term=None, auction_only=False, sort_by='latest'):
    conn = get_db_connection()
    if conn is None:
        return [], 0

    products = []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        sql_query = "SELECT * FROM V_All_Products"
        conditions = []
        params = []

        # 2. 동적 WHERE 조건 추가 및 조합 (유지)
        if category:
            conditions.append("category = %s")
            params.append(category)
        if search_term:
            conditions.append("product_name LIKE %s")
            params.append(f"%{search_term}%")

        # 경매 전용 필터: L.status가 경매 중/예정이거나 L.status가 '판매 종료'인 경우를 포함합니다.
        if auction_only:
            # 여기서 '판매 종료'는 경매 마감으로 인해 이미 업데이트된 상태를 포함합니다.
            conditions.append("listing_type = 'Resale' AND listing_status IN ('경매 중', '경매 예정', '판매 종료')")

        if conditions:
            sql_query += " WHERE " + " AND ".join(conditions)


        #정렬 로직 추가: sort_by 값에 따라 ORDER BY 절을 동적으로 변경
        if sort_by == 'low_price':
            order_clause = " ORDER BY price ASC"
        elif sort_by == 'high_price':
            order_clause = " ORDER BY price DESC"
        elif sort_by == 'rating':
            # 굿즈 등급(product_rating) 순으로 정렬 (S > A > B...)
            order_clause = " ORDER BY product_rating DESC NULLS LAST, listing_id DESC"
        else :
            order_clause = " ORDER BY listing_id DESC"  # 기본: 최신 등록순
        sql_query += order_clause

        cur.execute(sql_query, tuple(params))
        products_raw = cur.fetchall()
        products = [dict(product) for product in products_raw]


        cur.close()
        conn.close()

    except Exception as e:
        if conn:
            conn.close()
        print(f"상품 조회 중 오류 발생: {str(e)}")

    return products, len(products)


# 사용자 정보 가져오는 함수
def get_user_profile_data(user_id, role):
    conn = get_db_connection()
    if conn is None:
        return None

    user_profile = {'user': {'id': user_id, 'role': role}}
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        # 1. Users 테이블에서 이름 조회 (세션에 이름이 없는 경우 대비)
        cur.execute("SELECT name, role FROM Users WHERE user_id = %s", (user_id,))
        user_data = cur.fetchone()
        if user_data:
            user_profile['user']['name'] = user_data['name']
            user_profile['user']['role'] = user_data['role']  # 혹시 세션과 다를 경우 갱신

        # 2. 역할별 상세 프로필 조회
        if role == 'Buyer':
            cur.execute("SELECT address FROM BuyerProfile WHERE user_id = %s", (user_id,))
            user_profile['buyer_profile'] = dict(cur.fetchone()) if cur.rowcount > 0 else {}
        elif role in ['PrimarySeller', 'Reseller']:
            cur.execute("SELECT store_name, grade FROM SellerProfile WHERE user_id = %s", (user_id,))
            user_profile['seller_profile'] = dict(cur.fetchone()) if cur.rowcount > 0 else {}
        else:  # Administrator
            user_profile['admin_profile'] = {}  # 관리자는 특별 프로필 정보 없음

        cur.close()
        conn.close()
        return user_profile

    except Exception as e:
        if conn:
            conn.close()
        print(f"마이페이지 프로필 조회 중 오류 발생: {str(e)}")
        return None


# 주문 목록 조회 함수 (구매자 전용)
def get_orders_for_buyer(user_id):
    conn = get_db_connection()
    if conn is None:
        return [], 0
    orders = []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
                    SELECT O.order_id,
                           O.quantity,
                           O.total_price,
                           O.order_date,
                           O.status,
                           V.product_name,
                           V.seller_name,
                           V.image_url,
                           V.listing_id
                    FROM orderb O,
                         v_all_products V
                    WHERE O.buyer_id = %s
                      and O.listing_id = V.listing_id
                    ORDER BY O.order_date DESC;
                    """, (user_id,))
        orders = [dict(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return orders
    except Exception as e:
        if conn:
            conn.close()
        print(f"주문/배송 내역 조회 중 오류 발생: {str(e)}")
        return []  # 오류 시 빈 리스트 반환


# ---  판매자 주문/판매 내역 조회 함수 (Seller 전용) ---
def get_sales_for_seller(user_id):
    conn = get_db_connection()
    if conn is None:
        return []

    sales_orders = []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        # 해당 판매자(user_id)가 등록한 listing_id를 통해 들어온 주문을 조회
        cur.execute("""
                    SELECT O.order_id,
                           O.quantity,
                           O.total_price,
                           O.order_date,
                           O.status,
                           V.product_name,
                           V.seller_name,
                           V.image_url,
                           V.listing_id,
                           U.name     AS buyer_name,
                           U.user_uid AS buyer_uid,
                           B.address  as address
                    FROM orderb O
                             JOIN v_all_products V ON O.listing_id = V.listing_id
                             JOIN Listing L ON O.listing_id = L.listing_id
                             JOIN Users U ON O.buyer_id = U.user_id -- 구매자 정보 조회용
                             Join buyerprofile B on O.buyer_id = B.user_id
                    WHERE L.seller_id = %s
                    ORDER BY O.order_date DESC;
                    """, (user_id,))

        sales_orders = [dict(row) for row in cur.fetchall()]

        cur.close()
        conn.close()
        return sales_orders

    except Exception as e:
        if conn:
            conn.close()
        print(f"판매자 주문 내역 조회 중 오류 발생: {str(e)}")
        return []


def get_my_products_list(user_id):
    conn = get_db_connection()
    if conn is None:
        return []

    my_products = []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT 
                V.listing_id,
                V.product_id,
                V.product_name, 
                V.category,
                V.image_url,
                V.price,
                V.stock,
                V.listing_status,
                V.condition
            FROM listing L, v_all_products V  
            WHERE L.listing_id = V.listing_id and L.seller_id = %s
            """, (user_id,))

        my_products = [dict(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return my_products
    except Exception as e:
        if conn:
            conn.close()
        print(f"판매자 판매 상품 조회 중 오류 발생: {str(e)}")
        return []


# 장바구니 수량 계산 함수
def calculate_cart_count(user_id):
    """ 현재 사용자의 장바구니에 담긴 총 상품 개수를 계산합니다. """
    if not user_id:
        return 0

    conn = get_db_connection()
    if conn is None:
        return 0

    try:
        cur = conn.cursor()
        # ShoppingCart 테이블에서 해당 buyer_id의 quantity 합계를 조회
        cur.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM ShoppingCart WHERE buyer_id = %s",
            (user_id,)
        )
        total_items = cur.fetchone()[0]
        cur.close()
        return total_items
    except Exception as e:
        print(f"장바구니 수량 계산 오류: {e}")
        return 0
    finally:
        if conn:
            conn.close()


# 2. 모든 요청 전에 실행되는 함수 등록 (Flask의 before_request 사용)
@app.before_request
def load_user_data_to_session():
    # 사용자 ID가 세션에 있을 경우에만 실행
    if 'user_id' in session and session['user_role'] == 'Buyer':
        # 장바구니 수량을 계산하여 세션에 저장
        session['cart_count'] = calculate_cart_count(session['user_id'])
    else:
        # 비구매자 또는 비로그인 상태는 0으로 초기화
        session['cart_count'] = 0

    # Jinja2 템플릿에서 session 객체에 직접 접근하도록 설정
    # (이미 되어 있을 가능성이 높지만, 명시적으로 해줍니다.)
    from flask import g
    g.session = session  # 모든 템플릿에서 session을 사용할 수 있도록 보장 (선택적)


# 페이지 렌더링 라우터 (HTML)

# --- 메인 페이지 (전체 상품) ---
@app.route('/')
def show_main_page():
    # 정렬 기준 가져오기
    sort_by = request.args.get('sort_by', 'latest')

    # '전체 상품'을 조회
    products, product_count = get_products_from_db(sort_by=sort_by)

    return render_template(
        'index.html',
        products=products,
        product_count=product_count,
        page_title="전체 상품",
        sort_by=sort_by
    )


# --- 카테고리별 상품 페이지 ---
@app.route('/category/<category_name>')
def show_category_page(category_name):
    # 정렬 기준 가져오기
    sort_by = request.args.get('sort_by', 'latest')

    # '카테고리'로 필터링하여 상품 조회
    products, product_count = get_products_from_db(category=category_name, sort_by=sort_by)

    return render_template(
        'index.html',
        products=products,
        product_count=product_count,
        page_title=f"{category_name} 상품",
        sort_by=sort_by
    )


# --- 상품 상세 페이지 ---
@app.route('/product/<int:listing_id>')
def show_product_detail(listing_id):
    conn = get_db_connection()
    if conn is None:
        return render_template('product_detail.html', product=None, listing_id=listing_id)

    product = None
    listing = None
    seller = None
    resale_images = []
    auction = None  # ✨ 경매 변수 초기화 ✨
    is_auction_ended = False  # 경매 완료 확인

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # 1. Listing 및 Product 정보 조회 (기존 쿼리 유지)
        cur.execute(
            """
            SELECT L.listing_id,
                   L.product_id,
                   L.seller_id,
                   L.listing_type,
                   L.price,
                   L.stock,
                   L.status,
                   L.condition,
                   P.name   AS product_name,
                   P.category,
                   P.description,
                   P.rating,
                   P.image_url,
                   U.name   AS seller_name,
                   SP.store_name,
                   SP.grade AS seller_grade
            FROM Listing L
                     JOIN Product P ON L.product_id = P.product_id
                     JOIN SellerProfile SP ON L.seller_id = SP.user_id
                     JOIN Users U ON SP.user_id = U.user_id
            WHERE L.listing_id = %s
            """,
            (listing_id,)
        )
        data = cur.fetchone()

        if data:
            # 데이터 구조화 (product, listing, seller) 유지...
            product = {
                'id': data['product_id'],
                'name': data['product_name'],
                'category': data['category'],
                'description': data['description'],
                'rating': data['rating'],
                'image_url': data['image_url']
            }
            listing = {
                'listing_id': data['listing_id'],
                'listing_type': data['listing_type'],
                'price': data['price'],
                'stock': data['stock'],
                'status': data['status'],
                'condition': data['condition']
            }
            seller = {
                'seller_id': data['seller_id'],
                'seller_name': data['seller_name'],
                'store_name': data['store_name'],
                'seller_grade': data['seller_grade']
            }

            # 2. 2차 판매자(Resale)일 경우 실물 이미지 조회 (유지)
            if data['listing_type'] == 'Resale':
                cur.execute(
                    "SELECT image_url, is_main FROM ListingImage WHERE listing_id = %s ORDER BY is_main DESC, image_id ASC",
                    (listing_id,)
                )
                resale_images = [dict(row) for row in cur.fetchall()]

            # 3. ✨ 경매 상품일 경우 Auction 정보 조회 추가 ✨
            if data['status'] in ['경매 중', '경매 예정']:
                cur.execute(
                    """
                    SELECT auction_id,
                           start_price,
                           current_price,
                           start_date,
                           end_date,
                           current_highest_bidder_id
                    FROM Auction
                    WHERE listing_id = %s
                    """,
                    (listing_id,)
                )
                auction_data = cur.fetchone()

                if auction_data:
                    # 조회된 결과를 auction 변수에 딕셔너리로 담습니다.
                    auction = dict(auction_data)

                    # 최고 입찰자 이름 조회 (선택 사항: 템플릿에서 bidder_name 사용 시)
                    if auction['current_highest_bidder_id']:
                        cur.execute(
                            "SELECT name FROM Users WHERE user_id = %s",
                            (auction['current_highest_bidder_id'],)
                        )
                        bidder_info = cur.fetchone()
                        if bidder_info:
                            auction['highest_bidder_name'] = bidder_info['name']
                    else:
                        auction['highest_bidder_name'] = None

                    # ⚠️ 현재 시간이 마감 시간을 초과했는지 DB에서 확인합니다.
                    cur.execute("SELECT NOW() AT TIME ZONE 'KST' > %s", (auction['end_date'],))
                    is_auction_ended = cur.fetchone()[0]

                    if is_auction_ended and listing['status'] != '판매 종료':
                        # 4. 경매가 종료되었지만 DB 상태가 '판매 종료'가 아닌 경우
                        cur.execute("UPDATE Listing SET status = '판매 종료', stock = 0 WHERE listing_id = %s",
                                    (listing_id,))
                        conn.commit()  # ✨ DB 변경사항을 영구히 저장합니다. ✨
                        # 템플릿 렌더링을 위해 상태를 임시로 변경
                        listing['status'] = '판매 종료'

        cur.close()
        conn.close()

        return render_template(
            'product_detail.html',
            product=product,
            listing=listing,
            seller=seller,
            resale_images=resale_images,
            auction=auction,  # ✨ 조회한 auction 데이터를 템플릿에 전달합니다. ✨
            is_auction_ended=is_auction_ended,
            listing_id=listing_id
        )

    except Exception as e:
        # ... (오류 처리 유지) ...
        if conn:
            conn.close()
        print(f"상품 상세 조회 중 오류 발생: {str(e)}")
        return render_template('product_detail.html', product=None, listing_id=listing_id)


# 장바구니 페이지
@app.route('/cart')
def show_shopping_cart():
    # 1. 로그인 확인 (장바구니는 로그인 필수)
    if 'user_id' not in session:
        return redirect(url_for('show_login_page'))

    buyer_id = session.get('user_id')
    cart_items = []

    conn = get_db_connection()
    if conn is None:
        return render_template('shopping_cart.html', cart_items=[], total_price=0, shipping_fee=0)

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # 2. 장바구니 데이터와 연결된 상품/판매 목록 정보를 한 번에 조회
        cur.execute(
            """
            SELECT SC.cart_id,
                   SC.quantity,
                   L.listing_id,
                   L.price,
                   L.listing_type,
                   L.stock,
                   P.name AS product_name,
                   P.image_url
            FROM ShoppingCart SC
                     JOIN Listing L ON SC.listing_id = L.listing_id
                     JOIN Product P ON L.product_id = P.product_id
            WHERE SC.buyer_id = %s
            ORDER BY SC.cart_id DESC
            """,
            (buyer_id,)
        )
        cart_data = cur.fetchall()

        total_price = 0

        for item in cart_data:
            item_total = item['quantity'] * item['price']
            total_price += item_total

            cart_items.append({
                'cart_id': item['cart_id'],
                'listing_id': item['listing_id'],
                'product_name': item['product_name'],
                'price': item['price'],
                'quantity': item['quantity'],
                'listing_type': item['listing_type'],
                'image_url': item['image_url'],
                'item_total': item_total,
                'max_stock': item['stock']  # 최대 재고 수량
            })

        # 3. 배송비 계산 (예시: 5만원 이상 무료 배송)
        shipping_fee = 3000
        if total_price >= 50000:
            shipping_fee = 0

        final_total = total_price + shipping_fee

        cur.close()
        conn.close()

        return render_template(
            'shopping_cart.html',
            cart_items=cart_items,
            total_price=total_price,
            shipping_fee=shipping_fee,
            final_total=final_total
        )

    except Exception as e:
        if conn:
            conn.close()
        print(f"장바구니 조회 중 오류 발생: {str(e)}")
        return render_template('shopping_cart.html', cart_items=[], total_price=0, shipping_fee=0)


# --- 상품 검색 라우터 ---
@app.route('/search')
def search_products():
    search_query = request.args.get('query')
    sort_by = request.args.get('sort_by', 'latest')

    # '검색어'로 필터링하여 상품 조회
    products, product_count = get_products_from_db(search_term=search_query, sort_by=sort_by)

    return render_template(
        'index.html',
        products=products,
        product_count=product_count,
        page_title=f"'{search_query}' 검색 결과",
        sort_by=sort_by
    )


# --- 로그인 페이지 ---
@app.route('/login', methods=['GET'])
def show_login_page():
    return render_template('login.html')


# --- 회원가입 페이지 ---
@app.route('/signup', methods=['GET'])
def show_signup_page():
    return render_template('signup.html')


# --- 상품 등록 페이지 ---
# base.html의 링크 주소 '/seller/listing'과 맞춤
@app.route('/seller/listing', methods=['GET'])
def show_product_register_page():
    if 'user_id' not in session:
        return redirect(url_for('show_login_page'))

    if session.get('user_role') not in ['PrimarySeller', 'Reseller']:
        return "상품 등록 권한이 없습니다.", 403

    return render_template('seller_listing.html')

# --- 경매/리셀 페이지 ---
@app.route('/resale/auction')
def show_auction_page():
    sort_by = request.args.get('sort_by', 'latest')

    # '경매 중' 또는 '경매 예정' 상품만 조회
    products, product_count = get_products_from_db(auction_only=True, sort_by=sort_by)

    return render_template(
        'index.html',
        products=products,
        product_count=product_count,
        page_title="🔥 경매 / 리셀 상품",
        sort_by=sort_by  #  템플릿에 전달하여 선택 상태 유지
    )


# 로그아웃 페이지
@app.route('/logout', methods=['GET'])
def logout_user():
    session.pop('user_id', None)
    session.pop('user_name', None)
    session.pop('user_role', None)
    # 로그아웃 후 로그인 페이지로 이동
    return redirect(url_for('show_login_page'))


# 마이 페이지
@app.route('/mypage', methods=['GET'])
def show_mypage():
    # 로그인 여부 확인
    if 'user_id' not in session:
        return redirect(url_for('show_login_page'))

    user_id = session.get('user_id')
    user_role = session.get('user_role')

    # 쿼리 파라미터에서 현재 보여줄 뷰(view)를 가져옴 (기본값: summary)
    current_view = request.args.get('view', 'summary')

    # DB에서 사용자 역할에 따른 프로필 데이터 조회
    user_profile = get_user_profile_data(user_id, user_role)

    if user_profile is None:
        # DB 연결 실패 또는 데이터 조회 실패 시 임시 오류 처리
        return "마이페이지 데이터 로드에 실패했습니다. DB 연결을 확인해주세요.", 500

    # 뷰(view)에 따라 필요한 추가 데이터 조회
    template_data = {
        "user_profile": user_profile,
        "view": current_view,
        "orders": [],  # 기본값
        "sales_orders": [],  # 기본값
        "my_products": []  # 기본값
    }
    if current_view == 'orders' and user_role == 'Buyer':
        template_data["orders"] = get_orders_for_buyer(user_id)
    elif current_view == 'sales' and user_role in ['PrimarySeller', 'Reseller']:
        template_data["sales_orders"] = get_sales_for_seller(user_id)
    elif current_view == 'my_products' and user_role in ['PrimarySeller', 'Reseller']:
        template_data["my_products"] = get_my_products_list(user_id)
        # 5. 템플릿 렌더링
    return render_template('mypage.html', **template_data)


# ===============================================
# API 라우터 (JSON)
# ===============================================

# --- 회원가입 API ---
@app.route('/api/signup', methods=['POST'])
def signup_user():
    data = request.json
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

    conn.autocommit = False
    try:
        cur = conn.cursor()

        if role == 'Administrator' and admin_code != ADMIN_AUTH_CODE:
            conn.rollback()
            return jsonify({"message": "관리자 인증 번호가 올바르지 않습니다."}), 403

        cur.execute("SELECT user_id FROM Users WHERE user_uid = %s", (user_uid,))
        if cur.fetchone():
            conn.rollback()
            return jsonify({"message": "이미 사용 중인 ID입니다."}), 409

        cur.execute(
            "INSERT INTO Users (user_uid, password, name, role) VALUES (%s, %s, %s, %s) RETURNING user_id",
            (user_uid, password, name, role)
        )
        user_id = cur.fetchone()[0]

        if role == 'Administrator':
            cur.execute("INSERT INTO AdminProfile (user_id) VALUES (%s)", (user_id,))
        elif role in ['PrimarySeller', 'Reseller']:
            cur.execute("INSERT INTO SellerProfile (user_id, store_name, grade) VALUES (%s, %s, NULL)",
                        (user_id, store_name))
        elif role == 'Buyer':
            if not address:
                conn.rollback()
                return jsonify({"message": "구매자는 주소를 입력해야 합니다."}), 400
            cur.execute("INSERT INTO BuyerProfile (user_id, address) VALUES (%s, %s)", (user_id, address))

        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"message": f"{role} 회원가입 성공", "user_id": user_id}), 201

    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({"error": f"회원가입 트랜잭션 실패: {str(e)}"}), 500


# --- 로그인 API ---
@app.route('/api/login', methods=['POST'])
def login_user():
    data = request.json
    user_uid = data.get('user_uid')
    password = data.get('password')

    if not all([user_uid, password]):
        return jsonify({"error": "ID와 비밀번호를 모두 입력해야 합니다."}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "데이터베이스 연결 실패"}), 500

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        sql_query = """
                    SELECT user_id, name, role \
                    FROM Users
                    WHERE user_uid = %s \
                      AND password = %s \
                    """
        cur.execute(sql_query, (user_uid, password))
        user = cur.fetchone()

        cur.close()
        conn.close()

        if user:
            user_info = dict(user)

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


# --- 세션 확인 API (개발 테스트용) ---
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


# --- 상품 등록 API ---
@app.route('/api/product_register', methods=['POST'])
def product_register():
    if 'user_id' not in session:
        return jsonify({"error": "로그인이 필요합니다."}), 401

    seller_id = session.get('user_id')
    seller_role = session.get('user_role')

    if seller_role not in ['PrimarySeller', 'Reseller']:
        return jsonify({"error": "상품 등록 권한이 없는 역할입니다."}), 403

    data = request.json
    product_name = data.get('product_name')
    category = data.get('category')
    price = data.get('price')
    stock = data.get('stock')
    description = data.get('description')
    master_image_url = data.get('master_image_url')
    listing_status = data.get('listing_status', '판매중')
    condition = data.get('condition')
    resale_images = data.get('resale_images', [])
    is_auction = data.get('is_auction', False)
    auction_start_price = data.get('auction_start_price')
    auction_start_date = data.get('auction_start_date')
    auction_end_date = data.get('auction_end_date')

    if not all([product_name, category, price, stock]):
        return jsonify({"error": "필수 상품 정보(상품명, 카테고리, 가격, 재고)가 누락되었습니다."}), 400

    listing_type = 'Primary' if seller_role == 'PrimarySeller' else 'Resale'

    if seller_role == 'PrimarySeller' and is_auction:
        return jsonify({"error": "1차 판매자는 경매를 등록할 수 없습니다."}), 400

    if seller_role == 'Reseller':
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

        cur.execute(
            "SELECT product_id FROM Product WHERE name = %s AND category = %s",
            (product_name, category)
        )
        existing_product = cur.fetchone()

        product_id = None
        if existing_product:
            product_id = existing_product[0]
            if seller_role == 'PrimarySeller' and (description or master_image_url):
                cur.execute(
                    """
                    UPDATE Product
                    SET description = COALESCE(%s, description),
                        image_url   = COALESCE(%s, image_url)
                    WHERE product_id = %s
                    """,
                    (description, master_image_url, product_id)
                )
        else:
            cur.execute(
                """
                INSERT INTO Product (name, category, description, image_url)
                VALUES (%s, %s, %s, %s) RETURNING product_id
                """,
                (product_name, category, description, master_image_url)
            )
            product_id = cur.fetchone()[0]

        if seller_role == 'Reseller' and is_auction:
            cur.execute("SELECT rating FROM Product WHERE product_id = %s", (product_id,))
            product_rating_row = cur.fetchone()
            product_rating = product_rating_row[0] if product_rating_row else None

            if product_rating not in ('S', 'A', 'B'):
                conn.rollback()
                return jsonify({"error": f"경매 등록 실패: 상품 등급({product_rating})이 B등급 이상(S, A, B)이어야 합니다."}), 403

            cur.execute(
                """
                SELECT 1
                FROM Listing
                WHERE product_id = %s
                  AND listing_type = 'Primary'
                  AND status IN ('판매중', '경매 예정', '경매 중')
                """,
                (product_id,)
            )
            if cur.fetchone():
                conn.rollback()
                return jsonify({"error": "경매 등록 실패: 해당 상품의 1차 판매자가 여전히 판매/경매 중입니다."}), 403

        cur.execute(
            """
            INSERT INTO Listing (product_id, seller_id, listing_type, price, stock, status, condition)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING listing_id
            """,
            (product_id, seller_id, listing_type, price, stock, listing_status, condition)
        )
        listing_id = cur.fetchone()[0]

        if seller_role == 'Reseller' and resale_images:
            for i, img_url in enumerate(resale_images):
                is_main = (i == 0)
                cur.execute(
                    "INSERT INTO ListingImage (listing_id, image_url, is_main) VALUES (%s, %s, %s)",
                    (listing_id, img_url, is_main)
                )

        if seller_role == 'Reseller' and is_auction:
            cur.execute(
                """
                INSERT INTO Auction (listing_id, start_price, current_price, start_date, end_date,
                                     current_highest_bidder_id)
                VALUES (%s, %s, %s, %s, %s, NULL)
                """,
                (listing_id, auction_start_price, auction_start_price, auction_start_date, auction_end_date)
            )

            cur.execute("SELECT NOW() > %s::timestamp", (auction_end_date,))
            is_ended = cur.fetchone()[0]
            cur.execute("SELECT NOW() < %s::timestamp", (auction_start_date,))
            is_scheduled = cur.fetchone()[0]

            new_status = '판매중'
            if is_ended:
                new_status = '판매 종료'
            elif is_scheduled:
                new_status = '경매 예정'
            else:
                new_status = '경매 중'

            if listing_status != new_status:
                cur.execute(
                    "UPDATE Listing SET status = %s WHERE listing_id = %s",
                    (new_status, listing_id)
                )
                if new_status == '판매 종료':
                    cur.execute(
                        "UPDATE Listing SET stock = 0 WHERE listing_id = %s",
                        (listing_id,)
                    )

        conn.commit()
        return jsonify({
            "message": "상품 등록에 성공했습니다.",
            "product_id": product_id,
            "listing_id": listing_id,
            "listing_type": listing_type
        }), 201

    except Exception as e:
        conn.rollback()
        return jsonify({"error": f"상품 등록 트랜잭션 실패: {str(e)}"}), 500
    finally:
        cur.close()
        conn.close()


# --- 경매 입찰 API ---
@app.route('/api/auction/bid', methods=['POST'])
def auction_bid():
    data = request.json
    auction_id = data.get('auction_id')

    if 'user_id' not in session or session.get('user_role') != 'Buyer':
        return jsonify({"error": "구매자로 로그인해야 입찰할 수 있습니다."}), 401

    buyer_id = session.get('user_id')
    bid_price = data.get('bid_price')

    if not all([auction_id, bid_price]):
        return jsonify({"error": "경매ID와 입찰가가 모두 필요합니다."}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "데이터베이스 연결 실패"}), 500

    conn.autocommit = False  # 트랜잭션 시작
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        # 1. 현재 경매 상태 및 가격 확인 (FOR UPDATE로 레코드 잠금)
        cur.execute(
            """
            SELECT A.current_price, A.start_date, A.end_date, L.status, L.seller_id
            FROM Auction A
                     JOIN Listing L ON A.listing_id = L.listing_id
            WHERE A.auction_id = %s
                FOR UPDATE
            """,
            (auction_id,)
        )
        auction_info = cur.fetchone()
        current_highest_price = auction_info['current_price']

        if not auction_info:
            conn.rollback()
            return jsonify({"error": "존재하지 않는 경매입니다."}), 404

        # 본인 상품 입찰 금지
        if auction_info['seller_id'] == buyer_id:
            conn.rollback()
            return jsonify({"error": "자신이 등록한 경매에는 입찰할 수 없습니다."}), 403

        # 2. 경매 상태 검증
        if auction_info['status'] != '경매 중':
            conn.rollback()
            return jsonify({"error": f"현재 '경매 중' 상태가 아닙니다. (현재 상태: {auction_info['status']})"}), 403

        # 3. 시간 검증
        # NOW()를 가져와 파이썬에서 비교하는 대신, DB에게 현재 시간이
        # start_date와 end_date 사이에 있는지 물어봅니다.
        cur.execute(
            """
            SELECT (NOW() AT TIME ZONE 'KST' BETWEEN "start_date" AND "end_date")
            FROM Auction
            WHERE auction_id = %s;
            """,
            (auction_id,)
        )
        is_valid_time = cur.fetchone()[0]

        if not is_valid_time:
            conn.rollback()
            return jsonify({"error": "경매 시간이 종료되었거나 시작되지 않았습니다."}), 403

        # 4. 입찰 가격 검증
        if bid_price <= current_highest_price:
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
                VALUES (%s, %s, 1, %s, '상품 준비중') RETURNING order_id
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


# --- 장바구니에 상품 추가 API ---
@app.route('/api/cart/add', methods=['POST'])
def add_to_cart():
    # 1. 로그인 확인
    if 'user_id' not in session or session.get('user_role') != 'Buyer':
        return jsonify({"error": "구매자만 장바구니에 상품을 담을 수 있습니다."}), 401

    data = request.json
    listing_id = data.get('listing_id')
    quantity = data.get('quantity')
    buyer_id = session.get('user_id')
    session['cart_count'] = calculate_cart_count(session['user_id'])

    if not all([listing_id, quantity]) or quantity <= 0:
        return jsonify({"error": "상품 ID와 유효한 수량이 필요합니다."}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "데이터베이스 연결 실패"}), 500

    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        # 1. 재고 및 판매 상태 확인
        cur.execute("SELECT stock, status FROM Listing WHERE listing_id = %s", (listing_id,))
        listing_info = cur.fetchone()

        if not listing_info:
            conn.rollback()
            return jsonify({"error": "존재하지 않는 판매 목록입니다."}), 404

        if listing_info['status'] != '판매중':
            conn.rollback()
            return jsonify({"error": f"현재 판매 중인 상품이 아닙니다. (상태: {listing_info['status']})"}), 400

        if quantity > listing_info['stock']:
            conn.rollback()
            return jsonify({"error": f"요청 수량({quantity})이 재고({listing_info['stock']})를 초과합니다."}), 400

        # 2. 이미 장바구니에 있는 상품인지 확인
        cur.execute(
            "SELECT cart_id, quantity FROM ShoppingCart WHERE buyer_id = %s AND listing_id = %s FOR UPDATE",
            (buyer_id, listing_id)
        )
        cart_item = cur.fetchone()

        if cart_item:
            # 이미 있으면 수량 업데이트
            new_quantity = cart_item['quantity'] + quantity
            cur.execute(
                "UPDATE ShoppingCart SET quantity = %s WHERE cart_id = %s",
                (new_quantity, cart_item['cart_id'])
            )
            message = f"장바구니에 추가되었습니다. (총 수량: {new_quantity})"
        else:
            # 없으면 새로 삽입
            cur.execute(
                "INSERT INTO ShoppingCart (buyer_id, listing_id, quantity) VALUES (%s, %s, %s)",
                (buyer_id, listing_id, quantity)
            )
            message = "장바구니에 새 상품이 담겼습니다."

        conn.commit()
        return jsonify({"message": message}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": f"장바구니 추가 트랜잭션 실패: {str(e)}"}), 500
    finally:
        cur.close()
        conn.close()


# --- 장바구니 수량 변경 API ---
@app.route('/api/cart/update', methods=['POST'])
def update_cart():
    if 'user_id' not in session or session.get('user_role') != 'Buyer':
        return jsonify({"error": "구매자만 장바구니를 수정할 수 있습니다."}), 401

    data = request.json
    cart_items = data.get('items')  # [{'cart_id': 1, 'quantity': 2}, ...]
    buyer_id = session.get('user_id')

    if not cart_items or not isinstance(cart_items, list):
        return jsonify({"error": "유효한 장바구니 항목 목록이 필요합니다."}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "데이터베이스 연결 실패"}), 500

    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        for item in cart_items:
            cart_id = item.get('cart_id')
            quantity = item.get('quantity')

            if not all([cart_id, quantity]) or quantity <= 0:
                conn.rollback()
                return jsonify({"error": "항목 ID와 유효한 수량이 필요합니다."}), 400

            # 1. 장바구니 항목의 소유권 및 재고 확인
            cur.execute(
                """
                SELECT L.stock, L.status, SC.listing_id
                FROM ShoppingCart SC
                         JOIN Listing L ON SC.listing_id = L.listing_id
                WHERE SC.cart_id = %s
                  AND SC.buyer_id = %s
                    FOR UPDATE
                """,
                (cart_id, buyer_id)
            )
            info = cur.fetchone()

            if not info:
                conn.rollback()
                return jsonify({"error": f"장바구니 ID {cart_id}를 찾을 수 없거나 소유권이 없습니다."}), 404

            if info['status'] != '판매중':
                conn.rollback()
                return jsonify({"error": f"상품 상태가 '판매중'이 아닙니다. (ID: {cart_id})"}), 400

            if quantity > info['stock']:
                conn.rollback()
                return jsonify({"error": f"요청 수량({quantity})이 재고({info['stock']})를 초과합니다. (ID: {cart_id})"}), 400

            # 2. 수량 업데이트 실행
            cur.execute(
                "UPDATE ShoppingCart SET quantity = %s WHERE cart_id = %s",
                (quantity, cart_id)
            )

        conn.commit()
        return jsonify({"message": "선택 상품 수량이 성공적으로 업데이트되었습니다."}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": f"장바구니 업데이트 트랜잭션 실패: {str(e)}"}), 500
    finally:
        cur.close()
        conn.close()


# --- 장바구니 항목 삭제 API ---
@app.route('/api/cart/remove', methods=['POST'])
def remove_cart_item():
    data = request.json
    cart_ids = data.get('cart_ids')  # [1, 5, 8]
    buyer_id = session.get('user_id')

    if not cart_ids or not isinstance(cart_ids, list):
        return jsonify({"error": "유효한 장바구니 ID 목록이 필요합니다."}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "데이터베이스 연결 실패"}), 500

    conn.autocommit = False
    cur = conn.cursor()

    try:
        # IN 연산자를 사용하여 한 번에 여러 항목 삭제 (소유권 검증 포함)
        cur.execute(
            """
            DELETE
            FROM ShoppingCart
            WHERE cart_id IN %s
              AND buyer_id = %s
            """,
            (tuple(cart_ids), buyer_id)
        )

        deleted_count = cur.rowcount
        conn.commit()

        if deleted_count == 0:
            return jsonify({"message": "삭제할 항목을 찾을 수 없거나 소유권이 없습니다."}), 404

        return jsonify({"message": f"{deleted_count}개 상품이 장바구니에서 삭제되었습니다."}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": f"장바구니 삭제 트랜잭션 실패: {str(e)}"}), 500
    finally:
        cur.close()
        conn.close()


# --- 주문 생성 API (주문 시 재고 검증 및 차감) ---
@app.route('/api/order/place', methods=['POST'])
def place_order():
    if 'user_id' not in session or session.get('user_role') != 'Buyer':
        return jsonify({"error": "로그인이 필요합니다."}), 401

    data = request.json
    items_to_order = data.get('items')  # [{'listing_id': 1, 'quantity': 2}, ...]
    buyer_id = session.get('user_id')

    if not items_to_order or not isinstance(items_to_order, list):
        return jsonify({"error": "유효한 주문 항목 목록이 필요합니다."}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "데이터베이스 연결 실패"}), 500

    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        order_details = []
        total_order_price = Decimal('0.0')

        # 1. 모든 항목에 대해 재고 확인 및 가격 계산 (트랜잭션으로 보호)
        for item in items_to_order:
            listing_id = item.get('listing_id')
            quantity = item.get('quantity')

            if quantity <= 0:
                conn.rollback()
                return jsonify({"error": "유효하지 않은 주문 수량입니다."}), 400

            # 1-1. Listing 정보 잠금 및 재고/가격 확인
            cur.execute(
                "SELECT price, stock, status, seller_id FROM Listing WHERE listing_id = %s FOR UPDATE",
                (listing_id,)
            )
            listing_info = cur.fetchone()

            if not listing_info:
                conn.rollback()
                return jsonify({"error": f"판매 목록 ID {listing_id}를 찾을 수 없습니다."}), 404

            if listing_info['status'] != '판매중':
                conn.rollback()
                return jsonify({"error": f"상품 ID {listing_id}는 현재 판매 중이 아닙니다. (상태: {listing_info['status']})"}), 400

            if quantity > listing_info['stock']:
                conn.rollback()
                return jsonify({"error": f"재고 부족: 상품 ID {listing_id}의 재고({listing_info['stock']})가 부족합니다."}), 400

            # 가격 계산
            unit_price = listing_info['price']
            item_total = unit_price * quantity
            total_order_price += item_total

            # 주문 상세 정보 저장
            order_details.append({
                'listing_id': listing_id,
                'quantity': quantity,
                'item_total': item_total,
                'seller_id': listing_info['seller_id']
            })

            # 1-2. 재고 차감
            new_stock = listing_info['stock'] - quantity
            new_status = '품절' if new_stock == 0 else '판매중'

            cur.execute(
                "UPDATE Listing SET stock = %s, status = %s WHERE listing_id = %s",
                (new_stock, new_status, listing_id)
            )

        # 2. 총 배송비 계산 및 최종 금액 확정
        shipping_fee = Decimal('3000')
        if total_order_price >= Decimal('50000'):
            shipping_fee = Decimal('0')

        final_total = total_order_price + shipping_fee

        # 3. Orderb 테이블에 주문 삽입 (단일 주문으로 처리)
        # 실제로는 여러 리스팅 ID가 하나의 주문 ID를 공유하도록 OrderDetail 테이블을 사용해야 하지만,
        # 여기서는 단순화를 위해 각 리스팅별 주문으로 Orderb에 삽입
        order_ids = []
        for detail in order_details:
            cur.execute(
                """
                INSERT INTO Orderb (buyer_id, listing_id, quantity, total_price, status)
                VALUES (%s, %s, %s, %s, '상품 준비중') RETURNING order_id
                """,
                (buyer_id, detail['listing_id'], detail['quantity'], detail['item_total'])
            )
            order_ids.append(cur.fetchone()[0])

        # 4. 장바구니에서 주문한 항목 제거
        cart_ids = [item.get('cart_id') for item in data.get('items') if item.get('cart_id')]
        if cart_ids:
            cur.execute(
                """
                DELETE
                FROM ShoppingCart
                WHERE cart_id IN %s
                  AND buyer_id = %s
                """,
                (tuple(cart_ids), buyer_id)
            )

        # 5. 모든 작업 커밋
        conn.commit()

        return jsonify({
            "message": f"주문({','.join(map(str, order_ids))})이 성공적으로 접수되었습니다. 최종 결제 금액: {float(final_total):,.0f}원",
            "order_ids": order_ids,
            "total_price": float(final_total)
        }), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": f"주문 처리 트랜잭션 실패: {str(e)}"}), 500
    finally:
        cur.close()
        conn.close()


# --- 주문 상태 변경 API (판매자 전용) ---
@app.route('/api/order/update_status', methods=['POST'])
def update_order_status():
    # 1. 권한 확인
    if 'user_id' not in session or session.get('user_role') not in ['PrimarySeller', 'Reseller']:
        return jsonify({"error": "판매자만 주문 상태를 변경할 수 있습니다."}), 403

    data = request.json
    order_id = data.get('order_id')

    if not order_id:
        return jsonify({"error": "주문 ID가 필요합니다."}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "데이터베이스 연결 실패"}), 500

    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    seller_id = session.get('user_id')

    try:
        # 1. 주문 정보 및 소유권 확인 (Orderb와 Listing 조인하여 판매자 ID 확인)
        cur.execute(
            """
            SELECT O.status, O.order_id
            FROM Orderb O
                     JOIN Listing L ON O.listing_id = L.listing_id
            WHERE O.order_id = %s
              AND L.seller_id = %s
                FOR UPDATE
            """,
            (order_id, seller_id)
        )
        order_info = cur.fetchone()

        if not order_info:
            conn.rollback()
            return jsonify({"error": "주문 ID를 찾을 수 없거나 해당 주문의 판매자가 아닙니다."}), 404

        current_status = order_info['status']
        next_status = None

        # 2. 다음 상태 결정
        if current_status == '상품 준비중':
            next_status = '배송 중'
        elif current_status == '배송 중':
            next_status = '배송 완료'
        elif current_status in ['배송 완료', '환불', '교환']:
            conn.rollback()
            return jsonify({"message": f"주문 상태 '{current_status}'는 더 이상 변경할 수 없습니다."}), 400
        else:
            conn.rollback()
            return jsonify({"error": "알 수 없는 주문 상태입니다."}), 500

        # 3. DB 업데이트
        cur.execute(
            "UPDATE Orderb SET status = %s WHERE order_id = %s",
            (next_status, order_id)
        )

        conn.commit()
        return jsonify({
            "message": f"주문 #{order_id}의 상태가 '{next_status}'로 변경되었습니다.",
            "new_status": next_status
        }), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": f"주문 상태 업데이트 실패: {str(e)}"}), 500
    finally:
        cur.close()
        conn.close()


# --- 회원 정보 수정 API ---
@app.route('/api/mypage/update', methods=['POST'])
def api_update_profile():
    if 'user_id' not in session:
        return jsonify({"error": "로그인이 필요합니다."}), 401

    data = request.json
    user_id = session.get('user_id')
    role = session.get('user_role')

    # 공통 정보
    new_name = data.get('name')
    new_password = data.get('password')  # 실제 환경에서는 해싱 필수!

    # 역할별 정보
    new_address = data.get('address')
    new_store_name = data.get('store_name')

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "데이터베이스 연결 실패"}), 500

    conn.autocommit = False
    cur = conn.cursor()

    try:
        # 1. Users 테이블 업데이트 (이름, 비밀번호)
        update_user_sql = []
        update_user_params = []

        if new_name:
            update_user_sql.append("name = %s")
            update_user_params.append(new_name)
        if new_password:
            update_user_sql.append("password = %s")  # 실제로는 해싱해야 함
            update_user_params.append(new_password)

        if update_user_sql:
            sql = "UPDATE Users SET " + ", ".join(update_user_sql) + " WHERE user_id = %s"
            cur.execute(sql, update_user_params + [user_id])

            # 세션 이름 업데이트
            if new_name:
                session['user_name'] = new_name

        # 2. 역할별 프로필 테이블 업데이트
        if role == 'Buyer' and new_address:
            # BuyerProfile에 주소 업데이트 (INSERT ON CONFLICT UPDATE 로직이 더 안전하지만, 여기서는 UPDATE로 단순화)
            cur.execute("UPDATE BuyerProfile SET address = %s WHERE user_id = %s", (new_address, user_id))

        elif role in ['PrimarySeller', 'Reseller'] and new_store_name:
            # SellerProfile에 상점명 업데이트
            cur.execute("UPDATE SellerProfile SET store_name = %s WHERE user_id = %s", (new_store_name, user_id))

        conn.commit()
        return jsonify({"message": "회원 정보가 성공적으로 업데이트되었습니다."}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": f"정보 수정 트랜잭션 실패: {str(e)}"}), 500
    finally:
        cur.close()
        conn.close()

# 상품 수정 api (seller)
@app.route('/api/seller/product/update', methods=['PUT'])
def update_product_listing():
    if not session.get('user_id') or session.get('user_role') not in ['PrimarySeller', 'Reseller']:
        return jsonify({"error": "판매자 권한이 없습니다."}), 403

    data = request.get_json()
    listing_id = data.get('listing_id')
    product_name = data.get('product_name')
    category = data.get('category')
    price = data.get('price')
    stock = data.get('stock')
    status = data.get('listing_status')
    condition = data.get('condition')  # 2차 판매자만 사용 가능

    # 입력값 검증
    if not product_name or not product_name.strip():
        return jsonify({"error": "상품 이름은 필수이며, 공백만으로 채울 수 없습니다."}), 400

    if not all([listing_id, product_name is not None, category, price is not None, stock is not None, status]):
        return jsonify({"error": "필수 입력 항목이 누락되었습니다."}), 400
    if stock == 0 and status == "판매중":
        return jsonify({
            "success": False,
            "message": "재고가 0이면 '판매중'으로 변경할 수 없습니다."
        })

    try:
        price = int(price)
        stock = int(stock)
        if price < 0 or stock < 0:
            return jsonify({"error": "가격과 재고는 0 이상이어야 합니다."}), 400
    except ValueError:
        return jsonify({"error": "가격과 재고는 유효한 숫자여야 합니다."}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "데이터베이스 연결 오류"}), 500

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        user_id = session['user_id']

        # 1. 해당 Listing이 현재 로그인한 판매자의 상품인지 확인 및 product_id 가져오기
        cur.execute(
            "SELECT product_id, seller_id FROM Listing WHERE listing_id = %s",
            (listing_id,)
        )
        listing_info = cur.fetchone()

        if listing_info is None:
            return jsonify({"error": "해당 상품 목록(Listing)을 찾을 수 없습니다."}), 404

        if listing_info['seller_id'] != user_id:
            return jsonify({"error": "해당 상품에 대한 수정 권한이 없습니다."}), 403

        product_id = listing_info['product_id']

        # 2. Product 테이블 업데이트 (상품명, 카테고리)
        # Note: 실제 서비스에서는 Product 테이블 업데이트 권한 및 로직이 더 복잡할 수 있음.
        cur.execute(
            """
            UPDATE Product SET
                name = %s,
                category = %s
            WHERE product_id = %s
            """,
            (product_name, category, product_id)
        )

        # 3. Listing 테이블 업데이트 (가격, 재고, 판매 상태, 상태)
        # condition이 빈 문자열이면 NULL로 처리
        final_condition = condition if condition else None

        cur.execute(
            """
            UPDATE Listing SET
                price = %s,
                stock = %s,
                status = %s,
                condition = %s
            WHERE listing_id = %s
            """,
            (price, stock, status, final_condition, listing_id)
        )

        conn.commit()
        cur.close()
        return jsonify({"message": f"상품 (Listing ID: {listing_id}) 정보가 성공적으로 업데이트되었습니다."}), 200

    except psycopg2.Error as e:
        conn.rollback()
        print(f"DB Update Error: {e}")
        # ENUM 타입 불일치 등 DB 오류 상세 메시지 반환
        return jsonify({"error": f"데이터베이스 오류: 입력 값이 잘못되었거나 형식에 맞지 않습니다. (자세한 오류: {e.pgcode})"}), 500
    finally:
        if conn:
            conn.close()

# @app.route('/api/admin_rating', methods=['POST'])
# def api_admin_rating():
#     # TODO: 관리자 -> 판매자 굿즈 등급 부여 api
#
# @app.route('/api/admin_disputes', method=['POST'])
# def api_admin_disputes():
#     # TODO: 관리자 -> 구매자와 판매자 사이 분쟁 조정 api
#
# @app.route('/api/admin_seller_eval', method=['POST'])
# def api_admin_seller_eval():
#     #TODO: 관리자 -> 구매자가 올린 판매자 평가 내역 확인 후 승인



if __name__ == '__main__':
    # 디버그 모드를 켜고 실행
    app.run(debug=True)