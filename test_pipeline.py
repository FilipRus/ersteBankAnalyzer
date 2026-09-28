"""Unit tests for pipeline.py — pure functions only (no file I/O)."""

import pandas as pd
import pytest
import yaml

import pipeline
from pipeline import (
    SOURCE_COL,
    add_local_category,
    add_local_keyword,
    category_options,
    keyword_matches,
    _categorize,
    _classify_type,
    _drop_duplicate_transactions,
    _kw_match,
    _parse_amount,
)


# ---------------------------------------------------------------------------
# _parse_amount
# ---------------------------------------------------------------------------

class TestParseAmount:
    def test_negative_with_thousands_separator(self):
        assert _parse_amount("-2,000.00") == -2000.0

    def test_positive_plain(self):
        assert _parse_amount("1234.56") == 1234.56

    def test_nan_returns_zero(self):
        assert _parse_amount(float("nan")) == 0.0

    def test_none_returns_zero(self):
        assert _parse_amount(None) == 0.0

    def test_malformed_string_returns_zero(self):
        assert _parse_amount("abc") == 0.0

    def test_zero(self):
        assert _parse_amount("0.00") == 0.0


# ---------------------------------------------------------------------------
# _kw_match
# ---------------------------------------------------------------------------

class TestKwMatch:
    def test_matches_partner_name(self):
        assert _kw_match("obi", "obi", "some booking details")

    def test_no_false_positive_substring_in_partner(self):
        # "OBI" inside "T-Mobile Austria GmbH" must NOT match keyword "obi"
        assert not _kw_match("obi", "t-mobile austria gmbh", "")

    def test_falls_back_to_details_when_partner_absent(self):
        assert _kw_match("automat", "", "sb-automat wien")

    def test_no_match_on_details_when_partner_present(self):
        # If partner exists, details must NOT be searched
        assert not _kw_match("automat", "some partner name", "sb-automat wien")

    def test_case_insensitive_partner(self):
        # _kw_match receives pre-lowercased strings from _categorize
        assert _kw_match("billa", "billa wien", "")

    def test_case_insensitive_details(self):
        # _kw_match receives pre-lowercased strings from _categorize
        assert _kw_match("atm", "", "atm withdrawal")

    def test_word_boundary_in_details(self):
        # "atm" should not match "datm" in details
        assert not _kw_match("atm", "", "datm something")

    def test_multiword_keyword(self):
        assert _kw_match("t-mobile austria gmbh", "t-mobile austria gmbh", "")

    def test_no_match(self):
        assert not _kw_match("netflix", "amazon", "prime video")


# ---------------------------------------------------------------------------
# _categorize
# ---------------------------------------------------------------------------

def _row(partner=None, details="", reference=None):
    """Build a minimal Series mimicking a raw CSV row."""
    return pd.Series({"Partner Name": partner, "Booking details": details,
                      "Payment Reference": reference})


