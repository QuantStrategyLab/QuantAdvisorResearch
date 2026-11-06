from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from quant_advisor_research.site_contract import (
    SCHEMA_DIR,
    SiteBundle,
    SiteContractError,
    project_site_bundle,
    read_site_bundle,
    validate_site_bundle,
    write_site_bundle,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "site"
INPUTS = FIXTURES / "inputs"
GOLDEN_BUNDLE = FIXTURES / "bundle"
RELEASE_ID = "00000000-0000-4000-8000-000000000001"
BUILT_AT = "2026-06-01T00:00:00Z"
EVALUATED_AT = "2026-06-01T00:00:00Z"


def _load_inputs() -> list[dict]:
    return [
        json.loads((INPUTS / name).read_text(encoding="utf-8"))
        for name in (
            "2026-05-30-weekly-v6.json",
            "2026-05-23-weekly-v5.json",
            "2026-05-16-weekly-v6.json",
        )
    ]


def _project(reports: list[dict] | None = None, **overrides) -> SiteBundle:
    options = {
        "built_at": BUILT_AT,
        "evaluated_at": EVALUATED_AT,
        "release_id": RELEASE_ID,
    }
    options.update(overrides)
    return project_site_bundle(_load_inputs() if reports is None else reports, **options)


def _canonical_bytes(document: dict) -> bytes:
    text = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return (text + "\n").encode("utf-8")


def _resign(bundle: SiteBundle, documents: dict[str, dict]) -> SiteBundle:
    manifest = documents["manifest.json"]
    raw: dict[str, bytes] = {}
    files = []
    for path in sorted(documents):
        if path == "manifest.json":
            continue
        raw[path] = _canonical_bytes(documents[path])
        files.append(
            {
                "path": path,
                "kind": "report" if path.startswith("reports/") else path[: -len(".json")],
                "sha256": hashlib.sha256(raw[path]).hexdigest(),
                "bytes": len(raw[path]),
            }
        )
    manifest["data"]["files"] = files
    manifest["data"]["report_count"] = sum(path.startswith("reports/") for path in documents)
    raw["manifest.json"] = _canonical_bytes(manifest)
    return SiteBundle(
        release_id=bundle.release_id,
        built_at=bundle.built_at,
        documents=documents,
        raw=raw,
    )


def _mutated(bundle: SiteBundle) -> tuple[SiteBundle, dict[str, dict]]:
    documents = copy.deepcopy(dict(bundle.documents))
    return bundle, documents


def _minimal_v6(as_of: dt.date) -> dict:
    reference_time = as_of + dt.timedelta(days=1)
    generated_at = as_of + dt.timedelta(days=2)
    expires_at = generated_at + dt.timedelta(days=7)
    stamp = lambda value: value.isoformat() + "T00:00:00Z"
    return {
        "schema_version": "6",
        "contract_version": "model_recommendations.v6",
        "as_of": as_of.isoformat(),
        "reference_time": stamp(reference_time),
        "generated_at": stamp(generated_at),
        "expires_at": stamp(expires_at),
        "input_digest": "d" * 64,
        "mode": "model_recommendations",
        "cadence": "weekly",
        "audience_scope": "non_personalized_model_research",
        "source_artifacts": {
            "political_events": "",
            "political_watchlist": "",
            "ai_signal": "",
            "theme_momentum": "",
            "market_confirmation": "",
        },
        "freshness": {
            "ai_signal": {"present": False, "valid": False, "reason": "not_provided"},
            "theme_momentum": {"present": False, "valid": False, "reason": "not_provided"},
        },
        "summary": {},
        "recommendations": [],
        "policy": {
            "non_personalized_recommendations_allowed": True,
            "execution_allowed": False,
            "portfolio_allocation_allowed": False,
            "personalized_advice_allowed": False,
            "account_specific_advice_allowed": False,
            "downstream_use": "Intelligent advisory research only.",
        },
    }


def test_schema_files_are_six_draft_2020_12_schemas() -> None:
    from jsonschema import Draft202012Validator

    paths = sorted(SCHEMA_DIR.glob("*.schema.json"))
    assert {path.name for path in paths} == {
        "common.schema.json",
        "index.schema.json",
        "archive.schema.json",
        "report.schema.json",
        "feed.schema.json",
        "manifest.schema.json",
    }
    ids = set()
    for path in paths:
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"].startswith("https://quantstrategylab.github.io/QuantAdvisorResearch/schemas/site/1.0.0/")
        ids.add(schema["$id"])
    assert len(ids) == 6


def test_golden_bundle_reads_with_expected_semantics() -> None:
    bundle = read_site_bundle(GOLDEN_BUNDLE)

    manifest = bundle.documents["manifest.json"]
    assert manifest["data"]["report_count"] == 3
    assert len(manifest["data"]["files"]) == 6

    index = bundle.documents["index.json"]["data"]
    assert index["latest"]["id"] == "2026-05-30-weekly"
    assert index["latest_validity"] == "current"
    assert [summary["id"] for summary in index["recent"]] == [
        "2026-05-23-weekly",
        "2026-05-16-weekly",
    ]

    archive = bundle.documents["archive.json"]["data"]["reports"]
    assert [summary["id"] for summary in archive] == [
        "2026-05-30-weekly",
        "2026-05-23-weekly",
        "2026-05-16-weekly",
    ]
    latest, legacy, unavailable = archive
    assert latest["input_status"] == "verified"
    assert latest["final_recommendation_count"] == 2
    assert latest["horizons"]["medium"]["symbols"] == ["MU", "NVDA"]
    assert latest["horizons"]["medium"]["empty_reason"] is None
    assert latest["horizons"]["short"] == {
        "symbols": [],
        "empty_reason": "threshold_unmet",
    }
    assert latest["horizons"]["long"]["symbols"] == ["NVDA"]
    assert latest["legacy_horizon_symbols"]["long"] == ["NVDA"]
    assert latest["top_themes"][0]["zh-CN"] == "HBM / 存储"

    assert legacy["source_schema"] == "5"
    assert legacy["reference_time"] is None
    assert legacy["expires_at"] is None
    assert legacy["final_recommendation_count"] is None
    assert legacy["input_status"] == "unknown"
    assert legacy["horizons"]["medium"]["empty_reason"] == "unknown"

    assert unavailable["source_schema"] == "6"
    assert unavailable["final_recommendation_count"] is None
    assert unavailable["input_status"] == "partial"
    assert unavailable["horizons"]["short"]["empty_reason"] == "input_unavailable"

    report = bundle.documents["reports/2026-05-30-weekly.json"]["data"]
    assert [card["symbol"] for card in report["cards"]["medium"]] == ["MU", "NVDA"]
    assert [(card["symbol"], card["selection_basis"], card["horizon_action"]) for card in report["cards"]["long"]] == [
        ("NVDA", "long_fallback", "watch")
    ]
    assert len(report["lead"]) == 3
    assert "本期结论：" in report["lead"][0]["zh-CN"]
    assert report["disclaimer"]["zh-CN"].startswith("投资有风险。")

    feed = bundle.documents["feed.json"]["data"]
    assert [item["report_id"] for item in feed["items"]] == [
        "2026-05-30-weekly",
        "2026-05-23-weekly",
        "2026-05-16-weekly",
    ]


def test_projection_reproduces_golden_bundle_bytes() -> None:
    bundle = _project()
    validate_site_bundle(bundle)

    on_disk = {
        path.relative_to(GOLDEN_BUNDLE).as_posix(): path.read_bytes()
        for path in GOLDEN_BUNDLE.rglob("*.json")
    }
    assert set(bundle.raw) == set(on_disk)
    for path, expected in on_disk.items():
        assert bundle.raw[path] == expected, path


def test_projection_is_deterministic_and_release_id_is_uuid() -> None:
    first = _project()
    second = _project()
    assert first.raw == second.raw

    generated = _project(release_id=None)
    validate_site_bundle(generated)
    assert generated.release_id != first.release_id
    assert len(generated.release_id) == 36


def test_empty_site_requires_explicit_initialization() -> None:
    with pytest.raises(SiteContractError, match="reports_empty"):
        _project([])

    bundle = _project([], allow_empty=True)
    validate_site_bundle(bundle)
    assert bundle.documents["index.json"]["data"]["latest"] is None
    assert bundle.documents["index.json"]["data"]["latest_validity"] == "none"
    assert bundle.documents["feed.json"]["data"]["items"] == []
    assert bundle.documents["manifest.json"]["data"]["report_count"] == 0
    assert len(bundle.documents["manifest.json"]["data"]["files"]) == 3


def test_latest_selection_covers_expired_legacy_and_expiry_boundary() -> None:
    legacy = _load_inputs()[1]
    bundle = _project([legacy])
    assert bundle.documents["index.json"]["data"]["latest"]["id"] == "2026-05-23-weekly"
    assert bundle.documents["index.json"]["data"]["latest_validity"] == "unknown"

    expired = _load_inputs()[2]
    bundle = _project([expired])
    assert bundle.documents["index.json"]["data"]["latest"]["id"] == "2026-05-16-weekly"
    assert bundle.documents["index.json"]["data"]["latest_validity"] == "expired"

    current = _load_inputs()[0]
    at_boundary = _project([current], evaluated_at="2026-06-07T00:00:00Z")
    assert at_boundary.documents["index.json"]["data"]["latest_validity"] == "current"
    after_boundary = _project([current], evaluated_at="2026-06-07T00:00:01Z")
    assert after_boundary.documents["index.json"]["data"]["latest_validity"] == "expired"


def test_legacy_and_new_horizon_symbols_remain_distinct() -> None:
    report = _load_inputs()[0]
    report["final_decisions"]["horizon_buckets"]["medium"] = ["MU", "DELL"]
    bundle = _project([report])
    validate_site_bundle(bundle)
    summary = bundle.documents["archive.json"]["data"]["reports"][0]
    assert summary["horizons"]["medium"]["symbols"] == ["MU", "NVDA"]
    assert summary["legacy_horizon_symbols"]["medium"] == ["MU", "DELL"]


def test_feed_and_index_bounds_for_large_inventory() -> None:
    reports = [
        _minimal_v6(dt.date(2026, 1, 1) + dt.timedelta(days=index))
        for index in range(21)
    ]
    bundle = _project(reports, evaluated_at="2026-02-01T00:00:00Z")
    validate_site_bundle(bundle)
    assert len(bundle.documents["archive.json"]["data"]["reports"]) == 21
    assert len(bundle.documents["feed.json"]["data"]["items"]) == 20
    assert len(bundle.documents["index.json"]["data"]["recent"]) == 5
    assert bundle.documents["manifest.json"]["data"]["report_count"] == 21
    assert len(bundle.documents["manifest.json"]["data"]["files"]) == 24


def test_schema_rejects_unknown_property_version_and_boolean_count() -> None:
    bundle = read_site_bundle(GOLDEN_BUNDLE)
    _, documents = _mutated(bundle)

    documents["index.json"]["unexpected"] = True
    with pytest.raises(SiteContractError, match="schema_invalid"):
        validate_site_bundle(SiteBundle(bundle.release_id, bundle.built_at, documents, bundle.raw))

    documents = copy.deepcopy(dict(bundle.documents))
    documents["archive.json"]["contract_version"] = "2.0.0"
    with pytest.raises(SiteContractError, match="schema_invalid"):
        validate_site_bundle(SiteBundle(bundle.release_id, bundle.built_at, documents, bundle.raw))

    documents = copy.deepcopy(dict(bundle.documents))
    documents["archive.json"]["data"]["reports"][0]["final_recommendation_count"] = True
    with pytest.raises(SiteContractError, match="schema_invalid"):
        validate_site_bundle(SiteBundle(bundle.release_id, bundle.built_at, documents, bundle.raw))


def test_schema_rejects_empty_reason_incoherence() -> None:
    bundle = read_site_bundle(GOLDEN_BUNDLE)
    _, documents = _mutated(bundle)
    documents["archive.json"]["data"]["reports"][0]["horizons"]["medium"]["empty_reason"] = "unknown"
    with pytest.raises(SiteContractError, match="schema_invalid"):
        validate_site_bundle(SiteBundle(bundle.release_id, bundle.built_at, documents, bundle.raw))

    documents = copy.deepcopy(dict(bundle.documents))
    documents["archive.json"]["data"]["reports"][0]["horizons"]["short"]["empty_reason"] = None
    with pytest.raises(SiteContractError, match="schema_invalid"):
        validate_site_bundle(SiteBundle(bundle.release_id, bundle.built_at, documents, bundle.raw))


def test_manifest_hash_bytes_and_membership_are_enforced() -> None:
    bundle = read_site_bundle(GOLDEN_BUNDLE)

    documents = copy.deepcopy(dict(bundle.documents))
    documents["manifest.json"]["data"]["files"][0]["sha256"] = "0" * 64
    raw = dict(bundle.raw)
    raw["manifest.json"] = _canonical_bytes(documents["manifest.json"])
    with pytest.raises(SiteContractError, match="manifest_sha256_mismatch"):
        validate_site_bundle(SiteBundle(bundle.release_id, bundle.built_at, documents, raw))

    documents = copy.deepcopy(dict(bundle.documents))
    documents["manifest.json"]["data"]["files"][0]["bytes"] += 1
    raw = dict(bundle.raw)
    raw["manifest.json"] = _canonical_bytes(documents["manifest.json"])
    with pytest.raises(SiteContractError, match="manifest_bytes_mismatch"):
        validate_site_bundle(SiteBundle(bundle.release_id, bundle.built_at, documents, raw))

    documents = copy.deepcopy(dict(bundle.documents))
    documents["manifest.json"]["data"]["files"].pop()
    raw = dict(bundle.raw)
    raw["manifest.json"] = _canonical_bytes(documents["manifest.json"])
    with pytest.raises(SiteContractError, match="manifest_membership_mismatch"):
        validate_site_bundle(SiteBundle(bundle.release_id, bundle.built_at, documents, raw))


def test_read_rejects_path_traversal_and_non_finite_payload(tmp_path: Path) -> None:
    shutil.copytree(GOLDEN_BUNDLE, tmp_path / "bundle")
    manifest_path = tmp_path / "bundle" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["data"]["files"][0]["path"] = "../index.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SiteContractError, match="payload_path_invalid"):
        read_site_bundle(tmp_path / "bundle")

    shutil.rmtree(tmp_path / "bundle")
    shutil.copytree(GOLDEN_BUNDLE, tmp_path / "bundle")
    (tmp_path / "bundle" / "index.json").write_text('{"value": NaN}', encoding="utf-8")
    with pytest.raises(SiteContractError, match="payload_unreadable:index.json"):
        read_site_bundle(tmp_path / "bundle")


def test_cross_file_summary_feed_and_validity_mismatches_fail() -> None:
    bundle = read_site_bundle(GOLDEN_BUNDLE)

    _, documents = _mutated(bundle)
    documents["reports/2026-05-30-weekly.json"]["data"]["summary"]["title"]["zh-CN"] = "不同标题"
    with pytest.raises(SiteContractError, match="summary_mismatch"):
        validate_site_bundle(_resign(bundle, documents))

    _, documents = _mutated(bundle)
    documents["feed.json"]["data"]["items"][0]["guid"] = (
        "https://quantstrategylab.github.io/QuantAdvisorResearch/2026-05-16-weekly-model-recommendations.html"
    )
    with pytest.raises(SiteContractError, match="feed_guid_mismatch"):
        validate_site_bundle(_resign(bundle, documents))

    _, documents = _mutated(bundle)
    documents["archive.json"]["data"]["reports"].reverse()
    with pytest.raises(SiteContractError, match="archive_order_not_descending"):
        validate_site_bundle(_resign(bundle, documents))

    _, documents = _mutated(bundle)
    documents["index.json"]["data"]["latest_validity"] = "expired"
    with pytest.raises(SiteContractError, match="index_latest_validity_mismatch"):
        validate_site_bundle(_resign(bundle, documents))


def test_card_rank_symbol_and_selection_basis_are_enforced() -> None:
    bundle = read_site_bundle(GOLDEN_BUNDLE)

    _, documents = _mutated(bundle)
    documents["reports/2026-05-30-weekly.json"]["data"]["cards"]["medium"][1]["rank"] = 3
    with pytest.raises(SiteContractError, match="card_rank_invalid:medium"):
        validate_site_bundle(_resign(bundle, documents))

    _, documents = _mutated(bundle)
    documents["reports/2026-05-30-weekly.json"]["data"]["cards"]["long"] = []
    with pytest.raises(SiteContractError, match="card_symbols_mismatch:long"):
        validate_site_bundle(_resign(bundle, documents))

    _, documents = _mutated(bundle)
    documents["reports/2026-05-30-weekly.json"]["data"]["cards"]["medium"][0]["selection_basis"] = "long_fallback"
    with pytest.raises(SiteContractError, match="long_fallback_outside_long"):
        validate_site_bundle(_resign(bundle, documents))


def test_locale_translation_rules_are_enforced() -> None:
    bundle = read_site_bundle(GOLDEN_BUNDLE)

    _, documents = _mutated(bundle)
    for document in documents.values():
        document["locales"] = ["zh-CN", "en"]
    with pytest.raises(SiteContractError, match="locale_translation_missing"):
        validate_site_bundle(_resign(bundle, documents))

    _, documents = _mutated(bundle)
    documents["archive.json"]["data"]["reports"][0]["title"]["en"] = "Synthetic title"
    with pytest.raises(SiteContractError, match="locale_translation_unapproved"):
        validate_site_bundle(_resign(bundle, documents))


def test_legacy_timestamps_cannot_be_synthesized() -> None:
    bundle = read_site_bundle(GOLDEN_BUNDLE)
    _, documents = _mutated(bundle)
    documents["archive.json"]["data"]["reports"][1]["reference_time"] = "2026-05-24T00:00:00Z"
    with pytest.raises(SiteContractError, match="legacy_timestamp_synthesized"):
        validate_site_bundle(_resign(bundle, documents))


def test_write_and_read_round_trip(tmp_path: Path) -> None:
    bundle = _project()
    written = write_site_bundle(bundle, tmp_path / "data")
    assert {path.name for path in written} >= {"manifest.json", "index.json", "archive.json", "feed.json"}
    reread = read_site_bundle(tmp_path / "data")
    assert reread.raw == bundle.raw
