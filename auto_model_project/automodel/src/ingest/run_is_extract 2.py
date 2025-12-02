```python
# automodel/src/ingest/run_is_extract.py
from pathlib import Path
import re
import pandas as pd
import yaml
from io import StringIO

from automodel.src.extract.is_tidy import tidy_is
from automodel.src.map.map_to_coa import map_labels
from automodel.src.llm.ollama_client import infer_scale, map_label_to_coa

HTML = Path("automodel/data/samples/apple_10k_2025.html")   # adjust if different
MAP  = Path("automodel/configs/mappings.yaml")
COA  = Path("automodel/configs/coa.yaml")

SCALE_FACTORS = {"units":1.0,"thousands":1_000.0,"millions":1_000_000.0,"billions":1_000_000_000.0}

REV_RE = re.compile(r"\b(?:net\s+sales|revenue|total\s+net\s+sales)\b", re.I)
RD_RE  = re.compile(r"(?:research\s+and\s+development|r&d)", re.I)
BAD_HEADER = re.compile(r"(?:per\s+share|eps|ratio|percent|%)", re.I)

def _quality_score(tidy: pd.DataFrame) -> float:
    """Score a tidied table: ≥ years, has both revenue and R&D; higher latest revenue is better."""
    if tidy is None or tidy.empty or "year" not in tidy:
        return -1.0
    years = sorted(set(int(y) for y in tidy["year"]))
    if len(years) < 2:
        return -1.0
    latest = max(years)
    has_rev = tidy["label_raw"].str.lower().str.contains(REV_RE).any()
    has_rd  = tidy["label_raw"].str.lower().str.contains(RD_RE).any()
    if not (has_rev and has_rd):
        return -1.0
    rev_latest = tidy[ tidy["label_raw"].str.lower().str.contains(REV_RE) & (tidy["year"]==latest) ]["value"].abs().sum()
    rd_latest  = tidy[ tidy["label_raw"].str.lower().str.contains(RD_RE)  & (tidy["year"]==latest) ]["value"].abs().sum()
    if rd_latest > 0 and rev_latest <= 4 * rd_latest:
        return -1.0
    # prefer more years and larger latest revenue
    return rev_latest/1e9 + 5*len(years) + (latest-2000)

def _coherence_filter(df: pd.DataFrame, keep_top_n:int=20, tolerance:float=40.0) -> pd.DataFrame:
    """Drop rows wildly off-scale vs the year’s big lines."""
    if df.empty: return df
    out = []
    for y, g in df.groupby("year"):
        top = g["value"].abs().sort_values(ascending=False).head(min(len(g), keep_top_n))
        if top.empty or float(top.median()) <= 0:
            out.append(g); continue
        ref = float(top.median())
        out.append(g[g["value"].abs() >= (ref / tolerance)])
    return pd.concat(out, ignore_index=True)

def main():
    assert HTML.exists(), f"Missing: {HTML}"
    raw = HTML.read_text(errors="ignore")

    # 1) parse ALL tables in one shot (fast & robust)
    try:
        dfs = pd.read_html(raw)  # pandas will pick bs4/lxml automatically
    except Exception as e:
        raise SystemExit(f"pd.read_html failed: {type(e).__name__}: {e}")

    # 2) tidy, score, and keep only good candidates
    candidates = []
    for i, df in enumerate(dfs):
        t = tidy_is(df)
        if t is None or t.empty: 
            continue
        # quick ban if header row screams EPS/percent
        hdr_blob = " ".join(map(str, df.columns)).lower()
        if BAD_HEADER.search(hdr_blob):
            continue
        # per-table scale: hint → (if 'units') ask LLM using header blob
        hint = (t["scale_hint"].iloc[0] if "scale_hint" in t.columns and len(t) else "units")
        sample_vals = t["value"].dropna().astype(float).sample(min(6, len(t))).tolist() if len(t) else []
        inferred = infer_scale(hdr_blob[:400], sample_vals) if hint == "units" else hint
        factor = SCALE_FACTORS.get(inferred, 1.0)
        tt = t.copy(); tt["value"] = tt["value"] * factor; tt["src_id"] = i
        score = _quality_score(tt)
        if score > 0:
            candidates.append((score, tt))

    if not candidates:
        raise SystemExit("No income-statement-like tables found after scoring.")

    # 3) take top 4 candidates, combine, enforce coherence, then dedupe (max |value| per label/year)
    candidates.sort(key=lambda x: x[0], reverse=True)
    combine = pd.concat([t for _, t in candidates[:4]], ignore_index=True)
    combine = _coherence_filter(combine, keep_top_n=20, tolerance=40.0)

    def _pick_max_abs(g):
        idx = g["value"].abs().idxmax()
        return g.loc[idx, ["label_raw","year","value"]]

    all_tidy = (combine.groupby(["label_raw","year"], as_index=False, group_keys=False)
                      .apply(_pick_max_abs)
                      .reset_index(drop=True))

    # 4) map → CoA (rules), then LLM fallback; normalize signs
    mapped = map_labels(all_tidy, MAP)
    with open(COA, "r") as f:
        coa_candidates = list((yaml.safe_load(f) or {}).keys())
    unm = mapped["coa"].isna()
    if unm.any():
        uniq = mapped.loc[unm, "label_raw"].dropna().unique().tolist()
        llm_map = {lbl: map_label_to_coa(lbl, coa_candidates) for lbl in uniq}
        mapped.loc[unm, "coa"] = mapped.loc[unm, "label_raw"].map(llm_map)

    EXPENSE_COAS = {"COGS","Sales & Marketing","Research & Development","General & Administrative",
                    "Depreciation & Amortization","Income Tax Expense","Other Income (Expense)","Interest Expense"}
    REVENUE_COAS = {"Revenue"}
    def _norm(row):
        v = float(row["value"]); c = row.get("coa")
        if c in REVENUE_COAS: return abs(v)
        if c in EXPENSE_COAS: return -abs(v)
        return v
    mapped["value"] = mapped.apply(_norm, axis=1)

    # 5) write + summary
    outdir = Path("automodel/data/interim"); outdir.mkdir(parents=True, exist_ok=True)
    all_tidy.to_csv(outdir / "IS_tidy_best.csv", index=False)
    mapped.to_csv(outdir / "IS_tidy_mapped_best_llm.csv", index=False)

    view = (mapped.dropna(subset=["coa"])
                  .groupby(["coa","year"])["value"].sum()
                  .reset_index()
                  .sort_values(["coa","year"]))
    print("\nSummary by COA & year:")
    print(view.to_string(index=False))

if __name__ == "__main__":
    main()
