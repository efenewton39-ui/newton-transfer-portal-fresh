import os, sqlite3, secrets, hmac
from datetime import datetime, timezone
from functools import wraps
from decimal import Decimal, InvalidOperation
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort

app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET") or secrets.token_hex(32)
# Render's default filesystem is writable but ephemeral. For durable records, set
# DATABASE_PATH=/var/data/transfers.db and attach a persistent disk mounted at /var/data.
DB = os.environ.get("DATABASE_PATH", "/tmp/newton-transfer-portal/transfers.db")
STATUSES = ["Draft", "Pending", "Completed", "Failed", "Cancelled"]
CURRENCIES = ["USD", "EUR", "GBP", "NGN", "CAD", "AUD", "GHS", "KES", "ZAR", "MXN"]

def connect():
    folder = os.path.dirname(DB)
    if folder:
        os.makedirs(folder, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c

def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def init():
    with connect() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS transfers(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT UNIQUE NOT NULL, sender TEXT NOT NULL,
        recipient TEXT NOT NULL, amount TEXT NOT NULL, currency TEXT NOT NULL,
        provider TEXT DEFAULT '', destination TEXT DEFAULT '', note TEXT DEFAULT '',
        status TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS history(
        id INTEGER PRIMARY KEY AUTOINCREMENT, transfer_id INTEGER NOT NULL, action TEXT NOT NULL,
        details TEXT NOT NULL, created TEXT NOT NULL,
        FOREIGN KEY(transfer_id) REFERENCES transfers(id) ON DELETE CASCADE)""")
init()

def csrf():
    if "csrf" not in session: session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]

@app.context_processor
def template_globals():
    return {"csrf": csrf, "STATUSES": STATUSES, "CURRENCIES": CURRENCIES}

def check_csrf():
    if not session.get("csrf") or not hmac.compare_digest(session["csrf"], request.form.get("csrf", "")):
        abort(400, "Form expired. Refresh and try again.")

def admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin"): return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def log(c, tid, action, detail):
    c.execute("INSERT INTO history(transfer_id,action,details,created) VALUES(?,?,?,?)",
              (tid, action, detail[:500], now()))

def formdata():
    return {k: request.form.get(k, "").strip() for k in
            ["sender","recipient","amount","currency","provider","destination","note","status"]}

def validate(d):
    if not d["sender"] or not d["recipient"]: return "Sender and recipient are required."
    if len(d["sender"]) > 120 or len(d["recipient"]) > 120: return "Names must be 120 characters or fewer."
    try:
        n = Decimal(d["amount"])
        if not n.is_finite() or n <= 0 or n > Decimal("999999999999"):
            return "Amount must be greater than zero and within the allowed limit."
        d["amount"] = f"{n:.2f}"
    except (InvalidOperation, ValueError): return "Enter a valid amount."
    if d["currency"] not in CURRENCIES or d["status"] not in STATUSES:
        return "Choose a valid currency and status."
    for key, limit in [("provider",120),("destination",200),("note",1000)]:
        if len(d[key]) > limit: return f"{key.capitalize()} is too long."
    return None

@app.after_request
def headers(r):
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["X-Frame-Options"] = "DENY"
    r.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    r.headers["Cache-Control"] = "no-store"
    return r

@app.route("/")
def home(): return render_template("home.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        check_csrf()
        pw = os.environ.get("ADMIN_PASSWORD", "")
        if pw and hmac.compare_digest(request.form.get("password",""), pw):
            session.clear()
            session["admin"] = True
            session["csrf"] = secrets.token_urlsafe(32)
            return redirect(url_for("dashboard"))
        flash("Login failed. Check your password and Render configuration.")
    return render_template("login.html")

@app.post("/logout")
@admin
def logout():
    check_csrf()
    session.clear()
    return redirect(url_for("home"))

@app.route("/dashboard")
@admin
def dashboard():
    q = request.args.get("q","").strip()[:100]
    with connect() as c:
        rows = c.execute("""SELECT * FROM transfers
        WHERE ref LIKE ? OR sender LIKE ? OR recipient LIKE ? OR destination LIKE ?
        ORDER BY id DESC LIMIT 250""", (f"%{q}%",)*4).fetchall()
        stats = [c.execute("SELECT COUNT(*) FROM transfers").fetchone()[0],
                 c.execute("SELECT COUNT(*) FROM transfers WHERE status='Pending'").fetchone()[0],
                 c.execute("SELECT COUNT(*) FROM transfers WHERE status='Completed'").fetchone()[0]]
    return render_template("dashboard.html", rows=rows, stats=stats, q=q)

@app.route("/new", methods=["GET","POST"])
@admin
def new():
    d = {"sender":"","recipient":"","amount":"","currency":"USD","provider":"","destination":"","note":"","status":"Draft"}
    if request.method == "POST":
        check_csrf(); d = formdata(); err = validate(d)
        if err:
            flash(err); return render_template("form.html", d=d, editing=False)
        ref, stamp = "NT-" + secrets.token_hex(5).upper(), now()
        with connect() as c:
            cur = c.execute("""INSERT INTO transfers
            (ref,sender,recipient,amount,currency,provider,destination,note,status,created,updated)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (ref,d["sender"],d["recipient"],d["amount"],d["currency"],d["provider"],d["destination"],d["note"],d["status"],stamp,stamp))
            tid = cur.lastrowid
            log(c, tid, "Created", "Record created with status " + d["status"])
        return redirect(url_for("detail", tid=tid))
    return render_template("form.html", d=d, editing=False)

@app.route("/<int:tid>/edit", methods=["GET","POST"])
@admin
def edit(tid):
    with connect() as c: row = c.execute("SELECT * FROM transfers WHERE id=?", (tid,)).fetchone()
    if not row: abort(404)
    if request.method == "POST":
        check_csrf(); d = formdata(); err = validate(d)
        if err:
            flash(err); return render_template("form.html", d=d, editing=True)
        stamp = now()
        with connect() as c:
            c.execute("""UPDATE transfers SET sender=?,recipient=?,amount=?,currency=?,provider=?,
            destination=?,note=?,status=?,updated=? WHERE id=?""",
            (d["sender"],d["recipient"],d["amount"],d["currency"],d["provider"],d["destination"],d["note"],d["status"],stamp,tid))
            log(c, tid, "Updated", "Record updated; status set to " + d["status"])
        return redirect(url_for("detail", tid=tid))
    return render_template("form.html", d=dict(row), editing=True)

@app.route("/record/<int:tid>")
@admin
def detail(tid):
    with connect() as c:
        row = c.execute("SELECT * FROM transfers WHERE id=?", (tid,)).fetchone()
        history = c.execute("SELECT * FROM history WHERE transfer_id=? ORDER BY id DESC", (tid,)).fetchall()
    if not row: abort(404)
    return render_template("detail.html", t=row, history=history)

@app.route("/track", methods=["GET","POST"])
def track():
    row = None
    submitted = request.method == "POST"
    if submitted:
        ref = request.form.get("ref","").strip().upper()[:40]
        with connect() as c:
            row = c.execute("SELECT ref,recipient,amount,currency,status,updated FROM transfers WHERE ref=?", (ref,)).fetchone()
    return render_template("track.html", t=row, submitted=submitted)

@app.errorhandler(400)
def bad(e): return render_template("error.html", message=getattr(e,"description","Bad request")), 400
@app.errorhandler(404)
def missing(e): return render_template("error.html", message="That page or record was not found."), 404
@app.errorhandler(500)
def server_error(e): return render_template("error.html", message="Something went wrong. Please try again later."), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT","5000")), debug=False)
