from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from models import get_db, migrate, next_invoice_no
from auth import require_login, is_factory, is_retail

bp_invoices = Blueprint('invoices_bp', __name__)

ITEM_TYPES = ["CUSTOM","LOCAL_CUSTOM","READY"]
CATEGORIES = ["SHEILA","ABAYA"]

def _branch_scope_clause():
    if is_retail():
        return " WHERE i.branch_id = ?", [session.get("retail_branch_id")]
    return "", []

@bp_invoices.route("/invoices", methods=["GET","POST"])
@require_login
def invoices_list():
    db = get_db(); migrate()

    if request.method == "POST":
        if is_retail():
            bid = session.get("retail_branch_id")
            br = db.execute("SELECT * FROM branches WHERE id=?", (bid,)).fetchone()
        else:
            bid = int(request.form.get("branch_id") or 1)
            br = db.execute("SELECT * FROM branches WHERE id=?", (bid,)).fetchone()

        inv_no = next_invoice_no(db)
        db.execute("""
            INSERT INTO invoices(invoice_no, branch_id, currency_code, vat_mode, vat_rate, created_at, status)
            VALUES (?,?,?,?,?, datetime('now'),'DRAFT')
        """, (inv_no, bid, br["currency_code"], br["vat_mode"], br["vat_rate"]))
        db.commit()
        iid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        return redirect(url_for("invoices_bp.invoice_edit", invoice_id=iid))

    where, params = _branch_scope_clause()
    rows = db.execute(f"SELECT i.*, b.name as branch_name FROM invoices i JOIN branches b ON b.id=i.branch_id{where} ORDER BY i.id DESC", params).fetchall()
    return render_template("invoice_list.html", rows=rows)

