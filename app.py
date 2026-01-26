# app.py (secure + mobile tweaks + SP override fix)
import io
import csv
import os
from datetime import datetime, timedelta
from dateutil import tz
from typing import Optional

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

    def __repr__(self) -> str:
        return f"<Client {self.name}>"


class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    client_name = db.Column(db.String(160), nullable=False)  # denormalized
    freight = db.Column(db.Float, nullable=False, default=0.0)
    quantity_kg = db.Column(db.Float, nullable=False, default=0.0, server_default="0.0")
    sale_type = db.Column(db.String(16), nullable=False, default="bill")   # <— NEW
    
    items = db.relationship("SaleItem", backref="sale", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Sale {self.id} {self.date} {self.client_name}>"

    @property
    def total_qty(self) -> float:
        return sum((i.quantity_kg or 0.0) for i in self.items)

    def total_cp(self) -> float:
        total = sum((i.cost_rate_per_kg or 0.0) * (i.quantity_kg or 0.0) for i in self.items)
        total += (self.freight or 0.0)
        return round(total, 2)

    def total_sp(self) -> float:
        total = sum((i.selling_rate_per_kg or 0.0) * (i.quantity_kg or 0.0) for i in self.items)
        return round(total, 2)

    def pl(self) -> float:
        return round(self.total_sp() - self.total_cp(), 2)


class SaleItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sale.id"), nullable=False)
    bottle_type_id = db.Column(db.Integer, db.ForeignKey("bottle_type.id"), nullable=True) 
    quantity_kg = db.Column(db.Float, nullable=False, default=0.0)  # for bottles = num_batches
    cost_rate_per_kg = db.Column(db.Float, nullable=False, default=0.0)
    selling_rate_per_kg = db.Column(db.Float, nullable=True, default=0.0)

    def __repr__(self) -> str:
        return f"<SaleItem {self.quantity_kg}kg cost={self.cost_rate_per_kg} sp={self.selling_rate_per_kg}>"


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
            "address": self.address,                                # <-- NEW
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<Lead {self.name} @ {self.location_id}>"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=True)
    indiamart_link = db.Column(db.String(1024), nullable=True)
    deal_status = db.Column(db.String(64), nullable=True)
    comments = db.Column(db.Text, nullable=True)
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
        # Latest sales listing
        latest = Sale.query.order_by(Sale.date.desc(), Sale.id.desc()).limit(10).all()


        totals = db.session.execute(
            text(
                """
                SELECT
                ROUND(SUM(qty_kg), 2) AS total_qty,
                ROUND(SUM(sp), 2) AS total_sp,
                ROUND(SUM(cp), 2) AS total_cp,
                ROUND(SUM(freight), 2) AS total_freight
                FROM (
                  SELECT
                    sale.id,
                    SUM(sale_item.quantity_kg) AS qty_kg,
                    SUM(sale_item.selling_rate_per_kg * sale_item.quantity_kg) AS sp,
                    SUM(sale_item.cost_rate_per_kg * sale_item.quantity_kg) AS cp,
                    COALESCE(sale.freight, 0) AS freight
                  FROM sale
                  JOIN sale_item ON sale_item.sale_id = sale.id
                  GROUP BY sale.id
                ) per_sale
                """
            )
        ).mappings().first()

        total_qty = float(totals["total_qty"] or 0)
        total_sp = float(totals["total_sp"] or 0)
        total_cp = float(totals["total_cp"] or 0)
        total_pl = round(total_sp - total_cp, 2)
        total_freight = float(totals["total_freight"] or 0)

        # --- Monthly (last 6) using same per-sale method, aggregated by month ---
        monthly = db.session.execute(
            text(
                """
                SELECT ym,
                    ROUND(SUM(qty_kg), 2) AS qty_kg,
                    ROUND(SUM(sp), 2) AS sp,
                    ROUND(SUM(cp), 2) AS cp,
                    ROUND(SUM(freight), 2) AS freight
                FROM (
                  SELECT
                    strftime('%Y-%m', sale.date) AS ym,
                    sale.id,
                    SUM(sale_item.quantity_kg) AS qty_kg,
                    SUM(sale_item.selling_rate_per_kg * sale_item.quantity_kg) AS sp,
                    SUM(sale_item.cost_rate_per_kg * sale_item.quantity_kg) AS cp,
                    COALESCE(sale.freight, 0) AS freight
                  FROM sale
                  JOIN sale_item ON sale_item.sale_id = sale.id
                  GROUP BY sale.id
                ) per_sale
                GROUP BY ym
                ORDER BY ym DESC
                LIMIT 6
                """
            )
        ).mappings().all()

        monthly = [
            {
                "ym": m["ym"],
                "qty_kg": float(m["qty_kg"] or 0),
                "sp": float(m["sp"] or 0),
                "cp": float(m["cp"] or 0),
                "freight": float(m["freight"] or 0),
                "pl": round((float(m["sp"] or 0) - float(m["cp"] or 0)), 2),
            }
            for m in monthly
        ]

        # --- Current month (same per-sale approach) ---
        current_ym = datetime.now().strftime("%Y-%m")
        current = db.session.execute(
            text(
                """
                SELECT
                ROUND(SUM(qty_kg), 2) AS qty_kg,
                ROUND(SUM(sp), 2) AS sp,
                ROUND(SUM(cp), 2) AS cp,
                ROUND(SUM(freight), 2) AS freight
                FROM (
                  SELECT
                    sale.id,
                    SUM(sale_item.quantity_kg) AS qty_kg,
                    SUM(sale_item.selling_rate_per_kg * sale_item.quantity_kg) AS sp,
                    SUM(sale_item.cost_rate_per_kg * sale_item.quantity_kg) AS cp,
                    COALESCE(sale.freight, 0) AS freight
                  FROM sale
                  JOIN sale_item ON sale_item.sale_id = sale.id
                  WHERE strftime('%Y-%m', sale.date) = :ym
                  GROUP BY sale.id
                ) per_sale
                """
            ),
            {"ym": current_ym},
        ).mappings().first()

        current_data = {
            "ym": current_ym,
            "qty": float(current["qty_kg"] or 0),
            "sp": float(current["sp"] or 0),
            "cp": float(current["cp"] or 0),
            "freight": float(current["freight"] or 0),
            "pl": round((float(current["sp"] or 0) - float(current["cp"] or 0)), 2),
        }

        return render_template(
            "index.html",
            total_qty=round(total_qty or 0.0, 2),
            total_cp=round(total_cp, 2),
            total_sp=round(total_sp, 2),
            total_pl=total_pl,
            total_freight=round(total_freight, 2),
            latest=latest,
            monthly=monthly,
            current_data=current_data,
        )

    # Clients
    @app.route("/clients")
    def clients_list():
        q = (request.args.get("q") or "").strip()
        query = Client.query
        if q:
            query = query.filter(Client.name.ilike(f"%{q}%"))
        rows = query.order_by(Client.name.asc()).all()
        return render_template("clients_list.html", rows=rows, q=q)

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
            if not name:
                flash("Client name is required", "danger")
                return render_template("clients_form.html", client=client)
            try:
                if not client:
                    client = Client(name=name, address=address, gst=gst)
                    db.session.add(client)
                else:
                    client.name = name
                    client.address = address
                    client.gst = gst
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

    # Sales - create/edit
    @app.route("/sales/new", methods=["GET", "POST"])
    @app.route("/sales/<int:sale_id>/edit", methods=["GET", "POST"])
    def sales_form(sale_id=None):
        sale = Sale.query.get(sale_id) if sale_id else None
        clients = Client.query.order_by(Client.name.asc()).all()
        bottle_types = BottleType.query.order_by(BottleType.quantity_ltr.asc()).all()

        if request.method == "POST":
            try:
                date_val = _parse_date(request.form.get("date") or "")
                sale_type = (request.form.get("sale_type") or "bill").strip().lower()

                # client name
                client_id = request.form.get("client_id")
                if client_id:
                    found = Client.query.get(int(client_id))
                    chosen_name = found.name if found else (request.form.get("client_name") or "").strip()
                else:
                    chosen_name = (request.form.get("client_name") or "").strip()

                if not chosen_name:
                    raise ValueError("Client is required")

                freight = _to_float(request.form.get("freight"), 0.0)

                # create or update sale
                if not sale:
                    sale = Sale(date=date_val, client_name=chosen_name, freight=freight, sale_type=sale_type)
                    db.session.add(sale)
                    db.session.flush()
                else:
                    sale.date = date_val
                    sale.client_name = chosen_name
                    sale.freight = freight
                    sale.sale_type = sale_type        
                    SaleItem.query.filter_by(sale_id=sale.id).delete()

                # CASH (bottle mode)
                if sale_type == "cash":
                    bt_ids = request.form.getlist("bottle_type_id[]")
                    batches_list = request.form.getlist("batches[]")
                    sp_overrides = request.form.getlist("sp_batch[]")

                    total_batches = 0.0
                    any_added = False

                    for i in range(len(bt_ids)):
                        bt_id = (bt_ids[i] or "").strip()
                        if not bt_id:
                            continue

                        bt = BottleType.query.get(int(bt_id))
                        if not bt:
                            raise ValueError("Invalid bottle type selected")

                        num_batches = _to_int(batches_list[i] if i < len(batches_list) else 0, 0)
                        if num_batches <= 0:
                            continue

                        submitted_sp = sp_overrides[i] if i < len(sp_overrides) else ""
                        if submitted_sp and submitted_sp.strip():
                            try:
                                chosen_sp = float(submitted_sp)
                            except Exception:
                                chosen_sp = bt.sp_per_batch()
                        else:
                            chosen_sp = bt.sp_per_batch()

                        item = SaleItem(
                            sale_id=sale.id,
                            bottle_type_id=bt.id,       
                            quantity_kg=float(num_batches),
                            cost_rate_per_kg=float(bt.cp_per_batch()),
                            selling_rate_per_kg=float(chosen_sp),
                        )
                        db.session.add(item)
                        total_batches += num_batches
                        any_added = True

                    if not any_added:
                        raise ValueError("At least one bottle line is required")

                    sale.quantity_kg = total_batches

                # BILL (freeform)
                else:
                    quantities = request.form.getlist("quantity[]")
                    units = request.form.getlist("unit[]")
                    cost_rates = request.form.getlist("cost_rate[]")
                    sell_rates = request.form.getlist("sell_rate[]")

                    if not quantities:
                        raise ValueError("At least one line item is required")

                    total_qty = 0.0
                    for q_val, u_val, cr, sr in zip(quantities, units, cost_rates, sell_rates):
                        qty_kg = to_kg(q_val or 0, u_val or "kg")
                        total_qty += qty_kg
                        item = SaleItem(
                            sale_id=sale.id,
                            quantity_kg=qty_kg,
                            cost_rate_per_kg=_to_float(cr, 0.0),
                            selling_rate_per_kg=_to_float(sr, 0.0),
                        )
                        db.session.add(item)

                    sale.quantity_kg = total_qty

                commit_or_rollback()
                flash("Saved successfully", "success")
                return redirect(url_for("sales_list"))
            except Exception as exc:
                db.session.rollback()
                flash(f"Error: {exc}", "danger")

        # Detect sale_type for edit mode

        if sale and getattr(sale, "sale_type", None):
            computed_sale_type = sale.sale_type
        else:
            # fallback heuristic for very old rows without sale_type
            computed_sale_type = "bill"
            if sale and sale.items:
                def looks_like_bottle(item):
                    is_int_batches = abs(item.quantity_kg - round(item.quantity_kg)) < 1e-6
                    cp_match = any(
                        abs((item.cost_rate_per_kg or 0.0) - bt.cp_per_batch()) < 0.5
                        for bt in bottle_types
                    )
                    return is_int_batches and cp_match

                if all(looks_like_bottle(i) for i in sale.items):
                    computed_sale_type = "cash"

        return render_template(
            "sales_form.html",
            sale=sale,
            clients=clients,
            bottle_types=bottle_types,
            sale_type=computed_sale_type,
        )

    @app.route("/sales")
    def sales_list():
        sales = Sale.query.order_by(Sale.date.desc(), Sale.id.desc()).all()
        return render_template("sales_list.html", rows=sales)

    @app.route("/sales/<int:sale_id>/delete", methods=["POST"])
    def sales_delete(sale_id):
        sale = Sale.query.get_or_404(sale_id)
        try:
            db.session.delete(sale)
            commit_or_rollback()
            flash("Deleted", "info")
        except Exception as exc:
            flash(f"Error: {exc}", "danger")
        return redirect(url_for("sales_list"))

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
        fname = f"hcl_sales_export_{datetime.now(tz=tz.gettz('Asia/Kolkata')).strftime('%Y%m%d_%H%M%S')}.csv"
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
    








# -----------------------------------------------------------------------------
# Run (local dev)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5002, debug=True)
