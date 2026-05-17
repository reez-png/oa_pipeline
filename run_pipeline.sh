#!/usr/bin/env bash
# =====================================================================
# run_pipeline.sh — drive the eight-notebook OA pipeline end-to-end.
#
# Usage:
#     ./run_pipeline.sh INPUT_XLSX OUTPUT_ROOT [options]
#
# Required arguments:
#     INPUT_XLSX     Path to the input Excel workbook.
#     OUTPUT_ROOT    Directory where every stage's outputs will be
#                    written. Each stage gets its own subfolder:
#                        <OUTPUT_ROOT>/oa_prelim_data__qc_outputs/
#                        <OUTPUT_ROOT>/oa_stage1a_outputs/
#                        ...
#                        <OUTPUT_ROOT>/oa_stage4_outputs/
#                    The final deliverable is
#                        <OUTPUT_ROOT>/oa_stage4_outputs/data/analysis_ready.csv
#
# Options:
#     --sheet N           Which sheet of the xlsx to process (default: 0)
#     --config-dir DIR    Look in DIR for per-stage YAML/JSON config
#                         overrides (e.g. 04_stage1a.yaml). Missing
#                         files are silently skipped.
#     --no-parquet        Pass NO_PARQUET=True to every stage.
#     --include-viewer    Also run Notebook 01 (HTML viewer, optional).
#     --include-review    Also run Notebook 03 (QC inspection, optional).
#     --start-from STAGE  Skip stages before STAGE. STAGE is one of:
#                         02, 04, 05, 06, 07, 08
#                         (e.g. --start-from 06 reruns 06+07+08 only)
#     --dry-run           Print the papermill commands but do not run them.
#     -h, --help          Show this help and exit.
#
# Examples:
#     # Run the critical-path stages with defaults
#     ./run_pipeline.sh data/oa_prelim_data.xlsx ./outputs
#
#     # Include the optional viewer + reviewer stages
#     ./run_pipeline.sh data/oa_prelim_data.xlsx ./outputs \
#         --include-viewer --include-review
#
#     # Re-run only the last three stages after a Stage 1B edit
#     ./run_pipeline.sh data/oa_prelim_data.xlsx ./outputs \
#         --start-from 06
#
#     # Use stage-specific configs from a directory
#     ./run_pipeline.sh data/oa_prelim_data.xlsx ./outputs \
#         --config-dir ./configs
# =====================================================================

set -euo pipefail

# ---- Argument parsing ----------------------------------------------
SHEET=0
CONFIG_DIR=""
NO_PARQUET="False"
INCLUDE_VIEWER=0
INCLUDE_REVIEW=0
START_FROM="02"
DRY_RUN=0
INPUT_XLSX=""
OUTPUT_ROOT=""

usage() {
    # Print the leading comment block (skip the shebang at line 1).
    awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)            usage; exit 0 ;;
        --sheet)              SHEET="$2"; shift 2 ;;
        --config-dir)         CONFIG_DIR="$2"; shift 2 ;;
        --no-parquet)         NO_PARQUET="True"; shift ;;
        --include-viewer)     INCLUDE_VIEWER=1; shift ;;
        --include-review)     INCLUDE_REVIEW=1; shift ;;
        --start-from)         START_FROM="$2"; shift 2 ;;
        --dry-run)            DRY_RUN=1; shift ;;
        -*)                   echo "Unknown option: $1" >&2; usage; exit 2 ;;
        *)
            if [[ -z "$INPUT_XLSX" ]]; then
                INPUT_XLSX="$1"
            elif [[ -z "$OUTPUT_ROOT" ]]; then
                OUTPUT_ROOT="$1"
            else
                echo "Unexpected extra argument: $1" >&2; usage; exit 2
            fi
            shift ;;
    esac
done

if [[ -z "$INPUT_XLSX" || -z "$OUTPUT_ROOT" ]]; then
    echo "ERROR: INPUT_XLSX and OUTPUT_ROOT are required." >&2
    usage
    exit 2
fi

if [[ ! -f "$INPUT_XLSX" ]]; then
    echo "ERROR: input not found: $INPUT_XLSX" >&2
    exit 2
fi

