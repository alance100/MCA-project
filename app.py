"""Electricity Consumption and Forecasting System (Flask).

Records live in a plain text file (data/records.txt), one line per month:
    YYYY-MM,kWh
Settings (rate, budget, forecast method) live in data/settings.json.
All maths is in analytics.py (no machine learning).

Security notes:
- All input validated server-side (allowlists, numeric ranges, size limits).
- CSRF token required on every state-changing request.
- Strict CSP (no inline scripts), clickjacking and MIME-sniffing protections.
- No file paths come from users; data file paths are fixed.
- Errors returned to the client are generic; details go to the server log.
"""
import json
import logging
import os
import secrets
import threading
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, session

import analytics as an

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "records.txt"
SETTINGS_FILE = BASE_DIR / "data" / "settings.json"
KEY_FILE = BASE_DIR / "data" / ".secret_key"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("electricity")
_lock = threading.Lock()


def load_secret_key():
    """Secret key from env, else a random key generated once and kept on disk
    (so open browser tabs keep working after a restart). Never hardcoded."""
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    try:
        if KEY_FILE.exists():
            key = KEY_FILE.read_text(encoding="utf-8").strip()
            if len(key) >= 32:
                return key
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_hex(32)
        KEY_FILE.write_text(key, encoding="utf-8")
        try:
            os.chmod(KEY_FILE, 0o600)
        except OSError:
            pass
        return key
    except OSError:
        return secrets.token_hex(32)  # read-only disk: per-process key


app = Flask(__name__)
app.config.update(
    SECRET_KEY=load_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    MAX_CONTENT_LENGTH=256 * 1024,
    TEMPLATES_AUTO_RELOAD=True,
    SEND_FILE_MAX_AGE_DEFAULT=0,  # always revalidate static files
)


@app.context_processor
def asset_version():
    """Cache-busting query string based on static file modification times."""
    try:
        ver = int(max(p.stat().st_mtime for p in (BASE_DIR / "static").iterdir()))
    except (OSError, ValueError):
        ver = 0
    return {"ver": ver}


# ----------------------------------------------------------------- storage
def _atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def load_records():
    """Return [{'month': 'YYYY-MM', 'kwh': float}] sorted by month."""
    records = {}
    if DATA_FILE.exists():
        with DATA_FILE.open("r", encoding="utf-8") as fh:
            for line in fh:
                parts = line.strip().split(",")
                if len(parts) != 2 or not an.MONTH_RE.match(parts[0]):
                    continue  # skip corrupt lines
                try:
                    kwh = float(parts[1])
                except ValueError:
                    continue
                if 0 <= kwh <= an.MAX_KWH:
                    records[parts[0]] = kwh
    return [{"month": m, "kwh": records[m]} for m in sorted(records)]


def save_records(records):
    _atomic_write(DATA_FILE, "".join(f"{r['month']},{r['kwh']:.2f}\n" for r in records))


def load_settings():
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(an.DEFAULT_SETTINGS)
    settings, err = an.validate_settings(data)
    return settings if not err else dict(an.DEFAULT_SETTINGS)


def save_settings(settings):
    _atomic_write(SETTINGS_FILE, json.dumps(settings))


def payload(**extra):
    records, settings = load_records(), load_settings()
    summary = an.summarise(records, settings)
    return {
        "records": an.enrich(records),
        "summary": summary,
        "insights": an.insights(records, summary, settings) if records else [],
        "settings": settings,
        "methods": an.METHODS,
        "years": sorted({int(r["month"][:4]) for r in records}),
        **extra,
    }


# ---------------------------------------------------------------- security
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def csrf_ok():
    sent = request.headers.get("X-CSRF-Token", "")
    expected = session.get("csrf", "")
    return bool(expected) and secrets.compare_digest(sent, expected)


@app.before_request
def guard():
    if request.method in ("POST", "PUT", "DELETE") and not csrf_ok():
        return jsonify(error="Your session expired. Reload the page and try again."), 403


@app.after_request
def headers(resp):
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'"
    )
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if request.path.startswith("/api/") or request.path == "/export.csv":
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ------------------------------------------------------------------ routes
@app.route("/")
def index():
    return render_template("index.html", csrf=csrf_token())


@app.route("/api/records", methods=["GET"])
def get_records():
    return jsonify(payload())


@app.route("/api/records", methods=["POST"])
def add_record():
    month, kwh, err = an.parse_record(request.get_json(silent=True))
    if err:
        return jsonify(error=err), 400
    with _lock:
        existing = {r["month"]: r for r in load_records()}
        if month not in existing and len(existing) >= an.MAX_RECORDS:
            return jsonify(error="Record limit reached."), 400
        existing[month] = {"month": month, "kwh": kwh}  # add or update
        save_records([existing[m] for m in sorted(existing)])
    return jsonify(payload()), 201


@app.route("/api/records", methods=["DELETE"])
def delete_all():
    with _lock:
        save_records([])
    return jsonify(payload())


@app.route("/api/records/<month>", methods=["DELETE"])
def delete_record(month):
    if not an.MONTH_RE.match(month):
        return jsonify(error="Invalid month."), 400
    with _lock:
        save_records([r for r in load_records() if r["month"] != month])
    return jsonify(payload())


@app.route("/api/settings", methods=["POST"])
def update_settings():
    with _lock:
        settings, err = an.validate_settings(request.get_json(silent=True), load_settings())
        if err:
            return jsonify(error=err), 400
        save_settings(settings)
    return jsonify(payload())


@app.route("/api/import", methods=["POST"])
def import_csv():
    data = request.get_json(silent=True)
    text = data.get("csv") if isinstance(data, dict) else None
    if not isinstance(text, str) or not text.strip():
        return jsonify(error="No CSV data received."), 400
    if len(text) > an.MAX_CSV_CHARS:
        return jsonify(error="File is too large."), 400
    new, errors = an.parse_csv(text)
    if not new:
        msg = errors[0] if errors else "No valid rows found."
        return jsonify(error=msg), 400
    with _lock:
        existing = {r["month"]: r["kwh"] for r in load_records()}
        added = sum(1 for m in new if m not in existing)
        if len(existing) + added > an.MAX_RECORDS:
            return jsonify(error="Record limit reached."), 400
        updated = len(new) - added
        existing.update(new)
        save_records([{"month": m, "kwh": existing[m]} for m in sorted(existing)])
    return jsonify(payload(imported={"added": added, "updated": updated,
                                     "skipped": len(errors), "errors": errors[:5]})), 201


@app.route("/export.csv")
def export_csv():
    lines = ["month,kwh"] + [f"{r['month']},{r['kwh']:.2f}" for r in load_records()]
    return Response(
        "\n".join(lines) + "\n",
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=electricity.csv"},
    )


@app.errorhandler(Exception)
def handle_error(exc):
    code = getattr(exc, "code", 500)
    if not isinstance(code, int):
        code = 500
    if code >= 500:
        log.exception("Unhandled error")
        return jsonify(error="Something went wrong."), code
    return jsonify(error=str(getattr(exc, "name", "Error"))), code


if __name__ == "__main__":
    # Debug is off; bind to localhost only.
    app.run(host="127.0.0.1", port=5000, debug=False)
