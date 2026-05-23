import pandas as pd
import pytest

from oa_pipeline.policy import (
    RangePolicy,
    add_range_reason_codes,
    add_stage_range_flags,
    policy_from_config,
)


def test_absent_optional_columns_do_not_create_missing_reason_codes():
    df = pd.DataFrame({"salinity": [35.0]})

    add_stage_range_flags(df, RangePolicy())
    add_range_reason_codes(df)

    assert df.loc[0, "range_reason_codes"] == ""


def test_string_false_is_not_treated_as_true():
    df = pd.DataFrame(
        {
            "flag_sal_out_of_range": ["False"],
            "flag_ph_observed_out_of_range": ["True"],
        }
    )

    add_range_reason_codes(
        df,
        flag_columns=["flag_sal_out_of_range", "flag_ph_observed_out_of_range"],
    )

    assert df.loc[0, "range_reason_codes"] == "ph_observed_out_of_range"


def test_range_policy_rejects_nonfinite_values():
    with pytest.raises(ValueError):
        RangePolicy(sal_min=float("nan"))

    with pytest.raises(ValueError):
        RangePolicy(sal_max=float("inf"))


def test_policy_from_config_uses_stage4_defaults():
    p = policy_from_config({}, stage="stage4")

    assert p.ta_min == 0.0
    assert p.ph_min == 6.0


def test_policy_from_config_rejects_unknown_range_policy_key():
    with pytest.raises(ValueError):
        policy_from_config({"range_policy": {"not_a_real_key": 1}})