from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

import quant_advisor_research.preview_bundle as preview_bundle
from quant_advisor_research.advisory_report import build_advisory_report
from quant_advisor_research.preview_bundle import (
    BUNDLE_CONTRACT,
    SOURCE_CONTRACT_VERSION,
    PreviewBundleError,
    build_preview_bundle,
    read_preview_bundle,
)

ROOT = Path(__file__).resolve().parents[1]


def report(*, cadence="daily", as_of="2026-06-20"):
    return build_advisory_report(
        as_of=as_of,
        cadence=cadence,
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
    )


def test_daily_bundle_builds_and_readback_validates(tmp_path):
    output = tmp_path / "preview"
    result = build_preview_bundle(report(), output)

    assert result.bundle_contract == BUNDLE_CONTRACT
    assert sorted(path.name for path in output.iterdir()) == ["manifest.json", "report.html", "report.json"]
    evidence = read_preview_bundle(output)
    assert evidence.report["cadence"] == "daily"
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest == {
        "bundle_contract": BUNDLE_CONTRACT,
        "source": {
            "schema_version": "5",
            "contract_version": SOURCE_CONTRACT_VERSION,
            "cadence": "daily",
            "as_of": "2026-06-20",
            "generated_at": report()["generated_at"],
        },
        "artifacts": {
            "report.json": {
                "name": "report.json",
                "role": "source_report",
                "sha256": hashlib.sha256((output / "report.json").read_bytes()).hexdigest(),
            },
            "report.html": {
                "name": "report.html",
                "role": "escaped_preview",
                "sha256": hashlib.sha256((output / "report.html").read_bytes()).hexdigest(),
            },
        },
    }


@pytest.mark.parametrize("cadence", ["weekly", "monthly"])
def test_non_daily_source_is_rejected_before_output(cadence, tmp_path):
    output = tmp_path / "preview"
    with pytest.raises(PreviewBundleError, match="daily_only"):
        build_preview_bundle(report(cadence=cadence), output)
    assert not output.exists()


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(schema_version="6"),
    lambda value: value.update(contract_version="wrong"),
    lambda value: value.update(generated_at="not-a-datetime"),
])
def test_source_contract_mutations_fail_closed_without_partial_output(mutation, tmp_path):
    value = report()
    mutation(value)
    output = tmp_path / "preview"
    with pytest.raises(PreviewBundleError):
        build_preview_bundle(value, output)
    assert not output.exists()


