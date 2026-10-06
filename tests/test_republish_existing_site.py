from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import republish_existing_site as republish


FIXTURE = Path(__file__).parent / "fixtures" / "advisory_report_v6.json"
SITE_URL = "https://example.test/advisor"


def _index(report: dict[str, object]) -> bytes:
    as_of = str(report["as_of"])
    cadence = str(report["cadence"])
    return json.dumps(
        {
            "schema_version": 1,
            "reports": [
                {
                    "as_of": as_of,
                    "cadence": cadence,
                    "html": f"{as_of}-{cadence}-model-recommendations.html",
                    "json": f"advisory_report_{as_of}.json",
                }
            ],
        }
    ).encode("utf-8")


def test_republishes_all_validated_reports_and_keeps_source_json_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report_bytes = FIXTURE.read_bytes()
    report = json.loads(report_bytes)
    filename = f"advisory_report_{report['as_of']}.json"
    index_bytes = _index(report)
    requested: list[str] = []

    def read_url(url: str, *, max_bytes: int) -> bytes:
        requested.append(url)
        if url.endswith("/reports_index.json"):
            assert max_bytes == republish.MAX_INDEX_BYTES
            return index_bytes
        assert url == f"{SITE_URL}/{filename}"
        assert max_bytes == republish.MAX_REPORT_BYTES
        return report_bytes

    monkeypatch.setattr(republish, "_read_url", read_url)
    output = tmp_path / "site"

    written = republish.republish_existing_site(site_url=SITE_URL, output_dir=output)

    assert len(requested) == 2
    assert (output / filename).read_bytes() == report_bytes
    assert (output / f"{report['as_of']}-{report['cadence']}-model-recommendations.html").is_file()
    assert (output / "archive.html").is_file()
    assert (output / "feed.xml").is_file()
    assert len(written) == 7


def test_rejects_unsafe_or_unverifiable_archive_before_writing_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report = json.loads(FIXTURE.read_text(encoding="utf-8"))
    malicious_index = json.dumps(
        {
            "schema_version": 1,
            "reports": [
                {
                    "as_of": report["as_of"],
                    "cadence": report["cadence"],
                    "html": f"{report['as_of']}-{report['cadence']}-model-recommendations.html",
                    "json": "../advisory_report_2026-08-22.json",
                }
            ],
        }
    ).encode("utf-8")
    monkeypatch.setattr(republish, "_read_url", lambda *_args, **_kwargs: malicious_index)
    output = tmp_path / "site"

    with pytest.raises(ValueError, match="invalid_published_reports_index"):
        republish.republish_existing_site(site_url=SITE_URL, output_dir=output)

    assert not output.exists()


def test_rejects_report_contract_failure_without_partial_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report = json.loads(FIXTURE.read_text(encoding="utf-8"))
    report["generated_at"] = "not-a-timestamp"
    bad_bytes = json.dumps(report).encode("utf-8")
    index_bytes = _index(report)

    def read_url(url: str, *, max_bytes: int) -> bytes:
        return index_bytes if url.endswith("/reports_index.json") else bad_bytes

    monkeypatch.setattr(republish, "_read_url", read_url)
    output = tmp_path / "site"

    with pytest.raises(ValueError, match="unverified_published_report"):
        republish.republish_existing_site(site_url=SITE_URL, output_dir=output)

    assert not output.exists()
