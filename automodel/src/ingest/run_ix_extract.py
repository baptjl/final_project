from pathlib import Path
import pandas as pd, yaml

from automodel.src.ingest.ixbrl import extract_ixbrl_facts

HTML = Path("automodel/data/samples/apple_10k_2025.html")   # <-- adjust if your filename differs
MAP  = Path("automodel/configs/xbrl_map.yaml")

EXPENSE_COAS = {
    "COGS","Sales & Marketing","Research & Development",
    "General & Administrative","Depreciation & Amortization",
    "Income Tax Expense","Interest Expense","Other Income (Expense)"
}
REVENUE_COAS = {"Revenue"}

def main():
    assert HTML.exists(), f"Missing HTML: {HTML}"
    with open(MAP, "r") as f:
        concept_to_coa = yaml.safe_load(f) or {}

    facts = extract_ixbrl_facts(HTML)
    if facts.empty:
        raise SystemExit("No iXBRL us-gaap facts found. We’ll use HTML-table fallback next.")

    # map concept → CoA and keep mapped only
    facts["coa"] = facts["concept"].map(concept_to_coa)
    facts = facts.dropna(subset=["coa"])

    # keep last 3 years available
    years = sorted(facts["year"].unique())[-3:]
    facts = facts[facts["year"].isin(years)]

    # aggregate duplicates
    out = facts.groupby(["coa","year"], as_index=False)["value"].sum()

    # normalize signs: revenues +, expenses -
    def norm(row):
        v = float(row["value"])
        if row["coa"] in REVENUE_COAS: return abs(v)
        if row["coa"] in EXPENSE_COAS: return -abs(v)
        return v
    out["value"] = out.apply(norm, axis=1)

    # write
    outdir = Path("automodel/data/interim"); outdir.mkdir(parents=True, exist_ok=True)
    out.to_csv(outdir / "IS_ixbrl_coa_3yrs.csv", index=False)
    print("Wrote:", outdir / "IS_ixbrl_coa_3yrs.csv")
    print(out.sort_values(["coa","year"]).to_string(index=False))

if __name__ == "__main__":
    main()
