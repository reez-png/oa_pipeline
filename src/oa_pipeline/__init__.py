"""
oa_pipeline
===========
Ocean acidification pre-processing pipeline.

FIX 10: Added __version__ so outputs can record which pipeline version
produced them, and added re-exports of the most commonly used public API
so notebooks can write `from oa_pipeline import die, load_config, RangePolicy`
instead of importing from each sub-module explicitly.

AUDIT FIX N-1 / N-6: Re-export the two new audit utilities so they are part
of the documented public surface and easy to wire into notebooks:
  - load_crm_certified_values: load certified CRM TA values from the versioned
    configs/crm_certified_values.yaml (replaces the fabricated hardcoded table).
  - assert_ph_scale_consistency: enforce that the accepted-pH-scale lists across
    schema/cruise/regional configs agree, instead of relying on sync comments.
"""

__version__ = "0.2.0"

# Most-used public API re-exported for notebook convenience.
from .common import (
    die,
    utc_stamp,
    load_config,
    write_csv_and_parquet,
    write_manifest,
    build_flag_summary,
    robust_outlier_flags,
)
from .policy import RangePolicy, policy_from_config
from .schema import (
    load_schema_config,
    apply_canonical_schema,
    normalize_ta_units,
    normalize_ph_scale,
    normalize_carbonate_unit,
    assert_ph_scale_consistency,
)
from .qc_ta_ph import (
    load_crm_certified_values,
    CRM_CERTIFIED_VALUES_CONFIG,
)

__all__ = [
    "__version__",
    "die",
    "utc_stamp",
    "load_config",
    "write_csv_and_parquet",
    "write_manifest",
    "build_flag_summary",
    "robust_outlier_flags",
    "RangePolicy",
    "policy_from_config",
    "load_schema_config",
    "apply_canonical_schema",
    "normalize_ta_units",
    "normalize_ph_scale",
    "normalize_carbonate_unit",
    "assert_ph_scale_consistency",
    "load_crm_certified_values",
    "CRM_CERTIFIED_VALUES_CONFIG",
]
