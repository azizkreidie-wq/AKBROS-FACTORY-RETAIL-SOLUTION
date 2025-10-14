from __future__ import annotations
import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from models import get_db, close_db, migrate
from auth import set_factory, set_retail, check_branch_pass, require_login, is_factory, is_retail
from routes_orders import bp_orders
from routes_invoices import bp_invoices
from routes_settings import bp_settings

APP_SECRET = os.environ.get("FLASK_SECRET", "dev-secret")
ADMIN_PASS = os.environ.get("ADMIN_PASSCODE", "HKGOF2025@")

app = Flask(__name__)
app.secret_key = APP_SECRET

app.teardown_appcontext(close_db)
app.register_blueprint(bp_orders)
app.register_blueprint(bp_invoices)
app.register_blueprint(bp_settings)

I18N = {
    "en": {
        "app_title": "HASSAN KREIDIE FACTORY ORDERS",
        "home_orders": "Orders",
        "home_invoices": "Invoicing",
        "home_print": "Print View",
        "export_all_csv": "Export All CSV",
        "login": "Login",
        "lang": "العربية",
    },
    "ar": {
        "app_title": "طلبات مصنع حسن قريدي",
        "home_orders": "الطلبات",
        "home_invoices": "الفواتير",
        "home_print": "عرض الطباعة",
        "export_all_csv": "تصدير الكل CSV",
        "login": "تسجيل الدخول",
        "lang": "English",
    },
}

def t(key:str)->str:
    lang = session.get("lang", "en")
    return I18N.get(lang, I18N["en"]).get(key, key)

@app.before_request
def ensure_lang():
    if "lang" not in session:
        session["lang"]="en"

@app.route("/lang/<code>")
def set_lang(code:str):
    if code in ("en","ar"):
        session["lang"]=code
    return redirect(request.referrer or url_for("home"))

@app.route("/")
def home():
    migrate()
    return render_template("choose_role.html", t=t)

@app.route("/health")
def health():
    return "OK", 200

@app.route("/login")
def login():
    return render_template("choose_role.html", t=t)

@app.route("/login/factory", methods=["GET","POST"])
def login_factory():
    if request.method == "POST":
        if (request.form.get("passcode") or "") == ADMIN_PASS:
            set_factory()
            return redirect(url_for("home"))
        else:
            flash("Invalid passcode.")
    return render_template("login_pass.html", title="Factory Login")

@app.route("/login/retail", methods=["GET","POST"])
def login_retail():
    db = get_db(); migrate()
    slots = db.execute("SELECT id, COALESCE(name, '') AS name FROM branches ORDER BY id").fetchall()
    return render_template("retail_slots.html", slots=slots)

@app.route("/retail/slot/<int:slot_id>", methods=["GET","POST"])
def retail_slot(slot_id:int):
    db = get_db(); migrate()
    br = db.execute("SELECT * FROM branches WHERE id=?", (slot_id,)).fetchone()
    if request.method == "POST":
        passcode = request.form.get("passcode") or ""
        if br["passcode"] and passcode != br["passcode"]:
            flash("Wrong passcode."); return redirect(url_for("retail_slot", slot_id=slot_id))
        name = (request.form.get("branch_name") or br["name"] or "").strip()
        if not br["name"] and not name:
            flash("Please set branch name."); return redirect(url_for("retail_slot", slot_id=slot_id))
        if not br["name"] and name:
            db.execute("UPDATE branches SET name=? WHERE id=?", (name, slot_id)); db.commit()
        session['authed']=True; session['role']='retail'; session['retail_branch_id']=slot_id; session['retail_branch_name']=name or br["name"] or f"Branch {slot_id}"
        return redirect(url_for("home"))
    return render_template("retail_slot_login.html", br=br, slot_id=slot_id)

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.")
    return redirect(url_for("login"))

@app.context_processor
def inject_header():
    return {"is_factory": is_factory, "is_retail": is_retail, "t": t}
 
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

