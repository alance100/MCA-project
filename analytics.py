"""Pure analytics, forecasting and validation (no Flask), so it is easy to unit-test.

Forecasting is mathematical only (no machine learning):
  avg3      mean of the latest 3 months          (default, as in the project spec)
  avg6      mean of the latest 6 months
  trend     least-squares line through the latest 12 months
  seasonal  same month last year, scaled by recent year-on-year change
Every method falls back to avg3 when there is not enough history.
"""
import math
import re

MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]
MAX_KWH = 1_000_000.0
MAX_RATE = 1000.0
MAX_BUDGET = 1_000_000_000.0
MAX_CSV_CHARS = 100_000
MAX_RECORDS = 1200

DEFAULT_METHOD = "avg3"
METHODS = {
    "avg3": "3-month average",
    "avg6": "6-month average",
    "trend": "Linear trend",
    "seasonal": "Same month last year",
}
DEFAULT_SETTINGS = {"rate": 0.0, "budget": 0.0, "method": DEFAULT_METHOD}


# ------------------------------------------------------------------ months
def month_index(month):
    return int(month[:4]) * 12 + int(month[5:]) - 1


def index_month(i):
    y, m = divmod(i, 12)
    return f"{y:04d}-{m + 1:02d}"


def month_label(month):
    return f"{MONTH_NAMES[int(month[5:]) - 1]} {month[:4]}"


def next_month(month):
    return index_month(month_index(month) + 1)


def normalise_month(text):
    """Accept 2026-01, 2026/1, 'Jan 2026', 'January 2026'. Return 'YYYY-MM' or None."""
    text = str(text).strip()
    m = re.fullmatch(r"(\d{4})[-/](\d{1,2})", text)
    if m:
        mo = int(m.group(2))
        return f"{m.group(1)}-{mo:02d}" if 1 <= mo <= 12 else None
    m = re.fullmatch(r"([A-Za-z]{3,9})\.?\s+(\d{4})", text)
    if m:
        key = m.group(1)[:3].lower()
        for i, name in enumerate(MONTH_NAMES, 1):
            if name[:3].lower() == key:
                return f"{m.group(2)}-{i:02d}"
    return None


# -------------------------------------------------------------- validation
def parse_number(value, low, high, what):
    """Return (float, error). Rejects bool, NaN, inf and out-of-range values."""
    if isinstance(value, bool):
        return None, f"{what} must be a number."
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None, f"{what} must be a number."
    if not math.isfinite(num) or num < low or num > high:
        return None, f"{what} must be between {low:g} and {high:,.0f}."
    return round(num, 2), None


def parse_record(data):
    """Validate {'month','kwh'}. Return (month, kwh, error)."""
    if not isinstance(data, dict):
        return None, None, "Invalid request."
    month = data.get("month")
    if not isinstance(month, str) or not MONTH_RE.match(month):
        return None, None, "Month must be in YYYY-MM format."
    kwh, err = parse_number(data.get("kwh"), 0, MAX_KWH, "Consumption")
    if err:
        return None, None, err
    return month, kwh, None


def validate_settings(data, base=None):
    """Return (settings, error). Only known keys are accepted."""
    if not isinstance(data, dict):
        return None, "Invalid request."
    out = dict(base or DEFAULT_SETTINGS)
    if "rate" in data:
        out["rate"], err = parse_number(data["rate"], 0, MAX_RATE, "Rate")
        if err:
            return None, err
    if "budget" in data:
        out["budget"], err = parse_number(data["budget"], 0, MAX_BUDGET, "Budget")
        if err:
            return None, err
    if "method" in data:
        if data["method"] not in METHODS:
            return None, "Unknown forecast method."
        out["method"] = data["method"]
    return out, None


