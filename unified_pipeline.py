"""
Unified pipeline: 10-K HTML → AutoModel extraction → Mid-Product Excel → FinMod projections → Final Excel

This script orchestrates the entire workflow:
1. Extract financial data from 10-K HTML filing
2. Generate Mid-Product Excel (bridge between automodel and finmod)
3. Run financial projections in finmod
4. Generate Final.xlsx with assumptions and projections
"""

import os
import sys
import re
from pathlib import Path
from typing import Optional, Dict
import subprocess

# Add project paths to sys.path
sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path.cwd() / "automodel"))
sys.path.insert(0, str(Path.cwd() / "final-project_finmod-main"))

import pandas as pd
from io import StringIO
import yaml
import math
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

# Import automodel modules
from automodel.src.extract.is_tidy import tidy_is
from automodel.src.map.map_to_coa import map_labels
from automodel.src.llm.ollama_client import infer_scale, _llm_chat

# Convert extracted values to millions for consistent downstream modeling/display
SCALE_FACTORS = {
    "units": 1.0 / 1_000_000.0,
    "thousands": 1.0 / 1_000.0,
    "millions": 1.0,
    "billions": 1_000.0,  # billions → millions
}

YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)", re.I)


def _heuristic_score(df: pd.DataFrame) -> int:
    """Basic heuristic score for income statement likelihood."""
    first_col = df.iloc[:, 0].astype(str).str.lower()
    has_revenue = any('net sales' in x or 'revenue' in x for x in first_col)
    has_cogs = any('cost of sales' in x or 'cogs' in x for x in first_col)
    has_gross = any('gross' in x for x in first_col)
    has_operating = any('operating' in x or 'ebitda' in x for x in first_col)
    has_net_income = any('net income' in x for x in first_col)
    return sum([has_revenue, has_cogs, has_gross, has_operating, has_net_income])


def _summarize_table(df: pd.DataFrame, idx: int) -> str:
    """Lightweight text summary of a table for LLM ranking."""
    col_headers = [str(c) for c in df.columns]
    first_rows = []
    for _, row in df.head(8).iterrows():
        first_rows.append("|".join(str(x) for x in row.tolist()))
    years = YEAR_RE.findall(" ".join(col_headers) + " " + df.head(4).astype(str).to_string())
    return (
        f"Table {idx}: shape={df.shape}, headers={col_headers}, years_in_header={years}, "
        f"first_rows={first_rows}"
    )


