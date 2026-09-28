import streamlit as st
import plotly.express as px
import pandas as pd

import re

from pipeline import (
    add_local_category,
    add_local_keyword,
    category_options,
    keyword_matches,
    load_budgets,
    load_data,
    load_notes,
)

st.set_page_config(page_title="Finance Dashboard", layout="wide")
st.title("Personal Finance Dashboard")


@st.cache_data
def get_data():
    return load_data()


@st.cache_data
def get_budgets():
    return load_budgets()


df = get_data()

if df.empty:
    st.warning("No transaction data found. Drop CSV files into the `data/` folder and refresh.")
    st.stop()

budgets = get_budgets()

# Consistent color map across all charts — built once so every chart uses the
# same color per category regardless of which sections render.
all_cats = sorted(df["category"].unique())
palette = px.colors.qualitative.Pastel + px.colors.qualitative.Safe
color_map = {cat: palette[i % len(palette)] for i, cat in enumerate(all_cats)}

# ---------------------------------------------------------------------------
# Sidebar — month selector
# ---------------------------------------------------------------------------
months = sorted(df["year_month"].unique())
# Newest first in the dropdown; the latest month is selected by default
month_labels = [str(m) for m in reversed(months)]

selected_label = st.sidebar.selectbox("Month", month_labels, index=0)
selected_month = pd.Period(selected_label, freq="M")

compare = st.sidebar.toggle("Compare with previous month", value=False)

all_categories = ["All"] + sorted(df["category"].unique())
selected_category = st.sidebar.selectbox("Filter by Category", all_categories)

month_df = df[df["year_month"] == selected_month]
expenses_df = month_df[month_df["type"] == "expense"]
income_df = month_df[month_df["type"] == "income"]

# Previous month for comparison
prev_month = selected_month - 1
prev_df = df[df["year_month"] == prev_month]
prev_expenses_df = prev_df[prev_df["type"] == "expense"]
prev_income_df = prev_df[prev_df["type"] == "income"]

# ---------------------------------------------------------------------------
# Summary row
# ---------------------------------------------------------------------------
total_income = income_df["amount"].sum()
total_expenses = expenses_df["amount"].sum()  # negative
net_savings = total_income + total_expenses
savings_rate = (net_savings / total_income * 100) if total_income > 0 else 0

prev_total_income = prev_income_df["amount"].sum()
prev_total_expenses = prev_expenses_df["amount"].sum()
prev_net = prev_total_income + prev_total_expenses
prev_rate = (prev_net / prev_total_income * 100) if prev_total_income > 0 else 0

cols = st.columns(4)

if compare:
    cols[0].metric("Total Income", f"€{total_income:,.2f}",
                   delta=f"€{total_income - prev_total_income:,.2f}")
    cols[1].metric("Total Expenses", f"€{abs(total_expenses):,.2f}",
                   delta=f"€{abs(total_expenses) - abs(prev_total_expenses):,.2f}",
                   delta_color="inverse")
    cols[2].metric("Net Savings", f"€{net_savings:,.2f}",
                   delta=f"€{net_savings - prev_net:,.2f}")
    cols[3].metric("Savings Rate", f"{savings_rate:.1f}%",
                   delta=f"{savings_rate - prev_rate:.1f}pp")
else:
    cols[0].metric("Total Income", f"€{total_income:,.2f}")
    cols[1].metric("Total Expenses", f"€{abs(total_expenses):,.2f}")
    cols[2].metric("Net Savings", f"€{net_savings:,.2f}")
    cols[3].metric("Savings Rate", f"{savings_rate:.1f}%")

st.divider()

# ---------------------------------------------------------------------------
# Year-to-Date summary
# ---------------------------------------------------------------------------
show_ytd = st.toggle("Show Year-to-Date summary", value=False)

