#!/usr/bin/env bash
# =====================================================================
# run_pipeline.sh — drive the OA notebook pipeline end to end.
#
# Usage:
#     ./run_pipeline.sh INPUT_XLSX OUTPUT_ROOT [options]
#
# Required arguments:
#     INPUT_XLSX     Path to the input Excel workbook.
#     OUTPUT_ROOT    Directory where every stage output will be written.
#
# Options:
#     --sheet N           Zero based Excel sheet index to process.
#                         Default: 0.
#     --config-dir DIR    Directory containing optional per stage YAML, YML,
#                         or JSON config overrides.
#
#                         The runner looks for these filenames:
#                             02_ta_ph_qc.yaml, 02_ta_ph_qc.yml, or 02_ta_ph_qc.json
#                             04_stage1a.yaml, 04_stage1a.yml, or 04_stage1a.json
#                             05_stage1b.yaml, 05_stage1b.yml, or 05_stage1b.json
#                             06_stage2.yaml, 06_stage2.yml, or 06_stage2.json
#                             07_stage3.yaml, 07_stage3.yml, or 07_stage3.json
#                             08_stage4.yaml, 08_stage4.yml, or 08_stage4.json
#
#                         Files such as cruise_grade_thresholds.yaml and
#                         regional.yaml are not automatically loaded by this
#                         runner unless the notebooks load them internally.
#                         The simplest current pattern is to create per stage
#                         config files that include or duplicate those settings.
#     --no-parquet        Pass NO_PARQUET=True to stages 04 to 08.
#     --include-viewer    Also run Notebook 01.
#     --include-review    Also run Notebook 03.
#     --start-from STAGE  Skip stages before STAGE. STAGE must be one of:
#                         02, 04, 05, 06, 07, 08.
#     --dry-run           Print Papermill commands but do not run them.
#                         In dry run mode, downstream required output files,
#                         Papermill, and oa_pipeline import checks are skipped.
#     -h, --help          Show this help and exit.
#
# Environment:
#     PYTHON_BIN          Optional Python executable to use. Defaults to python.
#                         Example:
#                             PYTHON_BIN=.venv/Scripts/python.exe ./run_pipeline.sh ...
#
# Examples:
#     ./run_pipeline.sh data/oa_prelim_data.xlsx outputs/real
#
#     ./run_pipeline.sh data/oa_prelim_data.xlsx outputs/real \
#         --include-viewer --include-review
#
#     ./run_pipeline.sh data/oa_prelim_data.xlsx outputs/real \
#         --start-from 06
#
#     ./run_pipeline.sh data/oa_prelim_data.xlsx outputs/real \
#         --config-dir configs
# =====================================================================

set -euo pipefail

# ---------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------

SHEET=0
CONFIG_DIR=""
NO_PARQUET="False"
INCLUDE_VIEWER=0
INCLUDE_REVIEW=0
START_FROM="02"
DRY_RUN=0
INPUT_XLSX=""
OUTPUT_ROOT=""
PYTHON_BIN="${PYTHON_BIN:-python}"

# ---------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------

usage() {
    awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"
}

need_value() {
    local opt="$1"
    local val="${2:-}"

    if [[ -z "$val" || "$val" == -* ]]; then
        echo "ERROR: $opt requires a value." >&2
        usage
        exit 2
    fi
}

stage_index() {
    case "$1" in
        02) echo 2 ;;
        04) echo 4 ;;
        05) echo 5 ;;
        06) echo 6 ;;
        07) echo 7 ;;
        08) echo 8 ;;
        *)
            echo "ERROR: --start-from must be one of 02, 04, 05, 06, 07, or 08. Got: $1" >&2
            exit 2
            ;;
    esac
}