def _choose_is_table(dfs: list[pd.DataFrame], use_llm: bool) -> int:
    """Pick income statement table using heuristics + optional LLM ranking."""
    # Heuristic: pick the highest score table
    scored = [( _heuristic_score(df), idx) for idx, df in enumerate(dfs)]
    scored_sorted = sorted(scored, key=lambda t: t[0], reverse=True)
    best_idx = scored_sorted[0][1] if scored_sorted else 0

    if not use_llm:
        return best_idx

    # LLM ranking: present top candidates
    top_candidates = [idx for _, idx in scored_sorted[:6]]
    summaries = [_summarize_table(dfs[idx], idx) for idx in top_candidates]
    prompt = (
        "You are selecting the INCOME STATEMENT table from scraped HTML tables. "
        "Pick the one that most likely represents a P&L (Revenue/Net sales, Cost of sales/COGS, "
        "Gross profit, Operating income, Net income). "
        "Respond with ONLY the table index number.\n\n"
        + "\n\n".join(summaries)
    )
    try:
        resp = _llm_chat(
            [
                {"role": "system", "content": "Select the income statement table index."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )
        # Parse first integer in response
        m = re.search(r"(\d+)", resp)
        if m:
            idx = int(m.group(1))
            if 0 <= idx < len(dfs):
                return idx
    except Exception as e:
        print(f"[WARN] LLM table selection failed ({e}); falling back to heuristic.")

    return best_idx


def custom_tidy_is(df: pd.DataFrame) -> pd.DataFrame:
    """
    Custom tidying for income statement tables from pd.read_html.
    Handles tables with complex headers and numeric columns.
    """
    # Drop completely empty columns to simplify year detection
    df = df.dropna(axis=1, how="all").reset_index(drop=True)

    # Remove header rows that are just the "(in thousands...)" note
    header_note_re = re.compile(r"in thousands", re.I)
    rows_to_drop = []
    for i in range(min(4, len(df))):
        row_blob = " ".join(df.iloc[i].astype(str).tolist())
        if header_note_re.search(row_blob.lower()):
            # Keep the row if it also contains explicit years (it might be the year header)
            if not YEAR_RE.search(row_blob):
                rows_to_drop.append(i)
    if rows_to_drop:
        df = df.drop(index=rows_to_drop).reset_index(drop=True)

    # Find year columns
    year_cols = {}
    header_blob = " ".join([str(c) for c in df.columns]) + " " + df.head(6).astype(str).to_string()
    
    # Extract unique years from header
    years_found = []
    for mo in YEAR_RE.finditer(header_blob):
        y = int(mo.group(1))
        if y not in years_found:
            years_found.append(y)
    
    if not years_found:
        return pd.DataFrame(columns=["label_raw", "year", "value", "scale_hint"])
    
    # Try to map columns to years.
    # Strategy: look at the first few rows per column for a year token, then map that
    # year to the nearest numeric column (current or next few columns).
    year_map: Dict[int, int] = {}
    for idx, col_label in enumerate(df.columns):
        header_bits = [str(col_label)]
        for r in range(min(6, len(df))):
            header_bits.append(str(df.iloc[r, idx]))
        blob = " ".join(header_bits)
        m = YEAR_RE.search(blob)
        if not m:
            continue
        year = int(m.group(1))
        if year in year_map.values():
            continue
        # Pick this column or the next couple columns that actually contain numbers
        numeric_target = None
        for j in range(idx, min(idx + 3, len(df.columns))):
            try:
                col_vals = pd.to_numeric(df.iloc[:, j], errors='coerce').dropna()
                if len(col_vals) > 0:
                    numeric_target = df.columns[j]
                    break
            except Exception:
                continue
        numeric_target = numeric_target if numeric_target is not None else col_label
        year_map[numeric_target] = year

    if not year_map and years_found:
        # Fallback: use rightmost numeric-ish columns matched to detected years
        numeric_cols = []
        for col_label in df.columns:
            try:
                col_vals = pd.to_numeric(df[col_label], errors='coerce').dropna()
                if len(col_vals) > 0:
                    numeric_cols.append(col_label)
            except Exception:
                pass
        numeric_cols = numeric_cols[-len(years_found):]
        year_map = {col_label: int(y) for col_label, y in zip(numeric_cols, years_found)}

    if not year_map:
        return pd.DataFrame(columns=["label_raw", "year", "value", "scale_hint"])

    # Choose the label column: first non-numeric-heavy column (fallback to first)
    label_col = df.columns[0]
    best_label_col = None
    best_score = -1
    for col in df.columns:
        series = df[col].dropna().astype(str)
        if series.empty:
            continue
        texty = sum(1 for v in series.head(8) if not re.fullmatch(r"-?\\d+(\\.\\d+)?", str(v).replace(',', '')))
        if texty > best_score:
            best_score = texty
            best_label_col = col
    if best_label_col is not None:
        label_col = best_label_col

    # Extract data
    rows = []
    
    def to_number(x):
        s = str(x).strip().replace(",", "").replace("$", "")
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1]
        if s in {"", "—", "–", "-", "nan", "NaN", "N/A"}:
            return None
        try:
            return float(s)
        except:
            return None
    
    for _, r in df.iterrows():
        label = str(r.get(label_col, "")).strip()
        if not label or pd.isna(label) or label.lower() in {'nan', ''}:
            continue
        if header_note_re.search(label.lower()):
            continue
        
        for col_idx, year in year_map.items():
            if col_idx not in r.index:
                continue
            val = to_number(r[col_idx])
            if val is not None:
                # Use 'units' as default so infer_scale can detect thousands/millions/billions from header
                rows.append({"label_raw": label, "year": year, "value": val, "scale_hint": "units"})
    
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["label_raw", "year", "value", "scale_hint"])