if show_ytd:
    selected_year = selected_month.year
    ytd_months = [m for m in months if m.year == selected_year and m <= selected_month]
    ytd_df = df[df["year_month"].isin(ytd_months)]
    ytd_expenses = ytd_df[ytd_df["type"] == "expense"]
    ytd_income = ytd_df[ytd_df["type"] == "income"]

    ytd_total_income = ytd_income["amount"].sum()
    ytd_total_expenses = ytd_expenses["amount"].sum()
    ytd_net = ytd_total_income + ytd_total_expenses
    ytd_rate = (ytd_net / ytd_total_income * 100) if ytd_total_income > 0 else 0
    num_months = len(ytd_months)

    st.subheader(f"Year-to-Date — {selected_year} (Jan–{selected_month.strftime('%b')})")

    ytd_cols = st.columns(5)
    ytd_cols[0].metric("YTD Income", f"€{ytd_total_income:,.2f}")
    ytd_cols[1].metric("YTD Expenses", f"€{abs(ytd_total_expenses):,.2f}")
    ytd_cols[2].metric("YTD Net Savings", f"€{ytd_net:,.2f}")
    ytd_cols[3].metric("YTD Savings Rate", f"{ytd_rate:.1f}%")
    ytd_cols[4].metric("Monthly Avg Expenses", f"€{abs(ytd_total_expenses) / max(num_months, 1):,.2f}")

    # Per-category YTD breakdown
    ytd_cat = (
        ytd_expenses.groupby("category")["amount"]
        .sum()
        .abs()
        .sort_values(ascending=False)
        .reset_index()
        .rename(columns={"amount": "ytd_spent"})
    )
    if not ytd_cat.empty:
        ytd_cat["monthly_avg"] = (ytd_cat["ytd_spent"] / max(num_months, 1)).round(2)
        ytd_cat["% of total"] = (ytd_cat["ytd_spent"] / ytd_cat["ytd_spent"].sum() * 100).round(1)
        ytd_display = ytd_cat.copy()
        ytd_display["ytd_spent"] = ytd_display["ytd_spent"].map(lambda x: f"€{x:,.2f}")
        ytd_display["monthly_avg"] = ytd_display["monthly_avg"].map(lambda x: f"€{x:,.2f}")
        ytd_display.columns = ["Category", "YTD Spent", "Monthly Avg", "% of Total"]
        st.dataframe(ytd_display, use_container_width=True, hide_index=True)

    st.divider()

# ---------------------------------------------------------------------------
# Spending by category — donut chart + table
# ---------------------------------------------------------------------------
st.subheader("Spending by Category")

cat_spend = (
    expenses_df.groupby("category")["amount"]
    .sum()
    .abs()
    .sort_values(ascending=False)
    .reset_index()
    .rename(columns={"amount": "spent"})
)

if not cat_spend.empty:
    cat_spend["% of total"] = (cat_spend["spent"] / cat_spend["spent"].sum() * 100).round(1)
    cat_spend["budget"] = cat_spend["category"].map(budgets).fillna(0)
    cat_spend["vs budget"] = cat_spend.apply(
        lambda r: f"€{r['spent'] - r['budget']:+,.2f}" if r["budget"] > 0 else "—", axis=1
    )
    cat_spend["over_budget"] = (cat_spend["budget"] > 0) & (cat_spend["spent"] > cat_spend["budget"])

    left, right = st.columns([1, 1])

    with left:
        fig = px.pie(
            cat_spend, values="spent", names="category", hole=0.45,
            color="category", color_discrete_map=color_map,
        )
        fig.update_traces(textposition="inside", textinfo="percent+label")
        fig.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=400)
        st.plotly_chart(fig, use_container_width=True)


    with right:
        display = cat_spend[["category", "spent", "% of total", "budget", "vs budget"]].copy()
        display["spent"] = display["spent"].map(lambda x: f"€{x:,.2f}")
        display["budget"] = display["budget"].map(lambda x: f"€{x:,.2f}" if x > 0 else "—")
        display.columns = ["Category", "Spent", "% of Total", "Budget", "vs Budget"]

        def highlight_over(row):
            cat = cat_spend[cat_spend["category"] == row["Category"]]
            if not cat.empty and cat.iloc[0]["over_budget"]:
                return ["background-color: #ffcccc"] * len(row)
            return [""] * len(row)

        st.dataframe(
            display.style.apply(highlight_over, axis=1),
            use_container_width=True,
            hide_index=True,
        )

st.divider()

# ---------------------------------------------------------------------------
# Monthly trend — stacked bar chart, last 12 months
# ---------------------------------------------------------------------------
st.subheader("Monthly Trend (Last 12 Months)")

show_rolling_avg = st.toggle("Show 3-month rolling average", value=False)