class TestCategorize:
    CATEGORIES = {
        "Salary": ["IBB Adaptive Solutions GmbH"],
        "Housing": {
            "Maintenance / Repairs": ["OBI"],
            "Furniture & Home Improvement": ["IKEA"],
        },
        "Utilities": {
            "Internet & Mobile Phones": ["T-Mobile Austria GmbH"],
        },
        "Cash": {
            "ATM Withdrawals": ["ATM", "AUTOMAT", "SB-Auszahlung"],
        },
        "Savings/Transfers": ["REVOLUT"],
    }

    def test_simple_list_category(self):
        cat, sub = _categorize(_row("IBB Adaptive Solutions GmbH"), self.CATEGORIES)
        assert cat == "Salary"
        assert sub == ""

    def test_subcategory_matched(self):
        cat, sub = _categorize(_row("OBI Baumarkt"), self.CATEGORIES)
        assert cat == "Housing"
        assert sub == "Maintenance / Repairs"

    def test_obi_not_inside_t_mobile(self):
        # Regression: "OBI" must NOT match inside "T-Mobile Austria GmbH"
        cat, sub = _categorize(_row("T-Mobile Austria GmbH"), self.CATEGORIES)
        assert cat == "Utilities"
        assert sub == "Internet & Mobile Phones"

    def test_automat_fallback_to_details(self):
        # No partner name → fall back to booking details
        cat, sub = _categorize(_row(partner=None, details="SB-Automat Wien"), self.CATEGORIES)
        assert cat == "Cash"
        assert sub == "ATM Withdrawals"

    def test_automat_not_matched_when_partner_present(self):
        # "AUTOMAT" in details must be ignored when a partner name exists
        cat, sub = _categorize(_row("Some Shop", details="SB-Automat Wien"), self.CATEGORIES)
        assert cat == "Uncategorized"

    def test_uncategorized_fallback(self):
        cat, sub = _categorize(_row("Unknown Merchant"), self.CATEGORIES)
        assert cat == "Uncategorized"
        assert sub == ""

    def test_nan_partner_treated_as_absent(self):
        cat, sub = _categorize(_row(partner=float("nan"), details="SB-Auszahlung"), self.CATEGORIES)
        assert cat == "Cash"

    def test_first_match_wins(self):
        # REVOLUT appears in Savings/Transfers; if it were also in another category
        # listed first, that one should win — here just verify correct single match
        cat, sub = _categorize(_row("REVOLUT"), self.CATEGORIES)
        assert cat == "Savings/Transfers"


# ---------------------------------------------------------------------------
# _classify_type
# ---------------------------------------------------------------------------

def _tx(category, amount):
    return pd.Series({"category": category, "amount": amount})


class TestClassifyType:
    def test_savings_transfers_is_transfer(self):
        assert _classify_type(_tx("Savings/Transfers", -100)) == "transfer"

    def test_adjustments_is_transfer(self):
        assert _classify_type(_tx("Adjustments", 50)) == "transfer"

    def test_positive_amount_is_income(self):
        assert _classify_type(_tx("Salary", 3000)) == "income"

    def test_zero_amount_is_income(self):
        assert _classify_type(_tx("Groceries", 0)) == "income"

    def test_negative_amount_is_expense(self):
        assert _classify_type(_tx("Groceries", -50)) == "expense"


# ---------------------------------------------------------------------------
# _drop_duplicate_transactions
# ---------------------------------------------------------------------------

def _raw(date, partner, amount, details="", currency="EUR", source=None, **extra):
    row = {
        "Booking Date": date,
        "Partner Name": partner,
        "Amount": amount,
        "Booking details": details,
        "Currency": currency,
        **extra,
    }
    if source is not None:
        row[SOURCE_COL] = source
    return row


class TestDropDuplicateTransactions:
    def test_overlapping_exports_are_deduped(self):
        # Same transaction present in two exports with overlapping date ranges
        tx = _raw("15.08.2025", "BILLA", "-42.10")
        df = pd.DataFrame([tx, tx])
        assert len(_drop_duplicate_transactions(df)) == 1

    def test_distinct_transactions_are_kept(self):
        df = pd.DataFrame([
            _raw("15.08.2025", "BILLA", "-42.10"),
            _raw("16.08.2025", "BILLA", "-42.10"),
            _raw("15.08.2025", "HOFER", "-42.10"),
            _raw("15.08.2025", "BILLA", "-13.37"),
        ])
        assert len(_drop_duplicate_transactions(df)) == 4

    def test_differing_details_are_kept(self):
        df = pd.DataFrame([
            _raw("15.08.2025", "BILLA", "-42.10", details="filiale 123"),
            _raw("15.08.2025", "BILLA", "-42.10", details="filiale 456"),
        ])
        assert len(_drop_duplicate_transactions(df)) == 2

    def test_index_is_reset(self):
        tx = _raw("15.08.2025", "BILLA", "-42.10")
        result = _drop_duplicate_transactions(pd.DataFrame([tx, tx]))
        assert list(result.index) == [0]

    def test_missing_key_columns_returns_input_unchanged(self):
        df = pd.DataFrame([{"Something Else": 1}, {"Something Else": 1}])
        assert len(_drop_duplicate_transactions(df)) == 2

    def test_empty_frame(self):
        df = pd.DataFrame(columns=["Booking Date", "Partner Name", "Amount"])
        assert _drop_duplicate_transactions(df).empty

    def test_repeats_within_one_export_are_kept(self):
        # Two genuine identical top-ups on the same day in a single export
        tx = _raw("26.05.2026", "BILLA", "-50.00", source=0)
        assert len(_drop_duplicate_transactions(pd.DataFrame([tx, tx]))) == 2

    def test_overlap_across_exports_collapses_per_occurrence(self):
        # File 0 has the transaction twice (genuine), file 1 repeats both
        a = _raw("26.05.2026", "BILLA", "-50.00", source=0)
        b = _raw("26.05.2026", "BILLA", "-50.00", source=1)
        assert len(_drop_duplicate_transactions(pd.DataFrame([a, a, b, b]))) == 2

    def test_copy_with_payment_reference_is_preferred(self):
        old = _raw("25.09.2026", "Revolut", "-7.00", source=0)
        new = _raw("25.09.2026", "Revolut", "-7.00", source=1,
                   **{"Payment Reference": "Spotify subscription"})
        result = _drop_duplicate_transactions(pd.DataFrame([old, new]))
        assert len(result) == 1
        assert result.loc[0, "Payment Reference"] == "Spotify subscription"