def step1_extract_from_html(html_path: Path, skip_llm: bool = True) -> Path:
    """
    Step 1: Run automodel extraction on 10-K HTML filing.
    
    Args:
        html_path: Path to 10-K HTML file
        skip_llm: If True, skip LLM-based label mapping
        
    Returns:
        Path to the mapped CSV output (IS_tidy_mapped_best_llm.csv)
    """
    print("\n" + "="*60)
    print("STEP 1: Extracting financial data from 10-K HTML")
    print("="*60)
    
    if not html_path.exists():
        raise FileNotFoundError(f"HTML file not found: {html_path}")
    
    raw = html_path.read_text(errors="ignore")
    
    # Parse all tables from HTML
    try:
        dfs = pd.read_html(StringIO(raw))
    except Exception as e:
        raise SystemExit(f"pd.read_html failed: {type(e).__name__}: {e}")
    
    if not dfs:
        raise SystemExit("No tables found in HTML.")
    
    print(f"Found {len(dfs)} tables in HTML")
    
    # Detect income statement table using heuristics + optional LLM (if not skipped)
    is_idx = _choose_is_table(dfs, use_llm=not skip_llm)
    print(f"Using table index {is_idx} as the income statement table.")
    
    is_df_raw = dfs[is_idx]
    
    # Tidy the chosen table (try custom tidy first, then fall back to standard)
    t = custom_tidy_is(is_df_raw)
    if t is None or t.empty:
        print("[WARN] Custom tidy returned empty; trying standard tidy_is...")
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
    
    # Keep label/year/value
    all_tidy = t[["label_raw", "year", "value"]].copy()
    
    # Map labels to COA
    mapped = map_labels(all_tidy, Path("automodel/configs/mappings.yaml"))
    
    with open(Path("automodel/configs/coa.yaml"), "r") as f:
        coa_candidates = list((yaml.safe_load(f) or {}).keys())
    
    unm = mapped["coa"].isna()
    
    if unm.any():
        if skip_llm:
            print(
                "Skipping LLM mapping. Unmapped labels will remain empty."
            )
        else:
            from automodel.src.llm.ollama_client import map_label_to_coa
            uniq = mapped.loc[unm, "label_raw"].dropna().unique().tolist()
            try:
                llm_map = {
                    lbl: map_label_to_coa(lbl, coa_candidates) for lbl in uniq
                }
            except Exception as e:
                # If Ollama/LLM is unavailable, fall back to heuristic-only mapping
                print(f"[WARN] LLM mapping failed ({e}); continuing without LLM.")
                llm_map = {}
            if llm_map:
                mapped.loc[unm, "coa"] = mapped.loc[unm, "label_raw"].map(llm_map)
    
    # Keep only P&L lines
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
    
    # Sign normalization
    def _norm(row):
        v = float(row["value"])
        c = row.get("coa")
        if c in REVENUE_COAS:
            return abs(v)
        if c in EXPENSE_COAS:
            return -abs(v)
        return v
    
    mapped["value"] = mapped.apply(_norm, axis=1)
    
    # Save outputs
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
    
    csv_path = Path("automodel/data/interim/IS_tidy_mapped_best_llm.csv")
    print(f"✅ Extracted financial data to {csv_path}")
    return csv_path