recent_months = sorted(months)[-12:]
trend_df = df[(df["year_month"].isin(recent_months)) & (df["type"] == "expense")]
trend_agg = (
    trend_df.groupby(["year_month", "category"])["amount"]
    .sum()
    .abs()
    .reset_index()
    .rename(columns={"amount": "spent", "year_month": "month"})
)
trend_agg["month"] = trend_agg["month"].astype(str)

if not trend_agg.empty:
    fig2 = px.bar(
        trend_agg, x="month", y="spent", color="category",
        color_discrete_map=color_map,
        labels={"spent": "Amount (€)", "month": "Month"},
    )
    fig2.update_layout(barmode="stack", margin=dict(t=20, b=20), height=420)

    if show_rolling_avg:
        monthly_totals = trend_agg.groupby("month")["spent"].sum().reset_index()
        monthly_totals = monthly_totals.sort_values("month")
        monthly_totals["rolling_avg"] = monthly_totals["spent"].rolling(window=3, min_periods=1).mean()
        fig2.add_scatter(
            x=monthly_totals["month"], y=monthly_totals["rolling_avg"],
            mode="lines+markers", name="3-mo avg",
            line=dict(color="#333333", width=3, dash="dot"),
            marker=dict(size=6),
        )

    st.plotly_chart(fig2, use_container_width=True)

# Income vs Expenses
st.subheader("Income vs Expenses (Last 12 Months)")

ie_df = df[df["year_month"].isin(recent_months) & df["type"].isin(["income", "expense"])]
ie_agg = (
    ie_df.groupby(["year_month", "type"])["amount"]
    .sum()
    .abs()
    .reset_index()
    .rename(columns={"amount": "total", "year_month": "month"})
)
ie_agg["month"] = ie_agg["month"].astype(str)

