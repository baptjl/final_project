from __future__ import annotations
from bs4 import BeautifulSoup
from pathlib import Path
import pandas as pd
import re

# --- helpers ---
def _to_float(v, decimals_attr):
    s = str(v).strip().replace(",", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        x = float(s)
    except:
        return None
    # We ignore decimals scaling for MVP; many issuers already provide rounded figures.
    return -x if neg else x

def _contexts(soup):
    ctx = {}
    for c in soup.find_all(["xbrli:context", "context"]):
        cid = c.get("id")
        if not cid:
            continue
        end = c.find(["xbrli:enddate", "enddate"])
        start = c.find(["xbrli:startdate", "startdate"])
        instant = c.find(["xbrli:instant", "instant"])
        if end and start:
            endY = pd.to_datetime(end.text.strip(), errors="coerce")
            startY = pd.to_datetime(start.text.strip(), errors="coerce")
            if pd.notna(endY) and pd.notna(startY):
                days = (endY - startY).days
                ctx[cid] = {"type": "duration", "end": endY, "days": days}
        elif instant:
            endY = pd.to_datetime(instant.text.strip(), errors="coerce")
            if pd.notna(endY):
                ctx[cid] = {"type": "instant", "end": endY, "days": 0}
    return ctx

USGAAP = re.compile(r"^us-gaap:", re.I)

def extract_ixbrl_facts(html_path: Path) -> pd.DataFrame:
    html = Path(html_path).read_text(errors="ignore")
    soup = BeautifulSoup(html, "lxml")
    ctx = _contexts(soup)

    rows = []
    for tag in soup.find_all(["ix:nonfraction", "ix:nonFraction"]):
        concept = tag.get("name") or ""
        if not USGAAP.match(concept):
            continue
        dec = tag.get("decimals")
        cref = tag.get("contextref")
        if not cref:
            continue
        val = _to_float(tag.text, dec)
        if val is None:
            continue
        cmeta = ctx.get(cref)
        if not cmeta:
            continue
        rows.append({
            "concept": concept,
            "value": val,
            "period_type": cmeta["type"],
            "end": cmeta["end"],
            "days": cmeta["days"],
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Annual durations only (roughly a fiscal year)
    df = df[(df["period_type"] == "duration") & (df["days"].between(300, 400))]
    if df.empty:
        return df

    df["year"] = df["end"].dt.year
    return df[["concept", "year", "value"]].copy()
