from flask import Blueprint, render_template, request, redirect, url_for, flash
from decimal import Decimal, InvalidOperation
from models import get_db

bp_invoices = Blueprint("invoices", __name__)

# -------- Utilities --------
def as_int(val, default=0):
    try:
        return int(str(val).strip())
    except Exception:
        return default

def as_money(val, default=0):
    s = (val or "").strip().replace(",", "")
    if s == "":
        return Decimal(default)
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal(default)


# Ensure base tables exist (idempotent)
def ensure_tables(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_name TEXT,
          customer_phone TEXT,
          notes TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS invoice_items (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          invoice_id INTEGER NOT NULL,
          item_type TEXT,        -- CUSTOM / LOCAL_CUSTOM / READY
          category TEXT,         -- ABAYA / SHEILA
          model_number TEXT,
          color TEXT,
          extra_note TEXT,
          qty INTEGER DEFAULT 1,
          unit_price REAL DEFAULT 0,
          discount_type TEXT DEFAULT 'NONE',  -- NONE/AMOUNT/PERCENT
          discount_value REAL DEFAULT 0,
          tax_rate REAL DEFAULT 0,            -- percent (e.g. 15)
          line_total REAL DEFAULT 0,
          FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
        )
    """)


# -------- Invoices List --------
@bp_invoices.route("/invoices")
def invoice_list():
    db = get_db()
    ensure_tables(db)
    invoices = db.execute("SELECT * FROM invoices ORDER BY id DESC").fetchall()
    return render_template("invoice_list.html", invoices=invoices)


# -------- Quick create via GET (link-friendly) --------
@bp_invoices.route("/invoices/new", methods=["GET"])
def invoice_new_quick():
    db = get_db()
    ensure_tables(db)
    cur = db.execute(
        "INSERT INTO invoices (customer_name, customer_phone, notes) VALUES (?,?,?)",
        ("", "", "")
    )
    new_id = cur.lastrowid
    db.commit()
    flash("New invoice created.")
    return redirect(url_for("invoices.invoice_detail", invoice_id=new_id))


# -------- Create form (GET shows form, POST saves) --------
@bp_invoices.route("/invoices/create", methods=["GET", "POST"])
def create_invoice():
    db = get_db()
    ensure_tables(db)
    if request.method == "POST":
        customer_name = request.form.get("customer_name") or ""
        customer_phone = request.form.get("customer_phone") or ""
        notes = request.form.get("notes") or ""
        cur = db.execute(
            "INSERT INTO invoices (customer_name, customer_phone, notes) VALUES (?,?,?)",
            (customer_name, customer_phone, notes)
        )
        new_id = cur.lastrowid
        db.commit()
        flash("Invoice created successfully.")
        return redirect(url_for("invoices.invoice_detail", invoice_id=new_id))
    # GET → show simple create header form
    return render_template("invoice_form.html", inv=None, items=[])


# -------- Invoice Detail (view + actions) --------
@bp_invoices.route("/invoices/<int:invoice_id>", methods=["GET", "POST"])
def invoice_detail(invoice_id):
    db = get_db()
    ensure_tables(db)

    inv = db.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        flash("Invoice not found.")
        return redirect(url_for("invoices.invoice_list"))

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()

        # ---- Add item ----
        if action == "add-item":
            f = request.form

            # Parse safely
            qty            = as_int(f.get("qty"), 1)
            unit_price     = as_money(f.get("unit_price"), 0)
            discount_type  = (f.get("discount_type") or "NONE").strip().upper()
            if discount_type not in ("NONE", "AMOUNT", "PERCENT"):
                discount_type = "NONE"
            discount_value = as_money(f.get("discount_value"), 0)
            tax_rate       = as_money(f.get("tax_rate"), 0)  # percent

            item_type   = (f.get("item_type") or "READY").strip().upper()
            if item_type not in ("CUSTOM", "LOCAL_CUSTOM", "READY"):
                item_type = "READY"
            category    = (f.get("category") or "ABAYA").strip().upper()
            if category not in ("ABAYA", "SHEILA"):
                category = "ABAYA"
            model_number = (f.get("model_number") or "").strip() or None
            color        = (f.get("color") or "").strip() or None
            extra_note   = (f.get("extra_note") or "").strip() or None

            # Total calculation
            line_subtotal = unit_price * qty
            if discount_type == "AMOUNT":
                after = max(Decimal("0"), line_subtotal - discount_value)
            elif discount_type == "PERCENT":
                pct = max(Decimal("0"), min(Decimal("100"), discount_value))
                after = line_subtotal * (Decimal("1") - pct / Decimal("100"))
            else:
                after = line_subtotal
            tax_amount = (after * (tax_rate / Decimal("100"))).quantize(Decimal("0.01"))
            line_total = (after + tax_amount).quantize(Decimal("0.01"))

            # Insert
            db.execute("""
                INSERT INTO invoice_items (
                  invoice_id, item_type, category, model_number, color, extra_note,
                  qty, unit_price, discount_type, discount_value, tax_rate, line_total
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                invoice_id, item_type, category, model_number, color, extra_note,
                int(qty), float(unit_price), discount_type, float(discount_value),
                float(tax_rate), float(line_total)
            ))
            db.commit()
            flash("Item added to invoice.")
            return redirect(url_for("invoices.invoice_detail", invoice_id=invoice_id))

        # ---- Delete item ----
        elif action == "delete-item":
            item_id = as_int(request.form.get("item_id"), 0)
            db.execute("DELETE FROM invoice_items WHERE id=?", (item_id,))
            db.commit()
            flash("Item deleted.")
            return redirect(url_for("invoices.invoice_detail", invoice_id=invoice_id))

        # ---- Update header (customer / notes) ----
        elif action == "update-header":
            customer_name  = request.form.get("customer_name") or ""
            customer_phone = request.form.get("customer_phone") or ""
            notes          = request.form.get("notes") or ""
            db.execute("""
                UPDATE invoices
                SET customer_name=?, customer_phone=?, notes=?
                WHERE id=?
            """, (customer_name, customer_phone, notes, invoice_id))
            db.commit()
            flash("Invoice updated.")
            return redirect(url_for("invoices.invoice_detail", invoice_id=invoice_id))

    # GET → render page
    items = db.execute("SELECT * FROM invoice_items WHERE invoice_id=? ORDER BY id DESC", (invoice_id,)).fetchall()
    return render_template("invoice_form.html", inv=inv, items=items)


# -------- Delete Invoice --------
@bp_invoices.route("/invoices/<int:invoice_id>/delete", methods=["POST"])
def delete_invoice(invoice_id):
    db = get_db()
    ensure_tables(db)
    db.execute("DELETE FROM invoice_items WHERE invoice_id=?", (invoice_id,))
    db.execute("DELETE FROM invoices WHERE id=?", (invoice_id,))
    db.commit()
    flash("Invoice deleted.")
    return redirect(url_for("invoices.invoice_list"))