# ---------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        --sheet)
            need_value "$1" "${2:-}"
            SHEET="$2"
            shift 2
            ;;
        --config-dir)
            need_value "$1" "${2:-}"
            CONFIG_DIR="$2"
            shift 2
            ;;
        --no-parquet)
            NO_PARQUET="True"
            shift
            ;;
        --include-viewer)
            INCLUDE_VIEWER=1
            shift
            ;;
        --include-review)
            INCLUDE_REVIEW=1
            shift
            ;;
        --start-from)
            need_value "$1" "${2:-}"
            START_FROM="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        -*)
            echo "ERROR: unknown option: $1" >&2
            usage
            exit 2
            ;;
        *)
            if [[ -z "$INPUT_XLSX" ]]; then
                INPUT_XLSX="$1"
            elif [[ -z "$OUTPUT_ROOT" ]]; then
                OUTPUT_ROOT="$1"
            else
                echo "ERROR: unexpected extra argument: $1" >&2
                usage
                exit 2
            fi
            shift
            ;;
    esac
done

if [[ -z "$INPUT_XLSX" || -z "$OUTPUT_ROOT" ]]; then
    echo "ERROR: INPUT_XLSX and OUTPUT_ROOT are required." >&2
    usage
    exit 2
fi

if ! [[ "$SHEET" =~ ^[0-9]+$ ]]; then
    echo "ERROR: --sheet must be a zero based integer such as 0, 1, or 2." >&2
    exit 2
fi

START_IDX="$(stage_index "$START_FROM")"

should_run() {
    local idx="$1"
    [[ "$idx" -ge "$START_IDX" ]]
}

# AUDIT FIX N-5: Warn when --start-from skips Stage 2 (06). Stage 4 (08)
# requires the depth_round_m key column, which is normally produced by Stage 2.
# A direct jump to Stage 4 relies on Stage 4's depth_round_m fallback (FIX 8-B),
# which derives a coarse key from depth_m. That fallback keeps the run from
# marking every row FAIL, but it is NOT a substitute for Stage 2's proper depth
# binning. Make this explicit so operators do not silently ship coarsely-keyed
# data. Stage 2 index is 6; warn if we start at or after Stage 3 (07).
STAGE2_IDX="$(stage_index 06)"
if [[ "$START_IDX" -gt "$STAGE2_IDX" ]]; then
    echo "WARNING: --start-from $START_FROM skips Stage 2 (06_stage2)." >&2
    echo "         Stage 4 needs depth_round_m, normally created by Stage 2." >&2
    echo "         Stage 4's depth_round_m fallback (derived from depth_m) will" >&2
    echo "         be used if the upstream input lacks it. This avoids a total" >&2
    echo "         FAIL but does not replace Stage 2's depth binning. Re-run" >&2
    echo "         from Stage 2 for proper depth keys before final delivery." >&2
fi

# ---------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------
# Resolve user supplied paths before changing into the project root. This
# allows the script to be launched from outside the repository while still
# accepting relative paths from the caller's current directory.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOTEBOOK_DIR="$SCRIPT_DIR/notebooks"

abs_file() {
    local path="$1"

    if [[ ! -f "$path" ]]; then
        echo "ERROR: file not found: $path" >&2
        exit 2
    fi

    local dir
    local base
    dir="$(cd "$(dirname "$path")" && pwd)"
    base="$(basename "$path")"
    printf "%s/%s\n" "$dir" "$base"
}

abs_existing_dir() {
    local path="$1"

    if [[ ! -d "$path" ]]; then
        echo "ERROR: directory not found: $path" >&2
        exit 2
    fi

    (cd "$path" && pwd)
}

abs_dir_create() {
    local path="$1"
    mkdir -p "$path"
    (cd "$path" && pwd)
}

INPUT_XLSX="$(abs_file "$INPUT_XLSX")"
OUTPUT_ROOT="$(abs_dir_create "$OUTPUT_ROOT")"

if [[ -n "$CONFIG_DIR" ]]; then
    CONFIG_DIR="$(abs_existing_dir "$CONFIG_DIR")"
fi

cd "$SCRIPT_DIR"

if [[ ! -d "$NOTEBOOK_DIR" ]]; then
    echo "ERROR: notebook directory not found: $NOTEBOOK_DIR" >&2
    exit 2
fi

TIMESTAMP="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
RUNS_DIR="$SCRIPT_DIR/runs/${TIMESTAMP}_pid$$"
mkdir -p "$RUNS_DIR"

# ---------------------------------------------------------------------
# Dependency and file checks
# ---------------------------------------------------------------------

