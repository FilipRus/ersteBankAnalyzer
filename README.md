# Personal Finance Dashboard

Monthly spending analysis for Erste Bank (George) CSV exports.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

1. Export your monthly CSV from George (Erste Bank) and drop it into the `data/` folder.
2. Run the dashboard:

```bash
streamlit run app.py
```

3. Open the URL shown in terminal (default: http://localhost:8501).

## Adding a new month

Drop the new CSV into `data/` and refresh the browser. The pipeline reads all CSVs in that folder automatically.

## Customizing categories

Edit `categories.yaml`. Each category maps to a list of keywords matched (case-insensitive) against Partner Name and Booking details. First match wins.

## Setting budgets

Edit `budgets.yaml` with monthly EUR limits per category. The dashboard highlights categories that exceed their budget in red.

## Project structure

```
data/              # raw George CSV exports (gitignored)
app.py             # Streamlit dashboard
pipeline.py        # CSV ingestion + categorization logic
categories.yaml    # keyword → category mapping
budgets.yaml       # monthly budget limits per category
```
