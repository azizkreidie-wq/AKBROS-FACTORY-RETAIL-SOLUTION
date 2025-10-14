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

        if act == "add-item":
            item_type = request.form.get("item_type")
            category = request.form.get("category")
            if item_type not in ITEM_TYPES or category not in CATEGORIES:
                flash("Select item type and category."); return redirect(url_for("invoices_bp.invoice_edit", invoice_id=invoice_id))

            model_number = request.form.get("model_number") or None
            qty = float(request.form.get("qty") or 1)
            unit_price = float(request.form.get("unit_price") or 0)

            db.execute("""
                INSERT INTO invoice_items(invoice_id, item_type, category, model_number, color, sheila_fabric, height_cm, width_cm, logo_color,
                                          abaya_fabric, size, upper_width_cm, lower_width_cm, sleeve_width_cm, sleeve_height_cm, logo,
                                          qty, unit_price, discount_amount, discount_percent, line_total, sync_status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 0, 'PENDING')
            """, (invoice_id, item_type, category,
                    model_number, request.form.get("color"),
                    request.form.get("sheila_fabric"), request.form.get("height_cm"),
                    request.form.get("width_cm"), request.form.get("logo_color"),
                    request.form.get("abaya_fabric"), request.form.get("size"),
                    request.form.get("upper_width_cm"), request.form.get("lower_width_cm"),
                    request.form.get("sleeve_width_cm"), request.form.get("sleeve_height_cm"),
                    request.form.get("logo"),
                    qty, unit_price,
                    float(request.form.get("discount_amount") or 0),
                    float(request.form.get("discount_percent") or 0)))
            db.commit()
            flash("Item added.")
            return redirect(url_for("invoices_bp.invoice_edit", invoice_id=invoice_id))

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