if [[ "$DRY_RUN" -eq 0 ]]; then
    "$PYTHON_BIN" -c "import papermill" >/dev/null 2>&1 || {
        echo "ERROR: papermill is not installed in this Python environment." >&2
        echo "Install with: $PYTHON_BIN -m pip install -e \".[all]\"" >&2
        exit 2
    }

    "$PYTHON_BIN" -c "import oa_pipeline" >/dev/null 2>&1 || {
        echo "ERROR: oa_pipeline is not importable in this Python environment." >&2
        echo "Install with: $PYTHON_BIN -m pip install -e \".[all]\"" >&2
        exit 2
    }
fi

require_file() {
    local path="$1"
    local label="$2"

    if [[ "$DRY_RUN" -eq 1 ]]; then
        return 0
    fi

    if [[ ! -f "$path" ]]; then
        echo "ERROR: missing required input for $label:" >&2
        echo "  $path" >&2
        echo "Run earlier stages first or use the correct OUTPUT_ROOT." >&2
        exit 2
    fi
}

require_notebook() {
    local path="$1"

    if [[ ! -f "$path" ]]; then
        echo "ERROR: notebook not found: $path" >&2
        exit 2
    fi
}

for notebook in \
    "$NOTEBOOK_DIR/01_excel_viewer.ipynb" \
    "$NOTEBOOK_DIR/02_ta_ph_qc.ipynb" \
    "$NOTEBOOK_DIR/03_qc_output_review.ipynb" \
    "$NOTEBOOK_DIR/04_stage1a.ipynb" \
    "$NOTEBOOK_DIR/05_stage1b.ipynb" \
    "$NOTEBOOK_DIR/06_stage2.ipynb" \
    "$NOTEBOOK_DIR/07_stage3.ipynb" \
    "$NOTEBOOK_DIR/08_stage4.ipynb"
do
    require_notebook "$notebook"
done

# ---------------------------------------------------------------------
# Per stage output directories
# ---------------------------------------------------------------------

QC_OUT="$OUTPUT_ROOT/oa_prelim_data__qc_outputs"
S1A_OUT="$OUTPUT_ROOT/oa_stage1a_outputs"
S1B_OUT="$OUTPUT_ROOT/oa_stage1b_outputs"
S2_OUT="$OUTPUT_ROOT/oa_stage2_outputs"
S3_OUT="$OUTPUT_ROOT/oa_stage3_outputs"
S4_OUT="$OUTPUT_ROOT/oa_stage4_outputs"
VIEWER_OUT="$OUTPUT_ROOT/oa_viewer_outputs"

# ---------------------------------------------------------------------
# Runtime helpers
# ---------------------------------------------------------------------

resolve_config() {
    local stage_name="$1"

    if [[ -n "$CONFIG_DIR" ]]; then
        for ext in yaml yml json; do
            local candidate="$CONFIG_DIR/${stage_name}.${ext}"
            if [[ -f "$candidate" ]]; then
                echo "$candidate"
                return
            fi
        done

        echo "WARNING: no per stage config found for $stage_name in $CONFIG_DIR; using notebook defaults." >&2
    fi

    echo "None"
}

resolve_qc_sheet_folder() {
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "sheet_$SHEET"
        return 0
    fi

    "$PYTHON_BIN" - "$INPUT_XLSX" "$SHEET" <<'PY'
from pathlib import Path
import sys

import pandas as pd

from oa_pipeline.common import safe_sheet_name

xlsx = Path(sys.argv[1])
sheet_index = int(sys.argv[2])

excel = pd.ExcelFile(xlsx, engine="openpyxl")

if sheet_index < 0 or sheet_index >= len(excel.sheet_names):
    raise SystemExit(
        f"Sheet index {sheet_index} is out of range. "
        f"Workbook has {len(excel.sheet_names)} sheets."
    )

print("sheet_" + safe_sheet_name(excel.sheet_names[sheet_index]))
PY
}

