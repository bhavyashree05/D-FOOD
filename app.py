import os
import sqlite3
import base64
from datetime import datetime

from flask import Flask, render_template, request, redirect, session

try:
    import telepot
except ImportError:  # pragma: no cover - optional dependency
    telepot = None

app = Flask(__name__)
app.secret_key = "dfood-secret-key"
app.config['DEBUG'] = True
app.config['PROPAGATE_EXCEPTIONS'] = True


def get_db_connection():
    try:
        conn = sqlite3.connect("users.db", timeout=30)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        app.logger.error("Database connection failed: %s", e)
        return None


def init_db():
    conn = get_db_connection()
    if conn is None:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recievers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                password TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected'))
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS doners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                password TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected'))
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS food_donations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                food_name TEXT NOT NULL,
                quantity TEXT NOT NULL,
                expiry_date TEXT NOT NULL,
                category TEXT NOT NULL,
                pickup_location TEXT NOT NULL,
                phone TEXT NOT NULL,
                image TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS food_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                donor_name TEXT NOT NULL,
                receiver_name TEXT NOT NULL,
                food_name TEXT NOT NULL,
                quantity TEXT NOT NULL,
                request_status TEXT NOT NULL DEFAULT 'pending',
                request_date TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                category TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_read INTEGER DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS request_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        for table_name, column_name, column_def in [
            ("recievers", "status", "TEXT NOT NULL DEFAULT 'pending'"),
            ("doners", "status", "TEXT NOT NULL DEFAULT 'pending'"),
            ("recievers", "phone", "TEXT"),
            ("recievers", "address", "TEXT"),
            ("recievers", "photo", "TEXT"),
            ("recievers", "created_at", "TEXT"),
            ("doners", "phone", "TEXT"),
            ("doners", "address", "TEXT"),
            ("doners", "photo", "TEXT"),
            ("doners", "created_at", "TEXT"),
            ("food_donations", "donor_name", "TEXT"),
            ("food_donations", "created_at", "TEXT"),
            ("food_donations", "pickup_address", "TEXT"),
            ("food_requests", "pickup_address", "TEXT"),
            ("food_requests", "created_at", "TEXT"),
        ]:
            try:
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")
            except sqlite3.OperationalError:
                pass
        conn.commit()
    finally:
        conn.close()


init_db()


def safe_count(cursor, table_name):
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        result = cursor.fetchone()
        return int(result[0] or 0)
    except sqlite3.Error:
        return 0