@bp_invoices.route("/invoices/<int:invoice_id>", methods=["GET","POST"])
@require_login
def invoice_edit(invoice_id):
    db = get_db()
    inv = db.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        flash("Invoice not found."); return redirect(url_for("invoices_bp.invoices_list"))

    if is_retail() and inv["branch_id"] != session.get("retail_branch_id"):
        flash("Access denied for this branch."); return redirect(url_for("invoices_bp.invoices_list"))

    if request.method == "POST":
        act = request.form.get("action")

        if act == "header-save":
            name = request.form.get("customer_name") or None
            phone = (request.form.get("customer_phone") or "").strip() or None

            if phone:
                phone_norm = "".join(ch for ch in phone if ch.isdigit() or ch=="+")
                row = db.execute("SELECT id FROM customers WHERE phone=?", (phone_norm,)).fetchone()
                if row:
                    db.execute("UPDATE customers SET name=COALESCE(?, name), updated_at=datetime('now') WHERE id=?",
                               (name, row["id"]))
                else:
                    db.execute("INSERT INTO customers(name, phone, created_at, updated_at) VALUES (?,?, datetime('now'), datetime('now'))",
                               (name, phone_norm))

            db.execute("""
                UPDATE invoices SET customer_name=?, customer_phone=?, title_override=?, terms=? WHERE id=?
            """, (name, phone, request.form.get("title_override") or None, request.form.get("terms") or None, invoice_id))
            db.commit()
            flash("Invoice header saved.")
            return redirect(url_for("invoices_bp.invoice_edit", invoice_id=invoice_id))

        if action == "add-item":
    from decimal import Decimal, InvalidOperation
    f = request.form

    def as_int(val, default=1):
        try: return int(str(val).strip())
        except Exception: return default

    def as_money(val, default=0):
        s = (val or "").strip().replace(",", "")
        if s == "": return Decimal(default)
        try: return Decimal(s)
        except InvalidOperation: return Decimal(default)

    invoice_id = as_int(f.get("invoice_id"), 0)
    inv = db.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        flash("Invoice not found.")
        return redirect(url_for("invoice_list"))

    item_type = (f.get("item_type") or "").strip().upper()
    if item_type not in ("CUSTOM", "LOCAL_CUSTOM", "READY"):
        item_type = "READY"

    category = (f.get("category") or "").strip().upper()
    if category not in ("ABAYA", "SHEILA"):
        category = "ABAYA"

    model_number = (f.get("model_number") or "").strip() or None
    color        = (f.get("color") or "").strip() or None
    extra_note   = (f.get("extra_note") or "").strip() or None

    qty            = as_int(f.get("qty"), 1)
    unit_price     = as_money(f.get("unit_price"), 0)
    discount_type  = (f.get("discount_type") or "NONE").strip().upper()
    if discount_type not in ("NONE", "AMOUNT", "PERCENT"):
        discount_type = "NONE"
    discount_value = as_money(f.get("discount_value"), 0)
    tax_rate       = as_money(f.get("tax_rate"), 0)

    # Optional category-specific fields (safe if absent)
    sheila_fabric = (f.get("sheila_fabric") or "").strip() or None
    height_cm     = (f.get("height_cm") or "").strip() or None
    width_cm      = (f.get("width_cm") or "").strip() or None
    logo_color    = (f.get("logo_color") or "").strip() or None

    abaya_fabric     = (f.get("abaya_fabric") or "").strip() or None
    size             = (f.get("size") or "").strip() or None
    upper_width_cm   = (f.get("upper_width_cm") or "").strip() or None
    lower_width_cm   = (f.get("lower_width_cm") or "").strip() or None
    sleeve_width_cm  = (f.get("sleeve_width_cm") or "").strip() or None
    sleeve_height_cm = (f.get("sleeve_height_cm") or "").strip() or None
    logo             = (f.get("logo") or "").strip() or None

    # Totals (safe)
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

    # Defensive migration (no-op if columns already exist)
    for stmt in [
        "ALTER TABLE invoice_items ADD COLUMN qty INTEGER DEFAULT 1",
        "ALTER TABLE invoice_items ADD COLUMN unit_price REAL DEFAULT 0",
        "ALTER TABLE invoice_items ADD COLUMN discount_type TEXT DEFAULT 'NONE'",
        "ALTER TABLE invoice_items ADD COLUMN discount_value REAL DEFAULT 0",
        "ALTER TABLE invoice_items ADD COLUMN tax_rate REAL DEFAULT 0",
        "ALTER TABLE invoice_items ADD COLUMN line_total REAL DEFAULT 0",
    ]:
        try: db.execute(stmt)
        except Exception: pass

    db.execute("""
      INSERT INTO invoice_items (
        invoice_id, item_type, category, model_number, color, extra_note,
        sheila_fabric, height_cm, width_cm, logo_color,
        abaya_fabric, size, upper_width_cm, lower_width_cm, sleeve_width_cm, sleeve_height_cm, logo,
        qty, unit_price, discount_type, discount_value, tax_rate, line_total
      ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        invoice_id, item_type, category, model_number, color, extra_note,
        sheila_fabric, height_cm, width_cm, logo_color,
        abaya_fabric, size, upper_width_cm, lower_width_cm, sleeve_width_cm, sleeve_height_cm, logo,
        int(qty), float(unit_price), discount_type, float(discount_value), float(tax_rate), float(line_total)
    ))
    db.commit()
    flash("Item added to invoice.")
    return redirect(url_for("invoice_detail", invoice_id=invoice_id))


        if act == "delete-item":
            iid = int(request.form.get("iid"))
            db.execute("DELETE FROM invoice_items WHERE id=? AND invoice_id=?", (iid, invoice_id))
            db.commit()
            flash("Item deleted.")
            return redirect(url_for("invoices_bp.invoice_edit", invoice_id=invoice_id))

        if act == "recalc":
            items = db.execute("SELECT * FROM invoice_items WHERE invoice_id=?", (invoice_id,)).fetchall()
            subtotal = 0.0
            for it in items:
                base = (it["qty"] or 1) * (it["unit_price"] or 0)
                disc = it["discount_amount"] or 0
                if (it["discount_percent"] or 0) > 0:
                    disc = base * (it["discount_percent"]/100.0)
                line_total = max(0.0, base - disc)
                db.execute("UPDATE invoice_items SET line_total=? WHERE id=?", (line_total, it["id"]))
                subtotal += line_total

            inv_disc = float(request.form.get("discount_amount") or 0)
            inv_disc_pct = float(request.form.get("discount_percent") or 0)
            if inv_disc_pct > 0:
                inv_disc = subtotal * (inv_disc_pct/100.0)
            after_disc = max(0.0, subtotal - inv_disc)

            vat_amount = 0.0
            if inv["vat_mode"] == "excluded":
                vat_amount = after_disc * (inv["vat_rate"] or 0)
                total = after_disc + vat_amount
            else:
                total = after_disc
                vat_amount = total - (total / (1 + (inv["vat_rate"] or 0))) if (inv["vat_rate"] or 0) > 0 else 0.0

            db.execute("""UPDATE invoices SET subtotal=?, discount_amount=?, discount_percent=?, vat_amount=?, total=? WHERE id=?""" ,
                       (subtotal, float(request.form.get("discount_amount") or 0), float(request.form.get("discount_percent") or 0),
                        vat_amount, total, invoice_id))
            db.commit()
            flash("Totals recalculated.")
            return redirect(url_for("invoices_bp.invoice_edit", invoice_id=invoice_id))

        if act == "finalize":
            db.execute("UPDATE invoices SET status='FINALIZED', finalized_at=datetime('now') WHERE id=?", (invoice_id,))
            items = db.execute("SELECT * FROM invoice_items WHERE invoice_id=? AND item_type='CUSTOM'", (invoice_id,)).fetchall()
            if items:
                br = db.execute("SELECT name FROM branches WHERE id=?", (inv["branch_id"],)).fetchone()
                order_no = inv["invoice_no"]
                db.execute("INSERT INTO orders(order_no, branch, status, notes) VALUES (?,?, 'SENT_TO_FACTORY', ?)",
                           (order_no, br["name"] or '-', f"Auto from invoice #{inv['invoice_no']}"))
                oid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                for it in items:
                    if it["category"] == "SHEILA":
                        db.execute("""
                          INSERT INTO order_items(order_id,category,model_number,color,extra_note,sheila_fabric,height_cm,width_cm,logo_color)
                          VALUES (?,?,?,?,?,?,?,?,?)
                        """, (oid, "SHEILA", it["model_number"], it["color"], None,
                                it["sheila_fabric"], it["height_cm"], it["width_cm"], it["logo_color"]))
                    else:
                        db.execute("""
                          INSERT INTO order_items(order_id,category,model_number,color,extra_note,abaya_fabric,size,upper_width_cm,lower_width_cm,sleeve_width_cm,sleeve_height_cm,logo)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                        """, (oid, "ABAYA", it["model_number"], it["color"], None,
                                it["abaya_fabric"], it["size"], it["upper_width_cm"], it["lower_width_cm"],
                                it["sleeve_width_cm"], it["sleeve_height_cm"], it["logo"]))
                db.commit()
            flash("Invoice finalized and synced (CUSTOM items).")
            return redirect(url_for("invoices_bp.invoice_edit", invoice_id=invoice_id))

    items = db.execute("SELECT * FROM invoice_items WHERE invoice_id=? ORDER BY id DESC", (invoice_id,)).fetchall()
    branch = db.execute("SELECT * FROM branches WHERE id=?", (inv["branch_id"],)).fetchone()
    return render_template("invoice_form.html", inv=inv, items=items, branch=branch,
                           item_types=ITEM_TYPES, categories=CATEGORIES)
