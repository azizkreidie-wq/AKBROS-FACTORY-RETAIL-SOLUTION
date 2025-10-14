from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from models import get_db, migrate
from auth import require_login, is_factory, is_retail

bp_settings = Blueprint("settings_bp", __name__)

@bp_settings.route("/settings/invoice", methods=["GET", "POST"])
@require_login
def invoice_settings():
    db = get_db(); migrate()

    if is_factory():
        sel_id = request.values.get("branch_id")
        try:
            branch_id = int(sel_id) if sel_id else 1
        except:
            branch_id = 1
    else:
        branch_id = int(session.get("retail_branch_id") or 1)

    br = db.execute("SELECT * FROM branches WHERE id=?", (branch_id,)).fetchone()

    if request.method == "POST":
        if not is_factory():
            flash("You do not have permission to update settings.")
            return redirect(url_for("settings_bp.invoice_settings"))

        name = (request.form.get("name") or "").strip() or None
        passcode = (request.form.get("passcode") or "").strip() or None
        currency_code = (request.form.get("currency_code") or "").strip() or "AED"
        vat_mode = request.form.get("vat_mode") or "included"
        try:
            vat_rate = float(request.form.get("vat_rate") or 0.0)
        except:
            vat_rate = 0.0

        company_title = (request.form.get("company_title") or "").strip() or "Invoice"
        company_name = (request.form.get("company_name") or "").strip() or None
        company_address = (request.form.get("company_address") or "").strip() or None
        invoice_template = (request.form.get("invoice_template") or "").strip() or "classic"

        db.execute("""
            UPDATE branches SET
              name=?, passcode=?, currency_code=?, vat_mode=?, vat_rate=?,
              company_title=?, company_name=?, company_address=?, invoice_template=?
            WHERE id=?
        """, (name, passcode, currency_code, vat_mode, vat_rate,
              company_title, company_name, company_address, invoice_template, branch_id))
        db.commit()
        flash("Invoice settings saved.")
        return redirect(url_for("settings_bp.invoice_settings", branch_id=branch_id))

    branch_choices = []
    if is_factory():
        branch_choices = db.execute("SELECT id, COALESCE(name, '') AS name FROM branches ORDER BY id").fetchall()

    return render_template("invoice_settings.html",
                           br=br,
                           branch_id=branch_id,
                           branch_choices=branch_choices,
                           is_factory=is_factory,
                           is_retail=is_retail)
