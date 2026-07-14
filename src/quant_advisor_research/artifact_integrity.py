from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .contracts import AdvisoryValidationError, validate_advisory_report
from .period_contract import PeriodContractError, canonical_period_identity
from .time_contract import TimeContractError


ARTIFACT_INTEGRITY_VERSION = "validated_report.v1.canonical-json.sha256"
MAX_SNAPSHOT_DEPTH = 64


class ArtifactIntegrityError(ValueError):
    """Stable, sanitized artifact-integrity error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ArtifactIntegrityEvidence:
    """Descriptive digest evidence; it carries no authority or raw report."""

    version: str
    digest: str
    period_key: str
    as_of: str
    cadence: str
    schema_version: str
    contract_version: str | None

    @property
    def artifact_integrity_version(self) -> str:
        return self.version

    @property
    def artifact_integrity_digest(self) -> str:
        return self.digest


def _integrity_error() -> ArtifactIntegrityError:
    return ArtifactIntegrityError("report_integrity_invalid")


def _snapshot_wire(value: object, *, depth: int) -> object:
    if depth > MAX_SNAPSHOT_DEPTH:
        raise _integrity_error()
    if value is None or type(value) is str or type(value) is bool or type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise _integrity_error()
        return value
    if type(value) is list:
        return [_snapshot_wire(item, depth=depth + 1) for item in value]
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        try:
            items = value.items()
            for key, item in items:
                if type(key) is not str or key in result:
                    raise _integrity_error()
                result[key] = _snapshot_wire(item, depth=depth + 1)
        except ArtifactIntegrityError:
            raise
        except Exception:
            raise _integrity_error() from None
        return result
    raise _integrity_error()


def snapshot_json_wire(value: Mapping[str, Any]) -> dict[str, object]:
    """Take one immutable-shape snapshot of a JSON-compatible Mapping."""

    if not isinstance(value, Mapping):
        raise _integrity_error()
    snapshot = _snapshot_wire(value, depth=0)
    if type(snapshot) is not dict:
        raise _integrity_error()
    return snapshot


def _validated_snapshot(report: Mapping[str, Any]) -> dict[str, object]:
    snapshot = snapshot_json_wire(report)
    try:
        validate_advisory_report(snapshot)
    except (
        AdvisoryValidationError,
        TimeContractError,
        PeriodContractError,
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
        UnicodeError,
        RecursionError,
    ):
        raise ArtifactIntegrityError("report_invalid") from None
    return snapshot


def _canonical_bytes(snapshot: dict[str, object]) -> bytes:
    try:
        text = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return text.encode("utf-8", errors="strict")
    except (TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        raise _integrity_error() from None


def canonicalize_validated_report(report: Mapping[str, Any]) -> bytes:
    """Validate one snapshot and return deterministic full-report canonical bytes."""

    return _canonical_bytes(_validated_snapshot(report))


def artifact_integrity_digest(report: Mapping[str, Any]) -> str:
    """Hash the complete validated report snapshot, including provenance metadata."""

    return hashlib.sha256(canonicalize_validated_report(report)).hexdigest()


def make_artifact_integrity_evidence(report: Mapping[str, Any]) -> ArtifactIntegrityEvidence:
    snapshot = _validated_snapshot(report)
    digest = hashlib.sha256(_canonical_bytes(snapshot)).hexdigest()
    try:
        as_of = snapshot["as_of"]
        cadence = snapshot["cadence"]
        schema_version = snapshot["schema_version"]
        contract_version = snapshot.get("contract_version")
        if not all(type(value) is str for value in (as_of, cadence, schema_version)):
            raise _integrity_error()
        if contract_version is not None and type(contract_version) is not str:
            raise _integrity_error()
        period_key = canonical_period_identity(cadence, as_of).key
    except (KeyError, TypeError, ValueError, PeriodContractError):
        raise _integrity_error() from None
    return ArtifactIntegrityEvidence(
        ARTIFACT_INTEGRITY_VERSION,
        digest,
        period_key,
        as_of,
        cadence,
        schema_version,
        contract_version,
    )
