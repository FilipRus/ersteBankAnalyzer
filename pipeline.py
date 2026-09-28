import re
from pathlib import Path

import pandas as pd
import yaml

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CATEGORIES_FILE = BASE_DIR / "categories.yaml"
# Optional, gitignored: personal keywords (names, employer, landlord). Same
# format as categories.yaml; its rules are tried before the public ones.
LOCAL_CATEGORIES_FILE = BASE_DIR / "categories.local.yaml"
BUDGETS_FILE = BASE_DIR / "budgets.yaml"
NOTES_FILE = BASE_DIR / "notes.yaml"

# Reserved key in categories.yaml: partners whose Payment Reference holds the
# real merchant (e.g. own Revolut / Trade Republic accounts). Not a category.
REFERENCE_PARTNERS_KEY = "_check_payment_reference"

# Temporary column tagging which CSV file a row came from (used for dedup).
SOURCE_COL = "_source_file"


def _read_yaml_dict(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_categories() -> dict[str, list[str]]:
    return _read_yaml_dict(CATEGORIES_FILE)


def _load_local_categories() -> dict:
    return _read_yaml_dict(LOCAL_CATEGORIES_FILE)


def category_options() -> list[tuple[str, str]]:
    """All (category, subcategory) targets from the public and local files.

    Subcategory is "" for flat categories. Used by the dashboard to offer
    choices when categorizing transactions.
    """
    options: list[tuple[str, str]] = []
    for categories in (_load_local_categories(), _load_categories()):
        for category, keywords in categories.items():
            if category == REFERENCE_PARTNERS_KEY:
                continue
            if isinstance(keywords, dict):
                targets = [(category, sub) for sub in keywords]
            else:
                targets = [(category, "")]
            options += [t for t in targets if t not in options]
    return options


def _write_local_categories(local: dict) -> None:
    with open(LOCAL_CATEGORIES_FILE, "w", encoding="utf-8") as f:
        f.write("# Personal keywords — gitignored. Tried before categories.yaml.\n")
        yaml.safe_dump(local, f, sort_keys=False, allow_unicode=True)


def add_local_category(category: str, subcategory: str = "") -> None:
    """Create an empty category (or subcategory) in categories.local.yaml so it
    can be chosen when categorizing. Keywords are added later."""
    category, subcategory = category.strip(), subcategory.strip()
    if not category:
        raise ValueError("Category name is empty")
    if category.startswith("_") or category == "Uncategorized" or "›" in category + subcategory:
        raise ValueError(f"'{category}' is not allowed as a category name")
    if (category, subcategory) in category_options():
        raise ValueError(f"'{category}{' › ' + subcategory if subcategory else ''}' already exists")

    local = _load_local_categories()
    entry = local.get(category)
    if subcategory:
        if isinstance(entry, list) and entry:
            raise ValueError(f"'{category}' already has keywords without subcategories")
        entry = entry if isinstance(entry, dict) else {}
        entry[subcategory] = None
    elif category in local:
        raise ValueError(f"'{category}' already exists with subcategories")
    local[category] = entry
    _write_local_categories(local)


def add_local_keyword(keyword: str, category: str, subcategory: str = "") -> None:
    """Append a keyword to categories.local.yaml under category[/subcategory].

    The file is rewritten, so comments in it are not preserved.
    """
    keyword = keyword.strip()
    if not keyword:
        raise ValueError("Keyword is empty")
    local = _load_local_categories()
    entry = local.get(category)

    if subcategory:
        if isinstance(entry, list) and entry:
            raise ValueError(f"'{category}' has no subcategories in categories.local.yaml")
        entry = entry if isinstance(entry, dict) else {}
        keywords = entry.get(subcategory) or []
        if keyword not in keywords:
            keywords.append(keyword)
        entry[subcategory] = keywords
    else:
        if isinstance(entry, dict):
            raise ValueError(f"'{category}' needs a subcategory in categories.local.yaml")
        entry = entry or []
        if keyword not in entry:
            entry.append(keyword)
    local[category] = entry
    _write_local_categories(local)


def load_budgets() -> dict[str, float]:
    with open(BUDGETS_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_notes() -> list[str]:
    if not NOTES_FILE.exists():
        return []
    with open(NOTES_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def _read_csvs() -> pd.DataFrame:
    """Read all CSVs from the data directory and merge into one DataFrame.

    Exports with overlapping date ranges repeat the same transactions, so rows
    repeated across files are dropped — otherwise every shared transaction
    would be counted twice.
    """
    frames = []
    for source, csv_path in enumerate(sorted(DATA_DIR.glob("*.csv"))):
        # Try UTF-16 first (George export default), fall back to UTF-8
        for enc in ("utf-16", "utf-8", "latin-1"):
            try:
                df = pd.read_csv(csv_path, encoding=enc)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        else:
            raise ValueError(f"Could not decode {csv_path.name}")
        df[SOURCE_COL] = source
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    merged = _drop_duplicate_transactions(pd.concat(frames, ignore_index=True))
    return merged.drop(columns=SOURCE_COL)


def _drop_duplicate_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """Drop transactions repeated across overlapping exports.

    Rows are matched on the identifying columns that are present. Identical
    rows within one export are genuine repeats (e.g. two equal top-ups on the
    same day) and are kept: the n-th occurrence in one file only collapses with
    the n-th occurrence in another. Copies carrying a Payment Reference are
    preferred, since older exports lack that column. Without SOURCE_COL, every
    identical row is treated as a duplicate.
    """
    key_cols = [c for c in ("Booking Date", "Partner Name", "Amount",
                            "Booking details", "Currency") if c in df.columns]
    if not key_cols:
        return df
    if SOURCE_COL not in df.columns:
        return df.drop_duplicates(subset=key_cols).reset_index(drop=True)

    df = df.copy()
    df["_occurrence"] = df.groupby([SOURCE_COL] + key_cols, dropna=False).cumcount()
    if "Payment Reference" in df.columns:
        # Stable sort: rows with a Payment Reference win the drop_duplicates below
        df = df.sort_values("Payment Reference", key=lambda s: s.isna(), kind="stable")
    df = df.drop_duplicates(subset=key_cols + ["_occurrence"]).sort_index()
    return df.drop(columns="_occurrence").reset_index(drop=True)


def _parse_amount(val) -> float:
    """Strip thousands separator and convert to float."""
    if pd.isna(val):
        return 0.0
    s = str(val).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _kw_match(kw: str, partner: str, details: str) -> bool:
    """Match keyword against partner name first (word-boundary), falling back to
    booking details when partner name is absent."""
    pattern = r'\b' + re.escape(kw.lower()) + r'\b'
    if partner:
        return bool(re.search(pattern, partner))
    return bool(re.search(pattern, details))


def _match_categories(categories: dict, partner: str, details: str) -> tuple[str, str] | None:
    """Return the first (category, subcategory) whose keyword matches, else None."""
    for category, keywords in categories.items():
        if isinstance(keywords, list):
            for kw in (keywords or []):
                if _kw_match(kw, partner, details):
                    return (category, "")
        elif isinstance(keywords, dict):
            for subcategory, subkws in keywords.items():
                for kw in (subkws or []):
                    if _kw_match(kw, partner, details):
                        return (category, subcategory)
    return None


def keyword_matches(keyword: str, partner: str | None, details: str | None) -> bool:
    """Whether `keyword` would match a transaction, using the pipeline's rules."""
    partner = "" if partner is None or pd.isna(partner) else str(partner).lower().strip()
    details = "" if details is None or pd.isna(details) else str(details).lower().strip()
    return _kw_match(keyword, partner, details)


def _categorize(row: pd.Series, categories: dict,
                reference_partners: list[str] = (),
                local_categories: dict | None = None) -> tuple[str, str]:
    """Return (category, subcategory) for a transaction row.

    Rules from `local_categories` are tried before `categories`. For partners
    listed under `_check_payment_reference`, the Payment Reference is matched
    first; if it yields nothing, normal partner matching applies.
    """
    layers = [local_categories or {}, categories]

    def match(partner: str, details: str) -> tuple[str, str] | None:
        for layer in layers:
            found = _match_categories(layer, partner, details)
            if found:
                return found
        return None

    partner_raw = row.get("Partner Name", "")
    details_raw = row.get("Booking details", "")
    reference_raw = row.get("Payment Reference", "")
    partner = "" if pd.isna(partner_raw) else str(partner_raw).lower().strip()
    details = "" if pd.isna(details_raw) else str(details_raw).lower().strip()
    reference = "" if pd.isna(reference_raw) else str(reference_raw).lower().strip()

    if reference and any(_kw_match(p, partner, "") for p in reference_partners):
        found = match(reference, "")
        if found:
            return found

    return match(partner, details) or ("Uncategorized", "")


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
    local_categories = _load_local_categories()
    reference_partners = ((categories.pop(REFERENCE_PARTNERS_KEY, None) or [])
                          + (local_categories.pop(REFERENCE_PARTNERS_KEY, None) or []))
    raw[["category", "subcategory"]] = raw.apply(
        lambda r: _categorize(r, categories, reference_partners, local_categories),
        axis=1, result_type="expand"
    )

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
             "booking_details", "category", "subcategory", "type", "year_month"]]
    df = df.sort_values("date", ascending=False).reset_index(drop=True)
    return df