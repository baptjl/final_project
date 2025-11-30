
from pathlib import Path
from io import StringIO
import os

import pandas as pd
import yaml

from automodel.src.extract.is_tidy import tidy_is
from automodel.src.map.map_to_coa import map_labels
from automodel.src.llm.ollama_client import (
    infer_scale,
    map_label_to_coa,
    pick_is_table_index,
)

HTML = Path("automodel/data/samples/apple_10k_2025.html")
MAP = Path("automodel/configs/mappings.yaml")
COA = Path("automodel/configs/coa.yaml")

SCALE_FACTORS = {
    "units": 1.0,
    "thousands": 1_000.0,
    "millions": 1_000_000.0,
    "billions": 1_000_000_000.0,
}


def main() -> None:
    assert HTML.exists(), f"Missing HTML sample: {HTML}"
    raw = HTML.read_text(errors="ignore")

    # ----------------------------------------------------------
    # 1) Parse ALL tables from the HTML
    # ----------------------------------------------------------
    try:
        dfs = pd.read_html(StringIO(raw))
    except Exception as e:
        raise SystemExit(f"pd.read_html failed: {type(e).__name__}: {e}")

    if not dfs:
        raise SystemExit("No tables found in HTML.")

    # Build small CSV snippets for each table to show the LLM
    snippets = []
    for i, df in enumerate(dfs):
        try:
            snip = df.head(12).to_csv(index=False)
        except Exception:
            snip = str(df.head(12))
        snippets.append(snip)

    # ----------------------------------------------------------
    # 2) Ask the LLM: which table index is the income statement?
    # ----------------------------------------------------------
    is_idx = None
    
    # Try LLM picker first
    try:
        is_idx = pick_is_table_index(snippets)
        if is_idx < 0 or is_idx >= len(dfs):
            is_idx = None
    except Exception as e:
        print(f"[WARN] LLM picker failed: {e}")
    
    # Fallback: heuristic table detection
    if is_idx is None:
        print("[INFO] Falling back to heuristic table detection...")
        for idx, df in enumerate(dfs):
            cols = df.columns.astype(str)
            first_col = df.iloc[:, 0].astype(str).str.lower()
            
            # Look for income statement keywords
            has_revenue = any('net sales' in str(x).lower() or 'revenue' in str(x).lower() for x in first_col)
            has_cogs = any('cost of sales' in str(x).lower() or 'cogs' in str(x).lower() for x in first_col)
            has_gross = any('gross' in str(x).lower() for x in first_col)
            has_operating = any('operating' in str(x).lower() or 'ebitda' in str(x).lower() for x in first_col)
            has_net_income = any('net income' in str(x).lower() for x in first_col)
            
            score = sum([has_revenue, has_cogs, has_gross, has_operating, has_net_income])
            
            if score >= 3:  # At least 3 income statement indicators
                is_idx = idx
                print(f"[INFO] Found likely income statement table at index {is_idx}")
                break
    
    if is_idx is None:
        is_idx = 0
        print(f"[WARN] Could not detect income statement table; using table 0")
    
    print(f"Using table index {is_idx} as the income statement table.")

    is_df_raw = dfs[is_idx]

    # ----------------------------------------------------------
    # 3) Tidy the chosen table into (label_raw, year, value)
    # ----------------------------------------------------------
    t = tidy_is(is_df_raw)
    if t is None or t.empty:
        raise SystemExit("tidy_is returned empty for the chosen IS table.")

    # Scale detection
    hdr_blob = " ".join(map(str, is_df_raw.columns)).lower()
    hint = t["scale_hint"].iloc[0] if "scale_hint" in t.columns and len(t) else "units"

    if len(t):
        try:
            sample_vals = (
                t["value"].dropna().astype(float).sample(min(6, len(t))).tolist()
            )
        except Exception:
            sample_vals = []
    else:
        sample_vals = []

    inferred = infer_scale(hdr_blob[:400], sample_vals) if hint == "units" else hint
    factor = SCALE_FACTORS.get(inferred, 1.0)
    t["value"] = t["value"] * factor

    # For downstream, just keep label/year/value
    all_tidy = t[["label_raw", "year", "value"]].copy()

    # ----------------------------------------------------------
    # 4) Map labels → COA using mappings.yaml + LLM
    # ----------------------------------------------------------
    mapped = map_labels(all_tidy, MAP)

    with open(COA, "r") as f:
        coa_candidates = list((yaml.safe_load(f) or {}).keys())

    unm = mapped["coa"].isna()

    if unm.any():
        if os.environ.get("AUTOMODEL_SKIP_LLM", "0") == "1":
            print(
                "Skipping LLM mapping (AUTOMODEL_SKIP_LLM=1). Unmapped labels will remain empty."
            )
        else:
            uniq = mapped.loc[unm, "label_raw"].dropna().unique().tolist()
            llm_map = {
                lbl: map_label_to_coa(lbl, coa_candidates) for lbl in uniq
            }
            mapped.loc[unm, "coa"] = mapped.loc[unm, "label_raw"].map(llm_map)

    # ----------------------------------------------------------
    # 5) Keep only P&L lines (by COA)
    # ----------------------------------------------------------
    REVENUE_COAS = {"Revenue", "Interest Income"}

    EXPENSE_COAS = {
        "COGS",
        "Sales & Marketing",
        "Research & Development",
        "General & Administrative",
        "Depreciation & Amortization",
        "Share-Based Compensation",
        "Interest Expense",
        "Income Tax Expense",
        "Other Income (Expense)",
    }

    PNL_TOTAL_COAS = REVENUE_COAS.union(EXPENSE_COAS).union(
        {
            "Gross Profit",
            "Operating Income (EBIT)",
            "Income Before Taxes",
            "Net Income",
        }
    )

    mapped = mapped[mapped["coa"].isin(PNL_TOTAL_COAS)].copy()

    # ----------------------------------------------------------
    # 6) Sign normalization
    # ----------------------------------------------------------
    def _norm(row):
        v = float(row["value"])
        c = row.get("coa")
        if c in REVENUE_COAS:
            return abs(v)
        if c in EXPENSE_COAS:
            return -abs(v)
        return v

    mapped["value"] = mapped.apply(_norm, axis=1)

    # ----------------------------------------------------------
    # 7) Save outputs + print summary
    # ----------------------------------------------------------
    outdir = Path("automodel/data/interim")
    outdir.mkdir(parents=True, exist_ok=True)
    all_tidy.to_csv(outdir / "IS_tidy_best.csv", index=False)
    mapped.to_csv(outdir / "IS_tidy_mapped_best_llm.csv", index=False)

    view = (
        mapped.dropna(subset=["coa"])
        .groupby(["coa", "year"])["value"]
        .sum()
        .reset_index()
        .sort_values(["coa", "year"])
    )

    print("\nSummary by COA & year:")
    print(view.to_string(index=False))


if __name__ == "__main__":
    main()
