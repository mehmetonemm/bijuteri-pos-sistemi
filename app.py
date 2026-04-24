from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from functools import wraps
from io import StringIO
from urllib.parse import quote

from flask import (
    Flask,
    Response,
    redirect,
    render_template_string,
    request,
    session,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///retail_crm.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = "retail-crm-secret-v3"

db = SQLAlchemy(app)

TR_TZ = timezone(timedelta(hours=3))


def now_local() -> datetime:
    return datetime.now(TR_TZ).replace(tzinfo=None)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(120), nullable=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now_local)


class Branch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now_local)


class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(20), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now_local)
    total_spent = db.Column(db.Float, nullable=False, default=0)
    visit_count = db.Column(db.Integer, nullable=False, default=0)
    last_visit = db.Column(db.DateTime, nullable=True)


class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    payment_type = db.Column(db.String(20), nullable=False, default="nakit")
    total_amount = db.Column(db.Float, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=now_local)
    is_refund = db.Column(db.Boolean, nullable=False, default=False)
    original_sale_id = db.Column(db.Integer, db.ForeignKey("sale.id"), nullable=True)
    refund_reason = db.Column(db.String(255), nullable=True)

    customer = db.relationship("Customer", backref=db.backref("sales", lazy=True))
    branch = db.relationship("Branch", backref=db.backref("sales", lazy=True))
    user = db.relationship("User", backref=db.backref("sales", lazy=True))
    original_sale = db.relationship("Sale", remote_side=[id], backref=db.backref("refund_rows", lazy=True))


class SaleItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sale.id"), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    sale = db.relationship("Sale", backref=db.backref("items", lazy=True, cascade="all, delete-orphan"))


class CashSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False)
    opened_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    closed_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    opening_cash = db.Column(db.Float, nullable=False, default=0)
    expected_cash = db.Column(db.Float, nullable=True)
    actual_cash = db.Column(db.Float, nullable=True)
    cash_difference = db.Column(db.Float, nullable=True)
    card_total = db.Column(db.Float, nullable=True)
    opened_at = db.Column(db.DateTime, nullable=False, default=now_local)
    closed_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="open")
    notes = db.Column(db.String(255), nullable=True)

    branch = db.relationship("Branch", backref=db.backref("cash_sessions", lazy=True))
    opened_by = db.relationship("User", foreign_keys=[opened_by_id])
    closed_by = db.relationship("User", foreign_keys=[closed_by_id])


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    title = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Float, nullable=False, default=0)
    category = db.Column(db.String(80), nullable=False, default="Genel")
    notes = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now_local)

    branch = db.relationship("Branch", backref=db.backref("expenses", lazy=True))
    user = db.relationship("User", backref=db.backref("expenses", lazy=True))


BASE_HTML = """
<!doctype html>
<html lang="tr">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ title }}</title>
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: Arial, sans-serif;
            background: #f7f4ef;
            margin: 0;
            color: #2c2c2c;
        }
        header {
            background: linear-gradient(135deg, #7d2130, #a63c4e);
            color: white;
            padding: 14px 16px;
            position: sticky;
            top: 0;
            z-index: 10;
            box-shadow: 0 4px 18px rgba(0,0,0,.12);
        }
        .topbar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            flex-wrap: wrap;
        }
        nav {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        nav a {
            color: white;
            text-decoration: none;
            font-weight: bold;
            padding: 8px 10px;
            border-radius: 10px;
            background: rgba(255,255,255,.12);
        }
        .top-info {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }
        .badge {
            padding: 8px 10px;
            border-radius: 999px;
            background: rgba(255,255,255,.12);
            font-size: 13px;
        }
        .container {
            max-width: 1200px;
            margin: 18px auto;
            padding: 0 14px 30px;
        }
        .hero {
            background: linear-gradient(135deg, #7d2130, #b85d39);
            color: white;
            border-radius: 18px;
            padding: 18px;
            margin-bottom: 18px;
            box-shadow: 0 8px 22px rgba(125,33,48,.18);
        }
        .hero h1, .hero p { margin: 0; }
        .hero p { margin-top: 8px; }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 14px;
        }
        .card {
            background: white;
            border-radius: 16px;
            padding: 16px;
            box-shadow: 0 2px 10px rgba(0,0,0,.08);
        }
        .kpi {
            font-size: 28px;
            font-weight: bold;
        }
        .muted {
            color: #666;
            font-size: 14px;
        }
        .sales-grid {
            display: grid;
            grid-template-columns: 1.1fr .9fr;
            gap: 14px;
            align-items: start;
        }
        .category-row, .price-row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
            gap: 10px;
            margin-top: 10px;
        }
        button, input, select, textarea {
            width: 100%;
            padding: 12px;
            border-radius: 12px;
            border: 1px solid #d6d6d6;
            font-size: 15px;
        }
        button {
            border: none;
            cursor: pointer;
            background: #7d2130;
            color: white;
            font-weight: bold;
        }
        button.secondary { background: #4b5563; }
        button.light { background: #eee; color: #222; }
        button.success { background: #0f766e; }
        button.danger { background: #b91c1c; }
        .pill {
            display: inline-block;
            background: #f1ece7;
            padding: 6px 10px;
            border-radius: 999px;
            margin-right: 6px;
            margin-bottom: 6px;
            font-size: 13px;
            text-decoration: none;
            color: #222;
        }
        .cart-row {
            display: flex;
            justify-content: space-between;
            gap: 10px;
            padding: 10px 0;
            border-bottom: 1px solid #eee;
        }
        .section-title { margin-bottom: 8px; }
        .customer-list a {
            display: block;
            padding: 10px 12px;
            border-radius: 12px;
            background: #faf7f2;
            color: #222;
            text-decoration: none;
            margin-bottom: 8px;
            border: 1px solid #eee;
        }
        .alert {
            background: #fff3cd;
            color: #7a5a00;
            padding: 10px 12px;
            border-radius: 12px;
            margin-bottom: 12px;
        }
        .danger-box {
            background: #fee2e2;
            color: #7f1d1d;
            padding: 10px 12px;
            border-radius: 12px;
            margin-bottom: 12px;
        }
        .success-box {
            background: #dcfce7;
            color: #166534;
            padding: 10px 12px;
            border-radius: 12px;
            margin-bottom: 12px;
        }
        .actions-inline {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }
        .actions-inline form,
        .actions-inline a { flex: 1; min-width: 120px; }
        @media (max-width: 820px) {
            .sales-grid { grid-template-columns: 1fr; }
            .container { padding: 0 10px 24px; }
            .card, .hero { border-radius: 16px; padding: 14px; }
            button, input, select, textarea { min-height: 48px; font-size: 16px; }
        }
    </style>
</head>
<body>
<header>
    <div class="topbar">
        <nav>
            <a href="{{ url_for('home') }}">Ana Sayfa</a>
            <a href="{{ url_for('customer_entry') }}">Müşteri Girişi</a>
            <a href="{{ url_for('sales_screen') }}">Satış Ekranı</a>
            <a href="{{ url_for('cash_register') }}">Kasa</a>
            <a href="{{ url_for('expenses_page') }}">Giderler</a>
            <a href="{{ url_for('sales_history') }}">Satış Geçmişi</a>
            <a href="{{ url_for('reports') }}">Raporlar</a>
            <a href="{{ url_for('customers') }}">Müşteriler</a>
            <a href="{{ url_for('campaigns') }}">Kampanya</a>
        </nav>
        <div class="top-info">
            {% if current_user %}
                <div class="badge">Kullanıcı: {{ current_user.display_name }}</div>
            {% endif %}
            {% if current_branch %}
                <div class="badge">Şube: {{ current_branch.name }}</div>
            {% endif %}
            <div class="badge">Saat: {{ current_time }}</div>
            {% if current_user %}
                <a href="{{ url_for('branch_select') }}" style="color:white;text-decoration:none;" class="badge">Şube Seç</a>
                <a href="{{ url_for('logout') }}" style="color:white;text-decoration:none;" class="badge">Çıkış</a>
            {% endif %}
        </div>
    </div>
</header>
<div class="container">{{ content|safe }}</div>
</body>
</html>
"""