if not ie_agg.empty:
    fig3 = px.bar(
        ie_agg, x="month", y="total", color="type", barmode="group",
        color_discrete_map={"income": "#66bb6a", "expense": "#ef5350"},
        labels={"total": "Amount (€)", "month": "Month"},
    )
    fig3.update_layout(margin=dict(t=20, b=20), height=400)
    st.plotly_chart(fig3, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Top 10 transactions
# ---------------------------------------------------------------------------
top_cols = ["date", "partner_name", "amount", "category", "booking_details"]
top_header = ["Date", "Partner", "Amount", "Category", "Details"]

left_top, right_top = st.columns(2)

with left_top:
    st.subheader(f"Top 10 Income — {selected_label}")
    top_income = (
        month_df[(month_df["amount"] > 0) & (month_df["category"] != "Savings/Transfers")]
        .sort_values("amount", ascending=False)
        .head(10)[top_cols].copy()
    )
    top_income["date"] = top_income["date"].dt.strftime("%d.%m.%Y")
    top_income["amount"] = top_income["amount"].map(lambda x: f"€{x:,.2f}")
    top_income.columns = top_header
    st.dataframe(top_income, use_container_width=True, hide_index=True)

exclude_cats = {"Savings/Transfers", "Cash Withdrawal"}

with right_top:
    st.subheader(f"Top 10 Expenses — {selected_label}")
    top_expense = (
        month_df[(month_df["amount"] < 0) & (~month_df["category"].isin(exclude_cats))]
        .sort_values("amount")
        .head(10)[top_cols].copy()
    )
    top_expense["date"] = top_expense["date"].dt.strftime("%d.%m.%Y")
    top_expense["amount"] = top_expense["amount"].map(lambda x: f"€{x:,.2f}")
    top_expense.columns = top_header
    st.dataframe(top_expense, use_container_width=True, hide_index=True)

cash_df = month_df[month_df["category"] == "Cash Withdrawal"]
if not cash_df.empty:
    st.subheader(f"Cash Withdrawals — {selected_label} ({len(cash_df)} transactions, €{cash_df['amount'].sum():,.2f})")
    cash_display = cash_df[["date", "amount", "booking_details"]].copy()
    cash_display = cash_display.sort_values("date")
    cash_display["date"] = cash_display["date"].dt.strftime("%d.%m.%Y")
    cash_display["amount"] = cash_display["amount"].map(lambda x: f"€{x:,.2f}")
    cash_display.columns = ["Date", "Amount", "Details"]
    st.dataframe(cash_display, use_container_width=True, hide_index=True)

st.divider()

# ---------------------------------------------------------------------------
# Category detail view
# ---------------------------------------------------------------------------
if selected_category != "All":
    cat_txns = month_df[month_df["category"] == selected_category]
    st.subheader(f"{selected_category} — {selected_label} ({len(cat_txns)} transactions)")

    if not cat_txns.empty:
        cat_expense_txns = cat_txns[cat_txns["type"] == "expense"]
        if cat_expense_txns["subcategory"].ne("").any():
            sub_spend = (
                cat_expense_txns.groupby("subcategory")["amount"]
                .sum().abs().sort_values(ascending=False).reset_index()
                .rename(columns={"amount": "spent"})
            )
            sub_total = sub_spend["spent"].sum()
            sub_spend["% of category"] = (sub_spend["spent"] / sub_total * 100).round(1) if sub_total > 0 else 0.0
            sub_display = sub_spend.copy()
            sub_display["spent"] = sub_display["spent"].map(lambda x: f"€{x:,.2f}")
            sub_display["% of category"] = sub_display["% of category"].map(lambda x: f"{x}%")
            sub_display.columns = ["Subcategory", "Spent", "% of Category"]
            st.markdown("**Subcategory Breakdown**")
            st.dataframe(sub_display, use_container_width=True, hide_index=True)

        cat_detail = cat_txns[["date", "partner_name", "amount", "booking_details"]].copy()
        cat_detail = cat_detail.sort_values("date")
        cat_detail["date"] = cat_detail["date"].dt.strftime("%d.%m.%Y")
        cat_total = cat_detail["amount"].sum()
        cat_detail["amount"] = cat_detail["amount"].map(lambda x: f"€{x:,.2f}")
        cat_detail.columns = ["Date", "Partner", "Amount", "Details"]
        st.dataframe(cat_detail, use_container_width=True, hide_index=True)
        st.caption(f"Total: €{cat_total:,.2f}")
    else:
        st.info(f"No {selected_category} transactions this month.")

    st.divider()

# ---------------------------------------------------------------------------
# Uncategorized transactions
# ---------------------------------------------------------------------------
uncat = month_df[month_df["category"] == "Uncategorized"]

if not uncat.empty:
    st.subheader(f"Uncategorized Transactions ({len(uncat)})")
    st.caption("Add keywords to `categories.yaml` to categorize these, then refresh.")

    uncat_display = uncat[["date", "partner_name", "amount", "booking_details"]].copy()
    uncat_display["date"] = uncat_display["date"].dt.strftime("%d.%m.%Y")
    uncat_display["amount"] = uncat_display["amount"].map(lambda x: f"€{x:,.2f}")
    uncat_display.columns = ["Date", "Partner", "Amount", "Details"]
    st.dataframe(uncat_display, use_container_width=True, hide_index=True)
else:
    st.success("All transactions are categorized for this month.")

# ---------------------------------------------------------------------------
# Categorize — assign uncategorized partners to a category from the dashboard
# ---------------------------------------------------------------------------
if "categorize_saved" in st.session_state:
    st.success(st.session_state.pop("categorize_saved"))

all_uncat = df[df["category"] == "Uncategorized"]
if not all_uncat.empty:
    with st.expander(f"Categorize transactions ({len(all_uncat)} uncategorized in all months)",
                     expanded=not uncat.empty):
        st.caption(
            "Pick a category for each partner and save. The keyword is added to the "
            "private, gitignored `categories.local.yaml` and applies to all months. "
            "Shorten the keyword to cover variants (e.g. `BILLA` instead of `BILLA DANKT 123`)."
        )
        with st.popover("➕ New category"):
            with st.form("new_category", clear_on_submit=True):
                new_cat = st.text_input("Category", placeholder="e.g. Pets")
                new_sub = st.text_input("Subcategory (optional)", placeholder="e.g. Vet")
                if st.form_submit_button("Create"):
                    try:
                        add_local_category(new_cat, new_sub)
                        label = f"{new_cat.strip()} › {new_sub.strip()}" if new_sub.strip() else new_cat.strip()
                        st.session_state["categorize_saved"] = (
                            f"Created “{label}” — pick it in the “Assign to” column.")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))

        scope = st.radio("Show", ["This month", "All months"], horizontal=True,
                         index=0 if not uncat.empty else 1)
        source = uncat if scope == "This month" else all_uncat

        # Group by the text the keyword is matched against: partner name, or
        # booking details when the partner is absent.
        grouped = (
            source.assign(
                match_on=source["partner_name"].where(
                    source["partner_name"].notna(), source["booking_details"]
                ).fillna(""),
                has_partner=source["partner_name"].notna(),
            )
            .groupby(["match_on", "has_partner"], as_index=False)
            .agg(count=("amount", "size"), total=("amount", "sum"))
            .sort_values(["count", "total"], ascending=[False, True])
            .reset_index(drop=True)
        )

        options = category_options()
        labels = [f"{c} › {s}" if s else c for c, s in options]
        target_by_label = dict(zip(labels, options))

        editor_df = pd.DataFrame({
            "Partner / details": grouped["match_on"],
            "Count": grouped["count"],
            "Total (€)": grouped["total"].round(2),
            "Keyword": grouped["match_on"].map(
                lambda t: re.sub(r"^\W+|\W+$", "", t)[:60]),
            "Assign to": pd.Series([None] * len(grouped), dtype="object"),
        })
        editor_key = f"categorize_editor_{scope}"
        edited = st.data_editor(
            editor_df,
            key=editor_key,
            hide_index=True,
            use_container_width=True,
            disabled=["Partner / details", "Count", "Total (€)"],
            column_config={
                "Total (€)": st.column_config.NumberColumn(format="€%.2f"),
                "Assign to": st.column_config.SelectboxColumn(options=labels),
            },
        )

        if st.button("Save categories", type="primary"):
            to_save = edited[edited["Assign to"].notna()]
            saved, errors = [], []
            for i, row in to_save.iterrows():
                keyword = str(row["Keyword"] or "").strip()
                partner = grouped.loc[i, "match_on"] if grouped.loc[i, "has_partner"] else None
                details = None if partner else grouped.loc[i, "match_on"]
                if not keyword or not keyword_matches(keyword, partner, details):
                    errors.append(f"`{keyword}` does not match “{row['Partner / details']}”")
                    continue
                category, subcategory = target_by_label[row["Assign to"]]
                try:
                    add_local_keyword(keyword, category, subcategory)
                    saved.append(f"`{keyword}` → {row['Assign to']}")
                except ValueError as e:
                    errors.append(f"`{keyword}`: {e}")
            if to_save.empty:
                st.info("Choose a category in the “Assign to” column first.")
            for err in errors:
                st.error(err)
            if saved:
                st.cache_data.clear()
                # Row positions change once saved partners drop out; reset edits
                st.session_state.pop(editor_key, None)
                if errors:
                    st.success("Saved: " + ", ".join(saved) + " — refresh to update the dashboard.")
                else:
                    st.session_state["categorize_saved"] = "Saved: " + ", ".join(saved)
                    st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Transaction search (across all months)