def step2_create_mid_product(
    csv_path: Path,
    template_path: Path,
    output_path: Path,
    company_name: str = "Company"
) -> Path:
    """
    Step 2: Convert automodel CSV to finmod-compatible Mid-Product Excel.
    
    Args:
        csv_path: Path to IS_tidy_mapped_best_llm.csv
        template_path: Path to Baseline IS.xlsx template
        output_path: Path to write Mid-Product.xlsx
        company_name: Company name for display
        
    Returns:
        Path to created Mid-Product Excel file
    """
    print("\n" + "="*60)
    print("STEP 2: Creating Mid-Product Excel")
    print("="*60)
    
    # Read the mapped data
    df = pd.read_csv(csv_path)
    
    # Remove rows without COA mapping
    df = df[df['coa'].notna()].copy()
    
    # Aggregate by COA and year
    df_pivot = df.groupby(['coa', 'year'])['value'].sum().reset_index()
    
    # Load the template workbook (with data_only=False to see formulas)
    wb = load_workbook(template_path, data_only=False)
    ws = wb.active
    
    # Update company name
    ws['D1'] = company_name
    
    # Get the year column mapping - handle both direct values and formulas.
    # Instead of relying on the template's starting year, anchor on the earliest
    # year present in the data so we don't drop older periods (e.g., when data
    # includes 2022 but the template header shows 2023).
    year_map = {}
    base_year = None

    # Determine the earliest data year to anchor column E
    data_min_year = int(df_pivot['year'].min()) if not df_pivot.empty else None

    if data_min_year:
        base_year = data_min_year
        # Write years explicitly across the available columns E-M
        for offset in range(0, 9):  # E to M inclusive is 9 columns
            col_idx = 5 + offset
            year = base_year + offset
            if col_idx < 14:
                year_map[year] = col_idx
                ws.cell(row=4, column=col_idx).value = year
    else:
        # Fallback to whatever is present in the template
        for col_idx in range(5, 14):  # E to M (cols 5-13)
            cell = ws.cell(row=4, column=col_idx)
            if cell.value:
                if isinstance(cell.value, str) and cell.value.startswith('='):
                    # It's a formula, skip for now
                    continue
                try:
                    year = int(cell.value)
                    if 2000 <= year <= 2100:  # Sanity check for year range
                        year_map[year] = col_idx
                        if base_year is None:
                            base_year = year
                except (ValueError, TypeError):
                    pass
        # If we found a base year, calculate subsequent years
        if base_year and year_map:
            for offset in range(1, 10):
                year = base_year + offset
                col_idx = 5 + offset  # Start from column E (5)
                if col_idx < 14:
                    year_map[year] = col_idx
                    # Explicitly set the year value in the cell (not as formula)
                    ws.cell(row=4, column=col_idx).value = year
    
    if not year_map:
        raise ValueError("Could not find year columns in template")
    
    # Mapping from extracted COA to template rows
    coa_mapping = {
        'Revenue': 'Revenue',
        'COGS': 'COGS',
        'Gross Profit': 'Gross Profit',
        'Sales & Marketing': 'SG&A',
        'General & Administrative': 'SG&A',
        'Research & Development': 'R&D',
        'Depreciation & Amortization': 'R&D',
        'Share-Based Compensation': 'R&D',
        'Operating Income (EBIT)': 'Organic EBITDA',
        'Interest Expense': 'Other Income',
        'Interest Income': 'Other Income',
        'Other Income (Expense)': 'Other Income',
        'Income Tax Expense': 'Other Income',
        'Income Before Taxes': 'Organic EBITDA',
        'Net Income': 'Total EBITDA',
    }
    
    # Find template row indices
    template_rows = {}
    for row_idx in range(1, ws.max_row + 1):
        cell = ws.cell(row=row_idx, column=3)  # Column C
        if cell.value:
            label = str(cell.value).strip()
            for target in set(coa_mapping.values()):
                if label.lower() == target.lower():
                    template_rows[target] = row_idx
                    break
    
    # Aggregate extracted data
    aggregated = {}
    for _, row in df_pivot.iterrows():
        coa = row['coa']
        year = int(row['year'])
        value = row['value']
        
        template_label = coa_mapping.get(coa)
        if template_label:
            if template_label not in aggregated:
                aggregated[template_label] = {}
            
            if year not in aggregated[template_label]:
                aggregated[template_label][year] = 0
            aggregated[template_label][year] += value
    
    # Fill template with data
    for template_label, year_values in aggregated.items():
        if template_label not in template_rows:
            continue
        
        row_idx = template_rows[template_label]
        for year, value in year_values.items():
            if year not in year_map:
                continue
            col_idx = year_map[year]
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.value = value
    
    # Save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    
    print(f"✅ Created Mid-Product: {output_path}")
    return output_path


