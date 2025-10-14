import os
from functools import wraps
from flask import session, redirect, url_for, request, flash
from models import get_db

ADMIN_PASS = os.environ.get("ADMIN_PASSCODE", "HKGOF2025@")

def is_authed():
    return bool(session.get("authed"))

def is_factory():
    return is_authed() and session.get("role") == "factory"

def is_retail():
    return is_authed() and session.get("role") == "retail"

def require_login(f):
    @wraps(f)
    def _w(*a, **k):
        if not is_authed():
            return redirect(url_for("login"))
        return f(*a, **k)
    return _w

def require_factory(f):
    @wraps(f)
    def _w(*a, **k):
        if not is_factory():
            flash("Factory access only.")
            return redirect(url_for("home"))
        return f(*a, **k)
    return _w

def set_factory():
    session["authed"] = True
    session["role"] = "factory"
    session["retail_branch_id"] = None
    session["retail_branch_name"] = None

def set_retail(branch_id, branch_name):
    session["authed"] = True
    session["role"] = "retail"
    session["retail_branch_id"] = branch_id
    session["retail_branch_name"] = branch_name

def check_branch_pass(branch_id, passcode):
    db = get_db()
    row = db.execute("SELECT passcode FROM branches WHERE id=?", (branch_id,)).fetchone()
    if not row or not row["passcode"]:
        return False
    return (passcode or "") == row["passcode"]
