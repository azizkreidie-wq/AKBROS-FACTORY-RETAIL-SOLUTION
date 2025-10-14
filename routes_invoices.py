from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from decimal import Decimal, InvalidOperation
from models import get_db

bp_invoices = Blueprint("invoices", __name__)

# Utility
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


# ------------------------
# Invoices List
# ------------------------
@bp_invoices.route("/invoices")
def invoice_list():
    db = get_db()
    invoices = db.execute("SELECT * FROM invoices ORDER BY id DESC").fetchall()
    return render_template("invoice_list.html", invoices=invoices)


# ------------------------
# Invoice Detail
# ------------------------
@bp_invoices.route("/invoices/<int:invoice_id>", methods=["GET", "POST"])
def invoice_detail(invoice_id):
    db = get_db()
    inv = db.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        flash("Invoice not found.")
        return redirect(url_for("invoices.invoice_list"))

    if request.method == "POST":
        action = request.form.get("action")

        # -------- ADD ITEM --------
        if action == "add-item":
            from decimal import Decimal, InvalidOperation
            f = request.form

            qty = as_int(f.get("qty"), 1)
            unit_price = as_money(f.get("unit_price"), 0)
            discount_type = (f.get("discount_type") or "NONE").strip().upper()
            discount_value = as_money(f.get("discount_value"), 0)
            tax_rate = as_money(f.get("tax_rate"), 0)

            item_type = (f.get("item_type") or "READY").upper()
            category = (f.get("category") or "ABAYA").upper()
            model_number = (f.get("model_number") or "").strip() or None
            color = (f.get("color") or "").strip() or None
            extra_note = (f.get("extra_note") or "").strip() or None

            # Compute line total
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

            # Create table if not exists
            for stmt in [
                "CREATE TABLE IF NOT EXISTS invoice_items (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER, item_type TEXT, category TEXT, model_number TEXT, color TEXT, extra_note TEXT, qty INTEGER, unit_price REAL, discount_type TEXT, discount_value REAL, tax_rate REAL, line_total REAL)"
            ]:
                db.execute(stmt)

            # Insert item
            db.execute("""
                INSERT INTO invoice_items (
                    invoice_id, item_type, category, model_number, color, extra_note,
                    qty, unit_price, discount_type, discount_value, tax_rate, line_total
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                invoice_id, item_type, category, model_number, color, extra_note,
                qty, float(unit_price), discount_type, float(discount_value),
                float(tax_rate), float(line_total)
            ))
            db.commit()
            flash("Item added successfully.")
            return redirect(url_for("invoices.invoice_detail", invoice_id=invoice_id))

        # -------- DELETE ITEM --------
        elif action == "delete-item":
            item_id = as_int(request.form.get("item_id"), 0)
            db.execute("DELETE FROM invoice_items WHERE id=?", (item_id,))
            db.commit()
            flash("Item deleted.")
            return redirect(url_for("invoices.invoice_detail", invoice_id=invoice_id))

        # -------- UPDATE HEADER --------
        elif action == "update-header":
            customer_name = request.form.get("customer_name")
            customer_phone = request.form.get("customer_phone")
            notes = request.form.get("notes")
            db.execute("""
                UPDATE invoices
                SET customer_name=?, customer_phone=?, notes=?
                WHERE id=?
            """, (customer_name, customer_phone, notes, invoice_id))
            db.commit()
            flash("Invoice updated.")
            return redirect(url_for("invoices.invoice_detail", invoice_id=invoice_id))

    # Retrieve all items
    items = db.execute("SELECT * FROM invoice_items WHERE invoice_id=?", (invoice_id,)).fetchall()
    return render_template("invoice_form.html", inv=inv, items=items)


# ------------------------
# Create Invoice
# ------------------------
@bp_invoices.route("/invoices/create", methods=["GET", "POST"])
def create_invoice():
    db = get_db()
    if request.method == "POST":
        customer_name = request.form.get("customer_name")
        customer_phone = request.form.get("customer_phone")
        db.execute("CREATE TABLE IF NOT EXISTS invoices (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT, customer_phone TEXT, notes TEXT)")
        db.execute("INSERT INTO invoices (customer_name, customer_phone, notes) VALUES (?,?,?)",
                   (customer_name, customer_phone, ""))
        db.commit()
        flash("Invoice created successfully.")
        return redirect(url_for("invoices.invoice_list"))
    return render_template("invoice_form.html", inv=None, items=[])


# ------------------------
# Delete Invoice
# ------------------------
@bp_invoices.route("/invoices/<int:invoice_id>/delete", methods=["POST"])
def delete_invoice(invoice_id):
    db = get_db()
    db.execute("DELETE FROM invoice_items WHERE invoice_id=?", (invoice_id,))
    db.execute("DELETE FROM invoices WHERE id=?", (invoice_id,))
    db.commit()
    flash("Invoice deleted successfully.")
    return redirect(url_for("invoices.invoice_list"))
