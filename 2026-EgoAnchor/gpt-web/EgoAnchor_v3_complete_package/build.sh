#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

# 1) Regenerate all figures from the packaged data.
python "$ROOT/code/make_polished_figures.py"

# 2) Build the Chinese PDF with XeLaTeX.
cd "$ROOT/manuscript"
if command -v latexmk >/dev/null 2>&1; then
  latexmk -xelatex -interaction=nonstopmode -halt-on-error EgoAnchor_cn_v3_polished.tex
else
  xelatex -interaction=nonstopmode -halt-on-error EgoAnchor_cn_v3_polished.tex
  xelatex -interaction=nonstopmode -halt-on-error EgoAnchor_cn_v3_polished.tex
fi