def test_build_is_deterministic_for_equivalent_mapping_order(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    value = report()
    reordered = {key: value[key] for key in reversed(list(value))}
    build_preview_bundle(value, left)
    build_preview_bundle(reordered, right)
    assert {path.name: path.read_bytes() for path in left.iterdir()} == {
        path.name: path.read_bytes() for path in right.iterdir()
    }


def test_html_escapes_snapshot_and_has_only_fixed_relative_links(tmp_path):
    output = tmp_path / "preview"
    value = report()
    value["source_artifacts"]["political_events"] = "<script>alert('x')</script>"
    build_preview_bundle(value, output)
    html = (output / "report.html").read_text()
    assert "&lt;script&gt;alert(&#x27; x&#x27;)&lt;/script&gt;" not in html
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in html
    assert 'href="report.json"' in html
    assert 'href="manifest.json"' in html
    assert html.count('href="') == 2


@pytest.mark.parametrize("tamper", [
    lambda path: path.joinpath("report.json").write_text(path.joinpath("report.json").read_text().replace('"cadence":"daily"', '"cadence":"weekly"')),
    lambda path: path.joinpath("manifest.json").write_text(path.joinpath("manifest.json").read_text().replace('report.json', 'other.json')),
    lambda path: path.joinpath("report.html").write_text(path.joinpath("report.html").read_text().replace('href="report.json"', 'href="other.json"')),
    lambda path: (path / "unexpected.txt").write_text("x"),
])
def test_readback_tamper_and_extra_file_fail_closed(tamper, tmp_path):
    output = tmp_path / "preview"
    build_preview_bundle(report(), output)
    tamper(output)
    with pytest.raises(PreviewBundleError):
        read_preview_bundle(output)


def test_non_empty_output_fails_without_touching_sentinel(tmp_path):
    output = tmp_path / "preview"
    output.mkdir()
    sentinel = output / "sentinel"
    sentinel.write_text("keep")
    with pytest.raises(PreviewBundleError, match="output_exists"):
        build_preview_bundle(report(), output)
    assert sentinel.read_text() == "keep"


def test_destination_is_not_visible_during_staging_readback(tmp_path, monkeypatch):
    output = tmp_path / "preview"
    observed = []
    original = preview_bundle.read_preview_bundle

    def inspect(path):
        observed.append(Path(path))
        assert not output.exists()
        return original(path)

    monkeypatch.setattr(preview_bundle, "read_preview_bundle", inspect)
    build_preview_bundle(report(), output)
    assert len(observed) == 1
    assert output.is_dir()


def test_concurrent_destination_winner_is_not_overwritten_or_cleaned(tmp_path, monkeypatch):
    output = tmp_path / "preview"
    real_mkdir = preview_bundle.os.mkdir

    def concurrent_winner(path, mode=0o777):
        if Path(path) == output:
            real_mkdir(path, mode)
            (output / "winner").write_text("keep")
            raise FileExistsError(path)
        return real_mkdir(path, mode)

    monkeypatch.setattr(preview_bundle.os, "mkdir", concurrent_winner)
    with pytest.raises(PreviewBundleError, match="output_exists"):
        build_preview_bundle(report(), output)
    assert (output / "winner").read_text() == "keep"
    assert not list(tmp_path.glob(".preview.staging-*"))


def test_relative_output_dir_works_from_current_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    build_preview_bundle(report(), "preview")
    assert {path.name for path in Path("preview").iterdir()} == {"report.json", "report.html", "manifest.json"}


def test_readback_rejects_symlinked_ancestor(tmp_path):
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    output = real_parent / "preview"
    build_preview_bundle(report(), output)
    alias = tmp_path / "alias"
    alias.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(PreviewBundleError, match="readback"):
        read_preview_bundle(alias / "preview")


def test_staging_directory_is_cleaned_when_install_fails(tmp_path, monkeypatch):
    output = tmp_path / "preview"

    def fail_readback(_path):
        raise PreviewBundleError("forced_readback_failure")

    monkeypatch.setattr(preview_bundle, "read_preview_bundle", fail_readback)
    with pytest.raises(PreviewBundleError, match="output_write_failed"):
        build_preview_bundle(report(), output)
    assert not output.exists()
    assert not list(tmp_path.glob(".preview.staging-*"))


def test_builder_rejects_symlink_member_without_touching_external_target(tmp_path, monkeypatch):
    output = tmp_path / "preview"
    external = tmp_path / "external.json"
    external.write_bytes(b"keep")
    original_mkdtemp = preview_bundle.tempfile.mkdtemp

    def inject_symlink(**kwargs):
        staging = original_mkdtemp(**kwargs)
        (Path(staging) / "report.json").symlink_to(external)
        return staging

    monkeypatch.setattr(preview_bundle.tempfile, "mkdtemp", inject_symlink)
    with pytest.raises(PreviewBundleError, match="output_write_failed"):
        build_preview_bundle(report(), output)
    assert external.read_bytes() == b"keep"
    assert not output.exists()


def test_readback_rejects_symlink_member(tmp_path):
    output = tmp_path / "preview"
    build_preview_bundle(report(), output)
    member = output / "report.json"
    original = member.read_bytes()
    member.unlink()
    outside = output.parent / "outside"
    outside.write_bytes(original)
    member.symlink_to(outside)
    with pytest.raises(PreviewBundleError, match="readback"):
        read_preview_bundle(output)


def test_readback_rejects_fifo_member(tmp_path):
    output = tmp_path / "preview"
    build_preview_bundle(report(), output)
    member = output / "report.json"
    member.unlink()
    os.mkfifo(member)
    with pytest.raises(PreviewBundleError, match="readback"):
        read_preview_bundle(output)


def test_readback_rejects_hardlink_alias(tmp_path):
    output = tmp_path / "preview"
    build_preview_bundle(report(), output)
    alias = tmp_path / "alias.json"
    alias.hardlink_to(output / "report.json")
    with pytest.raises(PreviewBundleError, match="readback"):
        read_preview_bundle(output)


def test_destination_symlink_is_rejected_without_following_it(tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    output = tmp_path / "preview"
    output.symlink_to(external, target_is_directory=True)
    with pytest.raises(PreviewBundleError, match="output_exists"):
        build_preview_bundle(report(), output)
    assert not (external / "report.json").exists()


def test_parent_symlink_is_rejected_without_writing_through_alias(tmp_path):
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    alias_parent = tmp_path / "alias"
    alias_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(PreviewBundleError, match="output_parent_invalid"):
        build_preview_bundle(report(), alias_parent / "preview")
    assert not (real_parent / "preview").exists()
