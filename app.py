# app.py (secure + mobile tweaks + SP override fix)
import io
import csv
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional
from sqlalchemy import func

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    send_file,
    session,
    render_template_string,
    jsonify,
    json
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, func

# -----------------------------------------------------------------------------
# Config / DB
# -----------------------------------------------------------------------------
db = SQLAlchemy()
KG_PER_TON = 1000.0


EXPENSE_CATEGORIES = [
    "CNG",
    "Labour",
    "Loading / Unloading",
    "Transport",
    "Office Rent",
    "Electricity",
    "Phone / Internet",
    "Repair & Maintenance",
    "Packaging",
    "Food / Tea",
    "Miscellaneous"
]


def create_app(test_config: Optional[dict] = None) -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")

    # default config (allow overrides via test_config or env)
    db_uri = (
        test_config.get("DATABASE_URL")
        if test_config and "DATABASE_URL" in test_config
        else os.environ.get("DATABASE_URL", "sqlite:///hcl_sales.db")
    )
    app.config.from_mapping(
        SQLALCHEMY_DATABASE_URI=db_uri,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SECRET_KEY=os.environ.get("SECRET_KEY", "change-this-key"),
        PERMANENT_SESSION_LIFETIME=timedelta(days=int(os.environ.get("SESSION_DAYS", "30"))),
    )

    if test_config:
        app.config.update(test_config)

    db.init_app(app)

    # create tables automatically for local dev
    with app.app_context():
        db.create_all()

    register_routes(app)
    register_cli(app)

    return app


# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, unique=True)
    address = db.Column(db.Text, nullable=True)
    gst = db.Column(db.String(32), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    opening_balance = db.Column(db.Float, nullable=False, default=0.0)

    def __repr__(self) -> str:
        return f"<Client {self.name}>"


class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    client_name = db.Column(db.String(160), nullable=False)
    freight = db.Column(db.Float, nullable=False, default=0.0)
    quantity_kg = db.Column(db.Float, nullable=False, default=0.0, server_default="0.0")
    sale_type = db.Column(db.String(16), nullable=False, default="bill")

    gst_percent = db.Column(db.Float, nullable=False, default=0.0)

    subtotal = db.Column(db.Float, nullable=False, default=0.0)
    cgst_amount = db.Column(db.Float, nullable=False, default=0.0)
    sgst_amount = db.Column(db.Float, nullable=False, default=0.0)
    igst_amount = db.Column(db.Float, nullable=False, default=0.0)

    misc_amount = db.Column(db.Float, nullable=False, default=0.0)

    grand_total = db.Column(db.Float, nullable=False, default=0.0)

    items = db.relationship("SaleItem", backref="sale", cascade="all, delete-orphan")
    payments = db.relationship("SalePayment", backref="sale_ref", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Sale {self.id} {self.date} {self.client_name}>"

    @property
    def total_qty(self) -> float:
        return sum((i.quantity_kg or 0.0) for i in self.items)

    def total_cp(self) -> float:
        # User requested raw cost price (cost/kg * quantity)
        total = sum((i.cost_rate_per_kg or 0.0) * (i.quantity_kg or 0.0) for i in self.items)
        return round(total, 2)

    def total_sp(self) -> float:
        total = sum((i.selling_rate_per_kg or 0.0) * (i.quantity_kg or 0.0) for i in self.items)
        return round(total, 2)

    # alias for reports and payments
    def total_amount(self):
        if self.grand_total and self.grand_total > 0:
            return round(self.grand_total, 2)
        return self.total_sp()

    def pl(self) -> float:
        # P/L = Selling Subtotal - (Raw Cost + Freight + Misc)
        # Note: Tax is matching so it cancels out for net P/L if items are inclusive/exclusive
        # but user specifically asked for SP - (total CP + freight + msc)
        raw_cp = self.total_cp()
        return round(self.total_sp() - (raw_cp + (self.freight or 0.0) + (self.misc_amount or 0.0)), 2)

    def total_received(self):
        return round(sum(p.amount for p in self.payments), 2)

    def balance_due(self):
        return round(self.total_amount() - self.total_received(), 2)

    def payment_status(self):
        if self.total_received() == 0:
            return "Unpaid"
        elif self.balance_due() > 0:
            return "Partial"
        else:
            return "Paid"

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    date = db.Column(db.Date, nullable=False)

    category = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(300))

    amount = db.Column(db.Float, nullable=False)

    mode = db.Column(db.String(50))   # Cash / Bank / UPI

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    def __repr__(self):
        return f"<Expense {self.category} ₹{self.amount}>"


class SaleItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sale.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=True)
    bottle_type_id = db.Column(db.Integer, db.ForeignKey("bottle_type.id"), nullable=True) 
    quantity_kg = db.Column(db.Float, nullable=False, default=0.0)  # for bottles = num_batches
    cost_rate_per_kg = db.Column(db.Float, nullable=False, default=0.0)
    selling_rate_per_kg = db.Column(db.Float, nullable=True, default=0.0)
    gst_percent = db.Column(db.Float, nullable=False, default=0.0, server_default="0.0")

    def __repr__(self) -> str:
        prod_info = f" product={self.product_id}" if self.product_id else ""
        return f"<SaleItem {self.quantity_kg}kg cost={self.cost_rate_per_kg} sp={self.selling_rate_per_kg}{prod_info}>"


class SalePayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    sale_id = db.Column(
        db.Integer,
        db.ForeignKey("sale.id"),
        nullable=False
    )

    date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Float, nullable=False)

    mode = db.Column(db.String(50))   # Cash / Bank / UPI
    notes = db.Column(db.String(250))

    collection_id = db.Column(
        db.Integer,
        db.ForeignKey("client_collection.id"),
        nullable=True
    )

class ClientCollection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    mode = db.Column(db.String(50))   # Cash / Bank / UPI
    notes = db.Column(db.String(250))

    client = db.relationship("Client", backref=db.backref("collections", cascade="all, delete-orphan"))
    payments = db.relationship("SalePayment", backref="collection_ref", cascade="all, delete-orphan")


class VendorCollection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vendor_name = db.Column(db.String(160), nullable=False)
    date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    mode = db.Column(db.String(50))   # Cash / Bank / UPI
    notes = db.Column(db.String(250))

    payments = db.relationship("PurchasePayment", backref="vendor_collection_ref", cascade="all, delete-orphan")


class Purchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    vendor_name = db.Column(db.String(160), nullable=False)
    freight = db.Column(db.Float, nullable=False, default=0.0)

    gst_percent = db.Column(db.Float, nullable=False, default=0.0)
    subtotal = db.Column(db.Float, nullable=False, default=0.0)
    cgst_amount = db.Column(db.Float, nullable=False, default=0.0)
    sgst_amount = db.Column(db.Float, nullable=False, default=0.0)
    igst_amount = db.Column(db.Float, nullable=False, default=0.0)
    grand_total = db.Column(db.Float, nullable=False, default=0.0)

    items = db.relationship("PurchaseItem", backref="purchase", cascade="all, delete-orphan")
    payments = db.relationship("PurchasePayment", backref="purchase_ref", cascade="all, delete-orphan")

    def total_cost(self):
        # If GST-based total exists, use it
        if self.grand_total and self.grand_total > 0:
            return round(self.grand_total, 2)

        # Fallback for old purchases
        total = sum(
            (i.rate_per_kg or 0.0) * (i.quantity_kg or 0.0)
            for i in self.items
        )
        total += (self.freight or 0.0)

        return round(total, 2)
    
    def total_quantity(self):
        return round(sum(i.quantity_kg or 0 for i in self.items), 2)

    def avg_cost_per_kg(self):
        qty = self.total_quantity()
        if qty == 0:
            return 0
        return round(self.total_cost() / qty, 2)
    
    def avg_raw_rate_per_kg(self):
        total_qty = sum(i.quantity_kg or 0 for i in self.items)
        if total_qty == 0:
            return 0
        total_value = sum(
            (i.rate_per_kg or 0) * (i.quantity_kg or 0)
            for i in self.items
        )
        return round(total_value / total_qty, 2)

    def total_paid(self):
        return round(sum(p.amount for p in self.payments), 2)

    def balance_due(self):
        return round(self.total_cost() - self.total_paid(), 2)

    def payment_status(self):
        if self.total_paid() == 0:
            return "Unpaid"
        elif self.balance_due() > 0:
            return "Partial"
        else:
            return "Paid"



class PurchaseItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("purchase.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=True)

    quantity_kg = db.Column(db.Float, nullable=False, default=0.0)
    rate_per_kg = db.Column(db.Float, nullable=False, default=0.0)


class PurchasePayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    purchase_id = db.Column(
        db.Integer,
        db.ForeignKey("purchase.id"),
        nullable=False
    )

    date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Float, nullable=False)

    mode = db.Column(db.String(50))   # Cash / Bank / UPI
    notes = db.Column(db.String(250))

    collection_id = db.Column(
        db.Integer,
        db.ForeignKey("vendor_collection.id"),
        nullable=True
    )




class BottleType(db.Model):
    __tablename__ = "bottle_type"

    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(64), nullable=False, unique=True)
    quantity_ltr = db.Column(db.Float, nullable=False, default=0.0)
    bottles_in_batch = db.Column(db.Integer, nullable=False, default=1)
    can_price = db.Column(db.Float, nullable=False, default=0.0)
    price_per_kg = db.Column(db.Float, nullable=False, default=0.0)
    box_cost = db.Column(db.Float, nullable=False, default=0.0)
    selling_price_per_batch = db.Column(db.Float, nullable=False, default=0.0)

    def __repr__(self) -> str:
        return f"<BottleType {self.label} x{self.bottles_in_batch}>"

    def cp_per_batch(self) -> float:
        bottle_cost = (self.can_price or 0.0) * (self.bottles_in_batch or 0)
        chemical_cost = (self.price_per_kg or 0.0) * (self.quantity_ltr or 0.0) * (self.bottles_in_batch or 0)
        return round(bottle_cost + chemical_cost + (self.box_cost or 0.0), 2)

    def sp_per_batch(self) -> float:
        return round(self.selling_price_per_batch or 0.0, 2)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, unique=True)
    current_stock_kg = db.Column(db.Float, nullable=False, default=0.0)
    min_stock_kg = db.Column(db.Float, nullable=False, default=0.0)
    
    def change_stock(self, amount):
        self.current_stock_kg = round((self.current_stock_kg or 0.0) + amount, 2)

    def __repr__(self) -> str:
        return f"<Product {self.name} {self.current_stock_kg}kg>"

class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Location {self.name}>"


class Lead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=True)
    indiamart_link = db.Column(db.String(1024), nullable=True)
    deal_status = db.Column(db.String(64), nullable=True)
    comments = db.Column(db.Text, nullable=True)
    address = db.Column(db.String(1024), nullable=True)           # <-- NEW
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    location = db.relationship("Location", backref=db.backref("leads", cascade="all, delete-orphan"))

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "location_id": self.location_id,
            "location_name": self.location.name if self.location else None,
            "indiamart_link": self.indiamart_link,
            "deal_status": self.deal_status,
            "comments": self.comments,
            "address": self.address,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<Lead {self.name} @ {self.location_id}>"


