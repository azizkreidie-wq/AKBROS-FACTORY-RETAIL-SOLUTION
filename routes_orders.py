from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from models import get_db, migrate
from auth import require_login, is_factory, is_retail

bp_orders = Blueprint('orders_bp', __name__)

STATUS_CHOICES = ["DRAFT","SENT_TO_FACTORY","IN_PRODUCTION","READY","DELIVERED","CANCELLED"]
ITEM_CATEGORIES = ["SHEILA","ABAYA"]

@bp_orders.route("/orders", methods=["GET","POST"])
@require_login
def orders_list():
    db = get_db(); migrate()
    if request.method == "POST":
        order_no = (request.form.get("order_no") or "").strip()
        if not order_no:
            flash("Order number is required."); return redirect(url_for("orders_bp.orders_list"))
        notes = request.form.get("notes") or None

        if is_retail():
            branch = session.get("retail_branch_name") or "-"
            status = "DRAFT"
        else:
            branch = (request.form.get("branch") or "").strip() or "-"
            status = request.form.get("status") or "DRAFT"

        db.execute("INSERT INTO orders(order_no, branch, status, notes) VALUES (?,?,?,?)",
                   (order_no, branch, status, notes))
        db.commit()
        oid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        return redirect(url_for("orders_bp.order_detail", order_id=oid))

    f_status = request.args.get("f_status","").strip()
    q = request.args.get("q","").strip()

    base = "SELECT * FROM orders WHERE 1=1"
    params = []
    if is_retail():
        base += " AND branch=?"; params.append(session.get("retail_branch_name") or "-")
    if f_status:
        base += " AND status=?"; params.append(f_status)
    if q:
        like = f"%{q}%"
        base += " AND (order_no LIKE ? OR branch LIKE ? OR notes LIKE ? OR CAST(id AS TEXT) LIKE ?)"
        params += [like, like, like, like]
    base += " ORDER BY id DESC"

    rows = db.execute(base, params).fetchall()
    counts = {r["id"]: db.execute("SELECT COUNT(*) FROM order_items WHERE order_id=?", (r["id"],)).fetchone()[0] for r in rows}

    branches = [r[0] for r in db.execute("SELECT DISTINCT branch FROM orders ORDER BY branch").fetchall()] if not is_retail() else []
    return render_template("orders_list.html",
                           rows=rows, counts=counts, branches=branches,
                           statuses=STATUS_CHOICES)

@bp_orders.route("/orders/<int:order_id>", methods=["GET","POST"])
@require_login
def order_detail(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        flash("Order not found."); return redirect(url_for("orders_bp.orders_list"))

    retail_locked = False
    if is_retail() and order["status"] != "DRAFT":
        retail_locked = True

    if request.method == "POST":
        act = request.form.get("action")
        if act == "update-order":
            notes = request.form.get("notes") or None
            order_no = (request.form.get("order_no") or "").strip()
            if not order_no:
                flash("Order number is required."); return redirect(url_for("orders_bp.order_detail", order_id=order_id))

            if is_factory():
                status = request.form.get("status") or order["status"]
                branch = (request.form.get("branch") or order["branch"]).strip()
            else:
                status = order["status"]
                branch = order["branch"]
                if retail_locked:
                    flash("Retail cannot edit non-DRAFT orders."); return redirect(url_for("orders_bp.order_detail", order_id=order_id))

            db.execute("UPDATE orders SET order_no=?, branch=?, status=?, notes=? WHERE id=?",
                       (order_no, branch, status, notes, order_id))
            db.commit()
            flash("Order updated.")
            return redirect(url_for("orders_bp.order_detail", order_id=order_id))

        if act == "delete-order":
            if is_retail() and order["status"] != "DRAFT":
                flash("Retail cannot delete non-DRAFT orders."); return redirect(url_for("orders_bp.order_detail", order_id=order_id))
            db.execute("DELETE FROM orders WHERE id=?", (order_id,))
            db.commit()
            flash("Order deleted.")
            return redirect(url_for("orders_bp.orders_list"))

        if act == "add-item":
            if is_retail() and retail_locked:
                flash("Retail cannot add items when not DRAFT."); return redirect(url_for("orders_bp.order_detail", order_id=order_id))

            cat = request.form.get("category")
            if cat not in ITEM_CATEGORIES:
                flash("Choose category."); return redirect(url_for("orders_bp.order_detail", order_id=order_id))
            common = {
                "model_number": request.form.get("model_number") or None,
                "color": request.form.get("color") or None,
                "extra_note": request.form.get("extra_note") or None,
            }
            if cat == "SHEILA":
                db.execute("""
                    INSERT INTO order_items(order_id,category,model_number,color,extra_note,sheila_fabric,height_cm,width_cm,logo_color)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, (order_id, cat, common["model_number"], common["color"], common["extra_note"],
                        request.form.get("sheila_fabric"), request.form.get("height_cm"),
                        request.form.get("width_cm"), request.form.get("logo_color")))
            else:
                db.execute("""
                    INSERT INTO order_items(order_id,category,model_number,color,extra_note,abaya_fabric,size,upper_width_cm,lower_width_cm,sleeve_width_cm,sleeve_height_cm,logo)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, (order_id, cat, common["model_number"], common["color"], common["extra_note"],
                        request.form.get("abaya_fabric"), request.form.get("size"),
                        request.form.get("upper_width_cm"), request.form.get("lower_width_cm"),
                        request.form.get("sleeve_width_cm"), request.form.get("sleeve_height_cm"),
                        request.form.get("logo")))
            db.commit()
            flash("Item added.")
            return redirect(url_for("orders_bp.order_detail", order_id=order_id))

        if act == "delete-item":
            if is_retail() and retail_locked:
                flash("Retail cannot delete items when not DRAFT."); return redirect(url_for("orders_bp.order_detail", order_id=order_id))
            item_id = int(request.form.get("item_id"))
            db.execute("DELETE FROM order_items WHERE id=? AND order_id=?", (item_id, order_id))
            db.commit()
            flash("Item deleted.")
            return redirect(url_for("orders_bp.order_detail", order_id=order_id))

    items = db.execute("SELECT * FROM order_items WHERE order_id=? ORDER BY id DESC", (order_id,)).fetchall()
    branches = [r[0] for r in db.execute("SELECT DISTINCT branch FROM orders ORDER BY branch").fetchall()] if not is_retail() else []
    return render_template("order_form.html",
                           order=order, items=items, statuses=STATUS_CHOICES, branches=branches,
                           retail_locked=retail_locked, is_factory=is_factory)
