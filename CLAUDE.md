# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Personal finance dashboard for monthly analysis of Erste Bank (George) CSV exports. Stack: Python, pandas, Streamlit, Plotly.

## Commands

```bash
pip install -r requirements.txt   # install dependencies
streamlit run app.py               # run the dashboard (http://localhost:8501)
```

## Architecture

- **`pipeline.py`** — Data ingestion and categorization. Three public functions:
  - `load_data()` — reads all CSVs from `data/`, parses dates/amounts, categorizes transactions, returns a clean DataFrame with columns: `date`, `partner_name`, `amount`, `currency`, `booking_details`, `category`, `type` (income/expense/transfer), `year_month`
  - `load_budgets()` — reads `budgets.yaml`
  - `load_notes()` — reads `notes.yaml`
- **`app.py`** — Streamlit dashboard. All data cached via `@st.cache_data` (clear cache or restart server after changing YAML/Python files).
  - Sidebar: month selector, "compare with previous month" toggle, category filter
  - Summary row: Total Income / Total Expenses / Net Savings / Savings Rate %
  - Spending by category: donut chart + table with budget comparison (red highlight if over)
  - Monthly trend: stacked bar chart by category (last 12 months)
  - Income vs Expenses: grouped bar chart (last 12 months)
  - Top 10 Income + Top 10 Expenses tables (excludes Savings/Transfers and Cash Withdrawal)
  - Cash Withdrawals: separate table
  - Category detail view: shows all transactions for a selected category
  - Uncategorized transactions: always visible if any exist
  - Notes: general notes from `notes.yaml` displayed at the bottom
- **`categories.yaml`** — Single source of truth for categorization. Maps category names to keyword lists. Keywords matched case-insensitively against Partner Name + Booking details. **First match wins** — order in the file matters.
- **`budgets.yaml`** — Monthly budget limits per category (EUR).
- **`notes.yaml`** — Flat list of general notes displayed at the bottom of the dashboard.
- **`data/`** — Raw George CSV exports (gitignored). Drop a new CSV and refresh to add a month.

## Data Format (George CSV)

- Encoding: UTF-16 with BOM (pipeline tries UTF-16, then UTF-8, then latin-1)
- Comma-delimited, all fields quoted
- Date format: DD.MM.YYYY
- Amount: period decimal separator, comma thousands separator (e.g., `-2,000.00`) — commas are stripped before float conversion
- Positive = income, negative = expense

## Key Design Decisions

- **categories.yaml is the sole source of truth** — no categories or keyword overrides are hardcoded in Python. To change categorization, edit the YAML only.
- **Order matters in categories.yaml** — first keyword match wins. Place more specific categories (e.g., Kindergarten with `Stadt Wien`) above broader ones (e.g., Savings/Transfers with `Amelie`) to avoid false matches.
- **Transfer-type categories**: `Savings/Transfers` and `Adjustments` get `type=transfer` and are excluded from income/expense totals. This is defined in `_classify_type()` in `pipeline.py`.
- **Caching**: After editing YAML files, clear Streamlit cache (press C → Enter in browser) or restart the server. After editing Python files, restart the server.
- Charts use a consistent color map (Pastel + Safe palettes) so each category keeps the same color across the donut and bar charts.