class Loan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    loan_type = db.Column(db.String(16), nullable=False)          # "given" or "taken"
    party_name = db.Column(db.String(200), nullable=False)
    principal = db.Column(db.Float, nullable=False, default=0.0)
    interest_rate = db.Column(db.Float, nullable=False, default=0.0)   # % per year
    date_issued = db.Column(db.Date, nullable=False)
    due_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_closed = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    repayments = db.relationship("LoanRepayment", backref="loan", cascade="all, delete-orphan", order_by="LoanRepayment.date")

    def total_repaid(self):
        return round(sum(r.amount for r in self.repayments), 2)

    def interest_accrued(self):
        """Simple interest accrued from issue date to today (or due_date if closed)."""
        if not self.interest_rate or self.interest_rate == 0:
            return 0.0
        from datetime import date as date_cls
        end = self.due_date if (self.is_closed and self.due_date) else date_cls.today()
        days = (end - self.date_issued).days
        if days <= 0:
            return 0.0
        return round(self.principal * (self.interest_rate / 100) * days / 365, 2)

    def total_due(self):
        return round(self.principal + self.interest_accrued(), 2)

    def outstanding(self):
        return round(self.total_due() - self.total_repaid(), 2)

    def status(self):
        if self.is_closed:
            return "Closed"
        from datetime import date as date_cls
        if self.due_date and date_cls.today() > self.due_date:
            return "Overdue"
        return "Active"

    def __repr__(self):
        return f"<Loan {self.loan_type} {self.party_name} ₹{self.principal}>"


class LoanRepayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey("loan.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    mode = db.Column(db.String(50), nullable=True)     # Cash / Bank / UPI
    notes = db.Column(db.String(250), nullable=True)

    def __repr__(self):
        return f"<LoanRepayment loan={self.loan_id} ₹{self.amount}>"



# -----------------------------------------------------------------------------
# Small helpers
# -----------------------------------------------------------------------------

def sale_item_actual_kg(item: SaleItem) -> float:
    """
    Returns actual KG for a sale item.
    - Bill items: quantity_kg is already KG
    - Bottle (cash) items: quantity_kg = batches
    """
    if not item:
        return 0.0

    # Bottle sale
    if item.bottle_type_id:
        bt = BottleType.query.get(item.bottle_type_id)
        if not bt:
            return 0.0
        return (
            (bt.quantity_ltr or 0.0)
            * (bt.bottles_in_batch or 0)
            * (item.quantity_kg or 0.0)
        )

    # Bill sale
    return item.quantity_kg or 0.0



def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _to_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _parse_date(date_str: str) -> datetime.date:
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def to_kg(quantity: float, unit: str) -> float:
    q = _to_float(quantity, 0.0)
    if (unit or "").strip().lower() == "ton":
        return q * KG_PER_TON
    return q


def commit_or_rollback():
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def get_vendor_dues():

    purchases = Purchase.query.all()
    report = {}

    for p in purchases:
        vendor = p.vendor_name

        if vendor not in report:
            report[vendor] = {
                "total_purchase": 0,
                "total_paid": 0,
                "balance": 0
            }

        report[vendor]["total_purchase"] += p.total_cost()
        report[vendor]["total_paid"] += p.total_paid()
        report[vendor]["balance"] += p.balance_due()

    return report


def get_sales_outstanding():
    clients = Client.query.order_by(Client.name).all()
    report = {}

    for c in clients:
        # Sales for this client
        sales = Sale.query.filter_by(client_name=c.name).all()
        
        total_sales = sum(s.total_amount() for s in sales)
        total_received = sum(s.total_received() for s in sales)
        
        # Balance = Opening Balance + Total Sales - Total Received
        # Opening balance is positive for receivable
        balance = c.opening_balance + total_sales - total_received
        
        if balance != 0:
            report[c.name] = {
                "total_sales": total_sales,
                "total_received": total_received,
                "balance": round(balance, 2),
                "phone": c.phone,
                "opening_balance": c.opening_balance
            }

    return report

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
def register_routes(app: Flask) -> None:
    # --- Simple login/session wall (single-user) ---
    LOGIN_USER = os.environ.get("APP_USER", "yash")
    LOGIN_PASS = os.environ.get("APP_PASS", None)  # REQUIRED in prod

    LOGIN_FORM = """
    {% extends 'base.html' %}
    {% block content %}
    <div class="row justify-content-center">
      <div class="col-12 col-sm-8 col-md-6 col-lg-4">
        <div class="card shadow-sm">
          <div class="card-body">
            <h4 class="mb-3">Sign in</h4>
            <form method="post">
              <div class="mb-3">
                <label class="form-label">Username</label>
                <input class="form-control" name="username" required autofocus>
              </div>
              <div class="mb-3">
                <label class="form-label">Password</label>
                <input type="password" class="form-control" name="password" required>
              </div>
              <div class="form-check mb-3">
                <input class="form-check-input" type="checkbox" name="remember" id="remember">
                <label class="form-check-label" for="remember">Stay signed in</label>
              </div>
              <button class="btn btn-primary w-100">Login</button>
            </form>
          </div>
        </div>
      </div>
    </div>
    {% endblock %}
    """

    @app.before_request
    def _require_login():
        # allow login, static without auth
        open_endpoints = {"login", "static"}
        if request.endpoint in open_endpoints:
            return
        if not session.get("user"):
            return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            u = (request.form.get("username") or "").strip()
            p = request.form.get("password") or ""
            remember = (request.form.get("remember") == "on")
            if LOGIN_PASS and u == LOGIN_USER and p == LOGIN_PASS:
                session["user"] = u
                session.permanent = remember
                return redirect(request.args.get("next") or url_for("index"))
            flash("Invalid credentials", "danger")
        return render_template_string(LOGIN_FORM)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # Dashboard
    @app.route("/")
    def index():

        # --------------------------------------------------
        # Latest sales
        # --------------------------------------------------
        latest = Sale.query.order_by(
            Sale.date.desc(),
            Sale.id.desc()
        ).limit(10).all()

        # --------------------------------------------------
        # TOTAL SALES SUMMARY (Sales Side Only)
        # --------------------------------------------------
        totals = db.session.execute(
            text("""
            SELECT
                ROUND(SUM(qty_kg),2) AS total_qty,
                ROUND(SUM(sp),2) AS total_sp,
                ROUND(SUM(cp),2) AS total_cp,
                ROUND(SUM(freight),2) AS total_freight
            FROM (
                SELECT
                    sale.id,
                    SUM(sale_item.quantity_kg) qty_kg,
                    SUM(sale_item.selling_rate_per_kg * sale_item.quantity_kg) sp,
                    SUM(sale_item.cost_rate_per_kg * sale_item.quantity_kg) cp,
                    COALESCE(sale.freight,0) freight
                FROM sale
                JOIN sale_item ON sale_item.sale_id = sale.id
                GROUP BY sale.id
            ) per_sale
            """)
        ).mappings().first()

        total_qty = float(totals["total_qty"] or 0)
        total_sp_sql = float(totals["total_sp"] or 0)
        total_cp_sql = float(totals["total_cp"] or 0)
        total_freight = float(totals["total_freight"] or 0)

        # --------------------------------------------------
        # MONTHLY SALES (LAST 6 MONTHS)
        # --------------------------------------------------
        monthly_raw = db.session.execute(
            text("""
            SELECT ym,
                ROUND(SUM(qty_kg),2) qty_kg,
                ROUND(SUM(sp),2) sp,
                ROUND(SUM(cp),2) cp,
                ROUND(SUM(freight),2) freight
            FROM (
                SELECT
                    strftime('%Y-%m', sale.date) ym,
                    sale.id,
                    SUM(sale_item.quantity_kg) qty_kg,
                    SUM(sale_item.selling_rate_per_kg * sale_item.quantity_kg) sp,
                    SUM(sale_item.cost_rate_per_kg * sale_item.quantity_kg) cp,
                    COALESCE(sale.freight,0) freight
                FROM sale
                JOIN sale_item ON sale_item.sale_id = sale.id
                GROUP BY sale.id
            ) per_sale
            GROUP BY ym
            ORDER BY ym DESC
            LIMIT 6
            """)
        ).mappings().all()

        expense_monthly = dict(
            db.session.query(
                func.strftime('%Y-%m', Expense.date),
                func.sum(Expense.amount)
            )
            .group_by(func.strftime('%Y-%m', Expense.date))
            .all()
        )

        monthly = []

        for m in monthly_raw:
            ym = m["ym"]
            qty = float(m["qty_kg"] or 0)
            sp = float(m["sp"] or 0)
            cp = float(m["cp"] or 0)
            freight = float(m["freight"] or 0)
            expense = float(expense_monthly.get(ym, 0) or 0)

            gross_pl = sp - (cp + freight)
            net_pl = gross_pl - expense

            monthly.insert(0, { # Insert at 0 to get chronological order for charts
                "ym": ym,
                "qty_kg": qty,
                "sp": sp,
                "cp": cp,
                "freight": freight,
                "expense": round(expense, 2),
                "pl": round(net_pl, 2)
            })

        # Top 5 Clients by Revenue for Chart
        client_stats = {}
        for s in Sale.query.all():
            name = s.client_name
            client_stats[name] = client_stats.get(name, 0) + s.total_sp()
        
        top_clients = sorted(client_stats.items(), key=lambda x: x[1], reverse=True)[:5]
        chart_labels = [c[0] for c in top_clients]
        chart_values = [round(c[1], 2) for c in top_clients]

        # --------------------------------------------------
        # CURRENT MONTH DATA
        # --------------------------------------------------
        current_ym = datetime.now().strftime("%Y-%m")

        current = next(
            (m for m in monthly if m["ym"] == current_ym),
            {
                "qty_kg": 0,
                "sp": 0,
                "cp": 0,
                "freight": 0,
                "expense": 0,
                "pl": 0
            }
        )

        current_data = {
            "ym": current_ym,
            "qty": current["qty_kg"],
            "sp": current["sp"],
            "cp": current["cp"],
            "freight": current["freight"],
            "expense": current["expense"],
            "pl": current["pl"]
        }

        # --------------------------------------------------
        # DASHBOARD METRICS (FIXED ACCOUNTING)
        # --------------------------------------------------
        sales = Sale.query.all()
        purchases = Purchase.query.all()

        total_expense = db.session.query(
            func.sum(Expense.amount)
        ).scalar() or 0

        total_sale_pending = round(sum(s.balance_due() for s in sales), 2)
        total_purchase_pending = round(sum(p.balance_due() for p in purchases), 2)

        # ✅ Standardized Accounting (Sales - (Cost + Freight + Expense))
        total_sales_base = round(total_sp_sql, 2)
        total_cost_base = round(total_cp_sql, 2)
        total_net_profit = round(
            total_sales_base - (total_cost_base + total_freight + total_expense),
            2
        )

        # --------------------------------------------------
        # LOAN METRICS
        # --------------------------------------------------
        active_loans = Loan.query.filter_by(is_closed=False).all()
        loan_given_out  = round(sum(l.outstanding() for l in active_loans if l.loan_type == "given"), 2)
        loan_taken_out  = round(sum(l.outstanding() for l in active_loans if l.loan_type == "taken"), 2)
        loan_active_count = len(active_loans)

        # --------------------------------------------------
        # RENDER
        # --------------------------------------------------
        return render_template(
            "index.html",
            total_qty=round(total_qty, 2),
            total_cp=total_cost_base,
            total_sp=total_sales_base,
            total_profit=total_net_profit,
            total_freight=round(total_freight, 2),

            latest=latest,
            monthly=monthly,
            current_data=current_data,

            total_sale_pending=total_sale_pending,
            total_purchase_pending=total_purchase_pending,
            total_expense=round(total_expense, 2),
            chart_labels=json.dumps(chart_labels),
            chart_values=json.dumps(chart_values),

            loan_given_out=loan_given_out,
            loan_taken_out=loan_taken_out,
            loan_active_count=loan_active_count,
        )

    # Clients
    @app.route("/clients")
    def clients_list():
        q = (request.args.get("q") or "").strip()
        query = Client.query
        if q:
            query = query.filter(Client.name.ilike(f"%{q}%"))
        rows = query.order_by(Client.name.asc()).all()

        # Compute outstanding balance per client for display
        balances = {}
        for c in rows:
            sales = Sale.query.filter_by(client_name=c.name).all()
            total_sales = sum(s.total_amount() for s in sales)
            total_received = sum(s.total_received() for s in sales)
            balances[c.id] = round(c.opening_balance + total_sales - total_received, 2)

        return render_template("clients_list.html", rows=rows, q=q, balances=balances)


    @app.route("/clients/new", methods=["GET", "POST"])
    @app.route("/clients/<int:client_id>/edit", methods=["GET", "POST"])
    def clients_form(client_id=None):
        client = Client.query.get(client_id) if client_id else None
        if request.method == "POST":
            print(request.form.get("name"))
            print(request.form.get("address"))
            name = (request.form.get("name") or "").strip()
            address = (request.form.get("address") or "").strip()
            gst = (request.form.get("gst") or "").strip().upper()
            phone = (request.form.get("phone") or "").strip()
            opening_balance = _to_float(request.form.get("opening_balance"), 0.0)
            if not name:
                flash("Client name is required", "danger")
                return render_template("clients_form.html", client=client)
            try:
                if not client:
                    client = Client(name=name, address=address, gst=gst, phone=phone, opening_balance=opening_balance)
                    db.session.add(client)
                else:
                    client.name = name
                    client.address = address
                    client.gst = gst
                    client.phone = phone
                    client.opening_balance = opening_balance
                commit_or_rollback()
                flash("Client saved", "success")
                return redirect(url_for("clients_list"))
            except Exception as exc:
                flash(f"Error: {exc}", "danger")
        return render_template("clients_form.html", client=client)

    @app.route("/clients/<int:client_id>/delete", methods=["POST"])
    def clients_delete(client_id):
        client = Client.query.get_or_404(client_id)
        try:
            db.session.delete(client)
            commit_or_rollback()
            flash("Client deleted", "info")
        except Exception as exc:
            flash(f"Error: {exc}", "danger")
        return redirect(url_for("clients_list"))

    
    @app.route("/sales-payments")
    def sales_payments():

        status_filter = request.args.get("status", "pending")
        q_list = [v for v in request.args.getlist("q") if v.strip()]

        all_sales = Sale.query.order_by(Sale.date.desc()).all()

        if status_filter == "paid":
            sales = [s for s in all_sales if s.payment_status() == "Paid"]
        elif status_filter == "unpaid":
            sales = [s for s in all_sales if s.payment_status() == "Unpaid"]
        elif status_filter == "partial":
            sales = [s for s in all_sales if s.payment_status() == "Partial"]
        else:
            sales = [s for s in all_sales if s.payment_status() in ["Unpaid", "Partial"]]

        if q_list:
            sales = [s for s in sales if s.client_name in q_list]

        clients = Client.query.order_by(Client.name).all()

        return render_template(
            "sales_payments.html",
            sales=sales,
            status_filter=status_filter,
            q_list=q_list,
            clients=clients
        )



    @app.route("/sale/<int:sale_id>/payment", methods=["GET","POST"])
    def add_sale_payment(sale_id):

        sale = Sale.query.get_or_404(sale_id)

        if request.method == "POST":

            amount = float(request.form.get("amount"))
            date = datetime.strptime(
                request.form.get("date"), "%Y-%m-%d"
            ).date()

            mode = request.form.get("mode")
            notes = request.form.get("notes")

            payment = SalePayment(
                sale_id=sale.id,
                amount=amount,
                date=date,
                mode=mode,
                notes=notes
            )

            db.session.add(payment)
            db.session.commit()

            flash("Payment recorded", "success")
            return redirect(url_for("party_ledger", party_type="client", name=sale.client_name))

        return render_template(
            "sale_payment_form.html",
            sale=sale
        )

    @app.route("/client/<int:client_id>/collection", methods=["GET", "POST"])
    def add_client_collection(client_id):
        client = Client.query.get_or_404(client_id)
        if request.method == "POST":
            try:
                amount = float(request.form.get("amount"))
                date_str = request.form.get("date")
                date = datetime.strptime(date_str, "%Y-%m-%d").date()
                mode = request.form.get("mode")
                notes = request.form.get("notes")
                selected_invoice_ids = request.form.getlist("invoice_ids")

                collection = ClientCollection(
                    client_id=client.id,
                    amount=amount,
                    date=date,
                    mode=mode,
                    notes=notes
                )
                db.session.add(collection)
                db.session.flush() # To get collection.id

                if selected_invoice_ids:
                    for sid in selected_invoice_ids:
                        sale = Sale.query.get(int(sid))
                        if sale:
                            # Create a payment for this specific sale linked to the collection
                            # We'll pay the full balance of the sale from this collection
                            # unless the collection amount is smaller (but UI auto-sums, so it should match)
                            bal = sale.balance_due()
                            if bal > 0:
                                payment = SalePayment(
                                    sale_id=sale.id,
                                    date=date,
                                    amount=bal,
                                    mode=mode,
                                    notes=f"Bulk Payment via Collection #{collection.id}",
                                    collection_id=collection.id
                                )
                                db.session.add(payment)

                db.session.commit()

                flash(f"Recorded bulk payment of ₹{amount:,.2f} from {client.name}", "success")
                return redirect(url_for("party_ledger", party_type="client", name=client.name))
            except Exception as e:
                db.session.rollback()
                flash(f"Error recording collection: {str(e)}", "danger")

        # GET: Fetch pending invoices
        all_sales = Sale.query.filter_by(client_name=client.name).all()
        pending_invoices = [s for s in all_sales if s.balance_due() > 0]

        return render_template(
            "client_collection_form.html",
            client=client,
            pending_invoices=pending_invoices,
            linked_sale_ids=[],
            current_date=datetime.now().strftime("%Y-%m-%d")
        )

    @app.route("/client/collection/<int:collection_id>/edit", methods=["GET", "POST"])
    def edit_client_collection(collection_id):
        collection = ClientCollection.query.get_or_404(collection_id)
        client = collection.client
        if request.method == "POST":
            try:
                collection.amount = float(request.form.get("amount"))
                date_str = request.form.get("date")
                collection.date = datetime.strptime(date_str, "%Y-%m-%d").date()
                collection.mode = request.form.get("mode")
                collection.notes = request.form.get("notes")
                selected_invoice_ids = request.form.getlist("invoice_ids")

                # Remove old payments linked to this collection
                SalePayment.query.filter_by(collection_id=collection.id).delete()
                db.session.flush()

                if selected_invoice_ids:
                    for sid in selected_invoice_ids:
                        sale = Sale.query.get(int(sid))
                        if sale:
                            bal = sale.balance_due()
                            if bal > 0:
                                payment = SalePayment(
                                    sale_id=sale.id,
                                    date=collection.date,
                                    amount=bal,
                                    mode=collection.mode,
                                    notes=f"Bulk Payment via Collection #{collection.id} (Updated)",
                                    collection_id=collection.id
                                )
                                db.session.add(payment)

                db.session.commit()
                flash("Bulk payment updated successfully", "success")
                return redirect(url_for("party_ledger", party_type="client", name=client.name))
            except Exception as e:
                db.session.rollback()
                flash(f"Error updating collection: {str(e)}", "danger")

        # GET: Fetch pending invoices + those currently linked to this collection
        all_sales = Sale.query.filter_by(client_name=client.name).all()
        # An invoice is "available" if it has a balance OR if it's already linked to this collection
        linked_sale_ids = [p.sale_id for p in collection.payments]
        pending_invoices = [s for s in all_sales if s.balance_due() > 0 or s.id in linked_sale_ids]

        return render_template(
            "client_collection_form.html",
            client=client,
            collection=collection,
            linked_sale_ids=linked_sale_ids,
            pending_invoices=pending_invoices,
            current_date=collection.date.strftime("%Y-%m-%d")
        )

    @app.route("/client/collection/<int:collection_id>/delete")
    def delete_client_collection(collection_id):
        collection = ClientCollection.query.get_or_404(collection_id)
        client_name = collection.client.name
        try:
            # SalePayment records will be deleted via cascade
            db.session.delete(collection)
            db.session.commit()
            flash("Bulk payment deleted successfully", "warning")
        except Exception as e:
            db.session.rollback()
            flash(f"Error deleting collection: {str(e)}", "danger")
        
        return redirect(url_for("party_ledger", party_type="client", name=client_name))

    # -----------------------------------------------------------------------
    # Vendor Bulk Payments (VendorCollection)
    # -----------------------------------------------------------------------

    @app.route("/vendor/<path:vendor_name>/collection", methods=["GET", "POST"])
    def add_vendor_collection(vendor_name):
        if request.method == "POST":
            try:
                amount = float(request.form.get("amount"))
                date = datetime.strptime(request.form.get("date"), "%Y-%m-%d").date()
                mode = request.form.get("mode")
                notes = request.form.get("notes")
                selected_ids = request.form.getlist("invoice_ids")

                collection = VendorCollection(
                    vendor_name=vendor_name,
                    amount=amount,
                    date=date,
                    mode=mode,
                    notes=notes
                )
                db.session.add(collection)
                db.session.flush()

                if selected_ids:
                    for pid in selected_ids:
                        purchase = Purchase.query.get(int(pid))
                        if purchase:
                            bal = purchase.balance_due()
                            if bal > 0:
                                pay = PurchasePayment(
                                    purchase_id=purchase.id,
                                    date=date,
                                    amount=bal,
                                    mode=mode,
                                    notes=f"Bulk Payment via VendorCollection #{collection.id}",
                                    collection_id=collection.id
                                )
                                db.session.add(pay)

                db.session.commit()
                flash(f"Recorded bulk payment of \u20b9{amount:,.2f} to {vendor_name}", "success")
                return redirect(url_for("party_ledger", party_type="vendor", name=vendor_name))
            except Exception as e:
                db.session.rollback()
                flash(f"Error recording vendor payment: {str(e)}", "danger")

        all_purchases = Purchase.query.filter_by(vendor_name=vendor_name).all()
        pending_invoices = [p for p in all_purchases if p.balance_due() > 0]
        return render_template(
            "vendor_collection_form.html",
            vendor_name=vendor_name,
            pending_invoices=pending_invoices,
            linked_purchase_ids=[],
            current_date=datetime.now().strftime("%Y-%m-%d")
        )

    @app.route("/vendor/collection/<int:collection_id>/edit", methods=["GET", "POST"])
    def edit_vendor_collection(collection_id):
        collection = VendorCollection.query.get_or_404(collection_id)
        vendor_name = collection.vendor_name
        if request.method == "POST":
            try:
                collection.amount = float(request.form.get("amount"))
                collection.date = datetime.strptime(request.form.get("date"), "%Y-%m-%d").date()
                collection.mode = request.form.get("mode")
                collection.notes = request.form.get("notes")
                selected_ids = request.form.getlist("invoice_ids")

                # Remove old linked payments
                PurchasePayment.query.filter_by(collection_id=collection.id).delete()
                db.session.flush()

                if selected_ids:
                    for pid in selected_ids:
                        purchase = Purchase.query.get(int(pid))
                        if purchase:
                            bal = purchase.balance_due()
                            if bal > 0:
                                pay = PurchasePayment(
                                    purchase_id=purchase.id,
                                    date=collection.date,
                                    amount=bal,
                                    mode=collection.mode,
                                    notes=f"Bulk Payment via VendorCollection #{collection.id} (Updated)",
                                    collection_id=collection.id
                                )
                                db.session.add(pay)

                db.session.commit()
                flash("Vendor bulk payment updated", "success")
                return redirect(url_for("party_ledger", party_type="vendor", name=vendor_name))
            except Exception as e:
                db.session.rollback()
                flash(f"Error updating vendor payment: {str(e)}", "danger")

        linked_purchase_ids = [p.purchase_id for p in collection.payments]
        all_purchases = Purchase.query.filter_by(vendor_name=vendor_name).all()
        pending_invoices = [p for p in all_purchases if p.balance_due() > 0 or p.id in linked_purchase_ids]
        return render_template(
            "vendor_collection_form.html",
            vendor_name=vendor_name,
            collection=collection,
            pending_invoices=pending_invoices,
            linked_purchase_ids=linked_purchase_ids,
            current_date=collection.date.strftime("%Y-%m-%d")
        )

    @app.route("/vendor/collection/<int:collection_id>/delete")
    def delete_vendor_collection(collection_id):
        collection = VendorCollection.query.get_or_404(collection_id)
        vendor_name = collection.vendor_name
        try:
            db.session.delete(collection)  # cascades PurchasePayment rows
            db.session.commit()
            flash("Vendor bulk payment deleted", "warning")
        except Exception as e:
            db.session.rollback()
            flash(f"Error deleting vendor payment: {str(e)}", "danger")
        return redirect(url_for("party_ledger", party_type="vendor", name=vendor_name))

    @app.route("/sale/<int:sale_id>/payments")
    def sale_payments_detail(sale_id):

        sale = Sale.query.get_or_404(sale_id)

        payments = SalePayment.query.filter_by(
            sale_id=sale.id
        ).order_by(SalePayment.date.desc()).all()

        return render_template(
            "sale_payments_detail.html",
            sale=sale,
            payments=payments
        )

    @app.route("/sale/payment/<int:payment_id>/delete", methods=["POST"])
    def delete_sale_payment(payment_id):
        payment = SalePayment.query.get_or_404(payment_id)
        sale_id = payment.sale_id
        try:
            db.session.delete(payment)
            db.session.commit()
            flash("Payment deleted", "info")
        except Exception as exc:
            db.session.rollback()
            flash(f"Error: {exc}", "danger")
        return redirect(url_for("sale_payments_detail", sale_id=sale_id))

    
    @app.route("/ledger")
    def ledger_list():
        # Just a redirect or a simple search page for parties
        q = (request.args.get("q") or "").strip()
        clients = Client.query.order_by(Client.name).all()
        return render_template("ledger_list.html", clients=clients, q=q)

    @app.route("/ledger/<party_type>/<path:name>")
    def party_ledger(party_type, name):
        # name can be a single name or a comma-separated list
        is_multi = request.args.get("multi") == "1"
        names = name.split(",") if is_multi else [name]
        
        transactions = []
        total_billed = 0
        total_paid = 0
        display_name = ", ".join(names) if len(names) > 1 else names[0]

        for n in names:
            n = n.strip()
            # 1. Opening Balance
            client_obj = Client.query.filter_by(name=n).first()
            opening_bal = client_obj.opening_balance if client_obj else 0.0
            
            if opening_bal != 0:
                transactions.append({
                    "date": None,
                    "desc": f"Opening Balance ({n})" if is_multi else "Opening Balance",
                    "ref": "",
                    "debit": opening_bal if opening_bal > 0 else 0,
                    "credit": abs(opening_bal) if opening_bal < 0 else 0,
                    "party_name": n
                })

            if party_type == "client":
                sales = Sale.query.filter_by(client_name=n).all()
                for s in sales:
                    amt = s.total_amount()
                    total_billed += amt
                    balance = s.balance_due()
                    status = "Paid" if balance <= 0 else ("Partial" if balance < amt else "Pending")
                    transactions.append({
                        "date": s.date,
                        "desc": f"Sale #{s.id} ({n})" if is_multi else f"Sale Invoice #{s.id}",
                        "ref": f"/sales/{s.id}/edit",
                        "debit": amt,
                        "credit": 0,
                        "id_for_sort": s.id,
                        "party_name": n,
                        "payment_status": status,
                        "sale_id": s.id
                    })
                    for p in s.payments:
                        if p.collection_id:
                            continue # Linked to a bulk payment, handled below
                        total_paid += p.amount
                        transactions.append({
                            "date": p.date,
                            "desc": f"Payment Recd (Inv #{s.id})",
                            "ref": f"/sale/{s.id}/payments",
                            "debit": 0,
                            "credit": p.amount,
                            "id_for_sort": p.id,
                            "party_name": n
                        })
                # 3. Direct Collections (Account Payments)
                if client_obj:
                    for c in client_obj.collections:
                        total_paid += c.amount
                        # Grouped description
                        inv_ids = [str(p.sale_id) for p in c.payments]
                        desc = f"Direct Payment ({c.mode})" if c.mode else "Direct Payment"
                        if inv_ids:
                            desc = f"Bulk Payment ({c.mode or 'N/A'}) - Invoices: " + ", ".join(inv_ids)
                        
                        transactions.append({
                            "date": c.date,
                            "desc": desc,
                            "ref": "",
                            "debit": 0,
                            "credit": c.amount,
                            "id_for_sort": -c.id,
                            "party_name": n,
                            "collection_id": c.id
                        })
            else: # vendor
                purchases = Purchase.query.filter_by(vendor_name=n).all()
                for p_rec in purchases:
                    cost = p_rec.total_cost()
                    total_billed += cost
                    balance = p_rec.balance_due()
                    status = "Paid" if balance <= 0 else ("Partial" if balance < cost else "Pending")
                    transactions.append({
                        "date": p_rec.date,
                        "desc": f"Purchase #{p_rec.id} ({n})" if is_multi else f"Purchase Invoice #{p_rec.id}",
                        "ref": f"/purchase/{p_rec.id}/edit",
                        "debit": 0,
                        "credit": cost,
                        "id_for_sort": p_rec.id,
                        "party_name": n,
                        "payment_status": status,
                        "purchase_id": p_rec.id
                    })
                    for pay in p_rec.payments:
                        if pay.collection_id:
                            continue  # Handled as a bulk payment row below
                        total_paid += pay.amount
                        transactions.append({
                            "date": pay.date,
                            "desc": f"Payment Paid (Inv #{p_rec.id})",
                            "ref": f"/purchase/{p_rec.id}/payments",
                            "debit": pay.amount,
                            "credit": 0,
                            "id_for_sort": pay.id,
                            "party_name": n
                        })

                # Vendor bulk payments
                vendor_collections = VendorCollection.query.filter_by(vendor_name=n).all()
                for vc in vendor_collections:
                    total_paid += vc.amount
                    inv_ids = [str(p.purchase_id) for p in vc.payments]
                    desc = f"Bulk Payment ({vc.mode or 'N/A'})"
                    if inv_ids:
                        desc = f"Bulk Payment ({vc.mode or 'N/A'}) - Invoices: " + ", ".join(inv_ids)
                    transactions.append({
                        "date": vc.date,
                        "desc": desc,
                        "ref": "",
                        "debit": vc.amount,
                        "credit": 0,
                        "id_for_sort": -vc.id,
                        "party_name": n,
                        "vendor_collection_id": vc.id
                    })

        # Sort: Opening balances first (date=None), then by date, then by ID
        def sort_key(t):
            # Use a very early date for opening balances
            d = t["date"] or datetime(1900, 1, 1).date()
            return (d, t.get("id_for_sort", 0))

        transactions.sort(key=sort_key)

        # Calculate Running Balance
        running = 0
        for t in transactions:
            if party_type == "client":
                running += (t["debit"] - t["credit"])
            else:
                running += (t["credit"] - t["debit"])
            t["balance"] = round(running, 2)

        # Detect if party exists on the other side (client↔vendor)
        if party_type == "client":
            other_side_count = Purchase.query.filter_by(vendor_name=display_name).count()
        else:
            other_side_count = Sale.query.filter_by(client_name=display_name).count()

        return render_template(
            "ledger.html",
            name=display_name,
            party_type=party_type.capitalize(),
            transactions=transactions,
            total_billed=round(total_billed, 2),
            total_paid=round(total_paid, 2),
            net_balance=round(running, 2),
            is_multi=is_multi,
            client_obj=client_obj if party_type == "client" else None,
            other_side_count=other_side_count,
        )

    @app.route("/ledger/combined/<path:name>")
    def combined_party_ledger(name):
        """Combined client + vendor ledger for parties that wear both hats."""
        name = name.strip()

        client_obj = Client.query.filter_by(name=name).first()
        transactions = []

        # ── CLIENT SIDE (sales = debit, receipts = credit) ──
        sales_total = 0
        sales_received = 0

        if client_obj:
            opening_bal = client_obj.opening_balance or 0.0
            if opening_bal != 0:
                transactions.append({
                    "date": None,
                    "desc": "Opening Balance (Client)",
                    "ref": "",
                    "debit": opening_bal if opening_bal > 0 else 0,
                    "credit": abs(opening_bal) if opening_bal < 0 else 0,
                    "side": "client",
                    "id_for_sort": -999999,
                })

        sales = Sale.query.filter_by(client_name=name).all()
        for s in sales:
            amt = s.total_amount()
            sales_total += amt
            bal = s.balance_due()
            status = "Paid" if bal <= 0 else ("Partial" if bal < amt else "Pending")
            transactions.append({
                "date": s.date,
                "desc": f"Sale Invoice #{s.id}",
                "ref": f"/sales/{s.id}/edit",
                "debit": amt,
                "credit": 0,
                "side": "sale",
                "payment_status": status,
                "sale_id": s.id,
                "id_for_sort": s.id,
            })
            for p in s.payments:
                if p.collection_id:
                    continue
                sales_received += p.amount
                transactions.append({
                    "date": p.date,
                    "desc": f"Receipt (Sale #{s.id})",
                    "ref": "",
                    "debit": 0,
                    "credit": p.amount,
                    "side": "receipt",
                    "id_for_sort": p.id,
                })
        if client_obj:
            for c in client_obj.collections:
                sales_received += c.amount
                inv_ids = [str(p.sale_id) for p in c.payments]
                desc = f"Bulk Receipt ({c.mode or 'N/A'})"
                if inv_ids:
                    desc += " - Inv: " + ", ".join(inv_ids)
                transactions.append({
                    "date": c.date,
                    "desc": desc,
                    "ref": "",
                    "debit": 0,
                    "credit": c.amount,
                    "side": "receipt",
                    "collection_id": c.id,
                    "id_for_sort": -c.id,
                })

        # ── VENDOR SIDE (purchases = credit, payments = debit) ──
        purchase_total = 0
        purchase_paid = 0

        purchases = Purchase.query.filter_by(vendor_name=name).all()
        for p_rec in purchases:
            cost = p_rec.total_cost()
            purchase_total += cost
            bal = p_rec.balance_due()
            status = "Paid" if bal <= 0 else ("Partial" if bal < cost else "Pending")
            transactions.append({
                "date": p_rec.date,
                "desc": f"Purchase Invoice #{p_rec.id}",
                "ref": f"/purchase/{p_rec.id}/edit",
                "debit": 0,
                "credit": cost,
                "side": "purchase",
                "payment_status": status,
                "purchase_id": p_rec.id,
                "id_for_sort": p_rec.id,
            })
            for pay in p_rec.payments:
                if pay.collection_id:
                    continue
                purchase_paid += pay.amount
                transactions.append({
                    "date": pay.date,
                    "desc": f"Payment Made (Purchase #{p_rec.id})",
                    "ref": "",
                    "debit": pay.amount,
                    "credit": 0,
                    "side": "payment",
                    "id_for_sort": pay.id,
                })

        vendor_collections = VendorCollection.query.filter_by(vendor_name=name).all()
        for vc in vendor_collections:
            purchase_paid += vc.amount
            inv_ids = [str(p.purchase_id) for p in vc.payments]
            desc = f"Bulk Payment ({vc.mode or 'N/A'})"
            if inv_ids:
                desc += " - Inv: " + ", ".join(inv_ids)
            transactions.append({
                "date": vc.date,
                "desc": desc,
                "ref": "",
                "debit": vc.amount,
                "credit": 0,
                "side": "payment",
                "vendor_collection_id": vc.id,
                "id_for_sort": -vc.id,
            })

        # ── Sort & running balance ──
        def sort_key(t):
            d = t["date"] or datetime(1900, 1, 1).date()
            return (d, t.get("id_for_sort", 0))

        transactions.sort(key=sort_key)

        # Net balance: we are owed (sales) minus we owe (purchases)
        # debit = we are owed / we paid out; credit = we received / we were billed
        # For combined: treat as: +debit (sale) -credit(purchase) side by side
        # Running: sale entries debit us (client owes), receipt credits reduce it
        #          purchase credit them (we owe), payment debit reduces it
        # Net = receivable_balance - payable_balance
        running = 0
        for t in transactions:
            side = t.get("side", "")
            if side in ("sale", "receipt", "client"):
                running += t["debit"] - t["credit"]
            else:  # purchase, payment
                running -= t["credit"] - t["debit"]
            t["balance"] = round(running, 2)

        sales_balance = sales_total - sales_received         # what client owes us
        purchase_balance = purchase_total - purchase_paid    # what we owe vendor
        net_position = round(sales_balance - purchase_balance, 2)

        return render_template(
            "combined_ledger.html",
            name=name,
            transactions=transactions,
            sales_total=round(sales_total, 2),
            sales_received=round(sales_received, 2),
            sales_balance=round(sales_balance, 2),
            purchase_total=round(purchase_total, 2),
            purchase_paid=round(purchase_paid, 2),
            purchase_balance=round(purchase_balance, 2),
            net_position=net_position,
            client_obj=client_obj,
            has_sales=bool(sales),
            has_purchases=bool(purchases),
        )

    @app.route("/reports/sales-outstanding")
    def sales_outstanding_report():

        sales = Sale.query.all()

        report = {}

        for s in sales:
            client = s.client_name

            if client not in report:
                report[client] = {
                    "total_sales": 0,
                    "total_received": 0,
                    "balance": 0
                }

            report[client]["total_sales"] += s.total_amount()
            report[client]["total_received"] += s.total_received()
            report[client]["balance"] += s.balance_due()

        return render_template(
            "sales_outstanding_report.html",
            report=report
        )

    # Sales - create/edit
    @app.route("/sales/new", methods=["GET", "POST"])
    @app.route("/sales/<int:sale_id>/edit", methods=["GET", "POST"])
    def sales_form(sale_id=None):

        sale = Sale.query.get(sale_id) if sale_id else None
        clients = Client.query.order_by(Client.name.asc()).all()
        bottle_types = BottleType.query.order_by(BottleType.quantity_ltr.asc()).all()
        hcl_products = Product.query.order_by(Product.name).all()

        if request.method == "POST":
            try:
                date_val = _parse_date(request.form.get("date") or "")
                sale_type = (request.form.get("sale_type") or "bill").strip().lower()

                # -----------------------------
                # Client Handling
                # -----------------------------
                client_id = request.form.get("client_id")
                if client_id:
                    found = Client.query.get(int(client_id))
                    chosen_name = found.name if found else (request.form.get("client_name") or "").strip()
                else:
                    chosen_name = (request.form.get("client_name") or "").strip()

                if not chosen_name:
                    raise ValueError("Client is required")

                freight = _to_float(request.form.get("freight"), 0.0)

                # -----------------------------
                # Create or Update Sale
                # -----------------------------
                if not sale:
                    sale = Sale(
                        date=date_val,
                        client_name=chosen_name,
                        freight=freight,
                        sale_type=sale_type
                    )
                    db.session.add(sale)
                    db.session.flush()
                else:
                    sale.date = date_val
                    sale.client_name = chosen_name
                    sale.freight = freight
                    sale.sale_type = sale_type
                    
                    # Reverse stock for old items
                    for old_item in sale.items:
                        if old_item.product_id:
                            prod = Product.query.get(old_item.product_id)
                            if prod:
                                prod.change_stock(old_item.quantity_kg)

                    SaleItem.query.filter_by(sale_id=sale.id).delete()

                # =====================================================
                # CASH MODE (Bottle)
                # =====================================================
                if sale_type == "cash":

                    bt_ids = request.form.getlist("bottle_type_id[]")
                    batches_list = request.form.getlist("batches[]")
                    sp_overrides = request.form.getlist("sp_batch[]")
                    gst_percents_cash = request.form.getlist("gst_percent_cash[]")

                    total_batches = 0
                    any_added = False
                    total_gst_val = 0.0

                    for i in range(len(bt_ids)):

                        bt_id = (bt_ids[i] or "").strip()
                        if not bt_id:
                            continue

                        bt = BottleType.query.get(int(bt_id))
                        if not bt:
                            raise ValueError("Invalid bottle type selected")

                        num_batches = _to_int(
                            batches_list[i] if i < len(batches_list) else 0, 0
                        )

                        if num_batches <= 0:
                            continue

                        submitted_sp = sp_overrides[i] if i < len(sp_overrides) else ""
                        if submitted_sp and submitted_sp.strip():
                            try:
                                chosen_sp = float(submitted_sp)
                            except:
                                chosen_sp = bt.sp_per_batch()
                        else:
                            chosen_sp = bt.sp_per_batch()

                        item = SaleItem(
                            sale_id=sale.id,
                            bottle_type_id=bt.id,
                            quantity_kg=float(num_batches),
                            cost_rate_per_kg=float(bt.cp_per_batch()),
                            selling_rate_per_kg=float(chosen_sp),
                            gst_percent=_to_float(gst_percents_cash[i] if i < len(gst_percents_cash) else 0, 0.0)
                        )
                        total_gst_val += (item.selling_rate_per_kg * item.quantity_kg) * (item.gst_percent / 100.0)

                        db.session.add(item)
                        total_batches += num_batches
                        any_added = True

                    if not any_added:
                        raise ValueError("At least one bottle line is required")

                    sale.quantity_kg = total_batches

                # =====================================================
                # BILL MODE (Freeform)
                # =====================================================
                else:

                    quantities = request.form.getlist("quantity[]")
                    units = request.form.getlist("unit[]")
                    cost_rates = request.form.getlist("cost_rate[]")
                    sell_rates = request.form.getlist("sell_rate[]")
                    prod_ids_bill = request.form.getlist("product_id[]")
                    gst_percents_bill = request.form.getlist("gst_percent[]")

                    if not quantities:
                        raise ValueError("At least one line item is required")

                    total_qty = 0
                    total_gst_val = 0.0

                    for i in range(len(quantities)):
                        q_val = quantities[i]
                        u_val = units[i] if i < len(units) else "kg"
                        cr = cost_rates[i] if i < len(cost_rates) else 0.0
                        sr = sell_rates[i] if i < len(sell_rates) else 0.0
                        p_id = prod_ids_bill[i] if i < len(prod_ids_bill) else ""

                        qty_kg = to_kg(q_val or 0, u_val or "kg")
                        total_qty += qty_kg

                        item = SaleItem(
                            sale_id=sale.id,
                            quantity_kg=qty_kg,
                            cost_rate_per_kg=_to_float(cr, 0.0),
                            selling_rate_per_kg=_to_float(sr, 0.0),
                            product_id=int(p_id) if (p_id and p_id.strip()) else None,
                            gst_percent=_to_float(gst_percents_bill[i] if i < len(gst_percents_bill) else 0, 0.0)
                        )
                        total_gst_val += (item.selling_rate_per_kg * item.quantity_kg) * (item.gst_percent / 100.0)
                        db.session.add(item)
                        
                        # Decrement stock if product linked
                        if item.product_id:
                            prod = Product.query.get(item.product_id)
                            if prod:
                                prod.change_stock(-qty_kg)

                    sale.quantity_kg = total_qty

                # =====================================================
                # GST + MISC LOGIC (PHASE 2)
                # =====================================================

                db.session.flush()

                misc_amount = _to_float(request.form.get("misc_amount"), 0.0)
                subtotal = sale.total_sp()
                gst_amount = total_gst_val

                # Assuming intra-state sale (CGST + SGST)
                cgst = gst_amount / 2
                sgst = gst_amount / 2
                igst = 0

                grand_total = subtotal + gst_amount

                sale.gst_percent = 0.0 # Deprecated global field
                sale.subtotal = round(subtotal, 2)
                sale.cgst_amount = round(cgst, 2)
                sale.sgst_amount = round(sgst, 2)
                sale.igst_amount = round(igst, 2)
                sale.misc_amount = round(misc_amount, 2)
                sale.grand_total = round(grand_total, 2)

                # -----------------------------
                commit_or_rollback()
                flash("Saved successfully", "success")
                return redirect(url_for("sales_list"))

            except Exception as exc:
                db.session.rollback()
                flash(f"Error: {exc}", "danger")

        return render_template(
            "sales_form.html",
            sale=sale,
            clients=clients,
            bottle_types=bottle_types,
            hcl_products=hcl_products,
            sale_type=sale.sale_type if sale else "bill",
        )

    
    @app.route("/sales")
    def sales_list():
        q_raw = request.args.getlist("q")
        q_list = [v for v in q_raw if v.strip()]

        query = Sale.query

        # Apply search filter
        if q_list:
            query = query.filter(
                Sale.client_name.in_(q_list)
            )

        sales = query.order_by(
            Sale.date.desc(),
            Sale.id.desc()
        ).all()

        clients = Client.query.order_by(Client.name).all()

        return render_template(
            "sales_list.html",
            rows=sales,
            q_list=q_list,
            clients=clients
        )

    @app.route("/sales/<int:sale_id>/delete", methods=["POST"])
    def sales_delete(sale_id):
        sale = Sale.query.get_or_404(sale_id)
        try:
            # Reverse stock
            for item in sale.items:
                if item.product_id:
                    prod = Product.query.get(item.product_id)
                    if prod:
                        prod.change_stock(item.quantity_kg)

            db.session.delete(sale)
            commit_or_rollback()
            flash("Deleted", "info")
        except Exception as exc:
            flash(f"Error: {exc}", "danger")
        return redirect(url_for("sales_list"))

    @app.route("/purchases")
    def purchases():
        q_raw = request.args.getlist("q")
        q_list = [v for v in q_raw if v.strip()]

        query = Purchase.query
        if q_list:
            # allow search by multiple vendor names
            query = query.filter(
                Purchase.vendor_name.in_(q_list)
            )
        all_purchases = query.order_by(Purchase.date.desc()).all()
        clients = Client.query.order_by(Client.name).all()
        return render_template("purchases.html", purchases=all_purchases, q_list=q_list, clients=clients)




    @app.route("/purchase/new", methods=["GET", "POST"])
    def new_purchase():

        clients = Client.query.order_by(Client.name).all()
        products = Product.query.order_by(Product.name).all()

        if request.method == "POST":

            try:
                vendor_id = request.form.get("vendor_id")
                vendor_name = request.form.get("vendor_name")

                # If vendor selected from dropdown
                if vendor_id:
                    vendor = Client.query.get(vendor_id)
                    vendor_name = vendor.name if vendor else vendor_name

                if not vendor_name:
                    raise ValueError("Vendor name is required")

                date_str = request.form.get("date")
                freight = float(request.form.get("freight") or 0)
                gst_percent = float(request.form.get("gst_percent") or 0)

                purchase = Purchase(
                    vendor_name=vendor_name,
                    date=datetime.strptime(date_str, "%Y-%m-%d").date(),
                    freight=freight,
                    gst_percent=gst_percent
                )

                db.session.add(purchase)
                db.session.flush()   # generate purchase.id

                # -----------------------------
                # Save Line Items
                # -----------------------------
                qty_list = request.form.getlist("quantity[]")
                rate_list = request.form.getlist("rate[]")
                prod_id_list = request.form.getlist("product_id[]")

                subtotal = 0

                for i in range(min(len(qty_list), len(rate_list))):
                    q = qty_list[i]
                    r = rate_list[i]
                    p_id = prod_id_list[i] if i < len(prod_id_list) else ""

                    if q and r:
                        qty = float(q)
                        rate = float(r)
                        subtotal += qty * rate

                        item = PurchaseItem(
                            purchase_id=purchase.id,
                            quantity_kg=qty,
                            rate_per_kg=rate,
                            product_id=int(p_id) if (p_id and p_id.strip()) else None
                        )
                        db.session.add(item)
                        
                        # Increment stock if product linked
                        if item.product_id:
                            prod = Product.query.get(item.product_id)
                            if prod:
                                prod.change_stock(qty)

                # Add freight to subtotal
                subtotal += freight

                # -----------------------------
                # GST Calculation
                # -----------------------------
                gst_amount = subtotal * gst_percent / 100

                cgst = gst_amount / 2
                sgst = gst_amount / 2
                igst = 0  # assuming intra-state purchase

                grand_total = subtotal + gst_amount

                # -----------------------------
                # Save GST Fields
                # -----------------------------
                purchase.subtotal = round(subtotal, 2)
                purchase.cgst_amount = round(cgst, 2)
                purchase.sgst_amount = round(sgst, 2)
                purchase.igst_amount = round(igst, 2)
                purchase.grand_total = round(grand_total, 2)

                db.session.commit()

                flash("Purchase created successfully", "success")
                return redirect(url_for("purchases"))

            except Exception as exc:
                db.session.rollback()
                flash(f"Error: {exc}", "danger")

        return render_template(
            "purchase_form.html",
            clients=clients,
            products=products,
            purchase=None
        )

    @app.route("/purchase/<int:purchase_id>/edit", methods=["GET", "POST"])
    def edit_purchase(purchase_id):

        purchase = Purchase.query.get_or_404(purchase_id)
        clients = Client.query.order_by(Client.name).all()
        products = Product.query.order_by(Product.name).all()

        if request.method == "POST":

            try:
                vendor_id = request.form.get("vendor_id")
                vendor_name = request.form.get("vendor_name")

                if vendor_id:
                    vendor = Client.query.get(vendor_id)
                    vendor_name = vendor.name if vendor else vendor_name

                if not vendor_name:
                    raise ValueError("Vendor name is required")

                # -----------------------------
                # Basic Fields
                # -----------------------------
                purchase.vendor_name = vendor_name
                purchase.date = datetime.strptime(
                    request.form.get("date"), "%Y-%m-%d"
                ).date()

                purchase.freight = float(request.form.get("freight") or 0)
                purchase.gst_percent = float(request.form.get("gst_percent") or 0)

                # -----------------------------
                # Delete Old Line Items & Reverse Stock
                # -----------------------------
                for old_item in purchase.items:
                    if old_item.product_id:
                        prod = Product.query.get(old_item.product_id)
                        if prod:
                            prod.change_stock(-old_item.quantity_kg)

                PurchaseItem.query.filter_by(purchase_id=purchase.id).delete()

                qty_list = request.form.getlist("quantity[]")
                rate_list = request.form.getlist("rate[]")
                prod_id_list = request.form.getlist("product_id[]")

                subtotal = 0

                # -----------------------------
                # Re-add Line Items & Apply Stock
                # -----------------------------
                for i in range(min(len(qty_list), len(rate_list))):
                    q = qty_list[i]
                    r = rate_list[i]
                    p_id = prod_id_list[i] if i < len(prod_id_list) else ""

                    if q and r:
                        qty = float(q)
                        rate = float(r)
                        subtotal += qty * rate

                        new_item = PurchaseItem(
                            purchase_id=purchase.id,
                            quantity_kg=qty,
                            rate_per_kg=rate,
                            product_id=int(p_id) if (p_id and p_id.strip()) else None
                        )
                        db.session.add(new_item)
                        
                        if new_item.product_id:
                            prod = Product.query.get(new_item.product_id)
                            if prod:
                                prod.change_stock(qty)

                # Add freight
                subtotal += purchase.freight

                # -----------------------------
                # GST Calculation
                # -----------------------------
                gst_amount = subtotal * purchase.gst_percent / 100

                cgst = gst_amount / 2
                sgst = gst_amount / 2
                igst = 0  # assuming intra-state

                grand_total = subtotal + gst_amount

                # -----------------------------
                # Update GST Fields
                # -----------------------------
                purchase.subtotal = round(subtotal, 2)
                purchase.cgst_amount = round(cgst, 2)
                purchase.sgst_amount = round(sgst, 2)
                purchase.igst_amount = round(igst, 2)
                purchase.grand_total = round(grand_total, 2)

                db.session.commit()

                flash("Purchase updated successfully", "success")
                return redirect(url_for("purchases"))

            except Exception as exc:
                db.session.rollback()
                flash(f"Error: {exc}", "danger")

        return render_template(
            "purchase_form.html",
            purchase=purchase,
            clients=clients,
            products=products
        )


    @app.route("/purchase/<int:purchase_id>/delete", methods=["POST"])
    def delete_purchase(purchase_id):

        purchase = Purchase.query.get_or_404(purchase_id)

        # Reverse stock
        for item in purchase.items:
            if item.product_id:
                prod = Product.query.get(item.product_id)
                if prod:
                    prod.change_stock(-item.quantity_kg)

        db.session.delete(purchase)
        db.session.commit()

        flash("Purchase deleted successfully", "success")
        return redirect(url_for("purchases"))


    @app.route("/purchase/<int:purchase_id>/payment", methods=["GET","POST"])
    def add_payment(purchase_id):

        purchase = Purchase.query.get_or_404(purchase_id)

        if request.method == "POST":
            amount = float(request.form.get("amount"))
            date = datetime.strptime(
                request.form.get("date"), "%Y-%m-%d"
            ).date()

            mode = request.form.get("mode")
            notes = request.form.get("notes")

            payment = PurchasePayment(
                purchase_id=purchase.id,
                amount=amount,
                date=date,
                mode=mode,
                notes=notes
            )

            db.session.add(payment)
            db.session.commit()

            flash("Payment recorded", "success")
            return redirect(url_for("purchases"))

        return render_template(
            "purchase_payment_form.html",
            purchase=purchase
        )


    @app.route("/purchase/<int:purchase_id>/payments")
    def purchase_payments(purchase_id):

        purchase = Purchase.query.get_or_404(purchase_id)

        payments = PurchasePayment.query.filter_by(
            purchase_id=purchase.id
        ).order_by(PurchasePayment.date.desc()).all()

        return render_template(
            "purchase_payments.html",
            purchase=purchase,
            payments=payments
        )

    @app.route("/purchase/payment/<int:payment_id>/delete", methods=["POST"])
    def delete_purchase_payment(payment_id):
        payment = PurchasePayment.query.get_or_404(payment_id)
        purchase_id = payment.purchase_id
        try:
            db.session.delete(payment)
            db.session.commit()
            flash("Payment deleted", "info")
        except Exception as exc:
            db.session.rollback()
            flash(f"Error: {exc}", "danger")
        return redirect(url_for("purchase_payments", purchase_id=purchase_id))


    @app.route("/payments")
    def payments_list():

        status_filter = request.args.get("status", "pending")
        q_list = [v for v in request.args.getlist("q") if v.strip()]

        all_purchases = Purchase.query.order_by(Purchase.date.desc()).all()

        if status_filter == "paid":
            purchases = [p for p in all_purchases if p.payment_status() == "Paid"]
        elif status_filter == "unpaid":
            purchases = [p for p in all_purchases if p.payment_status() == "Unpaid"]
        elif status_filter == "partial":
            purchases = [p for p in all_purchases if p.payment_status() == "Partial"]
        else:
            purchases = [p for p in all_purchases if p.payment_status() in ["Unpaid", "Partial"]]

        if q_list:
            purchases = [p for p in purchases if p.vendor_name in q_list]

        clients = Client.query.order_by(Client.name).all()

        return render_template(
            "payments_list.html",
            purchases=purchases,
            status_filter=status_filter,
            q_list=q_list,
            clients=clients
        )




    @app.route("/reports/vendor-dues")
    def vendor_dues_report():

        purchases = Purchase.query.all()

        report = {}

        for p in purchases:
            vendor = p.vendor_name

            if vendor not in report:
                report[vendor] = {
                    "total_purchase": 0,
                    "total_paid": 0,
                    "balance": 0
                }

            report[vendor]["total_purchase"] += p.total_cost()
            report[vendor]["total_paid"] += p.total_paid()
            report[vendor]["balance"] += p.balance_due()

        return render_template(
            "vendor_dues_report.html",
            report=report
        )


    @app.route("/outstanding-report")
    def outstanding_report():

        vendor_report = get_vendor_dues()
        client_report = get_sales_outstanding()

        return render_template(
            "outstanding_report.html",
            vendor_report=vendor_report,
            client_report=client_report
        )

    @app.route("/reports/profitability")
    def party_profitability():
        sales = Sale.query.all()
        report = {}
        
        for s in sales:
            client = s.client_name
            if client not in report:
                report[client] = {
                    "revenue": 0,
                    "cost": 0,
                    "profit": 0,
                    "qty": 0
                }
            
            revenue = s.total_sp()
            # Loaded Cost = Item Cost + Freight + Misc
            cost = s.total_cp() + (s.freight or 0) + (s.misc_amount or 0)
            
            report[client]["revenue"] += revenue
            report[client]["cost"] += cost
            report[client]["profit"] += (revenue - cost)
            report[client]["qty"] += s.total_qty
            
        # Add margin percentage
        for client in report:
            rev = report[client]["revenue"]
            profit = report[client]["profit"]
            report[client]["margin_pct"] = (profit / rev * 100) if rev != 0 else 0

        # Sort by profit descending
        sorted_report = dict(sorted(report.items(), key=lambda x: x[1]['profit'], reverse=True))

        return render_template("party_profitability_report.html", report=sorted_report)

    @app.route("/reports/payment-aging")
    def payment_aging():
        sales = Sale.query.all()
        today = datetime.now().date()
        
        buckets = {
            "0-15 Days": {"amount": 0, "count": 0},
            "16-30 Days": {"amount": 0, "count": 0},
            "31+ Days": {"amount": 0, "count": 0}
        }
        
        detail_list = []
        
        for s in sales:
            balance = s.balance_due()
            if balance > 0:
                age = (today - s.date).days
                if age <= 15:
                    bucket = "0-15 Days"
                elif age <= 30:
                    bucket = "16-30 Days"
                else:
                    bucket = "31+ Days"
                
                buckets[bucket]["amount"] += balance
                buckets[bucket]["count"] += 1
                
                detail_list.append({
                    "id": s.id,
                    "date": s.date,
                    "client": s.client_name,
                    "balance": balance,
                    "age": age,
                    "bucket": bucket
                })
        
        # Sort details by age descending
        detail_list.sort(key=lambda x: x['age'], reverse=True)
        
        total_outstanding = sum(b["amount"] for b in buckets.values())
        
        # Add percentages
        for b in buckets:
            amt = buckets[b]["amount"]
            buckets[b]["pct"] = (amt / total_outstanding * 100) if total_outstanding > 0 else 0

        return render_template("payment_aging_report.html", 
                               buckets=buckets, 
                               details=detail_list,
                               total_outstanding=total_outstanding)

    @app.route("/reports/expense-analysis")
    def expense_analysis():
        expenses = Expense.query.all()
        
        report = {}
        total_amount = 0
        
        for e in expenses:
            cat = e.category
            if cat not in report:
                report[cat] = {
                    "amount": 0,
                    "count": 0
                }
            
            report[cat]["amount"] += e.amount
            report[cat]["count"] += 1
            total_amount += e.amount
            
        # Add percentages and format
        for cat in report:
            amt = report[cat]["amount"]
            report[cat]["pct"] = (amt / total_amount * 100) if total_amount > 0 else 0
            
        # Sort by amount descending
        sorted_report = dict(sorted(report.items(), key=lambda x: x[1]['amount'], reverse=True))

        return render_template("expense_analysis_report.html", 
                               report=sorted_report, 
                               total_amount=total_amount)

    # Products & Stock
    @app.route("/products", methods=["GET", "POST"])
    def products_list():
        if request.method == "POST":
            name = request.form.get("name")
            min_stock = float(request.form.get("min_stock") or 0)
            if name:
                p = Product(name=name, min_stock_kg=min_stock)
                db.session.add(p)
                db.session.commit()
                flash(f"Product {name} added", "success")
            return redirect(url_for("products_list"))
        
        products = Product.query.order_by(Product.name.asc()).all()
        return render_template("products_list.html", products=products)

    @app.route("/product/<int:id>/delete", methods=["POST"])
    def delete_product(id):
        p = Product.query.get_or_404(id)
        db.session.delete(p)
        db.session.commit()
        flash("Product deleted", "info")
        return redirect(url_for("products_list"))

    @app.route("/reports/stock")
    def stock_report():
        products = Product.query.all()
        return render_template("stock_report.html", products=products)

    @app.route("/reports/monthly-pivot")
    def monthly_pivot_report():
        from collections import defaultdict

        # --- Determine selected month ---
        now = datetime.now()
        default_ym = now.strftime("%Y-%m")
        ym = (request.args.get("ym") or default_ym).strip()
        try:
            sel_year, sel_month = int(ym[:4]), int(ym[5:7])
        except (ValueError, IndexError):
            ym = default_ym
            sel_year, sel_month = now.year, now.month

        # --- All available months (for dropdown) ---
        months_raw = db.session.execute(
            text("SELECT DISTINCT strftime('%Y-%m', date) AS ym FROM sale ORDER BY ym DESC")
        ).mappings().all()
        available_months = [r["ym"] for r in months_raw]
        if ym not in available_months:
            available_months.insert(0, ym)

        # --- Fetch sale items for the selected month ---
        rows = db.session.execute(
            text("""
                SELECT
                    s.client_name,
                    COALESCE(p.name, 'Unknown') AS product_name,
                    ROUND(SUM(si.quantity_kg), 2) AS qty_kg
                FROM sale_item si
                JOIN sale s ON si.sale_id = s.id
                LEFT JOIN product p ON si.product_id = p.id
                WHERE strftime('%Y-%m', s.date) = :ym
                GROUP BY s.client_name, p.name
                ORDER BY s.client_name, p.name
            """),
            {"ym": ym}
        ).mappings().all()

        # --- Build pivot: {client: {product: qty_kg}} ---
        pivot = defaultdict(lambda: defaultdict(float))
        products_set = set()
        for r in rows:
            pivot[r["client_name"]][r["product_name"]] += float(r["qty_kg"] or 0)
            products_set.add(r["product_name"])

        clients = sorted(pivot.keys())
        products_list = sorted(products_set)

        # Row totals
        row_totals = {c: round(sum(pivot[c].values()), 2) for c in clients}
        # Column totals
        col_totals = {p: round(sum(pivot[c].get(p, 0) for c in clients), 2) for p in products_list}
        grand_total = round(sum(row_totals.values()), 2)

        # Convert defaultdict to plain dict for template
        pivot_plain = {c: dict(pivot[c]) for c in clients}

        # Pretty label for selected month
        try:
            sel_label = datetime(sel_year, sel_month, 1).strftime("%B %Y")
        except Exception:
            sel_label = ym

        return render_template(
            "monthly_pivot_report.html",
            ym=ym,
            sel_label=sel_label,
            available_months=available_months,
            clients=clients,
            products_list=products_list,
            pivot=pivot_plain,
            row_totals=row_totals,
            col_totals=col_totals,
            grand_total=grand_total,
        )


    # Reports & Export
    @app.route("/reports")
    def reports():
        client_rows_sql = text(
            """
            SELECT sale.client_name as client_name,
                   ROUND(SUM(sale_item.quantity_kg), 2) AS qty_kg,
                   ROUND(SUM(sale_item.selling_rate_per_kg * sale_item.quantity_kg), 2) AS sp
            FROM sale_item JOIN sale ON sale_item.sale_id = sale.id
            GROUP BY client_name
            ORDER BY sp DESC
            """
        )
        client_rows = db.session.execute(client_rows_sql).mappings().all()

        all_sales = Sale.query.all()
        client_pl = {}
        for s in all_sales:
            d = client_pl.setdefault(s.client_name, {"cp": 0.0, "pl": 0.0})
            d["cp"] += s.total_cp()
            d["pl"] += s.pl()

        enriched = []
        for row in client_rows:
            name = row["client_name"]
            cp_val = round(client_pl.get(name, {}).get("cp", 0.0), 2)
            pl_val = round(client_pl.get(name, {}).get("pl", 0.0), 2)
            enriched.append(
                {"client_name": name, "qty_kg": row["qty_kg"], "sp": row["sp"], "cp": cp_val, "pl": pl_val}
            )

        totals = {
            "qty_kg": round(sum(x["qty_kg"] for x in enriched), 2),
            "sp": round(sum(x["sp"] for x in enriched), 2),
            "cp": round(sum(x["cp"] for x in enriched), 2),
            "pl": round(sum(x["pl"] for x in enriched), 2),
        }

        return render_template("reports.html", rows=enriched, totals=totals)

    @app.route("/export.csv")
    def export_csv():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            ["Date", "Client Name", "Quantity (kg)", "Rate/ kg (cost)", "Selling Rate/kg", "Freight", "SP Total", "CP (auto)", "P/L (auto)"]
        )
        for sale in Sale.query.order_by(Sale.date.asc(), Sale.id.asc()).all():
            for s in sale.items:
                writer.writerow(
                    [
                        sale.date.isoformat(),
                        sale.client_name,
                        round(s.quantity_kg, 2),
                        s.cost_rate_per_kg,
                        s.selling_rate_per_kg,
                        sale.freight,
                        round((s.selling_rate_per_kg or 0.0) * (s.quantity_kg or 0.0), 2),
                        round((s.cost_rate_per_kg or 0.0) * (s.quantity_kg or 0.0), 2),
                        round(
                            ((s.selling_rate_per_kg or 0.0) * (s.quantity_kg or 0.0))
                            - ((s.cost_rate_per_kg or 0.0) * (s.quantity_kg or 0.0)),
                            2,
                        ),
                    ]
                )

        mem = io.BytesIO()
        mem.write(output.getvalue().encode("utf-8"))
        mem.seek(0)
        fname = f"hcl_sales_export_{datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%Y%m%d_%H%M%S')}.csv"
        return send_file(mem, as_attachment=True, download_name=fname, mimetype="text/csv")

    # Bottle types
    @app.route("/bottles")
    def bottles_list():
        q = (request.args.get("q") or "").strip()
        query = BottleType.query
        if q:
            query = query.filter(BottleType.label.ilike(f"%{q}%"))
        rows = query.order_by(BottleType.quantity_ltr.asc()).all()
        return render_template("bottle_list.html", rows=rows, q=q)

    @app.route("/bottles/new", methods=["GET", "POST"])
    @app.route("/bottles/<int:bt_id>/edit", methods=["GET", "POST"])
    def bottles_form(bt_id=None):
        bt = BottleType.query.get(bt_id) if bt_id else None
        if request.method == "POST":
            label = (request.form.get("label") or "").strip()
            quantity_ltr = _to_float(request.form.get("quantity_ltr"), 0.0)
            bottles_in_batch = _to_int(request.form.get("bottles_in_batch"), 1)
            can_price = _to_float(request.form.get("can_price"), 0.0)
            box_cost = _to_float(request.form.get("box_cost"), 0.0)
            selling_price_per_batch = _to_float(request.form.get("selling_price_per_batch"), 0.0)
            price_per_kg = _to_float(request.form.get("price_per_kg"), 0.0)

            if not label:
                flash("Label (e.g. '1 ltr') is required", "danger")
                return render_template("bottle_form.html", bt=bt)

            try:
                if not bt:
                    bt = BottleType(
                        label=label,
                        quantity_ltr=quantity_ltr,
                        bottles_in_batch=bottles_in_batch,
                        can_price=can_price,
                        box_cost=box_cost,
                        selling_price_per_batch=selling_price_per_batch,
                        price_per_kg=price_per_kg,
                    )
                    db.session.add(bt)
                else:
                    bt.label = label
                    bt.quantity_ltr = quantity_ltr
                    bt.bottles_in_batch = bottles_in_batch
                    bt.can_price = can_price
                    bt.box_cost = box_cost
                    bt.selling_price_per_batch = selling_price_per_batch
                    bt.price_per_kg = price_per_kg

                commit_or_rollback()
                flash("Bottle type saved", "success")
                return redirect(url_for("bottles_list"))
            except Exception as exc:
                flash(f"Error: {exc}", "danger")
        return render_template("bottle_form.html", bt=bt)

    @app.route("/bottles/<int:bt_id>/delete", methods=["POST"])
    def bottles_delete(bt_id):
        bt = BottleType.query.get_or_404(bt_id)
        try:
            db.session.delete(bt)
            commit_or_rollback()
            flash("Deleted bottle type", "info")
        except Exception as exc:
            flash(f"Error: {exc}", "danger")
        return redirect(url_for("bottles_list"))


    # --- Leads / Locations UI + API ---
    DEAL_CHOICES = ["Need To Visit", "In Discussion", "Deal Closed", "Deal Rejected"]

    @app.route("/leads")
    def leads_page():
        # renders page. JS will call the APIs below.
        return render_template("leads.html", deal_choices=DEAL_CHOICES)

        loc = Location.query.get_or_404(loc_id)
        try:
            db.session.delete(loc)
            commit_or_rollback()
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        return "", 204

    # Leads API
    @app.route("/api/leads", methods=["GET"])
    def api_leads_list():
        location_id = request.args.get("location_id", type=int)
        deal_status_param = request.args.get("deal_status")  # comma-separated string if multiple selected

        # Start query
        query = Lead.query.order_by(Lead.created_at.desc())

        # Optional: filter by location
        if location_id:
            query = query.filter(Lead.location_id == location_id)

        # Optional: filter by deal status (multi-select)
        if deal_status_param:
            # Example: "Need To Visit,Deal Closed"
            statuses = [s.strip() for s in deal_status_param.split(",") if s.strip()]
            if statuses:
                query = query.filter(Lead.deal_status.in_(statuses))

        # Fetch rows
        rows = query.all()

        # Optional debug print
        print(json.dumps([r.to_dict() for r in rows], indent=2))

        # Return JSON
        return jsonify([r.to_dict() for r in rows])

    @app.route("/api/leads", methods=["POST"])
    def api_leads_create():
        data = request.json or request.form
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name required"}), 400
        location_id = data.get("location_id") or None
        if location_id == "":
            location_id = None
        if location_id:
            try:
                location_id = int(location_id)
            except Exception:
                location_id = None
        indiamart_link = (data.get("indiamart_link") or "").strip() or None
        deal_status = (data.get("deal_status") or "").strip() or None
        comments = (data.get("comments") or "").strip() or None
        address = (data.get("address") or "").strip() or None

        lead = Lead(
            name=name,
            location_id=location_id,
            indiamart_link=indiamart_link,
            deal_status=deal_status,
            comments=comments,
            address=address
        )
        db.session.add(lead)
        try:
            commit_or_rollback()
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        return jsonify(lead.to_dict()), 201

    @app.route("/api/leads/<int:lead_id>", methods=["PUT", "PATCH"])
    def api_leads_update(lead_id):
        lead = Lead.query.get_or_404(lead_id)
        data = request.json or request.form
        # update only provided fields
        if "name" in data:
            lead.name = (data.get("name") or "").strip()
        if "location_id" in data:
            locid = data.get("location_id")
            if locid == "":
                lead.location_id = None
            else:
                try:
                    lead.location_id = int(locid) if locid is not None else None
                except Exception:
                    lead.location_id = None
        if "indiamart_link" in data:
            lead.indiamart_link = (data.get("indiamart_link") or "").strip() or None
        if "deal_status" in data:
            lead.deal_status = (data.get("deal_status") or "").strip() or None
        if "comments" in data:
            lead.comments = (data.get("comments") or "").strip() or None
        if "address" in data:
            lead.address = (data.get("address") or "").strip() or None

        try:
            commit_or_rollback()
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        return jsonify(lead.to_dict()), 200

    @app.route("/api/leads/<int:lead_id>", methods=["DELETE"])
    def api_leads_delete(lead_id):
        lead = Lead.query.get_or_404(lead_id)
        try:
            db.session.delete(lead)
            commit_or_rollback()
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        return "", 204

    # -------------------------
    # Locations standalone page
    # -------------------------
    @app.route("/locations")
    def locations_page():
        # renders a dedicated locations management page
        return render_template("locations.html")

    # API: list/create/update/delete locations (reusable by leads page)
    @app.route("/api/locations", methods=["GET"])
    def api_locations_list():
        rows = Location.query.order_by(Location.name.asc()).all()
        out = [{"id": r.id, "name": r.name} for r in rows]
        return jsonify(out)

    @app.route("/api/locations", methods=["POST"])
    def api_locations_create():
        data = request.json or request.form
        print(data)
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name required"}), 400
        existing = Location.query.filter_by(name=name).first()
        if existing:
            return jsonify({"error": "already exists"}), 400
        loc = Location(name=name)
        db.session.add(loc)
        try:
            commit_or_rollback()
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        return jsonify({"id": loc.id, "name": loc.name}), 201

    @app.route("/api/locations/<int:loc_id>", methods=["DELETE"])
    def api_locations_delete(loc_id):
        loc = Location.query.get_or_404(loc_id)
        try:
            db.session.delete(loc)
            commit_or_rollback()
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        return "", 204

    @app.route("/api/locations/<int:loc_id>", methods=["PUT", "PATCH"])
    def api_locations_update(loc_id):
        loc = Location.query.get_or_404(loc_id)
        data = request.json or request.form
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name required"}), 400
        # check uniqueness
        other = Location.query.filter(Location.name == name, Location.id != loc.id).first()
        if other:
            return jsonify({"error": "another location with same name exists"}), 400
        loc.name = name
        try:
            commit_or_rollback()
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        return jsonify({"id": loc.id, "name": loc.name})



    @app.route("/expenses")
    def expenses_list():

        q = (request.args.get("q") or "").strip()

        query = Expense.query

        if q:
            query = query.filter(
                Expense.category.ilike(f"%{q}%")
            )

        expenses = query.order_by(
            Expense.date.desc(),
            Expense.id.desc()
        ).all()

        total = sum(e.amount for e in expenses)

        return render_template(
            "expenses_list.html",
            expenses=expenses,
            total=round(total,2),
            q=q
        )




    @app.route("/expenses/new", methods=["GET","POST"])
    @app.route("/expenses/<int:expense_id>/edit", methods=["GET","POST"])
    def expenses_form(expense_id=None):

        expense = Expense.query.get(expense_id) if expense_id else None

        if request.method == "POST":
            try:
                date = _parse_date(request.form.get("date"))
                category = request.form.get("category")
                description = request.form.get("description")
                amount = float(request.form.get("amount"))
                mode = request.form.get("mode")

                if not expense:
                    expense = Expense(
                        date=date,
                        category=category,
                        description=description,
                        amount=amount,
                        mode=mode
                    )
                    db.session.add(expense)
                else:
                    expense.date = date
                    expense.category = category
                    expense.description = description
                    expense.amount = amount
                    expense.mode = mode

                commit_or_rollback()

                flash("Expense saved", "success")
                return redirect(url_for("expenses_list"))

            except Exception as exc:
                flash(str(exc), "danger")

        return render_template(
            "expense_form.html",
            expense=expense,
            categories=EXPENSE_CATEGORIES
        )



    @app.route("/expenses/<int:expense_id>/delete", methods=["POST"])
    def expenses_delete(expense_id):

        expense = Expense.query.get_or_404(expense_id)

        db.session.delete(expense)
        commit_or_rollback()

        flash("Expense deleted", "info")

        return redirect(url_for("expenses_list"))


