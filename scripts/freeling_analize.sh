#!/usr/bin/env bash

# ============================================================
# FreeLing Galician Tokenization Script
#
# - Recursively processes .txt files from a source directory
# - Preserves the directory structure in a new destination root
# - Uses FreeLing (analyze --nortk) to avoid morphological retokenization
#
# Usage:
#   ./freeling_tokenize_gl.sh <input_dir> <output_dir>
# ============================================================

# -------- CONFIGURATION --------
SRC_DIR="$1"   # Input root directory (original corpus)
DST_DIR="$2"   # Output root directory (processed corpus)
CFG="/usr/local/share/freeling/config/gl.cfg"

# -------- SANITY CHECKS --------
if [[ -z "$SRC_DIR" || -z "$DST_DIR" ]]; then
  echo "Usage: $0 <input_dir> <output_dir>"
  exit 1
fi

if [[ ! -d "$SRC_DIR" ]]; then
  echo "Error: input directory does not exist: $SRC_DIR"
  exit 1
fi

if [[ ! -f "$CFG" ]]; then
  echo "Error: FreeLing Galician config not found: $CFG"
  exit 1
fi

mkdir -p "$DST_DIR"

TOTAL=$(find "$SRC_DIR" -type f -name "*.txt" | wc -l)
count=0

progress_bar () {
  local current=$1
  local total=$2
  local width=40

  local percent=$(( current * 100 / total ))
  local filled=$(( percent * width / 100 ))
  local empty=$(( width - filled ))

  printf "\r["
  printf "%0.s#" $(seq 1 $filled)
  printf "%0.s-" $(seq 1 $empty)
  printf "] %3d%% (%d/%d)" "$percent" "$current" "$total"
}

# -------- MAIN PROCESSING LOOP --------
find "$SRC_DIR" -type f -name "*.txt" -print0 \
| while IFS= read -r -d '' file; do
    ((count++))
    rel="${file#$SRC_DIR/}"
    out="$DST_DIR/${rel%.txt}.tok"
    mkdir -p "$(dirname "$out")"

    # Run FreeLing analysis without retokenization
    analyze -f "$CFG" --nortk < "$file" 2>/dev/null \
    > "$out"
    progress_bar "$count" "$TOTAL"
done

echo "✔ Tokenization completed successfully."
