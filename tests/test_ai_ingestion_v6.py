from __future__ import annotations

import datetime as dt
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from quant_advisor_research import advisory_report as advisory_report_module
from quant_advisor_research.advisory_report import build_advisory_report
from quant_advisor_research.contracts import validate_advisory_report


def write_base_inputs(tmp_path: Path) -> tuple[Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    events = tmp_path / "events.csv"
    events.write_text(
        "event_id,event_date,symbol,event_type,direction,confidence,source_url,notes\n",
        encoding="utf-8",
    )
    watchlist = tmp_path / "watchlist.csv"
    watchlist.write_text(
        "symbol,name,bucket,research_status,thesis,source_url\n"
        "BASE,Base Candidate,macro_index,watchlist,Base research context,https://example.invalid/base\n",
        encoding="utf-8",
    )
    return events, watchlist


def valid_v2_signal(*, confidence: float = 0.6) -> dict[str, object]:
    return {
        "schema_version": "2",
        "model_version": "shadow-v2",
        "scoring_version": "rules-v2",
        "as_of": "2026-05-30",
        "generated_at": "2026-05-30T12:00:00Z",
        "mode": "shadow",
        "horizon": "1-3 years",
        "universe": ["AI1"],
        "regime": "neutral",
        "risk_flags": [],
        "candidate_bias": {
            "AI1": {
                "bias": "positive",
                "confidence": confidence,
                "rationale": "Synthetic advisory-only context.",
            }
        },
        "confidence": confidence,
        "evidence": {
            "sources": ["synthetic-source"],
            "summary": "Synthetic advisory-only evidence.",
            "data_gaps": [],
        },
        "expires_at": "2026-06-30",
        "policy": {
            "execution_allowed": False,
            "downstream_use": "Research-only shadow context.",
        },
    }


def build_report(tmp_path: Path, ai_signal: Path | None = None) -> dict[str, object]:
    events, watchlist = write_base_inputs(tmp_path)
    return build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=events,
        political_watchlist_path=watchlist,
        ai_signal_path=ai_signal,
    )


def write_signal(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return path


def replace_nested(payload: dict[str, object], path: tuple[str, ...], value: object) -> None:
    target = payload
    for key in path[:-1]:
        target = target[key]  # type: ignore[assignment]
    target[path[-1]] = value


def test_v2_signal_requires_versioned_model_metadata_and_fails_closed(tmp_path: Path) -> None:
    payload = valid_v2_signal()
    payload.pop("model_version")
    signal = write_signal(tmp_path / "signal.json", payload)

    report = build_report(tmp_path, signal)

    assert "AI1" not in {item["symbol"] for item in report["recommendations"]}
    assert "ai_signal_contract_invalid" in report["summary"]["data_quality_warnings"]
    assert report["source_artifacts"]["ai_signal"] == ""
    assert report["freshness"]["ai_signal"] == {
        "present": False,
        "valid": False,
        "reason": "not_provided",
    }


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema_version",), "3"),
        (("generated_at",), "2026-05-30T12:00:00"),
        (("mode",), "live"),
        (("horizon",), "1-3 months"),
        (("candidate_bias",), []),
        (("confidence",), True),
        (("evidence", "sources"), "not-a-list"),
        (("policy", "execution_allowed"), True),
    ],
)
def test_ai_contract_type_and_policy_violations_are_no_op(
    tmp_path: Path,
    path: tuple[str, ...],
    value: object,
) -> None:
    payload = deepcopy(valid_v2_signal())
    replace_nested(payload, path, value)
    signal = write_signal(tmp_path / "signal.json", payload)

    report = build_report(tmp_path, signal)

    assert "AI1" not in {item["symbol"] for item in report["recommendations"]}
    assert "ai_signal_contract_invalid" in report["summary"]["data_quality_warnings"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("orders", [{"symbol": "AI1"}]),
        ("target_weight", 0.5),
        ("portfolio_allocation_allowed", True),
    ],
)
def test_ai_authority_fields_are_rejected_as_no_op(tmp_path: Path, field: str, value: object) -> None:
    payload = valid_v2_signal()
    payload[field] = value
    signal = write_signal(tmp_path / "signal.json", payload)

    report = build_report(tmp_path, signal)

    assert "AI1" not in {item["symbol"] for item in report["recommendations"]}
    assert "ai_signal_contract_invalid" in report["summary"]["data_quality_warnings"]


def test_ai_live_downstream_policy_is_rejected_as_no_op(tmp_path: Path) -> None:
    payload = valid_v2_signal()
    payload["policy"]["downstream_use"] = "live portfolio allocation"
    signal = write_signal(tmp_path / "signal.json", payload)

    report = build_report(tmp_path, signal)

    assert "AI1" not in {item["symbol"] for item in report["recommendations"]}
    assert "ai_signal_contract_invalid" in report["summary"]["data_quality_warnings"]


def test_malformed_ai_json_is_sanitized_no_op(tmp_path: Path) -> None:
    signal = tmp_path / "signal.json"
    signal.write_text('{"secret": "must-not-leak",', encoding="utf-8")

    report = build_report(tmp_path, signal)

    assert "ai_signal_invalid_json" in report["summary"]["data_quality_warnings"]
    assert "must-not-leak" not in json.dumps(report)
    assert report["summary"]["ai_regime"] == "not_available"


