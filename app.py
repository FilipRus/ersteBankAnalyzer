import streamlit as st
import plotly.express as px
import pandas as pd

from pipeline import load_data, load_budgets, load_notes

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

# ---------------------------------------------------------------------------
# Sidebar — month selector
# ---------------------------------------------------------------------------
months = sorted(df["year_month"].unique())
month_labels = [str(m) for m in months]

selected_label = st.sidebar.selectbox("Month", month_labels, index=len(month_labels) - 1)
selected_month = months[month_labels.index(selected_label)]

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

    # Consistent color map across all charts
    all_cats = sorted(df["category"].unique())
    palette = px.colors.qualitative.Pastel + px.colors.qualitative.Safe
    color_map = {cat: palette[i % len(palette)] for i, cat in enumerate(all_cats)}

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
