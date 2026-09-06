from __future__ import annotations

import pytest

from quant_advisor_research.contracts import AdvisoryValidationError, _require_number_0_1


def test_require_number_0_1_rejects_nan() -> None:
    with pytest.raises(AdvisoryValidationError, match="finite|between 0 and 1|0 and 1"):
        _require_number_0_1(float("nan"), "score")


def test_require_number_0_1_still_accepts_bounds() -> None:
    _require_number_0_1(0, "score")
    _require_number_0_1(1, "score")
    _require_number_0_1(0.5, "score")
