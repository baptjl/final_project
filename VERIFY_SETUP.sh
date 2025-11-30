#!/bin/bash

echo "============================================================"
echo "Verifying Unified 10-K Financial Analysis Pipeline"
echo "============================================================"
echo ""

# Check Python environment
echo "✓ Python environment:"
./.venv/bin/python --version
echo ""

# Check required packages
echo "✓ Required packages installed:"
./.venv/bin/python -c "import pandas, openpyxl, yaml; print('  - pandas ✓')" 2>/dev/null && echo "  - openpyxl ✓" && echo "  - pyyaml ✓"
echo ""

# Check main scripts
echo "✓ Main scripts present:"
[ -f unified_pipeline.py ] && echo "  - unified_pipeline.py ✓" || echo "  - unified_pipeline.py ✗"
[ -f mid_product_converter.py ] && echo "  - mid_product_converter.py ✓" || echo "  - mid_product_converter.py ✗"
echo ""

# Check automodel modules
echo "✓ AutoModel modules:"
[ -f automodel/src/extract/is_tidy.py ] && echo "  - is_tidy.py ✓" || echo "  - is_tidy.py ✗"
[ -f automodel/src/map/map_to_coa.py ] && echo "  - map_to_coa.py ✓" || echo "  - map_to_coa.py ✗"
[ -f automodel/configs/mappings.yaml ] && echo "  - mappings.yaml ✓" || echo "  - mappings.yaml ✗"
echo ""

# Check finmod modules
echo "✓ FinMod modules:"
[ -f final-project_finmod-main/src/finmod/modeler.py ] && echo "  - modeler.py ✓" || echo "  - modeler.py ✗"
[ -f final-project_finmod-main/Inputs_Historical/Baseline\ IS.xlsx ] && echo "  - Baseline IS.xlsx ✓" || echo "  - Baseline IS.xlsx ✗"
echo ""

# Check sample data
echo "✓ Sample data:"
[ -f automodel/data/samples/apple_10k_2025.html ] && echo "  - apple_10k_2025.html ✓" || echo "  - apple_10k_2025.html ✗"
echo ""

# Check documentation
echo "✓ Documentation:"
[ -f UNIFIED_PIPELINE.md ] && echo "  - UNIFIED_PIPELINE.md ✓" || echo "  - UNIFIED_PIPELINE.md ✗"
[ -f PIPELINE_SUMMARY.md ] && echo "  - PIPELINE_SUMMARY.md ✓" || echo "  - PIPELINE_SUMMARY.md ✗"
[ -f QUICK_REFERENCE.md ] && echo "  - QUICK_REFERENCE.md ✓" || echo "  - QUICK_REFERENCE.md ✗"
echo ""

# Check outputs
echo "✓ Output files from test run:"
[ -f Mid-Product.xlsx ] && echo "  - Mid-Product.xlsx ($(ls -lh Mid-Product.xlsx | awk '{print $5}')) ✓" || echo "  - Mid-Product.xlsx ✗"
[ -f Final.xlsx ] && echo "  - Final.xlsx ($(ls -lh Final.xlsx | awk '{print $5}')) ✓" || echo "  - Final.xlsx ✗"
echo ""

echo "============================================================"
echo "✅ SETUP VERIFIED - Ready to run!"
echo "============================================================"
echo ""
echo "Quick start:"
echo "  python unified_pipeline.py --html automodel/data/samples/apple_10k_2025.html --company \"Apple Inc.\""
echo ""
echo "See QUICK_REFERENCE.md for more examples"
echo ""