def test_unavailable_ai_signal_is_sanitized_no_op(tmp_path: Path) -> None:
    missing_signal = tmp_path / "missing-signal.json"

    report = build_report(tmp_path, missing_signal)

    assert "ai_signal_unavailable" in report["summary"]["data_quality_warnings"]
    assert report["source_artifacts"]["ai_signal"] == ""
    assert report["freshness"]["ai_signal"] == {
        "present": False,
        "valid": False,
        "reason": "not_provided",
    }
    assert missing_signal.name not in json.dumps(report)


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"as_of": "2026-05-20", "generated_at": "2026-05-20T12:00:00Z"}, "stale_as_of"),
        ({"as_of": "2026-05-31"}, "as_of_in_future"),
        ({"generated_at": "2026-05-31T00:00:00.000001Z"}, "generated_after_reference"),
        (
            {
                "as_of": "2026-05-20",
                "generated_at": "2026-05-20T12:00:00Z",
                "expires_at": "2026-05-29",
            },
            "expired",
        ),
    ],
)
def test_temporally_invalid_ai_signal_is_reported_and_does_not_score(
    tmp_path: Path,
    updates: dict[str, object],
    reason: str,
) -> None:
    payload = valid_v2_signal()
    payload.update(updates)
    signal = write_signal(tmp_path / "signal.json", payload)

    report = build_report(tmp_path, signal)

    assert "AI1" not in {item["symbol"] for item in report["recommendations"]}
    assert report["freshness"]["ai_signal"]["valid"] is False
    assert report["freshness"]["ai_signal"]["reason"] == reason
    assert f"ai_signal_{reason}" in report["summary"]["data_quality_warnings"]


def test_new_builder_emits_v6_time_contract_and_content_bound_digest(tmp_path: Path) -> None:
    first = build_report(tmp_path / "first")
    second = build_report(tmp_path / "second")

    generated_at = dt.datetime.fromisoformat(first["generated_at"].replace("Z", "+00:00"))
    expires_at = dt.datetime.fromisoformat(first["expires_at"].replace("Z", "+00:00"))
    first_events = tmp_path / "first" / "events.csv"
    first_watchlist = tmp_path / "first" / "watchlist.csv"
    input_identities = {
        "political_events": hashlib.sha256(first_events.read_bytes()).hexdigest(),
        "political_watchlist": hashlib.sha256(first_watchlist.read_bytes()).hexdigest(),
        "ai_signal": None,
        "theme_momentum": None,
        "market_confirmation": None,
    }
    expected_digest = hashlib.sha256(
        json.dumps(input_identities, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    assert first["schema_version"] == "6"
    assert first["contract_version"] == "model_recommendations.v6"
    assert first["reference_time"] == "2026-05-31T00:00:00Z"
    assert expires_at == generated_at + dt.timedelta(days=7)
    assert first["freshness"] == {
        "ai_signal": {"present": False, "valid": False, "reason": "not_provided"},
        "theme_momentum": {"present": False, "valid": False, "reason": "not_provided"},
    }
    assert first["input_digest"] == expected_digest
    assert second["input_digest"] == first["input_digest"]
    validate_advisory_report(first)

    first_watchlist.write_text(first_watchlist.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    changed = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=first_events,
        political_watchlist_path=first_watchlist,
    )
    assert changed["input_digest"] != first["input_digest"]


def test_input_digest_binds_the_bytes_consumed_before_source_replacement(tmp_path: Path, monkeypatch) -> None:
    events, watchlist = write_base_inputs(tmp_path)
    signal = write_signal(tmp_path / "signal.json", valid_v2_signal())
    original_signal_bytes = signal.read_bytes()
    original_loader = advisory_report_module.load_ai_signal

    def replacing_loader(path, *args, **kwargs):
        payload = original_loader(path, *args, **kwargs)
        replacement = valid_v2_signal()
        replacement["candidate_bias"]["AI1"]["bias"] = "negative"
        signal.write_text(json.dumps(replacement) + "\n", encoding="utf-8")
        return payload

    monkeypatch.setattr(advisory_report_module, "load_ai_signal", replacing_loader)
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=events,
        political_watchlist_path=watchlist,
        ai_signal_path=signal,
    )
    identities = {
        "political_events": hashlib.sha256(events.read_bytes()).hexdigest(),
        "political_watchlist": hashlib.sha256(watchlist.read_bytes()).hexdigest(),
        "ai_signal": hashlib.sha256(original_signal_bytes).hexdigest(),
        "theme_momentum": None,
        "market_confirmation": None,
    }
    expected_digest = hashlib.sha256(
        json.dumps(identities, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    assert report["input_digest"] == expected_digest
    assert next(item for item in report["recommendations"] if item["symbol"] == "AI1")["ai_context"]["bias"] == "positive"


def test_positive_ai_confidence_is_display_only_for_recommendation_scoring(tmp_path: Path) -> None:
    low_path = write_signal(tmp_path / "low.json", valid_v2_signal(confidence=0.0))
    high_path = write_signal(tmp_path / "high.json", valid_v2_signal(confidence=1.0))
    low = build_report(tmp_path / "low", low_path)
    high = build_report(tmp_path / "high", high_path)

    low_rec = next(item for item in low["recommendations"] if item["symbol"] == "AI1")
    high_rec = next(item for item in high["recommendations"] if item["symbol"] == "AI1")

    assert low_rec["ai_context"]["confidence"] == 0.0
    assert high_rec["ai_context"]["confidence"] == 1.0
    for field in ("evidence_score", "risk_score", "rating", "score", "long_horizon_ai_score"):
        assert low_rec[field] == high_rec[field]
