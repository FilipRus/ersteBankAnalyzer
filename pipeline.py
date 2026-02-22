from pathlib import Path

import pandas as pd
import yaml

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CATEGORIES_FILE = BASE_DIR / "categories.yaml"
BUDGETS_FILE = BASE_DIR / "budgets.yaml"
NOTES_FILE = BASE_DIR / "notes.yaml"


def _load_categories() -> dict[str, list[str]]:
    with open(CATEGORIES_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_budgets() -> dict[str, float]:
    with open(BUDGETS_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_notes() -> list[str]:
    if not NOTES_FILE.exists():
        return []
    with open(NOTES_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def _read_csvs() -> pd.DataFrame:
    """Read all CSVs from the data directory and merge into one DataFrame."""
    frames = []
    for csv_path in sorted(DATA_DIR.glob("*.csv")):
        # Try UTF-16 first (George export default), fall back to UTF-8
        for enc in ("utf-16", "utf-8", "latin-1"):
            try:
                df = pd.read_csv(csv_path, encoding=enc)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        else:
            raise ValueError(f"Could not decode {csv_path.name}")
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _parse_amount(val) -> float:
    """Strip thousands separator and convert to float."""
    if pd.isna(val):
        return 0.0
    s = str(val).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _categorize(row: pd.Series, categories: dict[str, list[str]]) -> str:
    """Return the first matching category for a transaction row."""
    partner = str(row.get("Partner Name", "")).lower()
    details = str(row.get("Booking details", "")).lower()
    text = f"{partner} {details}"

    for category, keywords in categories.items():
        for kw in keywords:
            if kw.lower() in text:
                return category

    return "Uncategorized"


def _classify_type(row: pd.Series) -> str:
    """Classify transaction as income, expense, or transfer."""
    if row["category"] in ("Savings/Transfers", "Adjustments"):
        return "transfer"
    if row["amount"] >= 0:
        return "income"
    return "expense"


def load_data() -> pd.DataFrame:
    """Load, clean, categorize, and return the full transaction DataFrame.

    Returned columns:
        date, partner_name, amount, currency, booking_details,
        category, type, year_month
    """
    raw = _read_csvs()
    if raw.empty:
        return raw

    categories = _load_categories()
    raw["category"] = raw.apply(lambda r: _categorize(r, categories), axis=1)

    df = raw.rename(columns={
        "Booking Date": "date",
        "Partner Name": "partner_name",
        "Amount": "amount",
        "Currency": "currency",
        "Booking details": "booking_details",
    })

    df["date"] = pd.to_datetime(df["date"], format="%d.%m.%Y", dayfirst=True)
    df["amount"] = df["amount"].apply(_parse_amount)
    df["type"] = df.apply(_classify_type, axis=1)
    df["year_month"] = df["date"].dt.to_period("M")

    # Keep only useful columns
    df = df[["date", "partner_name", "amount", "currency",
             "booking_details", "category", "type", "year_month"]]
    df = df.sort_values("date", ascending=False).reset_index(drop=True)
    return df