# ---- Resolve paths -------------------------------------------------
# The script lives in the project root next to the notebooks; cd there
# so papermill can find the .ipynb files and the modules they import.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

INPUT_XLSX="$( cd "$( dirname "$INPUT_XLSX" )" && pwd )/$( basename "$INPUT_XLSX" )"
mkdir -p "$OUTPUT_ROOT"
OUTPUT_ROOT="$( cd "$OUTPUT_ROOT" && pwd )"

# Where papermill writes the executed copies of the notebooks (with
# their outputs). Separate from OUTPUT_ROOT so it's clear that the
# "real" pipeline outputs live in OUTPUT_ROOT.
TIMESTAMP="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
RUNS_DIR="$SCRIPT_DIR/runs/$TIMESTAMP"
mkdir -p "$RUNS_DIR"

# Per-stage output directories. Each stage's INPUT_CSV is the prior
# stage's deterministic output filename.
QC_OUT="$OUTPUT_ROOT/oa_prelim_data__qc_outputs"
S1A_OUT="$OUTPUT_ROOT/oa_stage1a_outputs"
S1B_OUT="$OUTPUT_ROOT/oa_stage1b_outputs"
S2_OUT="$OUTPUT_ROOT/oa_stage2_outputs"
S3_OUT="$OUTPUT_ROOT/oa_stage3_outputs"
S4_OUT="$OUTPUT_ROOT/oa_stage4_outputs"
VIEWER_OUT="$OUTPUT_ROOT/oa_viewer_outputs"
REVIEW_OUT="$OUTPUT_ROOT/oa_qc_review_outputs"

# ---- Helpers --------------------------------------------------------
# Resolve a per-stage config file if --config-dir was supplied AND the
# expected file exists. Returns the literal string "None" otherwise so
# the value can be passed directly to papermill -p.
resolve_config() {
    local stage_name="$1"   # e.g. "04_stage1a"
    if [[ -n "$CONFIG_DIR" ]]; then
        for ext in yaml yml json; do
            local candidate="$CONFIG_DIR/${stage_name}.${ext}"
            if [[ -f "$candidate" ]]; then
                echo "$candidate"
                return
            fi
        done
    fi
    echo "None"
}

run_papermill() {
    local notebook="$1"
    local out_ipynb="$2"
    shift 2
    local -a args=("$@")

    echo "----------------------------------------------------------------------"
    echo "papermill $notebook"
    for a in "${args[@]}"; do echo "    $a"; done
    echo "  -> $out_ipynb"

    if [[ "$DRY_RUN" -eq 1 ]]; then
        return 0
    fi

    papermill "$notebook" "$out_ipynb" "${args[@]}"
}

# Stage-order index, so --start-from can skip earlier stages.
stage_index() {
    case "$1" in
        02) echo 2 ;;
        04) echo 4 ;;
        05) echo 5 ;;
        06) echo 6 ;;
        07) echo 7 ;;
        08) echo 8 ;;
        *) echo "ERROR: --start-from must be 02/04/05/06/07/08, got $1" >&2; exit 2 ;;
    esac
}
START_IDX=$(stage_index "$START_FROM")

# Helper: should we run a given stage?
should_run() {
    local idx="$1"
    [[ "$idx" -ge "$START_IDX" ]]
}

# ---- Run the chain --------------------------------------------------
echo "======================================================================"
echo "OA pipeline run"
echo "  input xlsx  : $INPUT_XLSX"
echo "  output root : $OUTPUT_ROOT"
echo "  sheet       : $SHEET"
echo "  start from  : Stage $START_FROM"
echo "  config dir  : ${CONFIG_DIR:-(none)}"
echo "  parquet     : $( [[ "$NO_PARQUET" == "True" ]] && echo disabled || echo enabled )"
echo "  runs dir    : $RUNS_DIR"
echo "======================================================================"

# ---- Notebook 01 (optional viewer) ---------------------------------
if [[ "$INCLUDE_VIEWER" -eq 1 ]] && should_run 2; then
    CONFIG="$(resolve_config 01_excel_viewer)"
    run_papermill 01_excel_viewer.ipynb "$RUNS_DIR/01_excel_viewer.run.ipynb" \
        -p XLSX_PATH "$INPUT_XLSX" \
        -p OUT_DIR "$VIEWER_OUT" \
        -p SHEET "$SHEET"
