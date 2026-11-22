# Electricity Consumption & Forecasting System

Flask + HTML/CSS/JS dashboard. Records are kept in a plain text file (`data/records.txt`,
one `YYYY-MM,kWh` line per month); settings in `data/settings.json`.

## Run in an IDE (VS Code / PyCharm) on any laptop
1. Unzip, then open the `electricity-forecast` folder in your IDE (needs Python 3.9+).
2. Open a terminal in that folder and run:
   - Windows: `python -m venv .venv`, `.venv\Scripts\activate`, `pip install -r requirements.txt`, `python app.py`
   - Mac/Linux: `python3 -m venv .venv`, `source .venv/bin/activate`, `pip install -r requirements.txt`, `python3 app.py`
   (or just run `run.bat` on Windows / `./run.sh` on Mac/Linux)
3. Open http://127.0.0.1:5000. In VS Code you can also press F5 on `app.py`.

## Run
**Windows (easiest):** double-click `run.bat`. It creates a virtual environment, installs
Flask, starts the server and opens http://127.0.0.1:5000.

**Manual:**
```
pip install -r requirements.txt
python app.py
```
**Tests:** `python -m unittest test_analytics -v` (no Flask needed), or `pytest` for everything.

Optional env vars: `SECRET_KEY` (session signing), `COOKIE_SECURE=1` (when served over HTTPS).

## Features
- Add, edit, delete records (with Undo), sort and filter by year
- Total, average, highest, lowest, month-on-month and year-on-year change
- **Forecast methods** (all plain maths, no machine learning), each with a typical range:
  - 3-month average (default, per the project spec; uses all months if fewer than 3)
  - 6-month average
  - Linear trend (least squares over the latest 12 months)
  - Same month last year, scaled by recent year-on-year change
  - Any method falls back to the 3-month average if there is not enough history
- Rate per kWh + monthly budget: estimated bill with a progress bar (green / amber / red)
- Plain-English insights (vs average, vs last month / last year, trend, budget)
- Bar or line chart (12 / 36 months), average line, highlighted peak and lowest, forecast with range, tooltips
- CSV import (YYYY-MM, `2026/3`, `Jan 2026`...) and export, delete-all, sample data
- Light / dark theme, keyboard accessible, mobile layout

## Layout
- `analytics.py` - forecasting, summaries, insights, validation, CSV parsing (no Flask)
- `app.py` - routes, storage, security headers
- `templates/index.html`, `static/style.css`, `static/app.js` - UI

## Security
CSRF token on every state-changing request, server-side validation (ranges, NaN/inf rejected,
size limits), strict CSP with no inline scripts, no `innerHTML`, secure headers, atomic file
writes with locking, generic error messages. The session key is generated once and stored in
`data/.secret_key` (git-ignored).
