from pathlib import Path
import pandas as pd, yaml

def load_mapping(yaml_path: Path) -> dict:
    with open(yaml_path, "r") as f:
        pairs = yaml.safe_load(f) or {}
    return {str(k).lower(): v for k, v in pairs.items()}

def map_labels(df_tidy: pd.DataFrame, mapping_yaml: Path) -> pd.DataFrame:
    mapping = load_mapping(mapping_yaml)
    def choose(raw: str):
        s = raw.lower()
        if s in mapping: return mapping[s]
        for k, v in mapping.items():
            if k in s: return v
        return None
    out = df_tidy.copy()
    out["coa"] = out["label_raw"].map(choose)
    return out