def step3_run_finmod_projections(
    mid_product_path: Path,
    output_path: Path
) -> Path:
    """
    Step 3: Run finmod projections on Mid-Product to generate Final.xlsx.
    
    Args:
        mid_product_path: Path to Mid-Product.xlsx
        output_path: Path to write Final.xlsx
        
    Returns:
        Path to created Final.xlsx file
    """
    print("\n" + "="*60)
    print("STEP 3: Running FinMod Projections")
    print("="*60)
    
    if not mid_product_path.exists():
        raise FileNotFoundError(f"Mid-Product not found: {mid_product_path}")
    
    # Run finmod
    cmd = [
        sys.executable, "-m", "final-project_finmod-main.src.finmod.main",
        "--file", str(mid_product_path),
        "--output-xlsx", str(output_path)
    ]
    
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print("STDERR:", result.stderr)
        raise RuntimeError(f"FinMod projection failed: {result.stderr}")
    
    print("STDOUT:", result.stdout)
    
    if not output_path.exists():
        raise RuntimeError("FinMod did not produce expected output Excel")
    
    print(f"✅ Generated Final Excel: {output_path}")
    return output_path


def main(
    html_path: Path,
    mid_product_path: Optional[Path] = None,
    final_output_path: Optional[Path] = None,
    company_name: str = "Company",
    skip_llm: bool = True
):
    """
    Run the complete pipeline from 10-K HTML to Final Excel projections.
    
    Args:
        html_path: Path to 10-K HTML filing
        mid_product_path: Path for Mid-Product.xlsx (default: Mid-Product.xlsx)
        final_output_path: Path for Final.xlsx (default: Final.xlsx)
        company_name: Company name for display
        skip_llm: If True, skip LLM-based label mapping
    """
    
    print("\n" + "#"*60)
    print("# UNIFIED 10-K FINANCIAL ANALYSIS PIPELINE")
    print("#"*60)
    
    html_path = Path(html_path)
    mid_product_path = Path(mid_product_path or "Mid-Product.xlsx")
    final_output_path = Path(final_output_path or "Final.xlsx")
    template_path = Path("final-project_finmod-main/Inputs_Historical/Baseline IS.xlsx")
    
    try:
        # Step 1: Extract
        csv_path = step1_extract_from_html(html_path, skip_llm=skip_llm)
        
        # Step 2: Create Mid-Product
        step2_create_mid_product(
            csv_path,
            template_path,
            mid_product_path,
            company_name=company_name
        )
        
        # Step 3: Run projections
        step3_run_finmod_projections(mid_product_path, final_output_path)
        
        print("\n" + "#"*60)
        print("# PIPELINE COMPLETE!")
        print("#"*60)
        print(f"Mid-Product: {mid_product_path}")
        print(f"Final Output: {final_output_path}")
        print("#"*60 + "\n")
        
    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="End-to-end pipeline: 10-K HTML → Mid-Product.xlsx → Final.xlsx"
    )
    parser.add_argument(
        "--html",
        required=True,
        help="Path to 10-K HTML filing"
    )
    parser.add_argument(
        "--mid-product",
        default="Mid-Product.xlsx",
        help="Output path for Mid-Product.xlsx (default: Mid-Product.xlsx)"
    )
    parser.add_argument(
        "--final",
        default="Final.xlsx",
        help="Output path for Final.xlsx (default: Final.xlsx)"
    )
    parser.add_argument(
        "--company",
        default="Company",
        help="Company name for display (default: Company)"
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Use LLM for label mapping (default: disabled for speed)"
    )
    
    args = parser.parse_args()
    
    main(
        html_path=args.html,
        mid_product_path=args.mid_product,
        final_output_path=args.final,
        company_name=args.company,
        skip_llm=not args.use_llm
    )