resolve_qc_derived_csv() {
    local sheet_folder
    sheet_folder="$(resolve_qc_sheet_folder)"
    local expected="$QC_OUT/$sheet_folder/data/derived.csv"

    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "$expected"
        return 0
    fi

    if [[ -f "$expected" ]]; then
        echo "$expected"
        return 0
    fi

    if [[ ! -d "$QC_OUT" ]]; then
        echo "ERROR: could not find Notebook 02 output folder:" >&2
        echo "  $QC_OUT" >&2
        echo "Run Notebook 02 first or use the correct OUTPUT_ROOT." >&2
        exit 2
    fi

    mapfile -t matches < <(find "$QC_OUT" -type f -path "*/data/derived.csv" | sort)

    if [[ "${#matches[@]}" -eq 1 ]]; then
        echo "${matches[0]}"
        return 0
    fi

    if [[ "${#matches[@]}" -eq 0 ]]; then
        echo "ERROR: could not find Notebook 02 derived.csv under:" >&2
        echo "  $QC_OUT" >&2
        exit 2
    fi

    echo "ERROR: multiple derived.csv files found under $QC_OUT:" >&2
    printf '  %s\n' "${matches[@]}" >&2
    echo "Use --sheet or clean OUTPUT_ROOT so only one sheet output is present." >&2
    exit 2
}

run_papermill() {
    local notebook="$1"
    local out_ipynb="$2"
    shift 2
    local -a args=("$@")

    echo "----------------------------------------------------------------------"
    echo "$PYTHON_BIN -m papermill $notebook"
    for arg in "${args[@]}"; do
        echo "    $arg"
    done
    echo "  -> $out_ipynb"

    if [[ "$DRY_RUN" -eq 1 ]]; then
        return 0
    fi

    "$PYTHON_BIN" -m papermill "$notebook" "$out_ipynb" "${args[@]}"
}

# ---------------------------------------------------------------------
# Run chain header
# ---------------------------------------------------------------------

echo "======================================================================"
echo "OA pipeline run"
echo "  input xlsx   : $INPUT_XLSX"
echo "  output root  : $OUTPUT_ROOT"
echo "  notebook dir : $NOTEBOOK_DIR"
echo "  python bin   : $PYTHON_BIN"
echo "  sheet        : $SHEET"
echo "  start from   : Stage $START_FROM"
echo "  config dir   : ${CONFIG_DIR:-(none)}"
echo "  config mode  : per stage CONFIG_PATH files"
echo "  parquet      : $( [[ "$NO_PARQUET" == "True" ]] && echo disabled || echo enabled )"
echo "  dry run      : $( [[ "$DRY_RUN" -eq 1 ]] && echo yes || echo no )"
echo "  runs dir     : $RUNS_DIR"
echo "======================================================================"

# ---------------------------------------------------------------------
# Notebook 01: Optional Excel viewer
# ---------------------------------------------------------------------

if [[ "$INCLUDE_VIEWER" -eq 1 ]] && should_run 2; then
    run_papermill "$NOTEBOOK_DIR/01_excel_viewer.ipynb" "$RUNS_DIR/01_excel_viewer.run.ipynb" \
        -p XLSX_PATH "$INPUT_XLSX" \
        -p OUT_DIR "$VIEWER_OUT" \
        -p SHEET "$SHEET"
fi

# ---------------------------------------------------------------------
# Notebook 02: TA and pH QC
# ---------------------------------------------------------------------

if should_run 2; then
    CONFIG="$(resolve_config 02_ta_ph_qc)"

    run_papermill "$NOTEBOOK_DIR/02_ta_ph_qc.ipynb" "$RUNS_DIR/02_ta_ph_qc.run.ipynb" \
        -p XLSX_PATH "$INPUT_XLSX" \
        -p OUT_DIR "$QC_OUT" \
        -p SHEET "$SHEET" \
        -p CONFIG_PATH "$CONFIG"
fi

# ---------------------------------------------------------------------
# Notebook 03: Optional QC output review
# ---------------------------------------------------------------------

if [[ "$INCLUDE_REVIEW" -eq 1 ]] && should_run 2; then
    QC_DERIVED_CSV="$(resolve_qc_derived_csv)"
    require_file "$QC_DERIVED_CSV" "Notebook 03 review"

    run_papermill "$NOTEBOOK_DIR/03_qc_output_review.ipynb" "$RUNS_DIR/03_qc_output_review.run.ipynb" \
        -p OUTPUT_ROOT "$QC_OUT"
fi

