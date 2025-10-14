import os, sqlite3
from flask import g

DB_PATH = os.environ.get("ORDER_DB", "orders_full.db")

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON;")
    return g.db

def close_db(_=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

SCHEMA = r"""
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS branches (
  id INTEGER PRIMARY KEY,
  name TEXT,
  passcode TEXT,
  currency_code TEXT DEFAULT 'AED',
  vat_mode TEXT DEFAULT 'included',
  vat_rate REAL DEFAULT 0.05,
  company_title TEXT DEFAULT 'Invoice',
  company_name TEXT,
  company_address TEXT,
  invoice_template TEXT DEFAULT 'classic',
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_no TEXT NOT NULL,
  branch TEXT NOT NULL,
  order_date TEXT NOT NULL DEFAULT (DATE('now')),
  status TEXT NOT NULL DEFAULT 'DRAFT',
  notes TEXT
);

CREATE TABLE IF NOT EXISTS order_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL,
  category TEXT NOT NULL CHECK (category IN ('SHEILA','ABAYA')),
  model_number TEXT,
  color TEXT,
  extra_note TEXT,
  sheila_fabric TEXT,
  height_cm TEXT,
  width_cm TEXT,
  logo_color TEXT,
  abaya_fabric TEXT,
  size TEXT,
  upper_width_cm TEXT,
  lower_width_cm TEXT,
  sleeve_width_cm TEXT,
  sleeve_height_cm TEXT,
  logo TEXT,
  FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS invoices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_no TEXT UNIQUE,
  branch_id INTEGER NOT NULL,
  customer_name TEXT,
  customer_phone TEXT,
  title_override TEXT,
  terms TEXT,
  status TEXT NOT NULL DEFAULT 'DRAFT',
  subtotal REAL DEFAULT 0,
  discount_amount REAL DEFAULT 0,
  discount_percent REAL DEFAULT 0,
  vat_amount REAL DEFAULT 0,
  total REAL DEFAULT 0,
  currency_code TEXT,
  vat_mode TEXT,
  vat_rate REAL,
  created_at TEXT DEFAULT (datetime('now')),
  finalized_at TEXT,
  FOREIGN KEY(branch_id) REFERENCES branches(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS invoice_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER NOT NULL,
  item_type TEXT NOT NULL CHECK (item_type IN ('CUSTOM','LOCAL_CUSTOM','READY')),
  category TEXT NOT NULL CHECK (category IN ('SHEILA','ABAYA')),
  model_number TEXT,
  color TEXT,
  sheila_fabric TEXT,
  height_cm TEXT,
  width_cm TEXT,
  logo_color TEXT,
  abaya_fabric TEXT,
  size TEXT,
  upper_width_cm TEXT,
  lower_width_cm TEXT,
  sleeve_width_cm TEXT,
  sleeve_height_cm TEXT,
  logo TEXT,
  qty REAL DEFAULT 1,
  unit_price REAL DEFAULT 0,
  discount_amount REAL DEFAULT 0,
  discount_percent REAL DEFAULT 0,
  line_total REAL DEFAULT 0,
  linked_order_id INTEGER,
  linked_order_item_id INTEGER,
  sync_status TEXT,
  FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS invoice_payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER NOT NULL,
  payment_date TEXT,
  method TEXT,
  amount REAL,
  note TEXT,
  FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS customers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT,
  phone TEXT,
  created_at TEXT,
  updated_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);

CREATE TABLE IF NOT EXISTS customer_sizes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id INTEGER NOT NULL,
  category TEXT NOT NULL CHECK (category IN ('SHEILA','ABAYA')),
  model_number TEXT,
  color TEXT,
  sheila_fabric TEXT,
  height_cm TEXT,
  width_cm TEXT,
  logo_color TEXT,
  abaya_fabric TEXT,
  size TEXT,
  upper_width_cm TEXT,
  lower_width_cm TEXT,
  sleeve_width_cm TEXT,
  sleeve_height_cm TEXT,
  logo TEXT,
  updated_at TEXT,
  UNIQUE(customer_id, category, model_number),
  FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS price_book (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  branch_id INTEGER,
  category TEXT,
  model_number TEXT,
  last_unit_price REAL,
  updated_at TEXT,
  UNIQUE(branch_id, category, model_number)
);

CREATE INDEX IF NOT EXISTS idx_invoices_created_at ON invoices(created_at);
"""

def migrate():
    db = get_db()
    db.executescript(SCHEMA)
    for i in range(1, 51):
        got = db.execute("SELECT id FROM branches WHERE id=?", (i,)).fetchone()
        if not got:
            db.execute("INSERT INTO branches(id, created_at) VALUES (?, datetime('now'))", (i,))
    db.commit()

def next_invoice_no(db):
    row = db.execute("SELECT COUNT(*) AS c FROM invoices").fetchone()
    n = (row['c'] or 0) + 1
    return f"INV-{n:06d}"
