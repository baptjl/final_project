import pandas as pd, re

YEAR_RE = re.compile(r"(20\d{2})", re.I)

def _scan_scale_hint(df: pd.DataFrame) -> str:
    def grab(x):
        if isinstance(x, (list, tuple)): return " ".join(map(str, x))
        return str(x)
    blob = " ".join([grab(c) for c in df.columns]) + " " + df.head(2).astype(str).to_string()
    blob = blob.lower()
    if "in billions" in blob or "($ in billions)" in blob:   return "billions"
    if "in millions" in blob or "($ in millions)" in blob:   return "millions"
    if "in thousands" in blob or "($ in thousands)" in blob: return "thousands"
    return "units"

def _to_number(x):
    s = str(x).strip().replace(",", "")
    if s in {"", "—", "–", "-", "nan", "NaN"}: return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
        return -v if neg else v
    except:
        return None

# heuristics for signs
EXPENSE_HINTS = re.compile(r"(cost of|costs|expense|expenses|research|r&d|selling|administrative|sg&a|provision)", re.I)
REVENUE_HINTS = re.compile(r"(net sales|revenue|sales)", re.I)

def tidy_is(df: pd.DataFrame) -> pd.DataFrame:
    scale_hint = _scan_scale_hint(df)

    # detect year columns
    cols = []
    # 1) look for explicit years in column headers
    for c in df.columns:
        m = YEAR_RE.search(str(c))
        if m:
            cols.append((c, int(m.group(1))))

    # 2) if none found, try to infer years from header + first rows (preserve order)
    if not cols:
        header_blob = " ".join([str(c) for c in df.columns]) + " " + df.head(6).astype(str).to_string()
        years_found = []
        for mo in YEAR_RE.finditer(header_blob):
            y = int(mo.group(1))
            if y not in years_found:
                years_found.append(y)

        # fallback: take last 3 numeric-looking columns
        numeric_like = [c for c in df.columns
                        if (df[c].astype(str).str.replace(r"[(),\s.-]", "", regex=True).str.isnumeric()).mean() > 0.6]
        # keep original column order
        numeric_like = numeric_like[-3:]

        if years_found and len(years_found) >= len(numeric_like):
            # use the first matching years in the order they appear
            chosen_years = years_found[:len(numeric_like)]
            cols = list(zip(numeric_like, chosen_years))
        else:
            # fallback to recent years based on current year
            import datetime
            current = datetime.date.today().year
            cols = list(zip(numeric_like, range(current - len(numeric_like) + 1, current + 1)))

    if not cols:
        return pd.DataFrame(columns=["label_raw","year","value","scale_hint"])

    label_col = df.columns[0]
    rows = []
    for _, r in df.iterrows():
        label = str(r[label_col]).strip()
        if not label: continue
        for c, y in cols:
            val = _to_number(r.get(c))
            if val is None: continue
            low = label.lower()
            v = val
            if REVENUE_HINTS.search(low): v = abs(v)
            elif EXPENSE_HINTS.search(low): v = -abs(v)
            rows.append({"label_raw": label, "year": y, "value": v, "scale_hint": scale_hint})

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=["label_raw","year","value","scale_hint"])
    return out