# -----------------------------------------------------------------------------
# CLI helpers
# -----------------------------------------------------------------------------
def register_cli(app: Flask) -> None:
    @app.cli.command("init-db")
    def init_db():
        db.create_all()
        print("Database initialized OK")

    @app.cli.command("seed-bottles")
    def seed_bottles():
        data = [
            {"label": "1 ltr", "quantity_ltr": 1.0, "bottles_in_batch": 12, "can_price": 4.25, "price_per_kg": 9.0, "box_cost": 21, "selling_price_per_batch": 170},
            {"label": "0.5 ltr", "quantity_ltr": 0.5, "bottles_in_batch": 24, "can_price": 6.0, "price_per_kg": 9.0, "box_cost": 21, "selling_price_per_batch": 220},
            {"label": "5 ltr", "quantity_ltr": 5.0, "bottles_in_batch": 1, "can_price": 15.0, "price_per_kg": 9.0, "box_cost": 0.0, "selling_price_per_batch": 80},
        ]
        created = 0
        for d in data:
            existing = BottleType.query.filter_by(label=d["label"]).first()
            if existing:
                existing.quantity_ltr = d["quantity_ltr"]
                existing.bottles_in_batch = d["bottles_in_batch"]
                existing.can_price = d["can_price"]
                existing.price_per_kg = d["price_per_kg"]
                existing.box_cost = d["box_cost"]
                existing.selling_price_per_batch = d["selling_price_per_batch"]
            else:
                bt = BottleType(**d)
                db.session.add(bt)
                created += 1
        commit_or_rollback()
        print(f"Seeded bottle master. Created: {created}")
    

    # ── Loans ──────────────────────────────────────────────────────────────────
    @app.route("/loans", methods=["GET", "POST"])
    def loans_list():
        if request.method == "POST":
            party    = (request.form.get("party_name") or "").strip()
            ltype    = request.form.get("loan_type") or "given"
            principal = _to_float(request.form.get("principal"), 0.0)
            rate     = _to_float(request.form.get("interest_rate"), 0.0)
            date_str = request.form.get("date_issued") or ""
            due_str  = request.form.get("due_date") or ""
            notes    = (request.form.get("notes") or "").strip()

            if not party or principal <= 0:
                flash("Party name and principal amount are required.", "warning")
                return redirect(url_for("loans_list"))

            try:
                issued = _parse_date(date_str)
            except Exception:
                flash("Invalid issue date.", "danger")
                return redirect(url_for("loans_list"))

            due = None
            if due_str:
                try:
                    due = _parse_date(due_str)
                except Exception:
                    pass

            loan = Loan(
                loan_type=ltype,
                party_name=party,
                principal=principal,
                interest_rate=rate,
                date_issued=issued,
                due_date=due,
                notes=notes or None,
            )
            db.session.add(loan)
            commit_or_rollback()
            flash(f"Loan added for {party}.", "success")
            return redirect(url_for("loans_list"))

        # GET: build summary and list
        filter_type = request.args.get("type", "all")   # all / given / taken
        filter_status = request.args.get("status", "active")  # active / closed / all

        query = Loan.query
        if filter_type in ("given", "taken"):
            query = query.filter_by(loan_type=filter_type)

        loans = query.order_by(Loan.date_issued.desc()).all()

        if filter_status == "active":
            loans = [l for l in loans if not l.is_closed]
        elif filter_status == "closed":
            loans = [l for l in loans if l.is_closed]

        # Summary totals (all active loans)
        all_active = Loan.query.filter_by(is_closed=False).all()
        total_given_out = round(sum(l.outstanding() for l in all_active if l.loan_type == "given"), 2)
        total_taken_out = round(sum(l.outstanding() for l in all_active if l.loan_type == "taken"), 2)

        today = datetime.now().date().isoformat()
        clients = Client.query.order_by(Client.name).all()
        return render_template(
            "loans.html",
            loans=loans,
            filter_type=filter_type,
            filter_status=filter_status,
            total_given_out=total_given_out,
            total_taken_out=total_taken_out,
            today=today,
            clients=clients,
        )

    @app.route("/loans/<int:loan_id>", methods=["GET"])
    def loan_detail(loan_id):
        loan = Loan.query.get_or_404(loan_id)
        # Build running balance for repayment table
        balance = loan.total_due()
        timeline = []
        for r in loan.repayments:
            balance = round(balance - r.amount, 2)
            timeline.append({"repayment": r, "balance": balance})
        today = datetime.now().date().isoformat()
        return render_template("loan_detail.html", loan=loan, timeline=timeline, today=today)

    @app.route("/loans/<int:loan_id>/repay", methods=["POST"])
    def loan_repay(loan_id):
        loan = Loan.query.get_or_404(loan_id)
        amount = _to_float(request.form.get("amount"), 0.0)
        date_str = request.form.get("date") or ""
        mode = (request.form.get("mode") or "").strip() or None
        notes = (request.form.get("notes") or "").strip() or None

        if amount <= 0:
            flash("Repayment amount must be > 0.", "warning")
            return redirect(url_for("loan_detail", loan_id=loan_id))
        try:
            rdate = _parse_date(date_str)
        except Exception:
            flash("Invalid date.", "danger")
            return redirect(url_for("loan_detail", loan_id=loan_id))

        rep = LoanRepayment(loan_id=loan_id, date=rdate, amount=amount, mode=mode, notes=notes)
        db.session.add(rep)
        # Auto-close if fully repaid
        if loan.total_repaid() + amount >= loan.total_due():
            loan.is_closed = True
        commit_or_rollback()
        flash(f"Repayment of ₹{amount:,.2f} recorded.", "success")
        return redirect(url_for("loan_detail", loan_id=loan_id))

    @app.route("/loans/<int:loan_id>/close", methods=["POST"])
    def loan_close(loan_id):
        loan = Loan.query.get_or_404(loan_id)
        loan.is_closed = True
        commit_or_rollback()
        flash("Loan marked as closed.", "success")
        return redirect(url_for("loan_detail", loan_id=loan_id))

    @app.route("/loans/<int:loan_id>/delete", methods=["POST"])
    def loan_delete(loan_id):
        loan = Loan.query.get_or_404(loan_id)
        db.session.delete(loan)
        commit_or_rollback()
        flash("Loan deleted.", "info")
        return redirect(url_for("loans_list"))

    @app.route("/loans/<int:loan_id>/repayments/<int:rep_id>/delete", methods=["POST"])
    def loan_repayment_delete(loan_id, rep_id):
        rep = LoanRepayment.query.get_or_404(rep_id)
        db.session.delete(rep)
        # Re-open if was auto-closed
        loan = Loan.query.get_or_404(loan_id)
        loan.is_closed = False
        commit_or_rollback()
        flash("Repayment deleted.", "info")
        return redirect(url_for("loan_detail", loan_id=loan_id))


# -----------------------------------------------------------------------------
# Run (local dev)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5002, debug=True)



# -----------------------------------------------------------------------------
# Run (local dev)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5002, debug=True)
