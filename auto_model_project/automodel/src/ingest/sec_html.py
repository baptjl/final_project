# automodel/src/ingest/sec_html.py
from pathlib import Path
import pandas as pd
import re

# Keywords that commonly appear anywhere in an Income Statement table
FIN_KWS = {
    "net sales", "revenue", "sales",
    "cost of sales", "cost of goods",
    "gross profit",
    "research and development", "r&d",
    "selling", "general and administrative", "sga", "sg&a",
    "operating income", "operating loss",
    "interest expense", "interest income",
    "other income", "other (expense)",
    "income before taxes", "income before provision",
    "provision for income taxes", "income tax",
    "net income", "net earnings", "net (loss)"
}

YEAR_RE = re.compile(r"20\d{2}")

def _score_table(df: pd.DataFrame) -> int:
    """Score a table by how many distinct FIN_KWS appear in the first ~30 rows."""
    try:
        # flatten headers if they are MultiIndex
        cols = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in df.columns]
        head_text = " ".join(cols)
        body = df.head(30).astype(str).applymap(lambda x: x.lower()).to_numpy().ravel().tolist()
        all_txt = " ".join([head_text] + body)
    except Exception:
        return 0

    hits = {kw for kw in FIN_KWS if kw in all_txt}
    # small bonus if we see any 4-digit years (common in IS columns)
    year_bonus = 2 if YEAR_RE.search(all_txt) else 0
    # prefer wider numeric tables
    width_bonus = 1 if df.shape[1] >= 4 else 0
    return len(hits) + year_bonus + width_bonus

def read_income_statement_tables(html_path: Path) -> list[pd.DataFrame]:
    # Read all tables; don't assume the header row positions
    dfs = pd.read_html(html_path, flavor="bs4")
    if not dfs:
        return []
    # Score each table and keep the top-scoring few
    scored = [(df, _score_table(df)) for df in dfs]
    scored.sort(key=lambda t: t[1], reverse=True)
    # keep top 5 with score >= 3
    keep = [df for (df, s) in scored[:5] if s >= 3]
    return keep