fi

# ---- Notebook 02 (QC) ----------------------------------------------
if should_run 2; then
    CONFIG="$(resolve_config 02_ta_ph_qc)"
    run_papermill 02_ta_ph_qc.ipynb "$RUNS_DIR/02_ta_ph_qc.run.ipynb" \
        -p XLSX_PATH "$INPUT_XLSX" \
        -p OUT_DIR "$QC_OUT" \
        -p SHEET "$SHEET" \
        -p CONFIG_PATH "$CONFIG"
fi

# ---- Notebook 03 (optional QC inspection) --------------------------
if [[ "$INCLUDE_REVIEW" -eq 1 ]] && should_run 2; then
    CONFIG="$(resolve_config 03_qc_output_review)"
    run_papermill 03_qc_output_review.ipynb "$RUNS_DIR/03_qc_output_review.run.ipynb" \
        -p OUTPUT_ROOT "$QC_OUT"
fi

# ---- Notebook 04 (Stage 1A) ----------------------------------------
if should_run 4; then
    CONFIG="$(resolve_config 04_stage1a)"
    run_papermill 04_stage1a.ipynb "$RUNS_DIR/04_stage1a.run.ipynb" \
        -p INPUT_CSV "$QC_OUT/sheet_$SHEET/data/derived.csv" \
        -p OUT_DIR "$S1A_OUT" \
        -p CONFIG_PATH "$CONFIG" \
        -p NO_PARQUET "$NO_PARQUET"
fi

# ---- Notebook 05 (Stage 1B) ----------------------------------------
if should_run 5; then
    CONFIG="$(resolve_config 05_stage1b)"
    run_papermill 05_stage1b.ipynb "$RUNS_DIR/05_stage1b.run.ipynb" \
        -p INPUT_CSV "$S1A_OUT/data/staged.csv" \
        -p OUT_DIR "$S1B_OUT" \
        -p CONFIG_PATH "$CONFIG" \
        -p NO_PARQUET "$NO_PARQUET"
fi

# ---- Notebook 06 (Stage 2) -----------------------------------------
if should_run 6; then
    CONFIG="$(resolve_config 06_stage2)"
    run_papermill 06_stage2.ipynb "$RUNS_DIR/06_stage2.run.ipynb" \
        -p INPUT_CSV "$S1B_OUT/data/analysis_ready_samples.csv" \
        -p OUT_DIR "$S2_OUT" \
        -p CONFIG_PATH "$CONFIG" \
        -p NO_PARQUET "$NO_PARQUET"
fi

# ---- Notebook 07 (Stage 3) -----------------------------------------
if should_run 7; then
    CONFIG="$(resolve_config 07_stage3)"
    run_papermill 07_stage3.ipynb "$RUNS_DIR/07_stage3.run.ipynb" \
        -p INPUT_CSV "$S2_OUT/data/enhanced.csv" \
        -p OUT_DIR "$S3_OUT" \
        -p CONFIG_PATH "$CONFIG" \
        -p NO_PARQUET "$NO_PARQUET"
fi

# ---- Notebook 08 (Stage 4) -----------------------------------------
if should_run 8; then
    CONFIG="$(resolve_config 08_stage4)"
    run_papermill 08_stage4.ipynb "$RUNS_DIR/08_stage4.run.ipynb" \
        -p INPUT_CSV "$S3_OUT/data/enhanced.csv" \
        -p OUT_DIR "$S4_OUT" \
        -p CONFIG_PATH "$CONFIG" \
        -p NO_PARQUET "$NO_PARQUET"
fi

echo "======================================================================"
if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "Dry run complete. Re-run without --dry-run to execute."
else
    echo "Pipeline complete."
    echo "  Final deliverable: $S4_OUT/data/analysis_ready.csv"
    echo "  Per-stage reports: $OUTPUT_ROOT/<stage>/reports/report.md"
    echo "  Executed notebooks: $RUNS_DIR/*.run.ipynb"
fi
echo "======================================================================"