# ---------------------------------------------------------------------
# Notebook 04: Stage 1A
# ---------------------------------------------------------------------

if should_run 4; then
    QC_DERIVED_CSV="$(resolve_qc_derived_csv)"
    require_file "$QC_DERIVED_CSV" "Stage 04"
    CONFIG="$(resolve_config 04_stage1a)"

    run_papermill "$NOTEBOOK_DIR/04_stage1a.ipynb" "$RUNS_DIR/04_stage1a.run.ipynb" \
        -p INPUT_CSV "$QC_DERIVED_CSV" \
        -p OUT_DIR "$S1A_OUT" \
        -p CONFIG_PATH "$CONFIG" \
        -p NO_PARQUET "$NO_PARQUET"
fi

# ---------------------------------------------------------------------
# Notebook 05: Stage 1B
# ---------------------------------------------------------------------

if should_run 5; then
    require_file "$S1A_OUT/data/staged.csv" "Stage 05"
    CONFIG="$(resolve_config 05_stage1b)"

    run_papermill "$NOTEBOOK_DIR/05_stage1b.ipynb" "$RUNS_DIR/05_stage1b.run.ipynb" \
        -p INPUT_CSV "$S1A_OUT/data/staged.csv" \
        -p OUT_DIR "$S1B_OUT" \
        -p CONFIG_PATH "$CONFIG" \
        -p NO_PARQUET "$NO_PARQUET"
fi

# ---------------------------------------------------------------------
# Notebook 06: Stage 2
# ---------------------------------------------------------------------

if should_run 6; then
    require_file "$S1B_OUT/data/analysis_ready_samples.csv" "Stage 06"
    CONFIG="$(resolve_config 06_stage2)"

    run_papermill "$NOTEBOOK_DIR/06_stage2.ipynb" "$RUNS_DIR/06_stage2.run.ipynb" \
        -p INPUT_CSV "$S1B_OUT/data/analysis_ready_samples.csv" \
        -p OUT_DIR "$S2_OUT" \
        -p CONFIG_PATH "$CONFIG" \
        -p NO_PARQUET "$NO_PARQUET"
fi

# ---------------------------------------------------------------------
# Notebook 07: Stage 3
# ---------------------------------------------------------------------

if should_run 7; then
    require_file "$S2_OUT/data/enhanced.csv" "Stage 07"
    CONFIG="$(resolve_config 07_stage3)"

    run_papermill "$NOTEBOOK_DIR/07_stage3.ipynb" "$RUNS_DIR/07_stage3.run.ipynb" \
        -p INPUT_CSV "$S2_OUT/data/enhanced.csv" \
        -p OUT_DIR "$S3_OUT" \
        -p CONFIG_PATH "$CONFIG" \
        -p NO_PARQUET "$NO_PARQUET"
fi

# ---------------------------------------------------------------------
# Notebook 08: Stage 4
# ---------------------------------------------------------------------

if should_run 8; then
    require_file "$S3_OUT/data/enhanced.csv" "Stage 08"
    CONFIG="$(resolve_config 08_stage4)"

    run_papermill "$NOTEBOOK_DIR/08_stage4.ipynb" "$RUNS_DIR/08_stage4.run.ipynb" \
        -p INPUT_CSV "$S3_OUT/data/enhanced.csv" \
        -p OUT_DIR "$S4_OUT" \
        -p CONFIG_PATH "$CONFIG" \
        -p NO_PARQUET "$NO_PARQUET"
fi

# ---------------------------------------------------------------------
# Final deliverable check
# ---------------------------------------------------------------------

if [[ "$DRY_RUN" -eq 0 ]] && should_run 8; then
    require_file "$S4_OUT/data/analysis_ready.csv" "final Stage 4 deliverable"
fi

# ---------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------

echo "======================================================================"
if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "Dry run complete. Re run without --dry-run to execute."
else
    echo "Pipeline complete."
    echo "  Final deliverable : $S4_OUT/data/analysis_ready.csv"
    echo "  Per stage reports : $OUTPUT_ROOT/<stage>/reports/report.md"
    echo "  Executed notebooks: $RUNS_DIR/*.run.ipynb"
fi
echo "======================================================================"
