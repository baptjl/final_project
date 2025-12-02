# automodel/src/llm/ollama_client.py

import os
import json
import re
from typing import List, Dict, Any, Optional

import requests

# --------------------------------------------------------------------
# Basic Ollama config
# --------------------------------------------------------------------

# Change this if your model has a different name, or set env var:
#   export AUTOMODEL_OLLAMA_MODEL="your-model-name"
DEFAULT_MODEL = os.environ.get("AUTOMODEL_OLLAMA_MODEL", "mistral:7b-instruct")

# Change base URL if your Ollama is not on localhost:11434
BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

# Remote providers (Groq/OpenAI) — set LLM_PROVIDER=groq or LLM_PROVIDER=openai
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").lower()
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama3-8b-8192")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")


class OllamaError(RuntimeError):
    pass


def _ollama_chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.1,
) -> str:
    """
    Call Ollama /api/chat with simple non-streaming mode and return assistant content.
    """
    if model is None:
        model = DEFAULT_MODEL

    url = f"{BASE_URL}/api/chat"
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
        },
    }

    try:
        resp = requests.post(url, json=payload, timeout=120)
    except Exception as e:
        raise OllamaError(f"Failed to reach Ollama at {url}: {e}")

    if not resp.ok:
        raise OllamaError(f"Ollama HTTP {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    msg = data.get("message") or {}
    content = msg.get("content", "")

    if not isinstance(content, str):
        raise OllamaError(f"Ollama returned unexpected content: {content!r}")
    return content.strip()


def _groq_chat(
    messages: List[Dict[str, str]],
    temperature: float = 0.1,
) -> str:
    """Call Groq (OpenAI-compatible) chat endpoint."""
    if not GROQ_API_KEY:
        raise OllamaError("GROQ_API_KEY is not set")
    url = "https://api.groq.com/openai/v1/chat/completions"
    payload: Dict[str, Any] = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=120)
    except Exception as e:
        raise OllamaError(f"Failed to reach Groq at {url}: {e}")
    if not resp.ok:
        raise OllamaError(f"Groq HTTP {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise OllamaError(f"Groq returned no choices: {data}")
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if not isinstance(content, str):
        raise OllamaError(f"Groq returned unexpected content: {content!r}")
    return content.strip()


def _openai_chat(
    messages: List[Dict[str, str]],
    temperature: float = 0.1,
) -> str:
    """Call OpenAI chat endpoint (or compatible base URL)."""
    if not OPENAI_API_KEY:
        raise OllamaError("OPENAI_API_KEY is not set")
    url = f"{OPENAI_BASE_URL.rstrip('/')}/chat/completions"
    payload: Dict[str, Any] = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=120)
    except Exception as e:
        raise OllamaError(f"Failed to reach OpenAI at {url}: {e}")
    if not resp.ok:
        raise OllamaError(f"OpenAI HTTP {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise OllamaError(f"OpenAI returned no choices: {data}")
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if not isinstance(content, str):
        raise OllamaError(f"OpenAI returned unexpected content: {content!r}")
    return content.strip()


def _llm_chat(
    messages: List[Dict[str, str]],
    temperature: float = 0.1,
) -> str:
    """Dispatch to the configured LLM provider."""
    provider = LLM_PROVIDER
    if provider == "groq":
        return _groq_chat(messages, temperature=temperature)
    if provider == "openai":
        return _openai_chat(messages, temperature=temperature)
    # default: ollama
    return _ollama_chat(messages, model=DEFAULT_MODEL, temperature=temperature)


def _extract_json_from_text(text: str) -> Any:
    """
    Try to robustly load JSON, even if the model adds ``` fences.
    """
    txt = text.strip()

    # Remove ```json ... ``` or ``` ... ```
    if txt.startswith("```"):
        txt = re.sub(r"^```[a-zA-Z]*\s*", "", txt)
        if txt.endswith("```"):
            txt = txt[: -3].strip()

    # First attempt: direct parse
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        pass

    # Fallback: try to grab the first JSON-looking chunk (list or object)
    start = min(
        [i for i in [txt.find("["), txt.find("{")] if i != -1] or [-1]
    )
    if start != -1:
        # look for matching end
        end_bracket = txt.rfind("]")
        end_brace = txt.rfind("}")
        end = max(end_bracket, end_brace)
        if end != -1 and end > start:
            chunk = txt[start : end + 1]
            try:
                return json.loads(chunk)
            except json.JSONDecodeError:
                pass

    # Give up: caller decides what to do
    raise OllamaError(f"Could not parse JSON from model output:\n{text}")


# --------------------------------------------------------------------
# 1) infer_scale: attempts to guess units / thousands / millions / billions
# --------------------------------------------------------------------

def infer_scale(header_text: str, sample_values: List[float]) -> str:
    """
    Heuristic scale detector.
    - Look for 'thousands', 'millions', 'billions' in the header text.
    - If no keywords, use magnitude of sample_values as a rough guess.
    Returns one of: 'units', 'thousands', 'millions', 'billions'.
    """
    if not header_text:
        header_text = ""
    h = header_text.lower()

    # Keyword-based detection
    if "thousand" in h or "thousands" in h or "000s" in h or "000's" in h:
        return "thousands"
    if "million" in h or "millions" in h or "mm" in h:
        return "millions"
    if "billion" in h or "billions" in h or "bn" in h:
        return "billions"

    # Magnitude-based detection
    vals = [abs(x) for x in sample_values if x is not None]
    if vals:
        max_v = max(vals)
        if max_v >= 1e11:
            return "billions"
        if max_v >= 1e8:
            return "millions"
        if max_v >= 1e5:
            return "thousands"

    return "units"


# --------------------------------------------------------------------
# 2) map_label_to_coa: map a raw line label to a standard COA name
# --------------------------------------------------------------------

def map_label_to_coa(label: str, coa_candidates: List[str]) -> Optional[str]:
    """
    Use the LLM to map a messy line item label (e.g. 'Net sales',
    'Total turnover', 'Top-line revenue') to one canonical COA name from
    the given list (e.g. ['Revenue', 'COGS', 'R&D', ...]).

    Returns the chosen COA string or None if no reasonable match.
    """
    if label is None:
        return None
    label = str(label).strip()
    if not label:
        return None

    if not coa_candidates:
        return None

    # Quick exact match or very close match without LLM
    norm_label = label.lower()
    for c in coa_candidates:
        if norm_label == str(c).lower():
            return c

    candidates_str = ", ".join(sorted(set(str(c) for c in coa_candidates)))

    system_msg = (
        "You are a precise financial analyst. "
        "Your task is to map a given financial line item label into ONE of the "
        "standard chart-of-accounts (COA) names provided, or say there is no good match.\n\n"
        "You understand that different words can mean the same thing:\n"
        "- 'revenue', 'net sales', 'sales', 'turnover', 'top line' => Revenue\n"
        "- 'cost of revenue', 'cost of sales', 'cost of goods sold' => COGS\n"
        "- 'research and development', 'R&D' => Research & Development\n"
        "- 'selling, general and administrative', 'SG&A' => General & Administrative (or Sales & Marketing if that is a separate COA)\n\n"
        "You MUST answer with ONLY one of the COA names from the list, or the word NONE if there is no reasonable mapping. "
        "Do not explain your reasoning."
    )

    user_msg = (
        f"COA candidates:\n{candidates_str}\n\n"
        f"Line item label:\n{label}\n\n"
        "Respond with exactly ONE of the COA names above, or NONE."
    )

    content = _llm_chat(
        [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.0,
    )

    first_line = content.strip().splitlines()[0].strip().strip('"').strip("'")

    # Normalize
    if first_line.upper() == "NONE":
        return None

    # Try exact and case-insensitive matching back to the candidate list
    for c in coa_candidates:
        if first_line == c:
            return c
    for c in coa_candidates:
        if first_line.lower() == str(c).lower():
            return c

    # Sometimes the model might embed the choice in a sentence, try to pull it out
    for c in coa_candidates:
        if c.lower() in first_line.lower():
            return c

    return None


# --------------------------------------------------------------------
# 3) extract_structured_from_html: single-pass IS extraction
# --------------------------------------------------------------------

def extract_structured_from_html(
    html_or_text: str,
    coa_candidates: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Ask the LLM to read the HTML / text of a filing and return a structured
    representation of the income statement.

    Expected JSON schema (list of items):

    [
      {
        "label": "Revenue",
        "scale": "millions",   # one of: units, thousands, millions, billions
        "coa": "Revenue" or null,
        "year_values": {
          "2024": 12345.0,
          "2023": 12000.0
        }
      },
      ...
    ]

    - LLM should understand synonyms:
      revenue = net sales = sales = turnover = top line
      operating income = operating profit = profit from operations
      net income = profit for the year = profit attributable to shareholders

    Returns a list (possibly empty) of dicts matching the schema above.
    """
    if coa_candidates is None:
        coa_candidates = []

    coa_str = ", ".join(sorted(set(str(c) for c in coa_candidates))) if coa_candidates else ""

    system_msg = (
        "You are an expert financial analyst. "
        "You will receive the raw text or HTML from a company's financial filing "
        "(e.g., 10-K, annual report) and you must extract a CONSOLIDATED income statement "
        "into a compact JSON structure.\n\n"
        "WHERE TO LOOK FOR NUMBERS:\n"
        "- Look for income statement figures both in TABLES and in NARRATIVE TEXT.\n"
        "- Tables may show a full income statement; narrative sections (e.g., MD&A) may repeat or summarize key figures.\n"
        "- You must consider both, but avoid double-counting.\n\n"
        "IMPORTANT SEMANTIC RULES (synonyms you understand):\n"
        "- 'revenue', 'net sales', 'sales', 'turnover', 'top line' => Revenue\n"
        "- 'cost of revenue', 'cost of sales', 'cost of goods sold' => COGS\n"
        "- 'gross profit', 'gross margin' (dollar amount) => Gross Profit\n"
        "- 'operating income', 'operating profit', 'profit from operations' => Operating Income\n"
        "- 'net income', 'profit attributable to shareholders', 'profit for the year' => Net Income\n"
        "- Prefer TOTAL consolidated figures over segment or geographic breakdowns.\n\n"
        "HOW TO HANDLE MULTIPLE OCCURRENCES:\n"
        "- If the SAME metric for the SAME year appears more than once (for example, once in the consolidated income statement table and once in a paragraph), choose ONE authoritative value.\n"
        "- Prefer the figures in the primary consolidated income statement over narrative summaries or duplicated text.\n"
        "- Do NOT output duplicate entries for the same (metric, year) pair.\n\n"
        "SCALE RULES:\n"
        "- Look for phrases like 'in millions', 'in thousands', 'in billions' to infer scale.\n"
        "- If you cannot find a clear scale, assume 'units'.\n\n"
        "COA MAPPING:\n"
        "If a list of COA candidate names is provided, choose the BEST matching COA for each line item, "
        "or null if nothing fits. Only use the exact COA strings provided.\n\n"
        "OUTPUT FORMAT (VERY IMPORTANT):\n"
        "- Your ENTIRE reply must be a single valid JSON array.\n"
        "- Do NOT wrap it in any object.\n"
        "- Do NOT include keys like 'status', 'message', 'request', 'data', etc.\n"
        "- Do NOT include any explanatory text before or after the JSON.\n"
        "- It must be directly parseable by json.loads in Python.\n"
        "Example of the overall shape (illustrative only):\n"
        "[\n"
        "  {\n"
        '    \"label\": \"Net sales\",\n'
        '    \"scale\": \"millions\",\n'
        '    \"coa\": \"Revenue\",\n'
        '    \"year_values\": {\"2024\": 383285.0, \"2023\": 365817.0}\n'
        "  }\n"
        "]"
    )

    user_intro = "Below is the filing content. Focus on the CONSOLIDATED income statement numbers, wherever they appear (tables or paragraphs).\n"
    if coa_str:
        user_intro += f"\nUse these COA candidates when populating the 'coa' field:\n{coa_str}\n"

    user_msg = (
        user_intro
        + "\n\nFILING CONTENT START\n"
        + html_or_text
        + "\nFILING CONTENT END"
    )

    content = _ollama_chat(
        [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.1,
    )

    # DEBUG: see what the model actually returns
    print("DEBUG raw model output (first 800 chars):")
    print(content[:800])

    try:
        data = _extract_json_from_text(content)
    except OllamaError as e:
        # On parsing failure, bubble up as an empty result so caller can fall back.
        print(f"[WARN] extract_structured_from_html: {e}")
        return []

    if data is None:
        return []

    # We expect a list; if it's a dict, wrap it in a list.
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []

    # Light normalization: ensure required keys exist
    normalized: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        if label is None:
            continue
        scale = item.get("scale", "units")
        if scale not in {"units", "thousands", "millions", "billions"}:
            scale = "units"
        year_values = item.get("year_values") or {}
        if not isinstance(year_values, dict):
            year_values = {}
        coa = item.get("coa")
        if coa is not None and coa not in coa_candidates:
            # If the model invented a new name, just drop it.
            coa = None

        normalized.append(
            {
                "label": str(label),
                "scale": str(scale),
                "coa": coa,
                "year_values": year_values,
            }
        )

    # --- DEDUP: merge items with the same (label, coa, scale) and merge their year_values ---
    merged: Dict[tuple, Dict[str, Any]] = {}
    for item in normalized:
        key = (item["label"], item["coa"], item["scale"])
        if key not in merged:
            merged[key] = {
                "label": item["label"],
                "scale": item["scale"],
                "coa": item["coa"],
                "year_values": dict(item["year_values"]),  # copy
            }
        else:
            # Merge year_values; later occurrences overwrite earlier if conflict
            merged[key]["year_values"].update(item["year_values"])

    return list(merged.values())

from typing import List, Optional  # make sure this import is present at top
import re  # already imported, but ensure it's there


def pick_is_table_index(table_snippets: List[str]) -> int:
    """
    Ask the LLM: among these candidate tables, which ONE is the
    consolidated income statement / statement of operations?

    Returns an integer index in [0, len(table_snippets)-1].
    Falls back to 0 if the model gives nonsense.
    """
    if not table_snippets:
        raise ValueError("pick_is_table_index called with empty snippets list")

    # Build a compact prompt: each snippet is a tiny CSV of the top rows
    joined = []
    for i, snip in enumerate(table_snippets):
        joined.append(f"Table {i}:\n{snip}")
    tables_text = "\n\n---\n\n".join(joined)

    system_msg = (
        "You are an expert financial analyst. "
        "You will be given several tables extracted from a company's 10-K filing. "
        "Your job is ONLY to choose which table is the consolidated statement of "
        "operations (also called the income statement). "
        "The income statement is the table that contains lines such as 'Net sales', "
        "'Total net sales', 'Cost of sales', 'Gross margin', 'Operating income', "
        "and 'Net income', with multiple fiscal years as columns.\n\n"
        "Respond with ONLY the integer index of that table (0, 1, 2, ...). "
        "Do not output anything else."
    )

    user_msg = (
        "Here are the candidate tables extracted from the HTML filing:\n\n"
        f"{tables_text}\n\n"
        "Which table index is the consolidated statement of operations / income statement? "
        "Reply with just the number, e.g. 3."
    )

    content = _ollama_chat(
        [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.0,
    )

    # Try to extract the first integer from the response
    m = re.search(r"\b(\d+)\b", content)
    if not m:
        return 0
    idx = int(m.group(1))
    if idx < 0 or idx >= len(table_snippets):
        return 0
    return idx