def render_page(title: str, content: str):
    return render_template_string(
        BASE_HTML,
        title=title,
        content=content,
        current_user=get_current_user(),
        current_branch=get_current_branch(),
        current_time=now_local().strftime("%H:%M"),
    )


def clean_phone_for_whatsapp(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("0"):
        digits = "9" + digits
    elif digits.startswith("5"):
        digits = "90" + digits
    return digits


def get_current_user() -> User | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    return User.query.get(user_id)


def get_current_branch() -> Branch | None:
    branch_id = session.get("branch_id")
    if not branch_id:
        return None
    return Branch.query.get(branch_id)


def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not get_current_user():
            return redirect(url_for("login"))
        if not get_current_branch() and request.endpoint not in {"branch_select", "logout"}:
            return redirect(url_for("branch_select"))
        return view_func(*args, **kwargs)
    return wrapper


def get_active_cash_session(branch_id: int | None) -> CashSession | None:
    if not branch_id:
        return None
    return CashSession.query.filter_by(branch_id=branch_id, status="open").order_by(CashSession.id.desc()).first()


def get_period_totals(start_dt: datetime, end_dt: datetime, branch_id: int | None):
    query = Sale.query.filter(Sale.created_at >= start_dt, Sale.created_at < end_dt)
    if branch_id:
        query = query.filter(Sale.branch_id == branch_id)
    sales = query.all()
    total = sum(s.total_amount for s in sales)
    cash = sum(s.total_amount for s in sales if s.payment_type == "nakit")
    card = sum(s.total_amount for s in sales if s.payment_type == "kart")
    refunds = sum(s.total_amount for s in sales if s.is_refund)
    customer_count = len({s.customer_id for s in sales if s.customer_id})
    return total, cash, card, len(sales), customer_count, refunds


def get_period_expense_total(start_dt: datetime, end_dt: datetime, branch_id: int | None):
    query = Expense.query.filter(Expense.created_at >= start_dt, Expense.created_at < end_dt)
    if branch_id:
        query = query.filter(Expense.branch_id == branch_id)
    return sum(item.amount for item in query.all())


@app.route("/login", methods=["GET", "POST"])
def login():
    if get_current_user():
        return redirect(url_for("home"))
    message = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session["user_id"] = user.id
            branches = Branch.query.order_by(Branch.name.asc()).all()
            if len(branches) == 1:
                session["branch_id"] = branches[0].id
                return redirect(url_for("home"))
            return redirect(url_for("branch_select"))
        message = "Kullanıcı adı veya şifre yanlış."
    content = f'''
    <div class="hero">
        <h1>Giriş Yap</h1>
        <p>Varsayılan giriş: admin / 123456</p>
    </div>
    {f'<div class="danger-box">{message}</div>' if message else ''}
    <div class="card" style="max-width:520px;margin:0 auto;">
        <form method="post">
            <label>Kullanıcı Adı</label>
            <input type="text" name="username" placeholder="admin" required>
            <label>Şifre</label>
            <input type="password" name="password" placeholder="******" required>
            <button>Giriş Yap</button>
        </form>
    </div>
    '''
    return render_page("Giriş", content)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/branch-select", methods=["GET", "POST"])
@login_required
def branch_select():
    branches = Branch.query.order_by(Branch.name.asc()).all()
    if request.method == "POST":
        branch_id = request.form.get("branch_id", type=int)
        branch = Branch.query.get(branch_id) if branch_id else None
        if branch:
            session["branch_id"] = branch.id
            return redirect(url_for("home"))
    buttons = ""
    for branch in branches:
        buttons += f'''
        <form method="post" style="margin-bottom:10px;">
            <input type="hidden" name="branch_id" value="{branch.id}">
            <button>{branch.name} şubesini seç</button>
        </form>
        '''
    content = f'''
    <div class="hero">
        <h1>Şube Seç</h1>
        <p>Satış, kasa, gider ve raporlar seçili şubeye göre çalışır.</p>
    </div>
    <div class="card" style="max-width:520px;margin:0 auto;">
        {buttons or '<div class="muted">Şube bulunamadı.</div>'}
    </div>
    '''
    return render_page("Şube Seç", content)


@app.route("/")
@login_required
def home():
    branch = get_current_branch()
    if not branch:
        return redirect(url_for("branch_select"))

    now = now_local()
    day_start = datetime(now.year, now.month, now.day)
    week_start = day_start - timedelta(days=day_start.weekday())
    month_start = datetime(now.year, now.month, 1)

    daily_total, daily_cash, daily_card, daily_sales_count, daily_customers, daily_refunds = get_period_totals(day_start, day_start + timedelta(days=1), branch.id)
    weekly_total, _, _, weekly_sales_count, _, _ = get_period_totals(week_start, now + timedelta(days=1), branch.id)
    monthly_total, _, _, monthly_sales_count, _, _ = get_period_totals(month_start, now + timedelta(days=1), branch.id)
    daily_expense = get_period_expense_total(day_start, day_start + timedelta(days=1), branch.id)
    monthly_expense = get_period_expense_total(month_start, now + timedelta(days=1), branch.id)
    total_customers = Customer.query.count()
    active_cash = get_active_cash_session(branch.id)

    cash_box = f'<div class="success-box">Kasa açık • Açılış nakit: {active_cash.opening_cash:.2f} TL • Açılış: {active_cash.opened_at.strftime("%d.%m.%Y %H:%M")}</div>' if active_cash else '<div class="danger-box">Bu şubede açık kasa yok. Satış almadan önce kasayı aç.</div>'

    content = f'''
    <div class="hero">
        <h1>Perakende CRM ve Kasa Sistemi</h1>
        <p>Müşteri kaydı tut, hızlı satış gir, iade işle, günlük gider gir, kasa aç-kapat ve raporları gör.</p>
    </div>
    {cash_box}
    <div class="grid">
        <div class="card"><div class="muted">Bugünkü Ciro</div><div class="kpi">{daily_total:.2f} TL</div></div>
        <div class="card"><div class="muted">Bugünkü Nakit</div><div class="kpi">{daily_cash:.2f} TL</div></div>
        <div class="card"><div class="muted">Bugünkü Kart</div><div class="kpi">{daily_card:.2f} TL</div></div>
        <div class="card"><div class="muted">Bugünkü İşlem</div><div class="kpi">{daily_sales_count}</div></div>
        <div class="card"><div class="muted">Bugünkü Gider</div><div class="kpi">{daily_expense:.2f} TL</div></div>
        <div class="card"><div class="muted">Aylık Gider</div><div class="kpi">{monthly_expense:.2f} TL</div></div>
        <div class="card"><div class="muted">Aylık Ciro</div><div class="kpi">{monthly_total:.2f} TL</div></div>
        <div class="card"><div class="muted">Toplam Müşteri</div><div class="kpi">{total_customers}</div></div>
        <div class="card"><div class="muted">Bugün Kayıtlı Müşteriyle İşlem</div><div class="kpi">{daily_customers}</div></div>
        <div class="card"><div class="muted">Bugünkü İade Etkisi</div><div class="kpi">{daily_refunds:.2f} TL</div></div>
        <div class="card"><div class="muted">Haftalık Ciro</div><div class="kpi">{weekly_total:.2f} TL</div></div>
        <div class="card"><div class="muted">Bu Ay İşlem</div><div class="kpi">{monthly_sales_count}</div></div>
    </div>
    '''
    return render_page("Ana Sayfa", content)


@app.route("/cash-register", methods=["GET", "POST"])
@login_required
def cash_register():
    current_user = get_current_user()
    branch = get_current_branch()
    if not branch:
        return redirect(url_for("branch_select"))
    active_cash = get_active_cash_session(branch.id)
    message = ""

    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "open":
            if active_cash:
                message = "Bu şubede zaten açık kasa var."
            else:
                opening_cash = float(request.form.get("opening_cash", 0) or 0)
                notes = request.form.get("notes", "").strip() or None
                cash_session = CashSession(branch_id=branch.id, opened_by_id=current_user.id, opening_cash=opening_cash, notes=notes)
                db.session.add(cash_session)
                db.session.commit()
                return redirect(url_for("cash_register"))

        if action == "close" and active_cash:
            actual_cash = float(request.form.get("actual_cash", 0) or 0)
            notes = request.form.get("notes", "").strip() or None
            cash_sales = Sale.query.filter(Sale.branch_id == branch.id, Sale.created_at >= active_cash.opened_at, Sale.payment_type == "nakit").all()
            card_sales = Sale.query.filter(Sale.branch_id == branch.id, Sale.created_at >= active_cash.opened_at, Sale.payment_type == "kart").all()
            expense_total = sum(e.amount for e in Expense.query.filter(Expense.branch_id == branch.id, Expense.created_at >= active_cash.opened_at).all())
            cash_movement = sum(s.total_amount for s in cash_sales)
            card_total = sum(s.total_amount for s in card_sales)
            expected_cash = active_cash.opening_cash + cash_movement - expense_total
            difference = actual_cash - expected_cash
            active_cash.expected_cash = expected_cash
            active_cash.actual_cash = actual_cash
            active_cash.cash_difference = difference
            active_cash.card_total = card_total
            active_cash.closed_at = now_local()
            active_cash.closed_by_id = current_user.id
            active_cash.status = "closed"
            active_cash.notes = notes or active_cash.notes
            db.session.commit()
            return redirect(url_for("cash_register"))

    last_sessions = CashSession.query.filter_by(branch_id=branch.id).order_by(CashSession.id.desc()).limit(10).all()
    rows = ""
    for item in last_sessions:
        rows += f'''
        <div class="cart-row">
            <div>
                <strong>{'Açık' if item.status == 'open' else 'Kapalı'} Kasa</strong><br>
                <span class="muted">{item.opened_at.strftime('%d.%m.%Y %H:%M')} • Açılış {item.opening_cash:.2f} TL</span>
            </div>
            <div style="text-align:right;">
                <strong>{(item.expected_cash or 0):.2f} TL</strong><br>
                <span class="muted">Fark: {(item.cash_difference or 0):.2f}</span>
            </div>
        </div>
        '''

    if active_cash:
        open_box = f'''
        <div class="success-box">Açık kasa var. Açılış nakit: {active_cash.opening_cash:.2f} TL</div>
        <div class="card">
            <h3 class="section-title">Kasa Kapat</h3>
            <form method="post">
                <input type="hidden" name="action" value="close">
                <label>Kasadaki gerçek nakit</label>
                <input type="number" step="0.01" name="actual_cash" placeholder="Örn: 2450" required>
                <label>Not</label>
                <textarea name="notes" placeholder="İsteğe bağlı not"></textarea>
                <button class="danger">Kasayı Kapat</button>
            </form>
        </div>
        '''
    else:
        open_box = '''
        <div class="danger-box">Şu an açık kasa yok.</div>
        <div class="card">
            <h3 class="section-title">Kasa Aç</h3>
            <form method="post">
                <input type="hidden" name="action" value="open">
                <label>Açılış nakit</label>
                <input type="number" step="0.01" name="opening_cash" placeholder="Örn: 1000" required>
                <label>Not</label>
                <textarea name="notes" placeholder="İsteğe bağlı not"></textarea>
                <button class="success">Kasayı Aç</button>
            </form>
        </div>
        '''

    content = f'''
    <div class="hero">
        <h1>Kasa Açılış / Kapanış</h1>
        <p>Şube bazlı açılış nakdi gir, gün sonunda gerçek nakdi yazarak farkı otomatik gör. Giderler de hesaba katılır.</p>
    </div>
    {f'<div class="alert">{message}</div>' if message else ''}
    <div class="sales-grid">
        <div>{open_box}</div>
        <div class="card">
            <h3 class="section-title">Son Kasa Oturumları</h3>
            {rows or '<div class="muted">Henüz kasa hareketi yok.</div>'}
        </div>
    </div>
    '''
    return render_page("Kasa", content)


@app.route("/expenses", methods=["GET", "POST"])
@login_required
def expenses_page():
    branch = get_current_branch()
    current_user = get_current_user()
    if not branch:
        return redirect(url_for("branch_select"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        amount = float(request.form.get("amount", 0) or 0)
        category = request.form.get("category", "Genel").strip() or "Genel"
        notes = request.form.get("notes", "").strip() or None
        if title and amount > 0:
            expense = Expense(branch_id=branch.id, user_id=current_user.id if current_user else None, title=title, amount=amount, category=category, notes=notes)
            db.session.add(expense)
            db.session.commit()
            return redirect(url_for("expenses_page"))

    now = now_local()
    day_start = datetime(now.year, now.month, now.day)
    today_expenses = Expense.query.filter(Expense.branch_id == branch.id, Expense.created_at >= day_start).order_by(Expense.created_at.desc()).all()
    daily_total = sum(item.amount for item in today_expenses)

    rows = ""
    for item in today_expenses:
        rows += f'''
        <div class="cart-row">
            <div>
                <strong>{item.title}</strong><br>
                <span class="muted">{item.category} • {item.created_at.strftime('%d.%m.%Y %H:%M')} • {item.user.display_name if item.user else '-'}</span>
            </div>
            <div><strong>{item.amount:.2f} TL</strong></div>
        </div>
        '''

    content = f'''
    <div class="hero">
        <h1>Giderler</h1>
        <p>Gün içinde çay, kargo, yol, personel, paket gibi giderleri gir.</p>
    </div>
    <div class="grid">
        <div class="card"><div class="muted">Bugünkü Gider Toplamı</div><div class="kpi">{daily_total:.2f} TL</div></div>
    </div>
    <div class="sales-grid" style="margin-top:14px;">
        <div class="card">
            <h3 class="section-title">Yeni Gider Ekle</h3>
            <form method="post">
                <label>Gider Başlığı</label>
                <input type="text" name="title" placeholder="Örn: Kargo, çay, yol" required>
                <label>Tutar</label>
                <input type="number" step="0.01" min="0" name="amount" placeholder="Örn: 120" required>
                <label>Kategori</label>
                <select name="category">
                    <option value="Genel">Genel</option>
                    <option value="Kargo">Kargo</option>
                    <option value="Yol">Yol</option>
                    <option value="Personel">Personel</option>
                    <option value="Paket">Paket</option>
                    <option value="Diğer">Diğer</option>
                </select>
                <label>Not</label>
                <textarea name="notes" placeholder="İsteğe bağlı not"></textarea>
                <button class="danger">Gideri Kaydet</button>
            </form>
        </div>
        <div class="card">
            <h3 class="section-title">Bugünkü Giderler</h3>
            {rows or '<div class="muted">Bugün gider girilmedi.</div>'}
        </div>
    </div>
    '''
    return render_page("Giderler", content)


@app.route("/customers")
@login_required
def customers():
    all_customers = Customer.query.order_by(Customer.last_visit.desc().nullslast(), Customer.id.desc()).all()
    rows = ""
    for c in all_customers:
        last_visit = c.last_visit.strftime("%d.%m.%Y %H:%M") if c.last_visit else "-"
        rows += f'''
        <a href="{url_for('customer_detail', customer_id=c.id)}">
            <strong>{c.name or 'İsimsiz Müşteri'}</strong><br>
            <span class="muted">{c.phone} • Toplam: {c.total_spent:.2f} TL • Ziyaret: {c.visit_count} • Son: {last_visit}</span>
        </a>
        '''
    content = f'''
    <div class="hero">
        <h1>Müşteriler</h1>
        <p>Tüm müşteri kayıtları burada listelenir.</p>
    </div>
    <div class="card customer-list">{rows or '<div class="alert">Henüz müşteri kaydı yok.</div>'}</div>
    '''
    return render_page("Müşteriler", content)


@app.route("/customer-entry", methods=["GET", "POST"])
@login_required
def customer_entry():
    message = ""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        if not phone:
            message = "Telefon zorunlu."
        else:
            existing = Customer.query.filter_by(phone=phone).first()
            if existing:
                if name and not existing.name:
                    existing.name = name
                    db.session.commit()
                return redirect(url_for("sales_screen", customer_id=existing.id))
            customer = Customer(name=name or None, phone=phone)
            db.session.add(customer)
            db.session.commit()
            return redirect(url_for("sales_screen", customer_id=customer.id))

    recent_customers = Customer.query.order_by(Customer.id.desc()).limit(8).all()
    recent_html = ""
    for c in recent_customers:
        label = c.name or "İsimsiz Müşteri"
        recent_html += f'<a href="{url_for("sales_screen", customer_id=c.id)}"><strong>{label}</strong><br><span class="muted">{c.phone}</span></a>'

    content = f'''
    <div class="hero">
        <h1>Müşteri Girişi</h1>
        <p>Numarayı yaz, müşteri varsa bulunsun; yoksa saniyeler içinde yeni kayıt açılsın.</p>
    </div>
    {f'<div class="alert">{message}</div>' if message else ''}
    <div class="sales-grid">
        <div class="card">
            <h3 class="section-title">Yeni Müşteri / Var Olan Müşteriyi Aç</h3>
            <form method="post">
                <label>Ad Soyad</label>
                <input type="text" name="name" placeholder="İsteğe bağlı">
                <label>Telefon</label>
                <input type="text" name="phone" placeholder="05xx xxx xx xx" required>
                <button>Müşteriyi Aç ve Satışa Geç</button>
            </form>
        </div>
        <div class="card customer-list">
            <h3 class="section-title">Son Müşteriler</h3>
            {recent_html or '<div class="muted">Henüz kayıt yok.</div>'}
        </div>
    </div>
    '''
    return render_page("Müşteri Girişi", content)


@app.route("/customer/<int:customer_id>")
@login_required
def customer_detail(customer_id: int):
    customer = Customer.query.get_or_404(customer_id)
    wa_message = quote(f"Merhaba {customer.name or ''}, yeni ürünler ve kampanyalarımız için size yazıyoruz 🎁")
    wa_link = f"https://wa.me/{clean_phone_for_whatsapp(customer.phone)}?text={wa_message}"

    sales_html = ""
    branch = get_current_branch()
    customer_sales = Sale.query.filter_by(customer_id=customer.id)
    if branch:
        customer_sales = customer_sales.filter(Sale.branch_id == branch.id)
    for sale in customer_sales.order_by(Sale.created_at.desc()).limit(20).all():
        refund_btn = ""
        if not sale.is_refund and not sale.refund_rows:
            refund_btn = f'''
            <form method="post" action="{url_for('refund_sale', sale_id=sale.id)}">
                <input type="text" name="refund_reason" placeholder="İade nedeni (opsiyonel)">
                <button class="danger">İade Et</button>
            </form>
            '''
        status_label = "İade" if sale.is_refund else "Satış"
        sales_html += f'''
        <div class="card" style="margin-bottom:10px;">
            <div class="cart-row" style="padding-top:0;">
                <div>
                    <strong>{status_label} #{sale.id}</strong><br>
                    <span class="muted">{sale.created_at.strftime('%d.%m.%Y %H:%M')} • {sale.payment_type}</span>
                </div>
                <div><strong>{sale.total_amount:.2f} TL</strong></div>
            </div>
            {refund_btn if refund_btn else '<div class="muted">Bu işlem için tekrar iade açılamaz.</div>'}
        </div>
        '''

    content = f'''
    <div class="hero">
        <h1>{customer.name or 'İsimsiz Müşteri'}</h1>
        <p>{customer.phone}</p>
    </div>
    <div class="grid">
        <div class="card"><div class="muted">Toplam Harcama</div><div class="kpi">{customer.total_spent:.2f} TL</div></div>
        <div class="card"><div class="muted">Ziyaret Sayısı</div><div class="kpi">{customer.visit_count}</div></div>
        <div class="card"><div class="muted">Son Alışveriş</div><div class="kpi" style="font-size:18px;">{customer.last_visit.strftime('%d.%m.%Y %H:%M') if customer.last_visit else '-'}</div></div>
    </div>
    <div class="card" style="margin-top:14px;">
        <h3 class="section-title">Son Satışlar ve İade</h3>
        {sales_html or '<div class="muted">Henüz satış yok.</div>'}
    </div>
    <div class="card" style="margin-top:14px;">
        <a href="{url_for('sales_screen', customer_id=customer.id)}"><button>Bu Müşteri ile Satış Aç</button></a>
        <div style="margin-top:10px;"><a href="{wa_link}" target="_blank"><button class="secondary">WhatsApp Mesaj Gönder</button></a></div>
    </div>
    '''
    return render_page("Müşteri Detayı", content)


@app.route("/sales", methods=["GET"])
@login_required
def sales_screen():
    branch = get_current_branch()
    if not branch:
        return redirect(url_for("branch_select"))
    active_cash = get_active_cash_session(branch.id)
    selected_customer_id = request.args.get("customer_id", type=int)
    selected_customer = Customer.query.get(selected_customer_id) if selected_customer_id else None

    recent_customers = Customer.query.order_by(Customer.last_visit.desc().nullslast(), Customer.id.desc()).limit(10).all()
    customer_pills = "".join([f'<a class="pill" href="{url_for("sales_screen", customer_id=c.id)}">{c.name or c.phone}</a>' for c in recent_customers])

    categories = ["Hediyelik", "Küpe", "Takı", "Oyuncak", "Aksesuar"]
    prices = [5, 10, 20, 50, 100, 200]
    selected_category = request.args.get("category", categories[0])
    if selected_category not in categories:
        selected_category = categories[0]

    cart_entries = request.args.getlist("cart")
    extra_price = request.args.get("extra_price", "").strip()
    if extra_price:
        cart_entries.append(f"{selected_category}:{extra_price}")
    cart_items = []
    total = 0.0
    for entry in cart_entries:
        try:
            category, price = entry.split(":", 1)
            price_val = float(price)
            cart_items.append((category, price_val))
            total += price_val
        except Exception:
            pass

    category_tabs = ""
    for cat in categories:
        button_class = "secondary" if cat != selected_category else ""
        link = url_for("sales_screen", customer_id=selected_customer.id if selected_customer else None, category=cat, cart=[f"{c}:{p}" for c, p in cart_items])
        category_tabs += f'<a href="{link}"><button class="{button_class}" type="button">{cat}</button></a>'

    price_buttons = ""
    for price in prices:
        form_html = f'<form method="get" action="{url_for("sales_screen")}" style="margin:0;">'
        if selected_customer:
            form_html += f'<input type="hidden" name="customer_id" value="{selected_customer.id}">'
        form_html += f'<input type="hidden" name="category" value="{selected_category}">'
        for cat, val in cart_items:
            form_html += f'<input type="hidden" name="cart" value="{cat}:{val}">'
        form_html += f'<input type="hidden" name="cart" value="{selected_category}:{price}">'
        form_html += f'<button type="submit">{price} TL</button></form>'
        price_buttons += form_html

    cart_rows = ""
    for cat, price in cart_items:
        cart_rows += f'<div class="cart-row"><div><strong>{cat}</strong></div><div>{price:.2f} TL</div></div>'

    hidden_cart_inputs = "".join([f'<input type="hidden" name="cart" value="{cat}:{price}">' for cat, price in cart_items])
    active_customer_html = f'<div class="alert"><strong>{selected_customer.name or "İsimsiz Müşteri"}</strong><br>{selected_customer.phone}<br>Toplam Harcama: {selected_customer.total_spent:.2f} TL • Ziyaret: {selected_customer.visit_count}</div>' if selected_customer else '<div class="alert">Seçili müşteri yok. İstersen müşteri olmadan da satış girebilirsin.</div>'
    kasa_warning = '' if active_cash else '<div class="danger-box">Açık kasa yok. Satış tamamlamak için önce kasayı aç.</div>'

    content = f'''
    <div class="hero">
        <h1>Satış Ekranı</h1>
        <p>Kategori seç, fiyat butonlarına basarak toplama ekle, sonra ödeme tipini seçip satışı tamamla.</p>
    </div>
    {kasa_warning}
    <div class="sales-grid">
        <div>
            <div class="card">
                <h3 class="section-title">Aktif Müşteri</h3>
                {active_customer_html}
                <div>{customer_pills}</div>
                <div style="margin-top:10px;"><a href="{url_for('customer_entry')}"><button class="secondary">Yeni / Var Olan Müşteri Aç</button></a></div>
            </div>
            <div class="card" style="margin-top:14px;">
                <h3 class="section-title">Kategori Seç</h3>
                <div class="category-row">{category_tabs}</div>
                <div class="alert" style="margin-top:12px;">Seçili kategori: <strong>{selected_category}</strong></div>
                <h3 class="section-title" style="margin-top:10px;">Fiyat Butonları</h3>
                <div class="price-row">{price_buttons}</div>
                <h3 class="section-title" style="margin-top:14px;">Ekstra Tutar Gir</h3>
                <form method="get" action="{url_for('sales_screen')}">
                    <input type="hidden" name="customer_id" value="{selected_customer.id if selected_customer else ''}">
                    <input type="hidden" name="category" value="{selected_category}">
                    {hidden_cart_inputs}
                    <input type="number" step="0.01" min="0" name="extra_price" placeholder="Örn: 650" required>
                    <button type="submit">Sepete Ekle</button>
                </form>
            </div>
        </div>
        <div>
            <div class="card">
                <h3 class="section-title">Satış Özeti</h3>
                {cart_rows or '<div class="muted">Henüz sepete eklenmiş satış yok.</div>'}
                <div class="cart-row" style="border-bottom:none; margin-top:10px;"><div><strong>Toplam</strong></div><div><strong>{total:.2f} TL</strong></div></div>
                <form method="post" action="{url_for('add_sale')}" style="margin-top:12px;">
                    <input type="hidden" name="customer_id" value="{selected_customer.id if selected_customer else ''}">
                    {hidden_cart_inputs}
                    <label>Ödeme Tipi</label>
                    <select name="payment_type">
                        <option value="nakit">Nakit</option>
                        <option value="kart">Kart</option>
                    </select>
                    <button {'disabled' if (not cart_items or not active_cash) else ''}>Satışı Tamamla</button>
                </form>
                <form method="get" action="{url_for('sales_screen')}" style="margin-top:10px;">
                    <input type="hidden" name="customer_id" value="{selected_customer.id if selected_customer else ''}">
                    <button class="light" type="submit">Sepeti Temizle</button>
                </form>
            </div>
        </div>
    </div>
    '''
    return render_page("Satış Ekranı", content)


@app.route("/sales/add", methods=["POST"])
@login_required
def add_sale():
    branch = get_current_branch()
    current_user = get_current_user()
    if not branch:
        return redirect(url_for("branch_select"))
    active_cash = get_active_cash_session(branch.id)
    if not active_cash:
        return redirect(url_for("cash_register"))

    customer_id = request.form.get("customer_id", type=int)
    cart_entries = request.form.getlist("cart")
    payment_type = request.form.get("payment_type", "").strip().lower()

    items_to_add = []
    for entry in cart_entries:
        try:
            category, price = entry.split(":", 1)
            items_to_add.append((category, float(price)))
        except Exception:
            pass

    total_amount = sum(price for _, price in items_to_add)
    if not items_to_add or total_amount <= 0:
        return redirect(url_for("sales_screen", customer_id=customer_id if customer_id else None))

    sale = Sale(customer_id=customer_id if customer_id else None, branch_id=branch.id, user_id=current_user.id if current_user else None, payment_type=payment_type or "nakit", total_amount=total_amount, is_refund=False)
    db.session.add(sale)
    db.session.flush()

    for category, price in items_to_add:
        db.session.add(SaleItem(sale_id=sale.id, category=category, price=price, quantity=1))

    if customer_id:
        customer = Customer.query.get(customer_id)
        if customer:
            customer.total_spent += total_amount
            customer.visit_count += 1
            customer.last_visit = now_local()

    db.session.commit()
    return redirect(url_for("sales_screen", customer_id=customer_id if customer_id else None))


@app.route("/sales-history")
@login_required
def sales_history():
    branch = get_current_branch()
    if not branch:
        return redirect(url_for("branch_select"))
    sales = Sale.query.filter(Sale.branch_id == branch.id).order_by(Sale.created_at.desc()).limit(100).all()
    rows = ""
    for sale in sales:
        refund_action = ""
        if not sale.is_refund and not sale.refund_rows:
            refund_action = f'''
            <form method="post" action="{url_for('refund_sale', sale_id=sale.id)}">
                <input type="text" name="refund_reason" placeholder="İade nedeni (opsiyonel)">
                <button class="danger">İade Et</button>
            </form>
            '''
        label = "İADE" if sale.is_refund else "SATIŞ"
        rows += f'''
        <div class="card" style="margin-bottom:12px;">
            <div class="cart-row" style="padding-top:0;">
                <div>
                    <strong>{label} #{sale.id}</strong><br>
                    <span class="muted">{sale.created_at.strftime('%d.%m.%Y %H:%M')} • {sale.payment_type} • {sale.customer.name if sale.customer and sale.customer.name else (sale.customer.phone if sale.customer else 'Müşterisiz')}</span>
                </div>
                <div style="text-align:right;">
                    <strong>{sale.total_amount:.2f} TL</strong><br>
                    <span class="muted">Kasiyer: {sale.user.display_name if sale.user else '-'}</span>
                </div>
            </div>
            {refund_action if refund_action else '<div class="muted">İade açılamaz veya zaten açıldı.</div>'}
        </div>
        '''
    content = f'''
    <div class="hero">
        <h1>Satış Geçmişi</h1>
        <p>Son işlemleri gör, gerekirse iade oluştur.</p>
    </div>
    {rows or '<div class="card"><div class="muted">Henüz işlem yok.</div></div>'}
    '''
    return render_page("Satış Geçmişi", content)


@app.route("/sales/<int:sale_id>/refund", methods=["POST"])
@login_required
def refund_sale(sale_id: int):
    branch = get_current_branch()
    current_user = get_current_user()
    if not branch:
        return redirect(url_for("branch_select"))
    sale = Sale.query.get_or_404(sale_id)
    if sale.is_refund or sale.refund_rows:
        return redirect(request.referrer or url_for("sales_history"))
    if sale.branch_id != branch.id:
        return redirect(url_for("sales_history"))

    refund_reason = request.form.get("refund_reason", "").strip() or None
    refund_sale_row = Sale(customer_id=sale.customer_id, branch_id=sale.branch_id, user_id=current_user.id if current_user else None, payment_type=sale.payment_type, total_amount=-sale.total_amount, is_refund=True, original_sale_id=sale.id, refund_reason=refund_reason)
    db.session.add(refund_sale_row)
    db.session.flush()

    for item in sale.items:
        db.session.add(SaleItem(sale_id=refund_sale_row.id, category=item.category, price=-item.price, quantity=item.quantity))

    if sale.customer:
        sale.customer.total_spent += refund_sale_row.total_amount
        sale.customer.last_visit = now_local()

    db.session.commit()
    return redirect(request.referrer or url_for("sales_history"))


@app.route("/campaigns", methods=["GET", "POST"])
@login_required
def campaigns():
    selected_ids = request.form.getlist("customer_ids") if request.method == "POST" else []
    message_text = request.form.get("message_text", "").strip() if request.method == "POST" else ""
    filter_type = request.form.get("filter_type", "all") if request.method == "POST" else "all"

    base_query = Customer.query
    now = now_local()
    if filter_type == "recent30":
        base_query = base_query.filter(Customer.last_visit >= now - timedelta(days=30))
    elif filter_type == "highspend":
        base_query = base_query.filter(Customer.total_spent >= 1000)
    elif filter_type == "inactive60":
        base_query = base_query.filter(Customer.last_visit <= now - timedelta(days=60))

    filtered_customers = base_query.order_by(Customer.last_visit.desc().nullslast(), Customer.id.desc()).all()
    rows = ""
    for c in filtered_customers:
        checked = "checked" if (not selected_ids or str(c.id) in selected_ids) else ""
        wa_link = f'https://wa.me/{clean_phone_for_whatsapp(c.phone)}?text={quote(message_text)}' if message_text else ""
        rows += f'''
        <div class="cart-row">
            <div>
                <label>
                    <input type="checkbox" name="customer_ids" value="{c.id}" {checked} style="width:auto; margin-right:8px;">
                    <strong>{c.name or 'İsimsiz Müşteri'}</strong><br>
                    <span class="muted">{c.phone} • Toplam {c.total_spent:.2f} TL • Son ziyaret: {c.last_visit.strftime('%d.%m.%Y') if c.last_visit else '-'}</span>
                </label>
            </div>
            <div>
                {f'<a href="{wa_link}" target="_blank"><button type="button">WhatsApp Aç</button></a>' if wa_link else ''}
            </div>
        </div>
        '''

    bulk_links = ""
    if message_text:
        selected_customers = [c for c in filtered_customers if (not selected_ids or str(c.id) in selected_ids)]
        for c in selected_customers[:20]:
            link = f'https://wa.me/{clean_phone_for_whatsapp(c.phone)}?text={quote(message_text)}'
            bulk_links += f'<a class="pill" target="_blank" href="{link}">{c.name or c.phone}</a>'

    content = f'''
    <div class="hero">
        <h1>WhatsApp Kampanya Modülü</h1>
        <p>Müşterileri filtrele, mesajını yaz, sonra tek tek WhatsApp açarak kampanyayı gönder.</p>
    </div>
    <form method="post">
        <div class="sales-grid">
            <div class="card">
                <h3 class="section-title">Kampanya Ayarları</h3>
                <label>Filtre</label>
                <select name="filter_type">
                    <option value="all" {'selected' if filter_type == 'all' else ''}>Tüm Müşteriler</option>
                    <option value="recent30" {'selected' if filter_type == 'recent30' else ''}>Son 30 Günde Gelenler</option>
                    <option value="highspend" {'selected' if filter_type == 'highspend' else ''}>1000 TL Üstü Harcayanlar</option>
                    <option value="inactive60" {'selected' if filter_type == 'inactive60' else ''}>60 Gündür Gelmeyenler</option>
                </select>
                <label>Mesaj</label>
                <input type="text" name="message_text" value="{message_text}" placeholder="Örn: Bu hafta sonu tüm küpelerde %20 indirim 🎁">
                <button>Listeyi Hazırla</button>
            </div>
            <div class="card">
                <h3 class="section-title">Hızlı Kullanım</h3>
                <div class="muted">Bu modül tam otomatik toplu gönderim yapmaz. Seçtiğin müşteriler için WhatsApp penceresi hazırlar.</div>
                <div style="margin-top:12px;">{bulk_links or '<div class="muted">Mesaj yazınca burada hızlı bağlantılar oluşur.</div>'}</div>
            </div>
        </div>
        <div class="card" style="margin-top:14px;">
            <h3 class="section-title">Müşteri Listesi</h3>
            {rows or '<div class="muted">Bu filtrede müşteri yok.</div>'}
        </div>
    </form>
    '''
    return render_page("Kampanya", content)


@app.route("/reports")
@login_required
def reports():
    branch = get_current_branch()
    if not branch:
        return redirect(url_for("branch_select"))
    now = now_local()
    day_start = datetime(now.year, now.month, now.day)
    week_start = day_start - timedelta(days=day_start.weekday())
    month_start = datetime(now.year, now.month, 1)

    daily_total, daily_cash, daily_card, daily_sales_count, daily_customers, daily_refunds = get_period_totals(day_start, day_start + timedelta(days=1), branch.id)
    weekly_total, weekly_cash, weekly_card, weekly_sales_count, weekly_customers, weekly_refunds = get_period_totals(week_start, now + timedelta(days=1), branch.id)
    monthly_total, monthly_cash, monthly_card, monthly_sales_count, monthly_customers, monthly_refunds = get_period_totals(month_start, now + timedelta(days=1), branch.id)
    daily_expense = get_period_expense_total(day_start, day_start + timedelta(days=1), branch.id)
    monthly_expense = get_period_expense_total(month_start, now + timedelta(days=1), branch.id)

    category_rows = db.session.query(SaleItem.category, func.count(SaleItem.id), func.sum(SaleItem.price)).join(Sale).filter(Sale.created_at >= month_start, Sale.branch_id == branch.id).group_by(SaleItem.category).order_by(func.sum(SaleItem.price).desc()).all()
    category_html = ""
    for cat, count, total in category_rows:
        category_html += f'<div class="cart-row"><div><strong>{cat}</strong><br><span class="muted">{count} işlem</span></div><div><strong>{(total or 0):.2f} TL</strong></div></div>'

    expense_rows = Expense.query.filter(Expense.branch_id == branch.id, Expense.created_at >= month_start).order_by(Expense.created_at.desc()).limit(20).all()
    expense_html = ""
    for item in expense_rows:
        expense_html += f'<div class="cart-row"><div><strong>{item.title}</strong><br><span class="muted">{item.category} • {item.created_at.strftime("%d.%m.%Y %H:%M")}</span></div><div><strong>{item.amount:.2f} TL</strong></div></div>'

    top_customers = Customer.query.order_by(Customer.total_spent.desc()).limit(10).all()
    top_customer_html = ""
    for c in top_customers:
        top_customer_html += f'<div class="cart-row"><div><strong>{c.name or "İsimsiz Müşteri"}</strong><br><span class="muted">{c.phone}</span></div><div><strong>{c.total_spent:.2f} TL</strong></div></div>'

    content = f'''
    <div class="hero">
        <h1>Raporlar</h1>
        <p>Gün sonu kasa, haftalık performans, aylık müşteri, iade ve gider takibi.</p>
    </div>
    <div class="grid">
        <div class="card"><div class="muted">Bugün Toplam</div><div class="kpi">{daily_total:.2f} TL</div><div class="muted">Nakit {daily_cash:.2f} TL • Kart {daily_card:.2f} TL</div></div>
        <div class="card"><div class="muted">Bugün Gider</div><div class="kpi">{daily_expense:.2f} TL</div><div class="muted">Net etki: {(daily_total - daily_expense):.2f} TL</div></div>
        <div class="card"><div class="muted">Bu Hafta</div><div class="kpi">{weekly_total:.2f} TL</div><div class="muted">Nakit {weekly_cash:.2f} TL • Kart {weekly_card:.2f} TL • {weekly_sales_count} işlem</div></div>
        <div class="card"><div class="muted">Bu Ay</div><div class="kpi">{monthly_total:.2f} TL</div><div class="muted">Nakit {monthly_cash:.2f} TL • Kart {monthly_card:.2f} TL • {monthly_sales_count} işlem</div></div>
        <div class="card"><div class="muted">Aylık Gider</div><div class="kpi">{monthly_expense:.2f} TL</div><div class="muted">Net ay: {(monthly_total - monthly_expense):.2f} TL</div></div>
        <div class="card"><div class="muted">Aylık İade Etkisi</div><div class="kpi">{monthly_refunds:.2f} TL</div><div class="muted">Negatif işlem toplamı</div></div>
    </div>
    <div class="sales-grid" style="margin-top:14px;">
        <div class="card">
            <h3 class="section-title">Bu Ay Kategori Performansı</h3>
            {category_html or '<div class="muted">Henüz veri yok.</div>'}
        </div>
        <div class="card">
            <h3 class="section-title">Son Giderler</h3>
            {expense_html or '<div class="muted">Henüz gider yok.</div>'}
        </div>
    </div>
    <div class="sales-grid" style="margin-top:14px;">
        <div class="card">
            <h3 class="section-title">En Çok Harcayan Müşteriler</h3>
            {top_customer_html or '<div class="muted">Henüz müşteri verisi yok.</div>'}
        </div>
        <div class="card">
            <h3 class="section-title">Dışa Aktarım</h3>
            <div class="actions-inline">
                <a href="{url_for('export_sales_csv')}"><button class="secondary">Satışları CSV indir</button></a>
                <a href="{url_for('export_customers_csv')}"><button class="secondary">Müşterileri CSV indir</button></a>
                <a href="{url_for('export_expenses_csv')}"><button class="secondary">Giderleri CSV indir</button></a>
            </div>
        </div>
    </div>
    '''
    return render_page("Raporlar", content)


@app.route("/export/sales.csv")
@login_required
def export_sales_csv():
    branch = get_current_branch()
    if not branch:
        return redirect(url_for("branch_select"))
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "tarih", "sube", "musteri", "odeme", "tutar", "is_iade", "original_sale_id", "kasiyer"])
    query = Sale.query.filter(Sale.branch_id == branch.id).order_by(Sale.created_at.desc())
    for sale in query.all():
        writer.writerow([sale.id, sale.created_at.strftime("%Y-%m-%d %H:%M:%S"), sale.branch.name if sale.branch else "", sale.customer.name if sale.customer and sale.customer.name else (sale.customer.phone if sale.customer else ""), sale.payment_type, sale.total_amount, "evet" if sale.is_refund else "hayir", sale.original_sale_id or "", sale.user.display_name if sale.user else ""])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=satislar.csv"})


@app.route("/export/customers.csv")
@login_required
def export_customers_csv():
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "ad", "telefon", "toplam_harcama", "ziyaret", "son_ziyaret"])
    for customer in Customer.query.order_by(Customer.id.desc()).all():
        writer.writerow([customer.id, customer.name or "", customer.phone, customer.total_spent, customer.visit_count, customer.last_visit.strftime("%Y-%m-%d %H:%M:%S") if customer.last_visit else ""])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=musteriler.csv"})