# ---------------------------------------------------------------------------
# _categorize — Payment Reference lookup
# ---------------------------------------------------------------------------

class TestPaymentReference:
    CATEGORIES = {
        "Investing": ["Trade Republic"],
        "RevolutMissingVisibility": ["Revolut"],
        "Subscriptions": {"Streaming": ["Spotify", "Netflix"]},
    }
    PARTNERS = ["Revolut", "Trade Republic"]

    def test_reference_matched_for_listed_partner(self):
        row = _row("My Name Revolut", reference="Spotify subscription")
        assert _categorize(row, self.CATEGORIES, self.PARTNERS) == ("Subscriptions", "Streaming")

    def test_falls_back_to_partner_when_reference_unmatched(self):
        row = _row("My Name Revolut", reference="rent share")
        assert _categorize(row, self.CATEGORIES, self.PARTNERS) == ("RevolutMissingVisibility", "")

    def test_falls_back_to_partner_when_reference_missing(self):
        row = _row("My Name Revolut", reference=float("nan"))
        assert _categorize(row, self.CATEGORIES, self.PARTNERS) == ("RevolutMissingVisibility", "")

    def test_reference_ignored_for_unlisted_partner(self):
        row = _row("Trade Republic", reference="Netflix")
        assert _categorize(row, self.CATEGORIES, ["Revolut"]) == ("Investing", "")


# ---------------------------------------------------------------------------
# Local (private) categories
# ---------------------------------------------------------------------------

class TestLocalCategories:
    PUBLIC = {
        "Savings/Transfers": ["George-Transfer"],
        "Investing": ["Traderepublic"],
        "Dining": {"Restaurants": ["RESTAURANT"]},
    }

    def test_local_rules_win_over_public(self):
        local = {"Salary": ["Jane Doe"]}
        row = _row("Jane Doe AT Traderepublic")
        assert _categorize(row, self.PUBLIC, [], local) == ("Salary", "")

    def test_public_used_when_local_has_no_match(self):
        row = _row("Jane Doe AT Traderepublic")
        assert _categorize(row, self.PUBLIC, [], {"Salary": ["Someone Else"]}) == ("Investing", "")

    def test_reference_lookup_uses_local_rules(self):
        local = {"Subscriptions": {"Streaming": ["Spotify"]}}
        row = _row("Me Revolut", reference="Spotify subscription")
        assert _categorize(row, self.PUBLIC, ["Revolut"], local) == ("Subscriptions", "Streaming")


