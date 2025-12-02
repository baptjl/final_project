# AutoModel - AI-Powered Financial Analysis Tool

A sophisticated tool that ingests financial documents (HTML, PDF, iXBRL) and automatically extracts, maps, and analyzes financial data.

## Overview

AutoModel combines AI and coding to:
- **Ingest** documents (HTML, PDF, iXBRL formats)
- **Extract** financial statement line items (Income Statement, Balance Sheet, Cash Flow)
- **Map** raw labels to standardized Chart of Accounts (CoA)
- **Reformat** into clean Excel workbooks with 3 financial statements
- **Project** future financial performance using AI-powered analysis

## Project Structure

```
automodel/
├── configs/              # Configuration files
│   ├── coa.yaml         # Chart of Accounts definitions
│   ├── mappings.yaml    # Raw label → CoA mappings
│   └── xbrl_map.yaml    # iXBRL concept mappings
├── data/                # Data directory
│   ├── interim/         # Processing outputs (CSVs)
│   ├── processed/       # Final formatted data
│   ├── samples/         # Sample documents for testing
│   └── archive/         # Historical runs (optional)
├── src/                 # Source code
│   ├── ingest/          # Document ingestion
│   │   ├── run_is_extract.py      # Income Statement extraction
│   │   ├── run_ix_extract.py      # iXBRL extraction
│   │   ├── sec_html.py            # SEC HTML utilities
│   │   └── ixbrl.py               # iXBRL parser
│   ├── extract/         # Data extraction & tidying
│   │   └── is_tidy.py             # Income Statement tidying
│   ├── map/             # Label mapping logic
│   │   └── map_to_coa.py          # CoA mapping engine
│   ├── llm/             # AI-powered processing
│   │   └── ollama_client.py       # Ollama LLM integration
│   ├── excel/           # Excel output generation
│   ├── checks/          # Data validation
│   └── active_learning/ # Interactive labeling (future)
├── templates/           # Excel templates (future)
└── requirements.txt     # Python dependencies

```

## Installation

### Prerequisites
- Python 3.10+
- Ollama (for LLM features) - optional but recommended
- macOS/Linux/Windows

### Setup

1. **Clone and navigate:**
   ```bash
   cd automodel
   ```

2. **Create virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Ollama (optional but recommended):**
   ```bash
   # Install Ollama from https://ollama.ai
   ollama pull llama3.1
   ollama serve  # Start the Ollama server in another terminal
   ```

## Usage

### Extract Income Statement (HTML)

```bash
python -m automodel.src.ingest.run_is_extract
```

**Input:** HTML file path specified in `run_is_extract.py` (line 7)  
**Output:** 
- `data/interim/IS_tidy_best.csv` - Tidied line items
- `data/interim/IS_tidy_mapped_best_llm.csv` - Mapped to CoA with LLM

### Extract iXBRL Data

```bash
python -m automodel.src.ingest.run_ix_extract
```

### Configuration

Edit configuration files to customize behavior:

- **`configs/coa.yaml`** - Define your Chart of Accounts structure
- **`configs/mappings.yaml`** - Map raw labels to CoA entries
- **`configs/xbrl_map.yaml`** - Map iXBRL concepts (for SEC filings)

## Current Capabilities

✅ **Income Statement Extraction**
- Parses HTML tables from 10-K filings
- Multi-table scoring and candidate selection
- Automatic scale detection (units, thousands, millions, billions)
- LLM-powered label mapping to CoA
- Data quality filtering and coherence checks

✅ **CoA Mapping**
- Rule-based mappings (regex, exact match, fuzzy)
- LLM fallback for unmapped labels
- Sign normalization (revenue positive, expenses negative)

✅ **Data Quality**
- Automatic scale inference
- Outlier detection and removal
- Duplicate handling (max absolute value per label/year)
- Year detection from table headers

## Next Steps / Roadmap

### Phase 2: Excel Generation
- [ ] Create `src/excel/` module for workbook generation
- [ ] Template-based formatting (3 financial statements)
- [ ] Support Balance Sheet and Cash Flow extraction
- [ ] Formulas and cross-statement validation

### Phase 3: Financial Projections
- [ ] Create `src/projections/` module
- [ ] Time-series analysis (trend lines, growth rates)
- [ ] LLM-powered scenario generation
- [ ] Monte Carlo simulation for uncertainty

### Phase 4: PDF & Advanced Formats
- [ ] Add PDF text extraction (`pdfplumber` or `PyPDF2`)
- [ ] OCR support for scanned documents
- [ ] Semi-structured table parsing

### Phase 5: Active Learning
- [ ] Interactive label correction UI
- [ ] User feedback loop
- [ ] Model fine-tuning based on corrections

## Dependencies

| Package | Purpose |
|---------|---------|
| `pandas` | Data manipulation and CSV/Excel I/O |
| `pyyaml` | Configuration files |
| `requests` | HTTP requests to Ollama API |
| `lxml` | HTML/XML parsing |
| `beautifulsoup4` | HTML table extraction |
| `openpyxl` | Excel workbook generation |
| `numpy` | Numerical operations |

## Configuration

### Environment Variables

Create a `.env` file for sensitive settings:

```bash
OLLAMA_URL=http://localhost:11434/api/generate
OLLAMA_MODEL=llama3.1
OLLAMA_TIMEOUT=120
```

### Ollama Setup

```bash
# Pull the default model
ollama pull llama3.1

# Or use a specific quantization
ollama pull llama3.1:7b-q4_0  # Smaller, faster

# Test connection
curl http://localhost:11434/api/tags
```

## Troubleshooting

### Issue: Ollama connection fails
**Solution:**
```bash
# Check if Ollama is running
ollama serve
# In another terminal, test:
curl http://localhost:11434/api/generate -X POST -d '{"model": "llama3.1", "prompt": "Hi"}'
```

### Issue: Scale detection gives wrong results
**Solution:**
- Check the HTML headers for scale indicators ("in millions", etc.)
- Manually adjust scale in `configs/` if needed
- Verify sample values are reasonable

### Issue: Labels not mapping to CoA
**Solution:**
1. Check `mappings.yaml` for matching rules
2. Review LLM responses in console output
3. Add manual mappings to `mappings.yaml`

## Development Notes

### Code Organization

- **`ingest/`** - Entry points and document parsing
- **`extract/`** - Tidying and data cleaning logic
- **`map/`** - CoA mapping (rules + LLM)
- **`llm/`** - AI integrations (Ollama, future: GPT-4)
- **`excel/`** - Excel generation (coming soon)

### Testing

```bash
# Run extraction on sample file
python -m automodel.src.ingest.run_is_extract

# Check output
cat data/interim/IS_tidy_best.csv
```

### Adding New Extractors

Create a new file in `src/ingest/` following this pattern:

```python
def extract_balance_sheet(html_path: Path) -> pd.DataFrame:
    """Extract balance sheet data from HTML."""
    # Your implementation
    pass

def main():
    # Entry point
    pass

if __name__ == "__main__":
    main()
```

## License

[Add your license here]

## Contact

Baptiste Joffe  
Yale School of Management  
[Add contact info]

---

**Last Updated:** November 15, 2025