def parse_csv(text):
    """Parse 'month,kwh' lines. Return (records_dict, errors)."""
    records, errors = {}, []
    lines = text.splitlines()
    if len(lines) > MAX_RECORDS + 5:
        return {}, [f"Too many lines (max {MAX_RECORDS})."]
    for n, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        if n == 1 and line.lower().replace(" ", "").startswith("month"):
            continue  # header row
        parts = [p.strip() for p in re.split(r"[,;\t]", line)]
        if len(parts) != 2:
            errors.append(f"Line {n}: expected 'month,kwh'.")
            continue
        month = normalise_month(parts[0])
        if not month:
            errors.append(f"Line {n}: unrecognised month '{parts[0][:20]}'.")
            continue
        kwh, err = parse_number(parts[1], 0, MAX_KWH, "Consumption")
        if err:
            errors.append(f"Line {n}: {err}")
            continue
        records[month] = kwh
    return records, errors


# ---------------------------------------------------------------- maths
def _mean(vals):
    return sum(vals) / len(vals)


def _std(vals):
    if len(vals) < 2:
        return 0.0
    mu = _mean(vals)
    return math.sqrt(sum((v - mu) ** 2 for v in vals) / (len(vals) - 1))


def _linreg(xs, ys):
    """Least squares. Return (slope, intercept, residual_std)."""
    n = len(xs)
    mx, my = _mean(xs), _mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = 0.0 if sxx == 0 else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    intercept = my - slope * mx
    if n > 2:
        resid = math.sqrt(sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys)) / (n - 2))
    else:
        resid = 0.0
    return slope, intercept, resid


def pct_change(new, old):
    if old is None or old <= 0:
        return None
    return round((new - old) / old * 100, 1)


def forecast(records, method=DEFAULT_METHOD):
    """Forecast the month after the latest record. `records` sorted by month."""
    if not records:
        return None
    if method not in METHODS:
        method = DEFAULT_METHOD
    target = month_index(records[-1]["month"]) + 1
    by = {month_index(r["month"]): r["kwh"] for r in records}
    vals = [r["kwh"] for r in records]
    used, note = method, ""
    value = spread = None
    basis = 0

    if used == "seasonal":
        prev = by.get(target - 12)
        if prev is None:
            used = "avg3"
            note = "Needs the same month from last year; used the 3-month average instead."
        else:
            ratio = 1.0
            pairs = [(by.get(target - k), by.get(target - k - 12)) for k in (1, 2, 3)]
            if all(a is not None and b is not None and b > 0 for a, b in pairs):
                ratio = min(2.0, max(0.5, sum(a for a, _ in pairs) / sum(b for _, b in pairs)))
            value, spread, basis = prev * ratio, _std(vals[-6:]), 1

    if used == "trend":
        pts = records[-12:]
        if len(pts) < 3:
            used = "avg3"
            note = "Trend needs at least 3 months; used the 3-month average instead."
        else:
            xs = [month_index(r["month"]) for r in pts]
            slope, icpt, spread = _linreg(xs, [r["kwh"] for r in pts])
            value, basis = max(0.0, slope * target + icpt), len(pts)

    if used in ("avg3", "avg6"):
        window = vals[-(3 if used == "avg3" else 6):]
        value, spread, basis = _mean(window), _std(window), len(window)

    month = index_month(target)
    return {
        "value": round(value, 2),
        "low": round(max(0.0, value - spread), 2),
        "high": round(value + spread, 2),
        "month": month,
        "label": month_label(month),
        "method": used,
        "method_label": METHODS[used],
        "requested": method,
        "note": note,
        "basis": basis,
    }


def enrich(records):
    """Add label, year, month-on-month and year-on-year change to each record."""
    by = {month_index(r["month"]): r["kwh"] for r in records}
    out = []
    for r in records:
        i = month_index(r["month"])
        out.append({
            **r,
            "label": month_label(r["month"]),
            "year": int(r["month"][:4]),
            "mom_pct": pct_change(r["kwh"], by.get(i - 1)),
            "yoy_pct": pct_change(r["kwh"], by.get(i - 12)),
        })
    return out