@pytest.fixture
def category_files(tmp_path, monkeypatch):
    public = tmp_path / "categories.yaml"
    local = tmp_path / "categories.local.yaml"
    public.write_text(yaml.safe_dump({
        "_check_payment_reference": ["Revolut"],
        "Groceries": ["BILLA"],
        "Dining": {"Restaurants": ["RESTAURANT"], "Cafes": ["CAFE"]},
    }, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(pipeline, "CATEGORIES_FILE", public)
    monkeypatch.setattr(pipeline, "LOCAL_CATEGORIES_FILE", local)
    return local


class TestAddLocalKeyword:
    def test_creates_file_with_flat_category(self, category_files):
        add_local_keyword("ASIA GOURMET", "Groceries")
        assert yaml.safe_load(category_files.read_text(encoding="utf-8")) == {"Groceries": ["ASIA GOURMET"]}

    def test_adds_to_subcategory_without_duplicates(self, category_files):
        add_local_keyword("ASIA GOURMET", "Dining", "Restaurants")
        add_local_keyword("ASIA GOURMET", "Dining", "Restaurants")
        add_local_keyword("TOPCAFE", "Dining", "Cafes")
        assert yaml.safe_load(category_files.read_text(encoding="utf-8")) == {
            "Dining": {"Restaurants": ["ASIA GOURMET"], "Cafes": ["TOPCAFE"]}}

    def test_structure_mismatch_raises(self, category_files):
        add_local_keyword("ASIA GOURMET", "Dining", "Restaurants")
        with pytest.raises(ValueError):
            add_local_keyword("X", "Dining")

    def test_empty_keyword_raises(self, category_files):
        with pytest.raises(ValueError):
            add_local_keyword("  ", "Groceries")

    def test_category_options_merge_local_and_public(self, category_files):
        add_local_keyword("Jane Doe", "Personal", "Jane")
        assert category_options() == [
            ("Personal", "Jane"), ("Groceries", ""),
            ("Dining", "Restaurants"), ("Dining", "Cafes"),
        ]


class TestAddLocalCategory:
    def test_new_flat_category_is_offered(self, category_files):
        add_local_category("Pets")
        assert ("Pets", "") in category_options()

    def test_new_subcategory_then_keyword(self, category_files):
        add_local_category("Pets", "Vet")
        add_local_category("Pets", "Food")
        add_local_keyword("FRESSNAPF", "Pets", "Food")
        assert yaml.safe_load(category_files.read_text(encoding="utf-8")) == {
            "Pets": {"Vet": None, "Food": ["FRESSNAPF"]}}

    def test_empty_flat_category_then_keyword(self, category_files):
        add_local_category("Pets")
        add_local_keyword("FRESSNAPF", "Pets")
        assert yaml.safe_load(category_files.read_text(encoding="utf-8")) == {"Pets": ["FRESSNAPF"]}

    def test_empty_categories_do_not_break_categorize(self, category_files):
        add_local_category("Pets")
        add_local_category("Kids", "School")
        local = pipeline._load_local_categories()
        assert _categorize(_row("BILLA"), {"Groceries": ["BILLA"]}, [], local) == ("Groceries", "")

    @pytest.mark.parametrize("category, subcategory", [
        ("Groceries", ""),            # exists in public file
        ("Dining", "Cafes"),          # exists in public file
        ("", ""),
        ("_hidden", ""),
        ("Uncategorized", ""),
    ])
    def test_invalid_or_existing_raises(self, category_files, category, subcategory):
        with pytest.raises(ValueError):
            add_local_category(category, subcategory)

    def test_duplicate_local_raises(self, category_files):
        add_local_category("Pets", "Vet")
        with pytest.raises(ValueError):
            add_local_category("Pets", "Vet")


class TestKeywordMatches:
    def test_matches_partner(self):
        assert keyword_matches("ASIA GOURMET", "ASIA GOURMET WIEN", None)

    def test_uses_details_when_partner_missing(self):
        assert keyword_matches("savings purpose", float("nan"), "Your savings purpose zu P")

    def test_trailing_symbol_keyword_fails(self):
        # Word boundary after "*" cannot match — the app strips such characters
        assert not keyword_matches("SHOP**1234*", "SHOP**1234*", None)