@app.route("/export/expenses.csv")
@login_required
def export_expenses_csv():
    branch = get_current_branch()
    if not branch:
        return redirect(url_for("branch_select"))
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "tarih", "sube", "baslik", "kategori", "tutar", "not", "kullanici"])
    query = Expense.query.filter(Expense.branch_id == branch.id).order_by(Expense.created_at.desc())
    for item in query.all():
        writer.writerow([item.id, item.created_at.strftime("%Y-%m-%d %H:%M:%S"), item.branch.name if item.branch else "", item.title, item.category, item.amount, item.notes or "", item.user.display_name if item.user else ""])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=giderler.csv"})


def seed_defaults():
    if Branch.query.count() == 0:
        db.session.add(Branch(name="Merkez"))
        db.session.add(Branch(name="2. Şube"))
        db.session.commit()
    if User.query.count() == 0:
        admin = User(username="admin", password_hash=generate_password_hash("123456"), display_name="Yönetici", is_admin=True)
        db.session.add(admin)
        db.session.commit()


@app.cli.command("init-db")
def init_db_command():
    db.drop_all()
    db.create_all()
    seed_defaults()
    print("Veritabanı sıfırlandı ve hazırlandı.")


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        seed_defaults()
    app.run(host="0.0.0.0", port=5000, debug=True)