def summarise(records, settings=None):
    settings = settings or DEFAULT_SETTINGS
    if not records:
        return {"count": 0}
    vals = [r["kwh"] for r in records]
    total = sum(vals)
    average = total / len(records)
    hi = max(records, key=lambda r: r["kwh"])
    lo = min(records, key=lambda r: r["kwh"])
    latest = records[-1]
    fc = forecast(records, settings.get("method", DEFAULT_METHOD))
    by = {month_index(r["month"]): r["kwh"] for r in records}
    li = month_index(latest["month"])

    rate, budget = settings.get("rate", 0), settings.get("budget", 0)
    cost = round(fc["value"] * rate, 2) if rate > 0 else None
    budget_pct = round(cost / budget * 100, 1) if cost is not None and budget > 0 else None
    status = None
    if budget_pct is not None:
        status = "over" if budget_pct > 100 else "near" if budget_pct >= 90 else "ok"

    years = {}
    for r in records:
        y = r["month"][:4]
        years.setdefault(y, []).append(r["kwh"])

    def pack(r):
        return {"month": r["month"], "label": month_label(r["month"]), "kwh": r["kwh"]}

    return {
        "count": len(records),
        "total": round(total, 2),
        "average": round(average, 2),
        "highest": pack(hi),
        "lowest": pack(lo),
        "latest": pack(latest),
        "forecast": fc,
        "mom_pct": pct_change(latest["kwh"], by.get(li - 1)),
        "yoy_pct": pct_change(latest["kwh"], by.get(li - 12)),
        "vs_average_pct": pct_change(latest["kwh"], average),
        "cost": cost,
        "budget_pct": budget_pct,
        "budget_status": status,
        "years": [{"year": int(y), "total": round(sum(v), 2),
                   "average": round(_mean(v), 2), "count": len(v)}
                  for y, v in sorted(years.items())],
    }


def insights(records, summary, settings=None):
    """Short plain-language observations. Returns [{'level','text'}]."""
    settings = settings or DEFAULT_SETTINGS
    out = []
    if not records:
        return [{"level": "info", "text": "Add your first month of consumption to see insights."}]
    n = len(records)
    if n < 3:
        out.append({"level": "info",
                    "text": "Add at least 3 months for a more reliable forecast."})
    s, latest = summary, summary["latest"]

    v = s["vs_average_pct"]
    if n >= 2 and v is not None:
        level = "warn" if v > 15 else "good" if v < -15 else "info"
        word = "more" if v > 0 else "less"
        out.append({"level": level,
                    "text": f"{latest['label']} used {abs(v):g}% {word} than your monthly average."})
    if s["mom_pct"] is not None:
        word = "up" if s["mom_pct"] > 0 else "down"
        out.append({"level": "warn" if s["mom_pct"] > 15 else "info",
                    "text": f"Usage is {word} {abs(s['mom_pct']):g}% from the previous month."})
    if s["yoy_pct"] is not None:
        word = "higher" if s["yoy_pct"] > 0 else "lower"
        out.append({"level": "warn" if s["yoy_pct"] > 15 else "good" if s["yoy_pct"] < -5 else "info",
                    "text": f"{abs(s['yoy_pct']):g}% {word} than the same month last year."})
    if n >= 4:
        pts = records[-6:]
        slope, _, _ = _linreg([month_index(r["month"]) for r in pts], [r["kwh"] for r in pts])
        if abs(slope) >= 0.02 * s["average"]:
            out.append({"level": "warn" if slope > 0 else "good",
                        "text": f"Over the last {len(pts)} months usage is {'rising' if slope > 0 else 'falling'} "
                                f"by about {abs(slope):.1f} kWh per month."})
    fc = s["forecast"]
    if fc["note"]:
        out.append({"level": "info", "text": fc["note"]})
    if s["cost"] is None:
        out.append({"level": "info", "text": "Set a rate per kWh in Settings to see bill estimates."})
    elif s["budget_status"] == "over":
        out.append({"level": "warn",
                    "text": f"Forecast bill {s['cost']:,.2f} is over your budget by "
                            f"{s['cost'] - settings['budget']:,.2f}."})
    elif s["budget_status"] == "near":
        out.append({"level": "warn",
                    "text": f"Forecast bill is {s['budget_pct']:g}% of your budget - close to the limit."})
    elif s["budget_status"] == "ok":
        out.append({"level": "good", "text": f"Forecast bill is {s['budget_pct']:g}% of your budget."})
    return out