# ---------------------------------------------------------------------------
st.subheader("Transaction Search")

search_query = st.text_input("Search by partner name or booking details", placeholder="e.g. BILLA, IKEA")

if search_query:
    query_lower = search_query.lower()
    search_results = df[
        df["partner_name"].fillna("").str.lower().str.contains(query_lower, regex=False)
        | df["booking_details"].fillna("").str.lower().str.contains(query_lower, regex=False)
    ].copy()

    if not search_results.empty:
        total = search_results["amount"].sum()
        count = len(search_results)
        st.caption(f"Found **{count}** transactions matching \"{search_query}\" — Total: **€{total:,.2f}**")

        search_display = search_results[["date", "partner_name", "amount", "category", "booking_details"]].copy()
        search_display = search_display.sort_values("date", ascending=False)
        search_display["date"] = search_display["date"].dt.strftime("%d.%m.%Y")
        search_display["amount"] = search_display["amount"].map(lambda x: f"€{x:,.2f}")
        search_display.columns = ["Date", "Partner", "Amount", "Category", "Details"]
        st.dataframe(search_display, use_container_width=True, hide_index=True)
    else:
        st.info(f"No transactions found matching \"{search_query}\".")

st.divider()

# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------
notes = load_notes()

st.subheader("Notes")
if notes:
    for note in notes:
        st.markdown(f"- {note}")
else:
    st.caption("No notes yet. Add them in `notes.yaml`.")