def add_notification(title, message, category):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO notifications (title, message, category, created_at, is_read) VALUES (?, ?, ?, ?, 0)",
            (title, message, category, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
    finally:
        if conn is not None:
            conn.close()


def add_history(request_id, action, message):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO request_history (request_id, action, message, created_at) VALUES (?, ?, ?, ?)",
            (request_id, action, message, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
    finally:
        if conn is not None:
            conn.close()


def insert_food_request(donor_name, receiver_name, food_name, quantity, request_date, request_status='pending', pickup_address=''):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO food_requests (donor_name, receiver_name, food_name, quantity, request_status, request_date, pickup_address, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (donor_name, receiver_name, food_name, quantity, request_status, request_date, pickup_address, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
    finally:
        if conn is not None:
            conn.close()


def get_receiver_requests(receiver_name):
    conn = get_db_connection()
    try:
        if conn is None:
            return []
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, donor_name, receiver_name, food_name, quantity, request_status, request_date, pickup_address, created_at FROM food_requests WHERE receiver_name = ? ORDER BY id DESC",
            (receiver_name,),
        )
        return cursor.fetchall()
    finally:
        if conn is not None:
            conn.close()


@app.route('/')
def home():
    total_donors = 0
    total_receivers = 0
    total_donations = 0
    conn = get_db_connection()
    try:
        if conn is not None:
            cursor = conn.cursor()
            total_donors = safe_count(cursor, 'doners')
            total_receivers = safe_count(cursor, 'recievers')
            total_donations = safe_count(cursor, 'food_donations')
    finally:
        if conn is not None:
            conn.close()

    return render_template(
        'home.html',
        total_donors=total_donors,
        total_receivers=total_receivers,
        total_donations=total_donations,
        total_meals=total_donations,
    )


@app.route('/rsignup', methods=['GET', 'POST'])
def rsignup():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        phone = request.form.get('phone', '').strip()
        address = request.form.get('address', '').strip()

        if not name or not email or not password:
            return render_template('rsignup.html', msg="Please provide your full details.")

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO recievers (name, email, password, status, phone, address, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, email, password, 'pending', phone, address, datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
            )
            conn.commit()
        finally:
            if conn is not None:
                conn.close()
        add_notification('New Receiver Registered', f'{name} joined the D-FOOD platform.', 'receiver')
        return render_template('rsignin.html', msg="Signup successful. Your account is pending admin approval.")

    return render_template('rsignup.html')


@app.route('/rsignin', methods=['GET', 'POST'])
def rsignin():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM recievers WHERE email = ? AND password = ? AND status='approved'", (email, password))
            user = cursor.fetchone()
            if user:
                session['user_id'] = user[0]
                session['user_name'] = user[1]
                session['user_type'] = 'receiver'
                session['admin'] = False
                cursor.execute("SELECT * FROM food_donations ORDER BY id DESC")
                books = cursor.fetchall()
                my_requests = get_receiver_requests(user[1])
                return render_template('books.html', books=books, my_requests=my_requests, msg="Welcome back! Your request status is shown below.")
            return render_template('rsignin.html', msg="Invalid email or password, or your account is waiting for admin approval.")
        finally:
            if conn is not None:
                conn.close()

    return render_template('rsignin.html')


@app.route('/dsignup', methods=['GET', 'POST'])
def dsignup():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        phone = request.form.get('phone', '').strip()
        address = request.form.get('address', '').strip()

        if not name or not email or not password:
            return render_template('dsignup.html', msg="Please provide your full details.")

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO doners (name, email, password, status, phone, address, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, email, password, 'pending', phone, address, datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
            )
            conn.commit()
        finally:
            if conn is not None:
                conn.close()
        add_notification('New Donor Registered', f'{name} joined as a donor on D-FOOD.', 'donor')
        return render_template('dsignin.html', msg="Signup successful. Your account is pending admin approval.")

    return render_template('dsignup.html')


@app.route('/dsignin', methods=['GET', 'POST'])
def dsignin():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM doners WHERE email = ? AND password = ? AND status='approved'", (email, password))
            user = cursor.fetchone()
            if user:
                session['user_id'] = user[0]
                session['user_name'] = user[1]
                session['user_type'] = 'donor'
                session['admin'] = False
                return render_template('upload.html', user_name=user[1])
            return render_template('dsignin.html', msg="Invalid email or password, or your account is waiting for admin approval.")
        finally:
            if conn is not None:
                conn.close()

    return render_template('dsignin.html')


@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        food_name = request.form.get('food_name', '').strip()
        quantity = request.form.get('quantity', '').strip()
        expiry_date = request.form.get('expiry_date', '').strip()
        category = request.form.get('category', '').strip()
        pickup_location = request.form.get('pickup_location', '').strip()
        phone = request.form.get('phone', '').strip()
        donor_name = request.form.get('donor_name', session.get('user_name', '')).strip()
        image_file = request.files.get('image')

        if image_file and image_file.filename:
            file_content = image_file.read()
            encoded_image = base64.b64encode(file_content).decode('utf-8')
        else:
            encoded_image = ''

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO food_donations (food_name, quantity, expiry_date, category, pickup_location, phone, image, donor_name, created_at, pickup_address) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (food_name, quantity, expiry_date, category, pickup_location, phone, encoded_image, donor_name, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), pickup_location),
            )
            conn.commit()
        finally:
            if conn is not None:
                conn.close()
        add_notification('New Donation Posted', f'{donor_name} donated {food_name}.', 'donation')
        return render_template('upload.html', msg="Donation submitted successfully.", user_name=donor_name)

    return render_template('upload.html', user_name=session.get('user_name', ''))


@app.route('/booklist')
def booklist():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM food_donations ORDER BY id DESC")
        books = cursor.fetchall()
    finally:
        if conn is not None:
            conn.close()
    return render_template('booklist.html', books=books)


@app.route('/delete_food/<int:id>')
def delete_food(id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM food_donations WHERE id = ?", (id,))
        conn.commit()
    finally:
        if conn is not None:
            conn.close()
    return redirect('/booklist')


@app.route('/Request/<Id>')
def Request(Id):
    if 'user_name' not in session:
        return redirect('/rsignin')

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM food_donations WHERE id = ?", (int(Id),))
        donation = cursor.fetchone()
        if donation:
            donor_name = donation['donor_name'] or 'Unknown Donor'
            receiver_name = session.get('user_name', 'Receiver')
            pickup_address = donation['pickup_location'] or donation['pickup_address'] or ''
            insert_food_request(donor_name, receiver_name, donation['food_name'], donation['quantity'], datetime.now().strftime('%Y-%m-%d'), 'pending', pickup_address)
            add_notification('New Food Request', f'{receiver_name} requested {donation["food_name"]}.', 'request')
            if telepot is not None:
                try:
                    bot = telepot.Bot("7596004372:AAGYOS-oLmFRNfI7ZqI3H4kLucPlbDpfrV4")
                    chat_id = "1225809407"
                    msg = f"{receiver_name} requested food donation: {donation['food_name']}"
                    bot.sendMessage(chat_id, str(msg))
                except Exception:
                    app.logger.error("Telegram notification failed")
        cursor.execute("SELECT * FROM food_donations ORDER BY id DESC")
        books = cursor.fetchall()
        my_requests = get_receiver_requests(session['user_name'])
    finally:
        if conn is not None:
            conn.close()
    return render_template('books.html', books=books, my_requests=my_requests, msg="Food request submitted. Pending Approval.")


@app.route('/approve_donor/<int:donor_id>')
def approve_donor(donor_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE doners SET status = 'approved' WHERE id = ?", (donor_id,))
        conn.commit()
    finally:
        if conn is not None:
            conn.close()
    add_notification('Donor Approved', f'Donor #{donor_id} was approved.', 'approval')
    session['admin_message'] = f'Donor #{donor_id} approved successfully.'
    session['admin_message_type'] = 'success'
    return redirect('/admin_dashboard')


@app.route('/reject_donor/<int:donor_id>')
def reject_donor(donor_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE doners SET status = 'rejected' WHERE id = ?", (donor_id,))
        conn.commit()
    finally:
        if conn is not None:
            conn.close()
    add_notification('Donor Rejected', f'Donor #{donor_id} was rejected.', 'rejection')
    session['admin_message'] = f'Donor #{donor_id} rejected.'
    session['admin_message_type'] = 'danger'
    return redirect('/admin_dashboard')


@app.route('/approve_receiver/<int:receiver_id>')
def approve_receiver(receiver_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE recievers SET status = 'approved' WHERE id = ?", (receiver_id,))
        conn.commit()
    finally:
        if conn is not None:
            conn.close()
    add_notification('Receiver Approved', f'Receiver #{receiver_id} was approved.', 'approval')
    session['admin_message'] = f'Receiver #{receiver_id} approved successfully.'
    session['admin_message_type'] = 'success'
    return redirect('/admin_dashboard')


@app.route('/reject_receiver/<int:receiver_id>')
def reject_receiver(receiver_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE recievers SET status = 'rejected' WHERE id = ?", (receiver_id,))
        conn.commit()
    finally:
        if conn is not None:
            conn.close()
    add_notification('Receiver Rejected', f'Receiver #{receiver_id} was rejected.', 'rejection')
    session['admin_message'] = f'Receiver #{receiver_id} rejected.'
    session['admin_message_type'] = 'danger'
    return redirect('/admin_dashboard')


@app.route('/approve_request/<int:request_id>')
def approve_request(request_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE food_requests SET request_status = 'approved' WHERE id = ?", (request_id,))
        conn.commit()
    finally:
        if conn is not None:
            conn.close()
    add_notification('Request Approved', f'Request #{request_id} was approved.', 'approval')
    add_history(request_id, 'approved', 'Request approved by admin')
    session['admin_message'] = f'Request #{request_id} approved successfully.'
    session['admin_message_type'] = 'success'
    return redirect('/admin_dashboard')


@app.route('/reject_request/<int:request_id>')
def reject_request(request_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE food_requests SET request_status = 'rejected' WHERE id = ?", (request_id,))
        conn.commit()
    finally:
        if conn is not None:
            conn.close()
    add_notification('Request Rejected', f'Request #{request_id} was rejected.', 'rejection')
    add_history(request_id, 'rejected', 'Request rejected by admin')
    session['admin_message'] = f'Request #{request_id} rejected.'
    session['admin_message_type'] = 'danger'
    return redirect('/admin_dashboard')


@app.route('/complete_request/<int:request_id>')
def complete_request(request_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE food_requests SET request_status = 'completed' WHERE id = ?", (request_id,))
        conn.commit()
    finally:
        if conn is not None:
            conn.close()
    add_notification('Delivery Completed', f'Request #{request_id} was completed.', 'delivery')
    add_history(request_id, 'completed', 'Delivery completed successfully')
    session['admin_message'] = f'Request #{request_id} marked as completed.'
    session['admin_message_type'] = 'success'
    return redirect('/admin_dashboard')


@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if username == 'admin' and password == 'admin123':
            session['admin'] = True
            session['user_name'] = 'Admin'
            return redirect('/admin_dashboard')
        return render_template('admin.html', msg='Invalid credentials')
    return render_template('admin.html')


@app.route('/admin_dashboard')
def admin_dashboard():
    if not session.get('admin'):
        return redirect('/admin')

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        search = request.args.get('search', '').strip()
        status_filter = request.args.get('status', '').strip()
        date_filter = request.args.get('date', '').strip()
        category_filter = request.args.get('category', '').strip()
        location_filter = request.args.get('location', '').strip()

        donor_query = "SELECT * FROM doners"
        donor_params = []
        donor_conditions = []
        if search:
            donor_conditions.append("(name LIKE ? OR email LIKE ? OR CAST(id AS TEXT) LIKE ?)")
            donor_params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])
        if status_filter:
            donor_conditions.append("status = ?")
            donor_params.append(status_filter)
        if donor_conditions:
            donor_query += " WHERE " + " AND ".join(donor_conditions)
        donor_query += " ORDER BY id DESC"
        donor_rows = cursor.execute(donor_query, donor_params).fetchall()

        receiver_query = "SELECT * FROM recievers"
        receiver_params = []
        receiver_conditions = []
        if search:
            receiver_conditions.append("(name LIKE ? OR email LIKE ? OR CAST(id AS TEXT) LIKE ?)")
            receiver_params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])
        if status_filter:
            receiver_conditions.append("status = ?")
            receiver_params.append(status_filter)
        if receiver_conditions:
            receiver_query += " WHERE " + " AND ".join(receiver_conditions)
        receiver_query += " ORDER BY id DESC"
        receiver_rows = cursor.execute(receiver_query, receiver_params).fetchall()

        donation_query = "SELECT * FROM food_donations"
        donation_params = []
        donation_conditions = []
        if search:
            donation_conditions.append("(food_name LIKE ? OR category LIKE ? OR pickup_location LIKE ? OR CAST(id AS TEXT) LIKE ?)")
            donation_params.extend([f'%{search}%', f'%{search}%', f'%{search}%', f'%{search}%'])
        if date_filter:
            donation_conditions.append("created_at LIKE ?")
            donation_params.append(f'%{date_filter}%')
        if category_filter:
            donation_conditions.append("category = ?")
            donation_params.append(category_filter)
        if location_filter:
            donation_conditions.append("pickup_location LIKE ?")
            donation_params.append(f'%{location_filter}%')
        if donation_conditions:
            donation_query += " WHERE " + " AND ".join(donation_conditions)
        donation_query += " ORDER BY id DESC"
        donation_rows = cursor.execute(donation_query, donation_params).fetchall()

        request_query = "SELECT * FROM food_requests"
        request_params = []
        request_conditions = []
        if search:
            request_conditions.append("(donor_name LIKE ? OR receiver_name LIKE ? OR food_name LIKE ? OR CAST(id AS TEXT) LIKE ?)")
            request_params.extend([f'%{search}%', f'%{search}%', f'%{search}%', f'%{search}%'])
        if status_filter:
            request_conditions.append("request_status = ?")
            request_params.append(status_filter)
        if date_filter:
            request_conditions.append("request_date = ?")
            request_params.append(date_filter)
        if location_filter:
            request_conditions.append("pickup_address LIKE ?")
            request_params.append(f'%{location_filter}%')
        if request_conditions:
            request_query += " WHERE " + " AND ".join(request_conditions)
        request_query += " ORDER BY id DESC"
        request_rows = cursor.execute(request_query, request_params).fetchall()

        pending_requests = cursor.execute("SELECT COUNT(*) FROM food_requests WHERE request_status = 'pending'").fetchone()[0]
        approved_requests = cursor.execute("SELECT COUNT(*) FROM food_requests WHERE request_status = 'approved'").fetchone()[0]
        completed_deliveries = cursor.execute("SELECT COUNT(*) FROM food_requests WHERE request_status = 'completed'").fetchone()[0]
        rejected_requests = cursor.execute("SELECT COUNT(*) FROM food_requests WHERE request_status = 'rejected'").fetchone()[0]
        notifications = cursor.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT 8").fetchall()

        request_table = []
        for row in request_rows:
            receiver = cursor.execute("SELECT * FROM recievers WHERE name = ? LIMIT 1", (row['receiver_name'],)).fetchone()
            request_table.append({
                'id': row['id'],
                'donor_name': row['donor_name'],
                'receiver_name': row['receiver_name'],
                'receiver_email': receiver['email'] if receiver else '-',
                'receiver_phone': receiver['phone'] if receiver else '-',
                'receiver_address': receiver['address'] if receiver else '-',
                'food_name': row['food_name'],
                'quantity': row['quantity'],
                'request_status': row['request_status'],
                'request_date': row['request_date'] or row['created_at'] or '-',
                'pickup_address': row['pickup_address'] or '-',
            })

        admin_message = session.pop('admin_message', '')
        admin_message_type = session.pop('admin_message_type', 'info')
    finally:
        if conn is not None:
            conn.close()

    return render_template(
        'admin_dashboard.html',
        donors=donor_rows,
        receivers=receiver_rows,
        donations=donation_rows,
        food_requests=request_table,
        pending_donors=[row for row in donor_rows if row['status'] == 'pending'],
        approved_donors=[row for row in donor_rows if row['status'] == 'approved'],
        pending_receivers=[row for row in receiver_rows if row['status'] == 'pending'],
        approved_receivers=[row for row in receiver_rows if row['status'] == 'approved'],
        total_donors=len(donor_rows),
        total_receivers=len(receiver_rows),
        total_donations=len(donation_rows),
        pending_requests=pending_requests,
        approved_requests=approved_requests,
        completed_deliveries=completed_deliveries,
        rejected_requests=rejected_requests,
        notifications=notifications,
        search=search,
        status_filter=status_filter,
        date_filter=date_filter,
        category_filter=category_filter,
        location_filter=location_filter,
        admin_message=admin_message,
        admin_message_type=admin_message_type,
    )


@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect('/rsignin')
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        if session.get('user_type') == 'donor':
            user = cursor.execute("SELECT * FROM doners WHERE id = ?", (session['user_id'],)).fetchone()
            history = cursor.execute("SELECT * FROM food_requests WHERE donor_name = ? ORDER BY id DESC", (session.get('user_name', ''),)).fetchall()
        else:
            user = cursor.execute("SELECT * FROM recievers WHERE id = ?", (session['user_id'],)).fetchone()
            history = cursor.execute("SELECT * FROM food_requests WHERE receiver_name = ? ORDER BY id DESC", (session.get('user_name', ''),)).fetchall()
    finally:
        if conn is not None:
            conn.close()
    return render_template('profile.html', user=user, user_type=session.get('user_type'), history=history)


@app.route('/profile/update', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return redirect('/rsignin')

    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '').strip()
    phone = request.form.get('phone', '').strip()
    address = request.form.get('address', '').strip()
    image_file = request.files.get('photo')

    if image_file and image_file.filename:
        photo_data = base64.b64encode(image_file.read()).decode('utf-8')
    else:
        photo_data = None

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        if session.get('user_type') == 'donor':
            if photo_data:
                cursor.execute("UPDATE doners SET name = ?, email = ?, password = ?, phone = ?, address = ?, photo = ? WHERE id = ?", (name, email, password or None, phone, address, photo_data, session['user_id']))
            else:
                cursor.execute("UPDATE doners SET name = ?, email = ?, password = ?, phone = ?, address = ? WHERE id = ?", (name, email, password or None, phone, address, session['user_id']))
        else:
            if photo_data:
                cursor.execute("UPDATE recievers SET name = ?, email = ?, password = ?, phone = ?, address = ?, photo = ? WHERE id = ?", (name, email, password or None, phone, address, photo_data, session['user_id']))
            else:
                cursor.execute("UPDATE recievers SET name = ?, email = ?, password = ?, phone = ?, address = ? WHERE id = ?", (name, email, password or None, phone, address, session['user_id']))
        conn.commit()
    finally:
        if conn is not None:
            conn.close()
    return redirect('/profile')


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


@app.route('/reports')
def reports():
    if not session.get('admin'):
        return redirect('/admin')
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        daily = cursor.execute("SELECT COUNT(*) FROM food_requests WHERE request_date = ?", (datetime.now().strftime('%Y-%m-%d'),)).fetchone()[0]
        weekly = cursor.execute("SELECT COUNT(*) FROM food_requests WHERE request_date >= ?", (datetime.now().strftime('%Y-%m-%d'),)).fetchone()[0]
        monthly = cursor.execute("SELECT COUNT(*) FROM food_requests WHERE request_date LIKE ?", (datetime.now().strftime('%Y-%m') + '%',)).fetchone()[0]
        donation_count = cursor.execute("SELECT COUNT(*) FROM food_donations").fetchone()[0]
        receiver_count = cursor.execute("SELECT COUNT(*) FROM recievers").fetchone()[0]
    finally:
        if conn is not None:
            conn.close()
    return render_template('reports.html', daily=daily, weekly=weekly, monthly=monthly, donation_count=donation_count, receiver_count=receiver_count)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

