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
shopt -s nullglob

# -------- CONFIGURATION --------
SRC_DIR="$1"   # Input root directory (original corpus)
DST_DIR="$2"   # Output root directory (processed corpus)
SRC_DIR="$(realpath "$SRC_DIR")"
DST_DIR="$(realpath "$DST_DIR")"
CFG="/usr/local/share/freeling/config/gl.cfg"
CHUNK_LINES=5000
PARALLEL_JOBS=4
WORK_ROOT="$DST_DIR/.work"

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

# -------- CLEANUP ON INTERRUPT --------
trap 'echo; echo "⛔ Interrupted. Cleaning temporary files..."; find "$DST_DIR" -name "*.tmp" -delete; exit 130' INT

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

echo "📂 Total files to process: $TOTAL"
echo 

process_chunk() {
  chunk="$1"
  CFG="$2"

  part="$chunk.tok.part"
  tmp="$part.tmp"

  [[ -f "$part" ]] && return 0

  rm -f "$tmp"

  if analyze -f "$CFG" --nortk < "$chunk" > "$tmp" 2>/dev/null \
     && [[ -s "$tmp" ]]; then
    mv "$tmp" "$part"
  else
    rm -f "$tmp"
    echo "⚠ Error en $(basename "$chunk")"
    return 1
  fi
}
export -f process_chunk
export CFG
# -------- MAIN PROCESSING LOOP --------
find "$SRC_DIR" -type f -name "*.txt" -print0 \
| while IFS= read -r -d '' file; do
    rel="${file#$SRC_DIR/}"
    out="$DST_DIR/${rel%.txt}.tok"
    workdir="$WORK_ROOT/${rel%.txt}"

    # Skip if already processed
    if [[ -f "$out" ]]; then
      ((count++))
      progress_bar "$count" "$TOTAL"
      continue
    fi

    mkdir -p "$(dirname "$out")"
    mkdir -p "$workdir"
    
    # -------- SPLIT INTO CHUNKS (once) --------
    if [[ ! -f "$workdir/.split_done" ]]; then
      split -l "$CHUNK_LINES" \
          --numeric-suffixes=1 \
          --suffix-length=4 \
          --additional-suffix=.txt \
      "$file" "$workdir/chunk_"
      touch "$workdir/.split_done"
    fi

    printf "\nProcesando: %.80s\n" "$rel"

    # -------- PROCESS CHUNKS --------export CFG
    find "$workdir" -type f -name "chunk_*.txt" -print0 \
    | xargs -0 -n 1 -P "$PARALLEL_JOBS" bash -c '
        process_chunk "$1" "$CFG"
    ' _

    # -------- CONCATENATE -------- 
    num_chunks=$(ls "$workdir"/chunk_*.txt 2>/dev/null | wc -l)
    num_parts=$(ls "$workdir"/chunk_*.txt.tok.part 2>/dev/null | wc -l)

    if [[ "$num_chunks" -gt 0 && "$num_chunks" -eq "$num_parts" ]]; then
      cat "$workdir"/chunk_*.txt.tok.part > "$out"
      rm -rf "$workdir"
    else
      echo "⚠ Incomplete file ($num_parts/$num_chunks), resuming later: $rel"
    fi

    ((count++))
    progress_bar "$count" "$TOTAL"
done

echo
echo "✔ Tokenization completed successfully."
