from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import input_digest_for_payloads, write_report_manifest
from .contracts import ALLOWED_CADENCES, validate_advisory_report
from .csv_utils import read_csv_rows, read_csv_rows_bytes
from .time_contract import (
    REPORT_EXPIRY_DAYS,
    ContextFreshness,
    assess_context_freshness,
    contract_version_for_schema,
    normalize_aware_datetime,
    report_time_bounds,
)


EVENT_WEIGHTS = {
    "public_mention": 4,
    "policy_capital": 4,
    "procurement": 4,
    "disclosure_buy": 3,
    "regulatory_action": 3,
    "market_reaction": 1,
}

BUCKET_WEIGHTS = {
    "named_mentioned": 4,
    "policy_capital": 4,
    "disclosed_holding": 2,
    "drone_policy_watchlist": 2,
    "macro_index": 1,
}

CONFIDENCE_WEIGHTS = {
    "high": 3,
    "medium": 2,
    "low": 1,
}

COMPANY_LEVEL_RELATIONSHIP_TYPES = frozenset({"issuer", "direct_beneficiary"})

AI_BIAS_WEIGHTS = {
    "positive": 3,
    "watch": 1,
    "neutral": 0,
    "avoid": -4,
    "negative": -3,
}

AI_LONG_CONTEXT_SCORES = {
    "positive": 0.5,
    "watch": 0.35,
}

AI_SIGNAL_REQUIRED_KEYS = frozenset(
    {
        "schema_version",
        "as_of",
        "generated_at",
        "mode",
        "horizon",
        "universe",
        "regime",
        "risk_flags",
        "candidate_bias",
        "confidence",
        "evidence",
        "expires_at",
        "policy",
    }
)
AI_SIGNAL_ALLOWED_KEYS = AI_SIGNAL_REQUIRED_KEYS | frozenset(
    {
        "model_version",
        "scoring_version",
        "theme_bias",
        "symbol_bias",
        "symbol_theme_exposure",
    }
)
AI_SIGNAL_SCHEMA_VERSIONS = frozenset({"1", "2"})
AI_SIGNAL_REGIMES = frozenset({"risk_on", "risk_off", "neutral", "mixed", "unknown"})
AI_SIGNAL_BIASES = frozenset({"positive", "negative", "neutral", "watch", "avoid"})
AI_SIGNAL_HORIZON = "1-3 years"
AI_BIAS_ALLOWED_KEYS = frozenset({"bias", "confidence", "rationale", "horizon", "risk_flags", "linked_themes"})
AI_EVIDENCE_ALLOWED_KEYS = frozenset({"sources", "summary", "data_gaps"})
AI_POLICY_ALLOWED_KEYS = frozenset({"execution_allowed", "portfolio_allocation_allowed", "downstream_use"})
AI_POLICY_FORBIDDEN_TERMS = frozenset({"live", "allocation", "broker", "execution", "order", "position", "account"})
AI_POLICY_BLOCKING_TERMS = frozenset({"blocked", "not allowed", "do not", "never", "no "})
AI_SIGNAL_MANIFEST_NAME = "latest_signal.manifest.json"
AI_SIGNAL_MANIFEST_PATH = "data/output/latest_signal.manifest.json"
AI_SIGNAL_PATH = "data/output/latest_signal.json"
AI_SIGNAL_PRODUCER_REPOSITORY = "QuantStrategyLab/ResearchSignalContextPipelines"
AI_SIGNAL_PROVENANCE_WARNING = "ai_signal_provenance_untrusted"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
_UNAVAILABLE_INPUT = object()

HORIZON_WINDOWS = {
    "short": "1-10个交易日",
    "medium": "2-12周",
    "long": "1-3年",
    "not_applicable": "不适用",
}
SHORT_PRIMARY_MIN_SCORE_EDGE = 0.05
THEME_MOMENTUM_ARTIFACT_TYPE = "medium_horizon_theme_context"

CADENCE_LABELS_ZH = {
    "daily": "日度",
    "weekly": "周度",
    "monthly": "月度",
}

SECTOR_LABELS_ZH = {
    "technology": "科技",
    "energy": "能源",
    "financials": "金融",
    "healthcare": "医疗",
    "industrials": "工业",
    "consumer": "消费",
    "consumer_discretionary": "可选消费",
    "communication_services": "通信服务",
    "utilities": "公用事业",
}

THEME_LABELS_ZH = {
    "ai_compute": "AI 算力平台",
    "hbm_memory": "HBM / 存储",
    "foundry_semicap": "晶圆代工 / 半导体设备",
    "ai_server_infrastructure": "AI 服务器 / 数据中心硬件",
    "data_center_power": "数据中心电力与冷却",
    "cybersecurity": "企业网络安全",
    "defense_aerospace": "国防与航空航天",
    "energy_security": "能源安全 / 油气",
    "clean_energy_grid": "清洁能源 / 电网",
    "financial_market_infrastructure": "金融与市场基础设施",
    "healthcare_policy": "医疗政策 / 管理式医疗",
    "consumer_platforms": "消费平台 / 广告",
    "industrial_automation": "工业自动化 / 回流制造",
    "crypto_infrastructure": "加密资产基础设施",
    "automobility_ev": "汽车智能化 / EV 转型",
}

COMPANY_PROFILES_ZH = {
    "AMD": {
        "business": "AMD 主要做 CPU、GPU、AI 加速器和数据中心芯片。",
        "prospect": "前景主要来自 AI 加速器放量、数据中心服务器更新，以及与 NVIDIA 之外第二供应商相关的需求。",
    },
    "AVGO": {
        "business": "Broadcom 主要做网络芯片、定制 ASIC、半导体连接方案和企业软件。",
        "prospect": "前景主要来自 AI 数据中心网络、定制加速芯片、云厂商资本开支和软件现金流。",
    },
    "COIN": {
        "business": "Coinbase 是美国主要加密资产交易和托管平台。",
        "prospect": "前景主要取决于数字资产监管清晰度、交易活跃度和机构托管需求。",
    },
    "CVX": {
        "business": "Chevron 是综合油气公司，覆盖上游勘探生产、炼化和天然气业务。",
        "prospect": "前景主要来自能源安全、油气供给约束、现金流和股东回报能力。",
    },
    "DELL": {
        "business": "Dell 主要做企业服务器、存储、PC 和 AI 服务器基础设施。",
        "prospect": "前景主要来自 AI 服务器、企业基础设施更新和数据中心资本开支。",
    },
    "INTC": {
        "business": "Intel 主要做 CPU、数据中心芯片、制造工艺和晶圆代工。",
        "prospect": "前景主要来自美国本土半导体制造、CHIPS Act、代工恢复和 AI PC / 数据中心需求。",
    },
    "MSTR": {
        "business": "Strategy 经营企业软件业务，同时持有大量比特币资产。",
        "prospect": "前景主要取决于比特币价格、资本市场融资能力和数字资产监管环境。",
    },
    "MU": {
        "business": "Micron 主要做 DRAM、NAND 和 HBM 等存储芯片。",
        "prospect": "前景主要来自 AI 服务器对 HBM 和高端 DRAM 的需求，以及存储周期修复。",
    },
    "NEE": {
        "business": "NextEra Energy 是美国大型电力公用事业和可再生能源公司。",
        "prospect": "前景主要来自电网投资、数据中心用电增长、可再生能源和储能项目需求。",
    },
    "TSM": {
        "business": "台积电是全球领先晶圆代工厂，服务 AI、手机、高性能计算和汽车芯片客户。",
        "prospect": "前景主要来自先进制程、AI 芯片代工需求和长期半导体外包趋势。",
    },
    "VRT": {
        "business": "Vertiv 主要做数据中心电源、散热、机柜和关键基础设施设备。",
        "prospect": "前景主要来自 AI 数据中心建设、电力密度提升、液冷和供电基础设施升级。",
    },
    "XOM": {
        "business": "Exxon Mobil 是综合油气公司，覆盖上游生产、炼化、化工和 LNG。",
        "prospect": "前景主要来自能源安全、LNG 需求、油气供给约束和长期现金流。",
    },
}

COMPANY_RISKS_ZH = {
    "AMD": "主要风险是 AI 加速器竞争强、客户订单兑现不及预期、毛利率波动，以及股价快速上涨后的回撤风险。",
    "AVGO": "主要风险是云厂商资本开支节奏放缓、定制芯片订单集中、软件整合不及预期，以及估值对 AI 需求预期较敏感。",
    "COIN": "主要风险是加密资产价格和交易量波动大、监管规则变化、手续费率下行，以及平台合规成本上升。",
    "CVX": "主要风险是油气价格回落、项目资本开支超预期、地缘政治和政策变化，以及能源股周期性回撤。",
    "DELL": "主要风险是 AI 服务器利润率偏低、订单转收入节奏不稳定、企业硬件需求周期波动，以及股价已反映较高增长预期。",
    "INTC": "主要风险是晶圆代工转型执行难度高、资本开支和现金流压力大、先进制程追赶不及预期，以及竞争格局仍然激烈。",
    "MSTR": "主要风险是比特币价格大幅波动、融资环境变化、资产净值溢价收缩，以及监管规则变化。",
    "MU": "主要风险是存储周期反转、HBM 供需和价格不及预期、客户集中度较高，以及强动量后的估值和回撤压力。",
    "NEE": "主要风险是利率上行压制公用事业估值、电网和新能源项目审批延迟、资本开支压力，以及电力需求兑现慢于预期。",
    "TSM": "主要风险是先进制程资本开支高、客户需求周期波动、地缘政治风险，以及 AI 芯片需求预期过高。",
    "VRT": "主要风险是数据中心建设节奏放缓、订单转收入和交付能力不及预期、液冷竞争加剧，以及估值已反映较高成长预期。",
    "XOM": "主要风险是油气价格回落、炼化利润收缩、地缘政治和政策变化，以及能源股周期性回撤。",
}

EXCLUDED_THEME_PICK_SYMBOLS = {
    "DIA",
    "IWM",
    "QQQ",
    "SMH",
    "SOXL",
    "SOXX",
    "SPY",
    "TQQQ",
    "XLE",
    "XLK",
}


@dataclass(frozen=True)
class Event:
    event_id: str
    event_date: dt.date
    symbol: str
    event_type: str
    direction: str
    confidence: str
    source_url: str
    notes: str
    entity_match_type: str = "unverified"
    match_evidence: str = ""
    relationship_type: str = "unverified"


@dataclass(frozen=True)
class WatchlistItem:
    symbol: str
    name: str
    bucket: str
    research_status: str
    thesis: str
    source_url: str


@dataclass(frozen=True)
class MarketConfirmation:
    symbol: str
    as_of: dt.date | None
    return_5d: float
    return_20d: float
    return_63d: float
    relative_return_20d: float
    relative_return_63d: float
    volume_zscore: float
    drawdown_63d: float
    volatility_21d: float
    market_score: float | None = None
    data_source: str = ""
    price_observation_count: int = 0


class AISignalValidationError(ValueError):
    """Raised with a sanitized reason when AI context is not consumable."""


def parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value.strip())


def utc_now_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_iso(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _ai_contract_invalid() -> None:
    raise AISignalValidationError("ai_signal_contract_invalid")


def _valid_ai_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_ai_string_list(value: Any, *, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(_valid_ai_string(item) for item in value)
    )


def _valid_ai_confidence(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1


def _validate_ai_bias_value(value: Any) -> None:
    if isinstance(value, str):
        bias = value
    elif isinstance(value, Mapping):
        if set(value) - AI_BIAS_ALLOWED_KEYS:
            _ai_contract_invalid()
        bias = value.get("bias")
        if not _valid_ai_string(bias):
            _ai_contract_invalid()
        if "confidence" in value and not _valid_ai_confidence(value["confidence"]):
            _ai_contract_invalid()
        if any(key in value and not _valid_ai_string(value[key]) for key in ("rationale", "horizon")):
            _ai_contract_invalid()
        if any(
            key in value and not _valid_ai_string_list(value[key], allow_empty=True)
            for key in ("risk_flags", "linked_themes")
        ):
            _ai_contract_invalid()
    else:
        _ai_contract_invalid()
    if not _valid_ai_string(bias) or bias not in AI_SIGNAL_BIASES:
        _ai_contract_invalid()


def _validate_ai_bias_mapping(value: Any) -> None:
    if not isinstance(value, Mapping):
        _ai_contract_invalid()
    for key, bias in value.items():
        if not _valid_ai_string(key):
            _ai_contract_invalid()
        _validate_ai_bias_value(bias)


def validate_ai_signal(payload: Any) -> None:
    if not isinstance(payload, Mapping) or not AI_SIGNAL_REQUIRED_KEYS <= set(payload):
        _ai_contract_invalid()
    if set(payload) - AI_SIGNAL_ALLOWED_KEYS:
        _ai_contract_invalid()
    schema_version = payload["schema_version"]
    if not _valid_ai_string(schema_version) or schema_version not in AI_SIGNAL_SCHEMA_VERSIONS:
        _ai_contract_invalid()
    if schema_version == "2" and any(
        not _valid_ai_string(payload.get(key)) for key in ("model_version", "scoring_version")
    ):
        _ai_contract_invalid()
    try:
        if not _valid_ai_string(payload["as_of"]):
            _ai_contract_invalid()
        dt.date.fromisoformat(payload["as_of"])
        if not _valid_ai_string(payload["generated_at"]):
            _ai_contract_invalid()
        normalize_aware_datetime(payload["generated_at"])
        if not _valid_ai_string(payload["expires_at"]):
            _ai_contract_invalid()
        dt.date.fromisoformat(payload["expires_at"])
    except (TypeError, ValueError):
        _ai_contract_invalid()
    if payload["mode"] != "shadow" or payload["horizon"] != AI_SIGNAL_HORIZON:
        _ai_contract_invalid()
    if not _valid_ai_string(payload["regime"]) or payload["regime"] not in AI_SIGNAL_REGIMES:
        _ai_contract_invalid()
    if not _valid_ai_string_list(payload["universe"]):
        _ai_contract_invalid()
    if not _valid_ai_string_list(payload["risk_flags"], allow_empty=True):
        _ai_contract_invalid()
    _validate_ai_bias_mapping(payload["candidate_bias"])
    for key in ("theme_bias", "symbol_bias"):
        if key in payload:
            _validate_ai_bias_mapping(payload[key])
    if "symbol_theme_exposure" in payload:
        exposure = payload["symbol_theme_exposure"]
        if not isinstance(exposure, Mapping):
            _ai_contract_invalid()
        for symbol, theme_ids in exposure.items():
            if not _valid_ai_string(symbol) or not _valid_ai_string_list(theme_ids):
                _ai_contract_invalid()
    if not _valid_ai_confidence(payload["confidence"]):
        _ai_contract_invalid()
    evidence = payload["evidence"]
    if not isinstance(evidence, Mapping) or set(evidence) - AI_EVIDENCE_ALLOWED_KEYS:
        _ai_contract_invalid()
    if not _valid_ai_string_list(evidence.get("sources")):
        _ai_contract_invalid()
    if not _valid_ai_string(evidence.get("summary")):
        _ai_contract_invalid()
    if not _valid_ai_string_list(evidence.get("data_gaps", []), allow_empty=True):
        _ai_contract_invalid()
    policy = payload["policy"]
    if not isinstance(policy, Mapping) or set(policy) - AI_POLICY_ALLOWED_KEYS:
        _ai_contract_invalid()
    downstream_use = policy.get("downstream_use")
    if (
        policy.get("execution_allowed") is not False
        or policy.get("portfolio_allocation_allowed", False) is not False
        or not _valid_ai_string(downstream_use)
    ):
        _ai_contract_invalid()
    normalized_use = str(downstream_use).lower()
    if not any(term in normalized_use for term in ("research", "advisory", "shadow")):
        _ai_contract_invalid()
    if "live" in normalized_use or (
        any(term in normalized_use for term in AI_POLICY_FORBIDDEN_TERMS)
        and not any(term in normalized_use for term in AI_POLICY_BLOCKING_TERMS)
    ):
        _ai_contract_invalid()


def freshness_record(result: ContextFreshness, payload: Mapping[str, Any] | None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "present": result.present,
        "valid": result.valid,
        "reason": result.reason,
    }
    if result.present and payload is not None:
        for key in ("as_of", "generated_at", "expires_at"):
            if key in payload:
                record[key] = payload[key]
        if result.reason == "legacy_expiry_compatibility":
            record["compatibility_warning"] = "missing_expires_at"
    return record


def load_events(path: str | Path, as_of: dt.date, *, source_bytes: bytes | None = None) -> list[Event]:
    events: list[Event] = []
    rows = read_csv_rows_bytes(source_bytes) if source_bytes is not None else read_csv_rows(path)
    for row in rows:
        event_date = parse_date(row["event_date"])
        if event_date > as_of:
            continue
        events.append(
            Event(
                event_id=row["event_id"],
                event_date=event_date,
                symbol=row["symbol"].upper(),
                event_type=row["event_type"],
                direction=row.get("direction", ""),
                confidence=row.get("confidence", ""),
                source_url=row.get("source_url", ""),
                notes=row.get("notes", ""),
                entity_match_type=row.get("entity_match_type", "unverified"),
                match_evidence=row.get("match_evidence", ""),
                relationship_type=row.get("relationship_type", "unverified"),
            )
        )
    return events


def event_has_company_entity_acceptance(event: Event) -> bool:
    return (
        event.relationship_type in COMPANY_LEVEL_RELATIONSHIP_TYPES
        and bool(event.match_evidence.strip())
    )



def dedupe_events_for_scoring(events: list[Event]) -> list[Event]:
    """Keep one row per news URL (or event_id) before score accumulation."""

    seen: set[str] = set()
    unique: list[Event] = []
    for event in events:
        key = event.source_url.strip() or event.event_id
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return unique

def accepted_entity_events(events: list[Event]) -> list[Event]:
    return [event for event in events if event_has_company_entity_acceptance(event)]


def entity_evidence_details(events: list[Event]) -> list[dict[str, Any]]:
    return [
        {
            "event_id": event.event_id,
            "entity_match_type": event.entity_match_type,
            "match_evidence": event.match_evidence,
            "relationship_type": event.relationship_type,
            "accepted": event_has_company_entity_acceptance(event),
        }
        for event in events
    ]


def load_watchlist(path: str | Path, *, source_bytes: bytes | None = None) -> dict[str, WatchlistItem]:
    items: dict[str, WatchlistItem] = {}
    rows = read_csv_rows_bytes(source_bytes) if source_bytes is not None else read_csv_rows(path)
    for row in rows:
        symbol = row["symbol"].upper()
        items[symbol] = WatchlistItem(
            symbol=symbol,
            name=row.get("name", ""),
            bucket=row.get("bucket", ""),
            research_status=row.get("research_status") or row.get("article_status", ""),
            thesis=row.get("thesis", ""),
            source_url=row.get("source_url", ""),
        )
    return items


def load_ai_signal(path: str | Path | None, *, source_bytes: bytes | None = None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        payload = json.loads(source_bytes.decode("utf-8")) if source_bytes is not None else json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError):
        raise AISignalValidationError("ai_signal_invalid_json") from None
    except OSError:
        raise AISignalValidationError("ai_signal_unavailable") from None
    validate_ai_signal(payload)
    return payload


def _ai_provenance_untrusted() -> None:
    raise AISignalValidationError(AI_SIGNAL_PROVENANCE_WARNING)


def _git_output(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        _ai_provenance_untrusted()
    return result.stdout


def _repository_from_remote(remote: str) -> str:
    value = remote.strip().removesuffix("/").removesuffix(".git")
    for prefix in ("https://github.com/", "git@github.com:", "ssh://git@github.com/"):
        if value.startswith(prefix):
            return value.removeprefix(prefix)
    return ""


def load_trusted_ai_signal(
    path: str | Path | None,
    *,
    source_bytes: bytes | None = None,
) -> dict[str, Any] | None:
    if path is None:
        return None
    signal_path = Path(path).resolve()
    signal_bytes = source_bytes
    if signal_bytes is None:
        try:
            signal_bytes = signal_path.read_bytes()
        except OSError:
            raise AISignalValidationError("ai_signal_unavailable") from None
    payload = load_ai_signal(signal_path, source_bytes=signal_bytes)
    if payload is None:
        return None
    manifest_path = signal_path.with_name(AI_SIGNAL_MANIFEST_NAME)
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _ai_provenance_untrusted()
    if not isinstance(manifest, Mapping):
        _ai_provenance_untrusted()
    required_keys = {
        "manifest_type",
        "schema_version",
        "artifact",
        "as_of",
        "generated_at",
        "expires_at",
        "mode",
        "producer",
        "input_digest",
        "policy",
    }
    artifact = manifest.get("artifact")
    producer = manifest.get("producer")
    policy = manifest.get("policy")
    if (
        set(manifest) != required_keys
        or manifest.get("manifest_type") != "research_signal_context"
        or manifest.get("schema_version") != 2
        or not isinstance(artifact, Mapping)
        or set(artifact) != {"path", "sha256"}
        or artifact.get("path") != AI_SIGNAL_PATH
        or not isinstance(artifact.get("sha256"), str)
        or SHA256_PATTERN.fullmatch(artifact["sha256"]) is None
        or artifact["sha256"] != hashlib.sha256(signal_bytes).hexdigest()
        or not isinstance(producer, Mapping)
        or set(producer) != {"repository", "commit_sha"}
        or producer.get("repository") != AI_SIGNAL_PRODUCER_REPOSITORY
        or not isinstance(producer.get("commit_sha"), str)
        or GIT_SHA_PATTERN.fullmatch(producer["commit_sha"]) is None
        or not isinstance(manifest.get("input_digest"), str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", manifest["input_digest"]) is None
        or not isinstance(policy, Mapping)
        or set(policy) != {"execution_allowed"}
        or policy.get("execution_allowed") is not False
        or any(manifest.get(key) != payload.get(key) for key in ("as_of", "generated_at", "expires_at", "mode"))
    ):
        _ai_provenance_untrusted()

    try:
        repo = Path(_git_output(signal_path.parent, "rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve()
        signal_relative = signal_path.relative_to(repo).as_posix()
        manifest_relative = manifest_path.resolve().relative_to(repo).as_posix()
        head = _git_output(repo, "rev-parse", "HEAD").decode("ascii").strip()
        remote = _git_output(repo, "remote", "get-url", "origin").decode("utf-8").strip()
    except (UnicodeError, ValueError):
        _ai_provenance_untrusted()
    if (
        signal_relative != AI_SIGNAL_PATH
        or manifest_relative != AI_SIGNAL_MANIFEST_PATH
        or GIT_SHA_PATTERN.fullmatch(head) is None
        or _repository_from_remote(remote) != AI_SIGNAL_PRODUCER_REPOSITORY
        or _git_output(repo, "show", f"{head}:{signal_relative}") != signal_bytes
        or _git_output(repo, "show", f"{head}:{manifest_relative}") != manifest_bytes
    ):
        _ai_provenance_untrusted()
    return payload



def load_theme_momentum(path: str | Path | None, *, source_bytes: bytes | None = None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = json.loads(source_bytes.decode("utf-8")) if source_bytes is not None else json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("mode") != "theme_momentum_snapshot":
        raise ValueError("Theme momentum input must remain mode=theme_momentum_snapshot.")
    if payload.get("policy", {}).get("execution_allowed") is not False:
        raise ValueError("Theme momentum input must not allow execution.")
    return payload


def summarize_theme_momentum(payload: dict[str, Any] | None, *, max_themes: int = 5) -> dict[str, Any]:
    if not payload:
        return {"available": False, "top_themes": [], "data_quality": {}}
    top_themes: list[dict[str, Any]] = []
    for theme in list(payload.get("theme_ranks", []))[:max_themes]:
        if not isinstance(theme, dict):
            continue
        top_symbols = []
        for item in list(theme.get("top_symbols", []))[:5]:
            if isinstance(item, dict) and item.get("symbol"):
                top_symbols.append(str(item["symbol"]).upper())
        top_themes.append(
            {
                "rank": theme.get("rank"),
                "theme_id": theme.get("theme_id", ""),
                "theme_name": theme.get("theme_name", ""),
                "sector": theme.get("sector", ""),
                "momentum_score": theme.get("momentum_score"),
                "breadth_3m": theme.get("breadth_3m"),
                "top_symbols": top_symbols,
            }
        )
    return {
        "available": True,
        "as_of": payload.get("as_of", ""),
        "artifact_type": payload.get("artifact_type", THEME_MOMENTUM_ARTIFACT_TYPE),
        "horizon": payload.get("horizon", "medium"),
        "horizon_window": payload.get("horizon_window", "2-12 weeks"),
        "horizon_window_label": payload.get("horizon_window_label", HORIZON_WINDOWS["medium"]),
        "taxonomy_version": payload.get("taxonomy_version", ""),
        "top_themes": top_themes,
        "data_quality": payload.get("data_quality", {}),
        "policy": {
            "execution_allowed": False,
            "theme_rank_is_research_context_only": True,
            "direct_short_term_recommendation_allowed": False,
        },
    }


def as_float(value: Any, *, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def optional_date(value: Any) -> dt.date | None:
    text = str(value or "").strip()
    if not text:
        return None
    return parse_date(text)


def load_market_confirmation(
    path: str | Path | None,
    as_of: dt.date,
    *,
    source_bytes: bytes | None = None,
) -> dict[str, MarketConfirmation]:
    if path is None:
        return {}
    confirmations: dict[str, MarketConfirmation] = {}
    rows = read_csv_rows_bytes(source_bytes) if source_bytes is not None else read_csv_rows(path)
    for row in rows:
        symbol = str(row.get("symbol", "")).upper().strip()
        if not symbol:
            continue
        row_as_of = optional_date(row.get("as_of"))
        if row_as_of and row_as_of > as_of:
            continue
        current = confirmations.get(symbol)
        if current and current.as_of and row_as_of and row_as_of < current.as_of:
            continue
        confirmations[symbol] = MarketConfirmation(
            symbol=symbol,
            as_of=row_as_of,
            return_5d=as_float(row.get("return_5d")),
            return_20d=as_float(row.get("return_20d")),
            return_63d=as_float(row.get("return_63d")),
            relative_return_20d=as_float(row.get("relative_return_20d")),
            relative_return_63d=as_float(row.get("relative_return_63d")),
            volume_zscore=as_float(row.get("volume_zscore")),
            drawdown_63d=as_float(row.get("drawdown_63d")),
            volatility_21d=as_float(row.get("volatility_21d")),
            market_score=as_float(row.get("market_score")) if str(row.get("market_score", "")).strip() else None,
            data_source=str(row.get("data_source", "")),
            price_observation_count=int(as_float(row.get("price_observation_count"))),
        )
    return confirmations


def display_number(value: Any, *, digits: int = 2) -> str:
    if value in {None, ""}:
        return "无"
    return f"{as_float(value):.{digits}f}"


def display_percent(value: Any, *, digits: int = 1) -> str:
    if value in {None, ""}:
        return "无"
    return f"{as_float(value) * 100:+.{digits}f}%"


def sector_label(value: Any) -> str:
    text = str(value or "").strip()
    return SECTOR_LABELS_ZH.get(text, text or "未分类")


def theme_label(theme_id: Any, theme_name: Any = "") -> str:
    theme_key = str(theme_id or "").strip()
    fallback = str(theme_name or "").strip()
    return THEME_LABELS_ZH.get(theme_key, fallback or theme_key or "未分类主题")


def event_evidence_label(confidence: Any) -> str:
    labels = {
        "high": "已有高置信来源事件",
        "medium": "已有中等置信来源事件",
        "mixed": "已有混合置信来源事件",
        "low": "仅低置信来源事件，需先核验",
        "unknown": "事件来源置信度待核验",
        "no_event": "暂无明确事件催化",
    }
    return labels.get(str(confidence or "").strip(), "暂无明确事件催化")


def company_profile(symbol: Any, name: Any = "") -> dict[str, str]:
    symbol_text = str(symbol or "").upper()
    profile = COMPANY_PROFILES_ZH.get(symbol_text)
    if profile:
        return profile
    display_name = str(name or symbol_text).strip() or symbol_text
    return {
        "business": f"{display_name}（{symbol_text}）为当前观察股票池标的。",
        "prospect": "推荐理由需要结合行业需求、公司财报、估值和价格趋势继续复核。",
    }


def company_risk_summary(symbol: Any) -> str:
    symbol_text = str(symbol or "").upper()
    return COMPANY_RISKS_ZH.get(
        symbol_text,
        "主要风险是行业需求不及预期、估值对增长假设较敏感、业绩兑现延后，以及股价波动带来的回撤。",
    )


def normalize_ai_mapping(mapping: Any) -> dict[str, Any]:
    if not isinstance(mapping, dict):
        return {}
    return {str(key).upper(): value for key, value in mapping.items()}


def bias_value(value: Any) -> str:
    raw_value = value.get("bias") if isinstance(value, dict) else value
    return str(raw_value or "").strip().lower()


def bias_confidence(value: Any) -> float | None:
    if isinstance(value, dict) and "confidence" in value:
        return clamp(as_float(value.get("confidence")), 0, 1)
    return None


def aggregate_theme_bias(values: list[str]) -> str | None:
    if not values:
        return None
    if "avoid" in values:
        return "avoid"
    if "negative" in values:
        return "negative"
    if "positive" in values:
        return "positive"
    if "watch" in values:
        return "watch"
    if "neutral" in values:
        return "neutral"
    return None


def resolve_ai_bias(symbol: str, ai_signal: dict[str, Any] | None) -> tuple[str | None, list[str], float | None]:
    if not ai_signal:
        return None, [], None
    normalized_symbol = symbol.upper()
    explicit_bias: dict[str, Any] = {}
    for key in ("candidate_bias", "symbol_bias"):
        explicit_bias.update(normalize_ai_mapping(ai_signal.get(key) or {}))
    if normalized_symbol in explicit_bias:
        raw_value = explicit_bias[normalized_symbol]
        return bias_value(raw_value), [], bias_confidence(raw_value)

    theme_bias = {str(theme): value for theme, value in dict(ai_signal.get("theme_bias") or {}).items()}
    raw_exposure = normalize_ai_mapping(ai_signal.get("symbol_theme_exposure") or {})
    theme_ids = raw_exposure.get(normalized_symbol, [])
    if isinstance(theme_ids, str):
        theme_ids = [theme_ids]
    if not isinstance(theme_ids, list):
        return None, [], None
    matched_values = [theme_bias[theme_id] for theme_id in theme_ids if theme_id in theme_bias]
    matched_biases = [bias_value(value) for value in matched_values]
    matched_confidences = [bias_confidence(value) for value in matched_values]
    confidence_values = [value for value in matched_confidences if value is not None]
    confidence = max(confidence_values) if confidence_values else None
    matched_theme_ids = [theme_id for theme_id in theme_ids if theme_id in theme_bias]
    return aggregate_theme_bias(matched_biases), matched_theme_ids, confidence


def freshness_bonus(event_date: dt.date, as_of: dt.date) -> int:
    age_days = (as_of - event_date).days
    if age_days <= 7:
        return 2
    if age_days <= 30:
        return 1
    return 0


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def strategy_style(item: WatchlistItem | None, events: list[Event], ai_bias: str | None) -> str:
    event_types = {event.event_type for event in events}
    bucket = item.bucket if item else ""
    if event_types & {"policy_capital", "procurement", "regulatory_action", "public_mention", "disclosure_buy"}:
        return "event_driven"
    if bucket == "macro_index" or ai_bias in {"positive", "negative"}:
        return "macro_context" if ai_bias in {"negative", "avoid"} else "long_horizon_growth"
    if bucket in {"disclosed_holding", "named_mentioned"}:
        return "value_quality"
    return "mixed_research"


def horizon_fit(style: str, rating: str) -> tuple[str, list[str], str, str]:
    if rating in {"verify_source", "defer", "monitor"}:
        return "not_applicable", ["not_applicable"], "不适用", "该项不是当前推荐，仅用于来源核验、风险暂缓或背景跟踪。"
    if style == "event_driven":
        return "medium", ["short", "medium"], "中线", "事件驱动主周期为2-12周；1-10个交易日只适合观察催化反应，波动和反转风险更高。"
    if style in {"long_horizon_growth", "value_quality"}:
        return "long", ["medium", "long"], "长线", "主周期为1-3年，更适合用基本面、产业趋势和事件持续性验证；超过3年需要年度复盘确认逻辑仍成立。"
    if style == "macro_context":
        return "medium", ["medium"], "中线", "主周期为2-12周，宏观和政策背景需要结合市场环境复核。"
    return "medium", ["medium"], "中线", "默认按2-12周中线研究处理，等待更多证据后再调整周期判断。"


def rating_label(rating: str) -> str:
    labels = {
        "recommend": "重点推荐",
        "watch": "观察",
        "verify_source": "先核验来源",
        "defer": "暂缓",
        "monitor": "背景跟踪",
    }
    return labels[rating]


def source_confidence(events: list[Event]) -> tuple[str, str]:
    if not events:
        return "no_event", "无事件"
    levels = {event.confidence for event in events if event.confidence}
    if not levels:
        return "unknown", "未知"
    if levels == {"high"}:
        return "high", "高"
    if levels <= {"high", "medium"}:
        return "medium", "中"
    if levels == {"low"}:
        return "low", "低"
    return "mixed", "混合"


def recommendation_tier(rating: str, score: float, confidence: str) -> tuple[str, str]:
    if rating == "recommend" and score >= 0.75 and confidence in {"high", "medium"}:
        return "tier_1", "一级推荐"
    if rating == "recommend":
        return "tier_2", "二级推荐"
    if rating == "watch":
        return "watchlist", "观察名单"
    if rating == "verify_source":
        return "source_check", "来源核验"
    if rating == "defer":
        return "defer", "暂缓"
    return "monitor", "背景跟踪"


def build_theme_first_candidates(
    theme_momentum: dict[str, Any] | None,
    recommendations: list[dict[str, Any]],
    *,
    max_candidates: int = 8,
    max_themes: int = 5,
) -> list[dict[str, Any]]:
    if not theme_momentum:
        return []

    rec_by_symbol = {str(rec.get("symbol", "")).upper(): rec for rec in recommendations}
    by_symbol: dict[str, dict[str, Any]] = {}
    for theme in list(theme_momentum.get("theme_ranks", []))[:max_themes]:
        if not isinstance(theme, dict):
            continue
        theme_rank = int(as_float(theme.get("rank"), default=999))
        theme_id = str(theme.get("theme_id", ""))
        theme_name = str(theme.get("theme_name", ""))
        theme_sector = str(theme.get("sector", ""))
        theme_score = round(as_float(theme.get("momentum_score")), 6)
        theme_breadth = round(as_float(theme.get("breadth_3m")), 6)
        for item in theme.get("top_symbols", []):
            if not isinstance(item, dict) or not item.get("symbol"):
                continue
            symbol = str(item["symbol"]).upper()
            if symbol in EXCLUDED_THEME_PICK_SYMBOLS:
                continue
            symbol_score = round(as_float(item.get("momentum_score")), 6)
            candidate = by_symbol.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "name": rec_by_symbol.get(symbol, {}).get("name", symbol),
                    "candidate_type": "theme_first",
                    "symbol_momentum_score": symbol_score,
                    "return_3m": item.get("return_3m"),
                    "return_6_1m": item.get("return_6_1m"),
                    "return_12_1m": item.get("return_12_1m"),
                    "best_theme_rank": theme_rank,
                    "primary_theme_id": theme_id,
                    "primary_theme_name": theme_name,
                    "primary_theme_sector": theme_sector,
                    "primary_theme_score": theme_score,
                    "primary_theme_breadth_3m": theme_breadth,
                    "theme_ids": [],
                    "themes": [],
                },
            )
            if symbol_score > as_float(candidate.get("symbol_momentum_score")):
                candidate["symbol_momentum_score"] = symbol_score
                candidate["return_3m"] = item.get("return_3m")
                candidate["return_6_1m"] = item.get("return_6_1m")
                candidate["return_12_1m"] = item.get("return_12_1m")
            if theme_rank < int(candidate.get("best_theme_rank", 999)):
                candidate["best_theme_rank"] = theme_rank
                candidate["primary_theme_id"] = theme_id
                candidate["primary_theme_name"] = theme_name
                candidate["primary_theme_sector"] = theme_sector
                candidate["primary_theme_score"] = theme_score
                candidate["primary_theme_breadth_3m"] = theme_breadth
            if theme_id and theme_id not in candidate["theme_ids"]:
                candidate["theme_ids"].append(theme_id)
                candidate["themes"].append(
                    {
                        "theme_id": theme_id,
                        "theme_name": theme_name,
                        "sector": theme_sector,
                        "rank": theme_rank,
                        "momentum_score": theme_score,
                        "breadth_3m": theme_breadth,
                    }
                )

    candidates = list(by_symbol.values())
    candidates.sort(
        key=lambda item: (
            -as_float(item.get("symbol_momentum_score")),
            int(item.get("best_theme_rank", 999)),
            str(item.get("symbol", "")),
        )
    )

    result: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates[:max_candidates], start=1):
        symbol = str(candidate["symbol"])
        rec = rec_by_symbol.get(symbol)
        advisor_status = "主题候选"
        source_confidence = str(rec.get("source_confidence", "no_event")) if rec else "no_event"
        source_confirmation = event_evidence_label(source_confidence)
        if rec:
            if rec.get("recommendation_tier") != "monitor":
                advisor_status = rec.get("recommendation_tier_label") or rec.get("rating_label") or advisor_status
        theme_ids = candidate.get("theme_ids", [])
        theme_name_by_id = {
            str(theme.get("theme_id", "")): str(theme.get("theme_name", ""))
            for theme in candidate.get("themes", [])
            if isinstance(theme, dict)
        }
        theme_labels = [theme_label(theme_id, theme_name_by_id.get(str(theme_id), "")) for theme_id in theme_ids]
        primary_theme_label = theme_label(candidate.get("primary_theme_id"), candidate.get("primary_theme_name"))
        reasons = [
            "主题和个股动量靠前，适合放入本期主题优先候选池。",
            (
                f"主主题 #{candidate.get('best_theme_rank')} {primary_theme_label} "
                f"主题分数={candidate.get('primary_theme_score')}，3个月广度={candidate.get('primary_theme_breadth_3m')}。"
            ),
            f"个股动量分数={candidate.get('symbol_momentum_score')}。",
        ]
        if len(theme_labels) > 1:
            reasons.append(f"同时暴露于多个强主题：{', '.join(theme_labels)}。")
        industry_background = (
            f"{sector_label(candidate.get('primary_theme_sector'))} / "
            f"{primary_theme_label}"
        )
        recommendation_summary = (
            f"属于{industry_background}，主主题排名 #{candidate.get('best_theme_rank')}；"
            f"个股动量 {display_number(candidate.get('symbol_momentum_score'))}，"
            f"近3个月 {display_percent(candidate.get('return_3m'))}。"
        )
        if len(theme_labels) > 1:
            recommendation_summary += f" 同时覆盖 {', '.join(theme_labels[:3])} 等主题。"
        risk_summary = "需复核估值、财报、回撤和流动性；当前暂无明确事件催化。"
        if source_confidence in {"high", "medium", "mixed"}:
            risk_summary = "已有来源事件，但仍需复核估值、财报、回撤和流动性。"
        elif source_confidence == "low":
            risk_summary = "事件来源置信度偏低，需先核验来源，再评估是否升级。"
        risk_notes = [
            "该候选来自主题和价格动量排序，不代表个性化建议或下单信号。",
            risk_summary,
        ]
        if rec and rec.get("risk_notes"):
            risk_notes.append(str(rec["risk_notes"][0]))
        result.append(
            {
                **candidate,
                "rank": index,
                "advisor_status": advisor_status,
                "source_confirmation": source_confirmation,
                "industry_background": industry_background,
                "recommendation_summary": recommendation_summary,
                "risk_summary": risk_summary,
                "reasons": dedupe(reasons),
                "risk_notes": dedupe(risk_notes),
            }
        )
    return result


def build_recommendation(
    symbol: str,
    item: WatchlistItem | None,
    events: list[Event],
    ai_signal: dict[str, Any] | None,
    as_of: dt.date,
) -> dict[str, Any]:
    accepted_events = dedupe_events_for_scoring(accepted_entity_events(events))
    rejected_events = [event for event in events if event not in accepted_events]
    ai_bias, ai_bias_source_themes, ai_bias_confidence = resolve_ai_bias(symbol, ai_signal)
    ai_confidence = (
        ai_bias_confidence
        if ai_bias_confidence is not None
        else float(ai_signal.get("confidence", 0.0))
        if ai_signal
        else 0.0
    )
    ai_regime = ai_signal.get("regime") if ai_signal else "unknown"

    evidence_score = BUCKET_WEIGHTS.get(item.bucket, 0) if item else 0
    risk_score = 0
    evidence_refs: list[str] = []
    risks: list[str] = []
    review_checklist: list[str] = []

    if item and item.source_url:
        evidence_refs.append(item.source_url)

    low_confidence_count = 0
    for event in accepted_events:
        evidence_score += EVENT_WEIGHTS.get(event.event_type, 0)
        evidence_score += CONFIDENCE_WEIGHTS.get(event.confidence, 0)
        evidence_score += freshness_bonus(event.event_date, as_of)
        if event.source_url:
            evidence_refs.append(event.source_url)
        if event.confidence == "low":
            low_confidence_count += 1
        if event.event_type == "market_reaction":
            risk_score += 1

    if ai_bias:
        evidence_score += AI_BIAS_WEIGHTS.get(ai_bias, 0)
        if ai_bias in {"avoid", "negative"}:
            risk_score += 4

    risk_flags = list(ai_signal.get("risk_flags", [])) if ai_signal else []
    if any("volatility" in flag or "high_vol" in flag for flag in risk_flags):
        risk_score += 2
    if ai_regime == "risk_off":
        risk_score += 3
    elif ai_regime == "mixed":
        risk_score += 1

    if low_confidence_count:
        risk_score += low_confidence_count * 2
        risks.append("事件证据包含低置信来源行，需要用官方来源复核。")
        review_checklist.append("对照官方公告、披露文件、讲话或公司材料复核事件日期和来源链接。")

    if rejected_events:
        risks.append("部分事件缺少明确的发行方/直接受益实体证据，未用于公司级评分。")
        review_checklist.append("补充实体匹配文本和 issuer/direct_beneficiary 关系后再评估公司级结论。")

    if ai_signal:
        evidence_refs.extend(ai_signal.get("evidence", {}).get("sources", []))
        data_gaps = ai_signal.get("evidence", {}).get("data_gaps", [])
        if data_gaps:
            risks.append("AI 长周期背景仍有未解决的数据缺口。")
            review_checklist.append("升级推荐前先复核 AI 长周期背景中的数据缺口。")

    if ai_bias in {"avoid", "negative"}:
        rating = "defer"
    elif low_confidence_count and not any(event.confidence in {"medium", "high"} for event in accepted_events):
        rating = "verify_source"
    elif evidence_score >= 12 and risk_score <= 7:
        rating = "recommend"
    elif evidence_score >= 5:
        rating = "watch"
    else:
        rating = "monitor"

    style = strategy_style(item, accepted_events, ai_bias)
    score = round(clamp((evidence_score - risk_score + 8) / 24, 0.05, 0.85), 2)
    primary_horizon, suitable_horizons, primary_horizon_label, horizon_note = horizon_fit(style, rating)
    primary_horizon_window = HORIZON_WINDOWS[primary_horizon]
    suitable_horizon_windows = {horizon: HORIZON_WINDOWS[horizon] for horizon in suitable_horizons}
    confidence, confidence_label = source_confidence(accepted_events)
    tier, tier_label = recommendation_tier(rating, score, confidence)
    source_score = normalize_source_score(
        {"source_confidence": confidence, "evidence_score": evidence_score}
    )

    reasons: list[str] = []
    if item and item.thesis:
        reasons.append(item.thesis)
    if accepted_events:
        event_names = ", ".join(sorted({event.event_type for event in accepted_events}))
        reasons.append(f"观察到事件证据：{event_names}。")
    if ai_bias:
        if ai_bias_source_themes:
            reasons.append(
                f"AI 长周期主题偏向为 {ai_bias}，市场状态={ai_regime}；主题={', '.join(ai_bias_source_themes)}。"
            )
        else:
            reasons.append(f"AI 长周期偏向为 {ai_bias}，市场状态={ai_regime}。")
    if not reasons:
        reasons.append("尚无足够强的时点证据，暂时只作为研究背景。")

    if not risks:
        risks.append("如果缺少最新价格、估值、来源和流动性检查，推荐结论可能失效。")
    review_checklist.extend(
        [
            "检查最新价格走势、财报日、估值和行业新闻。",
            "单独讨论策略前，记录来源质量和模型边界。",
        ]
    )

    long_horizon_ai_score = AI_LONG_CONTEXT_SCORES.get(ai_bias or "", 0.0)

    return {
        "symbol": symbol,
        "name": item.name if item else symbol,
        "rating": rating,
        "rating_label": rating_label(rating),
        "recommendation_tier": tier,
        "recommendation_tier_label": tier_label,
        "primary_horizon": primary_horizon,
        "primary_horizon_label": primary_horizon_label,
        "primary_horizon_window": primary_horizon_window,
        "horizon_note": horizon_note,
        "suitable_horizons": suitable_horizons,
        "suitable_horizon_windows": suitable_horizon_windows,
        "strategy_style": style,
        "score": score,
        "evidence_score": int(evidence_score),
        "source_score": source_score,
        "risk_score": int(risk_score),
        "source_confidence": confidence,
        "source_confidence_label": confidence_label,
        "reasons": dedupe(reasons),
        "risk_notes": dedupe(risks),
        "evidence_summary": " ".join(reasons),
        "evidence_refs": dedupe(evidence_refs),
        "review_checklist": dedupe(review_checklist),
        "entity_evidence": entity_evidence_details(events),
        "ai_context": {
            "source": "latest_signal" if ai_signal else "",
            "horizon": "long" if ai_signal else "",
            "horizon_window": HORIZON_WINDOWS["long"] if ai_signal else "",
            "bias": ai_bias or "",
            "confidence": round(ai_confidence, 3),
            "theme_ids": ai_bias_source_themes,
        },
        "long_horizon_ai_score": long_horizon_ai_score,
    }


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def source_mode_for_paths(*paths: str | Path | None) -> tuple[str, list[str]]:
    text = " ".join(str(path or "") for path in paths)
    warnings: list[str] = []
    if "/examples/" in text or text.startswith("examples/") or " example" in text:
        warnings.append("Input artifacts include example fixture paths; do not treat this report as live recommendations.")
    return ("fixture", warnings) if warnings else ("operator_supplied", warnings)


def normalize_source_score(rec: dict[str, Any] | None) -> float:
    if not rec:
        return 0.0
    confidence_scores = {
        "high": 1.0,
        "medium": 0.75,
        "mixed": 0.55,
        "low": 0.25,
        "unknown": 0.1,
        "no_event": 0.0,
    }
    if str(rec.get("source_confidence", "")) == "no_event":
        return 0.0
    evidence_component = clamp(as_float(rec.get("evidence_score")) / 18, 0, 1)
    confidence_component = confidence_scores.get(str(rec.get("source_confidence", "")), 0.0)
    blended = evidence_component * 0.65 + confidence_component * 0.35
    return round(blended, 3)


def theme_symbol_context(theme_momentum: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not theme_momentum:
        return {}
    theme_ranks = [theme for theme in theme_momentum.get("theme_ranks", []) if isinstance(theme, dict)]
    total_themes = max(len(theme_ranks), 1)
    contexts: dict[str, dict[str, Any]] = {}
    for theme in theme_ranks:
        theme_id = str(theme.get("theme_id", ""))
        theme_name = str(theme.get("theme_name", ""))
        rank = int(as_float(theme.get("rank"), default=total_themes))
        rank_score = clamp((total_themes - min(rank, total_themes) + 1) / total_themes, 0, 1)
        theme_score = clamp(as_float(theme.get("momentum_score")) / 2, 0, 1)
        ai_signal_score = round(rank_score * 0.65 + theme_score * 0.35, 3)
        for item in theme.get("top_symbols", []):
            if not isinstance(item, dict) or not item.get("symbol"):
                continue
            symbol = str(item["symbol"]).upper()
            if symbol in EXCLUDED_THEME_PICK_SYMBOLS:
                continue
            symbol_momentum_score = round(as_float(item.get("momentum_score")), 6)
            momentum_score = round(clamp(symbol_momentum_score / 1.5, 0, 1), 3)
            return_3m = item.get("return_3m")
            current = contexts.setdefault(
                symbol,
                {
                    "theme_ids": [],
                    "theme_labels": [],
                    "primary_theme_id": theme_id,
                    "primary_theme_label": theme_label(theme_id, theme_name),
                    "best_theme_rank": rank,
                    "ai_signal_score": ai_signal_score,
                    "medium_context_score": ai_signal_score,
                    "symbol_momentum_score": symbol_momentum_score,
                    "momentum_score": momentum_score,
                    "return_3m": return_3m,
                },
            )
            if theme_id and theme_id not in current["theme_ids"]:
                current["theme_ids"].append(theme_id)
                current["theme_labels"].append(theme_label(theme_id, theme_name))
            if rank < int(current.get("best_theme_rank", total_themes + 1)):
                current["primary_theme_id"] = theme_id
                current["primary_theme_label"] = theme_label(theme_id, theme_name)
                current["best_theme_rank"] = rank
            if ai_signal_score > as_float(current.get("ai_signal_score")):
                current["ai_signal_score"] = ai_signal_score
                current["medium_context_score"] = ai_signal_score
            if momentum_score > as_float(current.get("momentum_score")):
                current["symbol_momentum_score"] = symbol_momentum_score
                current["momentum_score"] = momentum_score
                current["return_3m"] = return_3m
    return contexts


def market_confirmation_score(market: MarketConfirmation | None) -> float | None:
    if market is None:
        return None
    if market.data_source == "theme_momentum_fallback":
        return None
    if market.market_score is not None:
        return round(clamp(market.market_score, 0, 1), 3)
    relative_20d = clamp(market.relative_return_20d / 0.20, -1, 1)
    relative_63d = clamp(market.relative_return_63d / 0.35, -1, 1)
    absolute_20d = clamp(market.return_20d / 0.20, -1, 1)
    absolute_63d = clamp(market.return_63d / 0.35, -1, 1)
    volume = clamp(market.volume_zscore / 3, 0, 1)
    drawdown_penalty = clamp(abs(min(market.drawdown_63d, 0)) / 0.30, 0, 1)
    volatility_penalty = clamp((market.volatility_21d - 0.35) / 0.45, 0, 1)
    score = (
        0.50
        + relative_20d * 0.20
        + relative_63d * 0.16
        + absolute_20d * 0.08
        + absolute_63d * 0.08
        + volume * 0.10
        - drawdown_penalty * 0.07
        - volatility_penalty * 0.06
    )
    return round(clamp(score, 0, 1), 3)


def horizon_score_components(
    rec: dict[str, Any] | None,
    theme: dict[str, Any],
    market: MarketConfirmation | None,
) -> dict[str, float | None]:
    source_score = normalize_source_score(rec)
    momentum_score = as_float(theme.get("momentum_score"))
    medium_context_score = as_float(theme.get("medium_context_score", theme.get("ai_signal_score")))
    long_context_score = as_float(rec.get("long_horizon_ai_score")) if rec else 0.0
    market_score = market_confirmation_score(market)
    return {
        "source": source_score,
        "momentum": momentum_score,
        "medium_context": medium_context_score,
        "long_context": long_context_score,
        "market_confirmation": market_score,
    }


def blend_optional_market(base_score: float, market_score: float | None, *, market_weight: float) -> float:
    if market_score is None:
        return base_score
    return round(base_score * (1 - market_weight) + market_score * market_weight, 3)


def build_horizon_scores(
    rec: dict[str, Any] | None,
    theme: dict[str, Any],
    market: MarketConfirmation | None,
) -> dict[str, dict[str, Any]]:
    components = horizon_score_components(rec, theme, market)
    source_score = as_float(components["source"])
    momentum_score = as_float(components["momentum"])
    medium_context_score = as_float(components["medium_context"])
    long_context_score = as_float(components["long_context"])
    market_score = components["market_confirmation"]

    short_base = round(
        source_score * 0.25
        + momentum_score * 0.30
        + (as_float(market_score) if market_score is not None else 0.0) * 0.45,
        3,
    )
    if market_score is None:
        short_base = round(source_score, 3)
    medium_base = round(source_score * 0.15 + momentum_score * 0.40 + medium_context_score * 0.45, 3)
    long_base = round(long_context_score * 0.60 + medium_context_score * 0.20 + source_score * 0.20, 3)
    long_score = blend_optional_market(long_base, market_score, market_weight=0.10)

    scores = {
        "short": {
            "score": short_base,
            "drivers": [
                driver
                for driver, score in (
                    ("source_events", source_score),
                    ("theme_momentum_snapshot", momentum_score),
                )
                if score >= 0.35
            ],
        },
        "medium": {
            "score": blend_optional_market(medium_base, market_score, market_weight=0.15),
            "drivers": [
                driver
                for driver, score in (
                    ("theme_momentum_snapshot", max(momentum_score, medium_context_score)),
                    ("source_events", source_score),
                )
                if score >= 0.35
            ],
        },
        "long": {
            "score": long_score,
            "drivers": [
                driver
                for driver, score in (
                    ("latest_signal", long_context_score),
                    ("theme_context", medium_context_score),
                    ("source_events", source_score),
                )
                if score >= 0.35
            ],
        },
    }
    if market_score is not None and market_score >= 0.35:
        scores["short"]["drivers"].append("market_confirmation")
        scores["medium"]["drivers"].append("market_confirmation")
    for item in scores.values():
        item["components"] = {
            key: round(value, 3) if isinstance(value, float) else value for key, value in components.items()
        }
        item["drivers"] = dedupe(item["drivers"])
    return scores


def selection_trace_for(
    symbol: str,
    rec: dict[str, Any] | None,
    theme: dict[str, Any],
    horizon_scores: dict[str, dict[str, Any]],
    action: str,
) -> list[str]:
    trace: list[str] = []
    if rec:
        trace.append("candidate_source=watchlist_or_source_events")
    if theme:
        trace.append("candidate_source=theme_momentum_snapshot")
    if not trace:
        trace.append("candidate_source=unknown")
    trace.extend(
        [
            f"short_score={display_number(horizon_scores['short']['score'])}",
            f"medium_score={display_number(horizon_scores['medium']['score'])}",
            f"long_score={display_number(horizon_scores['long']['score'])}",
            f"final_action={action}",
            f"symbol={symbol}",
        ]
    )
    return trace


def horizon_action_for(
    horizon: str,
    *,
    score: float,
    source_score: float,
    momentum_score: float,
    medium_context_score: float,
    long_context_score: float,
    market_score: float | None,
) -> str:
    """Return the horizon-specific action using deliberately different gates.

    Short horizon is market-confirmation led; medium horizon is theme/momentum led;
    long horizon is context led. Policy/news evidence can improve confidence, but
    is not required for medium-horizon recommendations.
    """
    market_value = as_float(market_score) if market_score is not None else 0.0
    if horizon == "short":
        if market_score is None:
            return "skip"
        if score >= 0.60 and market_value >= 0.55 and momentum_score >= 0.35 and (
            source_score >= 0.35 or market_value >= 0.70
        ):
            return "recommend"
        if score >= 0.45 and market_value >= 0.45 and (source_score >= 0.35 or momentum_score >= 0.35):
            return "watch"
        return "skip"
    if horizon == "medium":
        if score >= 0.52 and momentum_score >= 0.35 and medium_context_score >= 0.35:
            return "recommend"
        if score >= 0.38 and (momentum_score >= 0.35 or medium_context_score >= 0.35 or source_score >= 0.35):
            return "watch"
        return "skip"
    if horizon == "long":
        if score >= 0.62 and long_context_score >= 0.55 and (medium_context_score >= 0.35 or source_score >= 0.35):
            return "recommend"
        if score >= 0.45 and long_context_score >= 0.35:
            return "watch"
        return "skip"
    return "skip"


def horizon_actions_for(
    horizon_scores: dict[str, dict[str, Any]],
) -> dict[str, str]:
    components = horizon_scores["medium"]["components"]
    source_score = as_float(components.get("source"))
    momentum_score = as_float(components.get("momentum"))
    medium_context_score = as_float(components.get("medium_context"))
    long_context_score = as_float(components.get("long_context"))
    market_score = components.get("market_confirmation")
    return {
        horizon: horizon_action_for(
            horizon,
            score=as_float(horizon_scores[horizon]["score"]),
            source_score=source_score,
            momentum_score=momentum_score,
            medium_context_score=medium_context_score,
            long_context_score=long_context_score,
            market_score=market_score,
        )
        for horizon in ("short", "medium", "long")
    }


def primary_horizon_from_actions(
    horizon_scores: dict[str, dict[str, Any]],
    horizon_actions: dict[str, str],
) -> tuple[str, str]:
    for target_action in ("recommend", "watch"):
        eligible = [horizon for horizon, action in horizon_actions.items() if action == target_action]
        if not eligible:
            continue

        if "short" in eligible and "medium" in eligible:
            short_score = as_float(horizon_scores["short"]["score"])
            medium_score = as_float(horizon_scores["medium"]["score"])
            if short_score < medium_score + SHORT_PRIMARY_MIN_SCORE_EDGE:
                eligible = [horizon for horizon in eligible if horizon != "short"]

        eligible.sort(key=lambda horizon: (-as_float(horizon_scores[horizon]["score"]), horizon))
        return eligible[0], target_action
    return "medium", "skip"


def final_action_label(action: str) -> str:
    return {
        "recommend": "最终推荐",
        "watch": "观察名单",
    }.get(action, "跳过")


def supporting_context_for(
    rec: dict[str, Any] | None,
    *,
    source_score: float,
    momentum_score: float,
    medium_context_score: float,
    long_context_score: float,
    market_score: float | None = None,
) -> dict[str, list[str]]:
    context = {"short": [], "medium": [], "long": []}
    if source_score >= 0.35 and rec:
        context["short"].append("source_events")
    if market_score is not None and market_score >= 0.35:
        context["short"].append("market_confirmation")
    if momentum_score >= 0.35 or medium_context_score >= 0.35:
        context["medium"].append("theme_momentum_snapshot")
    if market_score is not None and market_score >= 0.35:
        context["medium"].append("market_confirmation")
    if long_context_score >= 0.35 and rec:
        context["long"].append("latest_signal")
    return context


def build_final_decisions(
    recommendations: list[dict[str, Any]],
    theme_momentum: dict[str, Any] | None,
    market_confirmations: dict[str, MarketConfirmation] | None = None,
    *,
    max_recommendations: int = 5,
    max_watchlist: int = 8,
) -> dict[str, Any]:
    rec_by_symbol = {str(rec.get("symbol", "")).upper(): rec for rec in recommendations}
    theme_context = theme_symbol_context(theme_momentum)
    market_confirmations = market_confirmations or {}
    symbols = sorted(set(rec_by_symbol) | set(theme_context))
    picks: list[dict[str, Any]] = []

    for symbol in symbols:
        rec = rec_by_symbol.get(symbol)
        theme = theme_context.get(symbol, {})
        market = market_confirmations.get(symbol)
        horizon_scores = build_horizon_scores(rec, theme, market)
        score_components = horizon_scores["medium"]["components"]
        source_score = as_float(score_components.get("source"))
        momentum_score = as_float(score_components.get("momentum"))
        medium_context_score = as_float(score_components.get("medium_context"))
        long_context_score = as_float(score_components.get("long_context"))
        market_score = score_components.get("market_confirmation")
        horizon_actions = horizon_actions_for(horizon_scores)
        selected_horizon, action = primary_horizon_from_actions(horizon_scores, horizon_actions)
        if action == "skip":
            continue
        combined_score = round(as_float(horizon_scores[selected_horizon]["score"]), 3)
        name = rec.get("name", symbol) if rec else symbol
        profile = company_profile(symbol, name)
        reasons: list[str] = []
        if source_score >= 0.35 and rec:
            reasons.append(
                f"政策/新闻：{rec.get('source_confidence_label')}置信来源，证据分数={rec.get('evidence_score')}。"
            )
        if momentum_score >= 0.35:
            reasons.append(
                f"动量：个股动量分数={display_number(theme.get('symbol_momentum_score'))}，近3个月={display_percent(theme.get('return_3m'))}。"
            )
        if medium_context_score >= 0.35:
            labels = ", ".join(theme.get("theme_labels", [])[:3]) or str(theme.get("primary_theme_label", ""))
            reasons.append(f"中线主题上下文：{labels}。")
        if market_score is not None and as_float(market_score) >= 0.35:
            reasons.append(f"市场确认：相对强度、近期走势和成交量确认分数={display_number(market_score)}。")
        if long_context_score >= 0.35 and rec:
            bias = rec.get("ai_context", {}).get("bias", "")
            reasons.append(f"长线AI背景：{bias or '已读取'}。")
        if not reasons:
            reasons.append("当前进入观察名单，但多源证据仍需继续补强。")
        if selected_horizon in {"short", "medium", "long"}:
            primary_horizon = selected_horizon
            primary_horizon_label = {"short": "短线", "medium": "中线", "long": "长线"}[selected_horizon]
            primary_horizon_window = HORIZON_WINDOWS[selected_horizon]
        elif rec and rec.get("primary_horizon") != "not_applicable":
            primary_horizon = rec.get("primary_horizon", "long")
            primary_horizon_label = rec.get("primary_horizon_label", "长线")
            primary_horizon_window = rec.get("primary_horizon_window", HORIZON_WINDOWS["long"])
        elif momentum_score >= 0.35:
            primary_horizon = "medium"
            primary_horizon_label = "中线"
            primary_horizon_window = HORIZON_WINDOWS["medium"]
        else:
            primary_horizon = "long"
            primary_horizon_label = "长线"
            primary_horizon_window = HORIZON_WINDOWS["long"]
        picks.append(
            {
                "symbol": symbol,
                "name": name,
                "action": action,
                "action_label": final_action_label(action),
                "primary_horizon": primary_horizon,
                "primary_horizon_label": primary_horizon_label,
                "primary_horizon_window": primary_horizon_window,
                "combined_score": combined_score,
                "source_score": round(source_score, 3),
                "momentum_score": round(momentum_score, 3),
                "ai_signal_score": round(medium_context_score, 3),
                "medium_context_score": round(medium_context_score, 3),
                "long_context_score": round(long_context_score, 3),
                "supporting_context": supporting_context_for(
                    rec,
                    source_score=source_score,
                    momentum_score=momentum_score,
                    medium_context_score=medium_context_score,
                    long_context_score=long_context_score,
                    market_score=as_float(market_score) if market_score is not None else None,
                ),
                "horizon_scores": horizon_scores,
                "horizon_actions": horizon_actions,
                "selection_trace": selection_trace_for(symbol, rec, theme, horizon_scores, action),
                "business_summary": profile["business"],
                "prospect_summary": profile["prospect"],
                "why_selected": dedupe(reasons),
                "risk_summary": company_risk_summary(symbol),
            }
        )

    picks.sort(
        key=lambda item: (
            0 if item["action"] == "recommend" else 1,
            -as_float(item.get("combined_score")),
            str(item.get("symbol", "")),
        )
    )
    recommendation_candidates = [item for item in picks if item["action"] == "recommend"]
    recommendations_out = recommendation_candidates[:max_recommendations]
    recommendation_symbols = {item["symbol"] for item in recommendations_out}
    overflow_recommendations = [
        item for item in recommendation_candidates if item["symbol"] not in recommendation_symbols
    ]
    watchlist_out = [
        item
        for item in picks
        if item["action"] == "watch"
    ][:max_watchlist]
    horizon_buckets = {
        horizon: [item["symbol"] for item in recommendations_out if item.get("primary_horizon") == horizon]
        for horizon in ("short", "medium", "long")
    }
    ranked_by_horizon = {
        horizon: sorted(
            picks,
            key=lambda candidate: (
                -as_float(candidate.get("horizon_scores", {}).get(horizon, {}).get("score")),
                str(candidate.get("symbol", "")),
            ),
        )
        for horizon in ("short", "medium", "long")
    }
    horizon_rankings = {
        horizon: [
            {
                "symbol": item["symbol"],
                "score": item["horizon_scores"][horizon]["score"],
                "action": item["horizon_actions"][horizon],
            }
            for item in ranked_by_horizon[horizon][:max_recommendations]
        ]
        for horizon in ("short", "medium", "long")
    }
    horizon_action_buckets = {
        horizon: {
            action: [
                item["symbol"]
                for item in ranked_by_horizon[horizon]
                if item["horizon_actions"].get(horizon) == action
            ][:max_recommendations]
            for action in ("recommend", "watch")
        }
        for horizon in ("short", "medium", "long")
    }
    return {
        "method": "Final recommendation blend for model scoring.",
        "recommendations": recommendations_out,
        "watchlist": watchlist_out,
        "overflow_recommendations": overflow_recommendations,
        "horizon_buckets": horizon_buckets,
        "horizon_rankings": horizon_rankings,
        "horizon_action_buckets": horizon_action_buckets,
        "position_policy": "No target shares, position size, portfolio weight, or account-specific allocation is provided.",
    }


def long_context_symbols_from_decisions(final_decisions: dict[str, Any]) -> list[str]:
    symbols: list[str] = []
    action_buckets = final_decisions.get("horizon_action_buckets", {})
    long_buckets = action_buckets.get("long", {}) if isinstance(action_buckets, dict) else {}
    if isinstance(long_buckets, dict):
        for action in ("recommend", "watch"):
            for symbol in long_buckets.get(action, []):
                symbol_text = str(symbol).upper()
                if symbol_text and symbol_text not in symbols:
                    symbols.append(symbol_text)
    if symbols:
        return symbols

    for section in ("recommendations", "watchlist"):
        for item in final_decisions.get(section, []):
            if not isinstance(item, dict):
                continue
            symbol_text = str(item.get("symbol", "")).upper()
            action = str(item.get("horizon_actions", {}).get("long", ""))
            has_long_context = action in {"recommend", "watch"} or as_float(item.get("long_context_score")) >= 0.35
            if symbol_text and has_long_context:
                if symbol_text not in symbols:
                    symbols.append(symbol_text)
    return symbols


def infer_long_context_missing_reason(ai_signal: dict[str, Any] | None) -> str:
    if not ai_signal:
        return "ai_signal_not_available"
    horizon_text = str(ai_signal.get("horizon", "")).strip()
    if horizon_text not in {HORIZON_WINDOWS["long"], "1-3 years"}:
        return "latest_signal_horizon_not_long"
    if not ai_signal.get("symbol_bias") and not ai_signal.get("theme_bias"):
        return "latest_signal_lacks_symbol_or_theme_bias"
    if not ai_signal.get("symbol_bias") and not ai_signal.get("symbol_theme_exposure"):
        return "latest_signal_lacks_symbol_theme_exposure"
    return "current_candidates_do_not_meet_long_context_gate"


def _snapshot_input(path: str | Path | None, *, fail_on_unavailable: bool) -> bytes | object | None:
    if path is None:
        return None
    try:
        return Path(path).read_bytes()
    except OSError:
        if fail_on_unavailable:
            raise
        return _UNAVAILABLE_INPUT


def build_advisory_report(
    *,
    as_of: str,
    cadence: str,
    political_events_path: str | Path,
    political_watchlist_path: str | Path,
    ai_signal_path: str | Path | None = None,
    theme_momentum_path: str | Path | None = None,
    market_confirmation_path: str | Path | None = None,
    max_candidates: int = 12,
) -> dict[str, Any]:
    if cadence not in ALLOWED_CADENCES:
        raise ValueError(f"cadence must be one of: {', '.join(sorted(ALLOWED_CADENCES))}")
    as_of_date = parse_date(as_of)
    report_bounds = report_time_bounds(as_of_date, utc_now_iso())
    input_payloads = {
        "political_events": _snapshot_input(political_events_path, fail_on_unavailable=True),
        "political_watchlist": _snapshot_input(political_watchlist_path, fail_on_unavailable=True),
        "ai_signal": _snapshot_input(ai_signal_path, fail_on_unavailable=False),
        "theme_momentum": _snapshot_input(theme_momentum_path, fail_on_unavailable=False),
        "market_confirmation": _snapshot_input(market_confirmation_path, fail_on_unavailable=True),
    }
    events_bytes = input_payloads["political_events"]
    watchlist_bytes = input_payloads["political_watchlist"]
    if not isinstance(events_bytes, bytes) or not isinstance(watchlist_bytes, bytes):
        raise ValueError("required advisory input unavailable")
    watchlist = load_watchlist(political_watchlist_path, source_bytes=watchlist_bytes)
    events = load_events(political_events_path, as_of_date, source_bytes=events_bytes)
    ai_signal: dict[str, Any] | None = None
    ai_source_artifact = ""
    ai_freshness_result = assess_context_freshness(
        None,
        report_as_of=as_of_date,
        reference_time=report_bounds.reference_time,
        report_generated_at=report_bounds.generated_at,
        max_age_days=REPORT_EXPIRY_DAYS,
    )
    ai_freshness_payload: Mapping[str, Any] | None = None
    ai_quality_warnings: list[str] = []
    if ai_signal_path:
        ai_bytes = input_payloads["ai_signal"]
        if ai_bytes is _UNAVAILABLE_INPUT:
            ai_quality_warnings.append("ai_signal_unavailable")
        else:
            try:
                candidate_ai_signal = load_trusted_ai_signal(
                    ai_signal_path,
                    source_bytes=ai_bytes if isinstance(ai_bytes, bytes) else None,
                )
            except AISignalValidationError as exc:
                ai_quality_warnings.append(str(exc))
            else:
                ai_freshness_payload = candidate_ai_signal
                ai_freshness_result = assess_context_freshness(
                    candidate_ai_signal,
                    report_as_of=as_of_date,
                    reference_time=report_bounds.reference_time,
                    report_generated_at=report_bounds.generated_at,
                    max_age_days=REPORT_EXPIRY_DAYS,
                )
                ai_source_artifact = str(ai_signal_path)
                if ai_freshness_result.valid:
                    ai_signal = candidate_ai_signal
                else:
                    ai_quality_warnings.append(f"ai_signal_{ai_freshness_result.reason}")

    theme_momentum: dict[str, Any] | None = None
    theme_source_artifact = ""
    theme_freshness_result = assess_context_freshness(
        None,
        report_as_of=as_of_date,
        reference_time=report_bounds.reference_time,
        report_generated_at=report_bounds.generated_at,
        max_age_days=REPORT_EXPIRY_DAYS,
    )
    theme_freshness_payload: Mapping[str, Any] | None = None
    theme_quality_warnings: list[str] = []
    if theme_momentum_path:
        theme_bytes = input_payloads["theme_momentum"]
        if theme_bytes is _UNAVAILABLE_INPUT:
            theme_quality_warnings.append("theme_momentum_contract_invalid")
        else:
            try:
                candidate_theme_momentum = load_theme_momentum(
                    theme_momentum_path,
                    source_bytes=theme_bytes if isinstance(theme_bytes, bytes) else None,
                )
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                theme_quality_warnings.append("theme_momentum_contract_invalid")
            else:
                theme_freshness_payload = candidate_theme_momentum
                if not candidate_theme_momentum.get("expires_at"):
                    theme_freshness_payload = {
                        **candidate_theme_momentum,
                        "reason": "legacy_expiry_compatibility",
                        "compatibility_warning": "missing_expires_at",
                    }
                theme_freshness_result = assess_context_freshness(
                    theme_freshness_payload,
                    report_as_of=as_of_date,
                    reference_time=report_bounds.reference_time,
                    report_generated_at=report_bounds.generated_at,
                    max_age_days=REPORT_EXPIRY_DAYS,
                    allow_legacy_expiry=True,
                )
                if theme_freshness_result.valid:
                    theme_source_artifact = str(theme_momentum_path)
                    theme_momentum = candidate_theme_momentum
                else:
                    theme_quality_warnings.append(f"theme_momentum_{theme_freshness_result.reason}")
                    if not candidate_theme_momentum.get("expires_at"):
                        theme_freshness_payload = None
                        theme_freshness_result = assess_context_freshness(
                            None,
                            report_as_of=as_of_date,
                            reference_time=report_bounds.reference_time,
                            report_generated_at=report_bounds.generated_at,
                            max_age_days=REPORT_EXPIRY_DAYS,
                        )
                    else:
                        theme_source_artifact = str(theme_momentum_path)
    market_bytes = input_payloads["market_confirmation"]
    market_confirmations = load_market_confirmation(
        market_confirmation_path,
        as_of_date,
        source_bytes=market_bytes if isinstance(market_bytes, bytes) else None,
    )
    theme_momentum_summary = summarize_theme_momentum(theme_momentum)
    source_mode, data_quality_warnings = source_mode_for_paths(
        political_events_path,
        political_watchlist_path,
        ai_signal_path,
        theme_momentum_path,
        market_confirmation_path,
    )
    data_quality_warnings = dedupe(data_quality_warnings + ai_quality_warnings + theme_quality_warnings)

    events_by_symbol: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        events_by_symbol[event.symbol].append(event)

    symbols = set(watchlist) | set(events_by_symbol)
    if ai_signal:
        symbols |= {symbol.upper() for symbol in ai_signal.get("universe", [])}
        for key in ("symbol_bias", "candidate_bias"):
            symbols |= {symbol.upper() for symbol in normalize_ai_mapping(ai_signal.get(key) or {})}

    all_recommendations = [
        build_recommendation(
            symbol=symbol,
            item=watchlist.get(symbol),
            events=sorted(events_by_symbol.get(symbol, []), key=lambda event: event.event_date),
            ai_signal=ai_signal,
            as_of=as_of_date,
        )
        for symbol in sorted(symbols)
    ]
    all_recommendations.sort(key=lambda rec: (-rec["evidence_score"], rec["risk_score"], rec["symbol"]))
    recommendations = all_recommendations[:max_candidates]
    theme_first_candidates = build_theme_first_candidates(theme_momentum, all_recommendations)
    final_decisions = build_final_decisions(all_recommendations, theme_momentum, market_confirmations)
    long_context_symbols = long_context_symbols_from_decisions(final_decisions)

    digest_payloads = {
        name: "unavailable" if payload is _UNAVAILABLE_INPUT else payload
        for name, payload in input_payloads.items()
    }
    report = {
        "schema_version": "6",
        "contract_version": contract_version_for_schema("6"),
        "as_of": as_of_date.isoformat(),
        "reference_time": utc_iso(report_bounds.reference_time),
        "generated_at": utc_iso(report_bounds.generated_at),
        "expires_at": utc_iso(report_bounds.expires_at),
        "input_digest": input_digest_for_payloads(digest_payloads),
        "freshness": {
            "ai_signal": freshness_record(ai_freshness_result, ai_freshness_payload),
            "theme_momentum": freshness_record(theme_freshness_result, theme_freshness_payload),
        },
        "mode": "model_recommendations",
        "cadence": cadence,
        "audience_scope": "non_personalized_model_research",
        "source_artifacts": {
            "political_events": str(political_events_path),
            "political_watchlist": str(political_watchlist_path),
            "ai_signal": ai_source_artifact,
            "theme_momentum": theme_source_artifact,
            "market_confirmation": str(market_confirmation_path) if market_confirmation_path else "",
        },
        "summary": {
            # Keep recommendation_count as the historical base-layer count.
            "recommendation_count": len(recommendations),
            "base_recommendation_count": len(recommendations),
            "final_recommendation_count": len(final_decisions["recommendations"]),
            "final_watchlist_count": len(final_decisions["watchlist"]),
            "final_overflow_recommendation_count": len(final_decisions["overflow_recommendations"]),
            "candidate_universe_count": len(all_recommendations),
            "source_event_count": len(events),
            "ai_regime": ai_signal.get("regime", "not_available") if ai_signal else "not_available",
            "ai_confidence": ai_signal.get("confidence", 0.0) if ai_signal else 0.0,
            "source_mode": source_mode,
            "data_quality_warnings": data_quality_warnings,
            "theme_momentum_available": theme_momentum_summary["available"],
            "theme_momentum_artifact_type": theme_momentum_summary.get("artifact_type", ""),
            "theme_momentum_horizon": theme_momentum_summary.get("horizon", ""),
            "theme_momentum_horizon_window": theme_momentum_summary.get("horizon_window_label", ""),
            "top_theme_ids": [theme["theme_id"] for theme in theme_momentum_summary["top_themes"]],
            "theme_first_candidate_count": len(theme_first_candidates),
            "market_confirmation_count": len(market_confirmations),
            "long_context_available": bool(long_context_symbols),
            "long_context_symbol_count": len(long_context_symbols),
            "long_context_symbols": long_context_symbols[:12],
            "long_context_missing_reason": ""
            if long_context_symbols
            else infer_long_context_missing_reason(ai_signal),
            "top_theme_candidate_symbols": [item["symbol"] for item in theme_first_candidates[:8]],
            "top_recommended_symbols": [item["symbol"] for item in final_decisions["recommendations"][:5]],
            "review_note": "Intelligent advisory research output. No order, target quantity, account suitability, or portfolio allocation is encoded.",
        },
        "recommendations": recommendations,
        "final_decisions": final_decisions,
        "theme_first_candidates": theme_first_candidates,
        "theme_momentum": theme_momentum_summary,
        "policy": {
            "non_personalized_recommendations_allowed": True,
            "execution_allowed": False,
            "portfolio_allocation_allowed": False,
            "personalized_advice_allowed": False,
            "account_specific_advice_allowed": False,
            "downstream_use": "Intelligent advisory research only; do not route to broker execution or account-level allocation.",
        },
    }
    validate_advisory_report(report)
    return report


def render_markdown(report: dict[str, Any]) -> str:
    cadence_label = CADENCE_LABELS_ZH.get(str(report["cadence"]), str(report["cadence"]).title())
    lines = [
        f"# 智慧投顾研究{cadence_label}复盘 - {report['as_of']}",
        "",
    ]
    final_decisions = report.get("final_decisions", {})
    if final_decisions:
        horizon_buckets = final_decisions.get("horizon_buckets", {})
        for horizon, label in (("short", "短线"), ("medium", "中线"), ("long", "长线")):
            symbols = ", ".join(horizon_buckets.get(horizon, [])) or "暂无系统结论"
            lines.append(f"- {label}({HORIZON_WINDOWS[horizon]}): {symbols}")
        lines.append("")
        for pick in final_decisions.get("recommendations", []):
            lines.extend(
                [
                    f"### {pick.get('symbol')} - {pick.get('action_label')}",
                    "",
                    f"- 周期: {pick.get('primary_horizon_label')}({pick.get('primary_horizon_window')})",
                    f"- 股票背景: {pick.get('business_summary')}",
                    f"- 推荐理由: {pick.get('prospect_summary')}",
                    "- 多源依据:",
                ]
            )
            lines.extend(f"  - {reason}" for reason in pick.get("why_selected", []))
            lines.extend(
                [
                    f"- 主要风险: {pick.get('risk_summary')}",
                    "",
                ]
            )
        return "\n".join(lines).rstrip() + "\n"
    theme_candidates = report.get("theme_first_candidates", [])
    if theme_candidates:
        lines.extend(["## 主题候选（解释材料，不是最终推荐）", ""])
        lines.append("- 先看这里: 每期选出 5-10 个股票/公司标的，说明行业主题、入选理由、事件证据和主要风险。")
        lines.append("- 边界: 这是非个性化模型股票池，不是买入清单；`暂无明确事件催化` 表示该标的主要来自主题/动量排序。")
        lines.append("")
        for candidate in theme_candidates:
            primary_theme_label = theme_label(candidate.get("primary_theme_id"), candidate.get("primary_theme_name"))
            lines.extend(
                [
                    f"### #{candidate.get('rank')} {candidate.get('symbol')} - {candidate.get('advisor_status')}",
                    "",
                    f"- 行业/主题: {candidate.get('industry_background')}",
                    f"- 主主题: {primary_theme_label}",
                    f"- 个股动量分数: `{display_number(candidate.get('symbol_momentum_score'))}`",
                    f"- 近3个月: `{display_percent(candidate.get('return_3m'))}`",
                    f"- 事件证据: `{candidate.get('source_confirmation')}`",
                    f"- 为什么入选: {candidate.get('recommendation_summary')}",
                    f"- 主要风险: {candidate.get('risk_summary')}",
                ]
            )
            lines.append("")
    theme_momentum = report.get("theme_momentum", {})
    if theme_momentum.get("available"):
        lines.extend(["## 主题动量", ""])
        lines.append(f"- 快照日期: `{theme_momentum.get('as_of', '')}`")
        lines.append(f"- 主题版本: `{theme_momentum.get('taxonomy_version', '')}`")
        lines.append("- 注意: 主题动量只用于研究排序和候选展示，不直接改变推荐评级。")
        lines.append("")
        for theme in theme_momentum.get("top_themes", []):
            symbols = ", ".join(theme.get("top_symbols", [])) or "无"
            lines.append(
                f"- #{theme.get('rank')} {theme_label(theme.get('theme_id'), theme.get('theme_name'))} "
                f"分数=`{theme.get('momentum_score')}` 3个月广度=`{theme.get('breadth_3m')}` 代表标的={symbols}"
            )
        lines.append("")
    lines.extend([
        "## 推荐列表",
        "",
    ])
    for rec in report["recommendations"]:
        lines.extend(
            [
                f"### {rec['symbol']} - {rec['rating_label']}",
                "",
                f"- 推荐层级: `{rec['recommendation_tier_label']}`",
                f"- 适合周期: `{rec['primary_horizon_label']}({rec['primary_horizon_window']})`",
                "- 可观察周期: "
                + ", ".join(
                    f"`{horizon}={window}`" for horizon, window in rec["suitable_horizon_windows"].items()
                ),
                f"- 周期说明: {rec['horizon_note']}",
                f"- 策略风格: `{rec['strategy_style']}`",
                f"- 模型分数: `{rec['score']}`",
                f"- 来源置信度: `{rec['source_confidence_label']}`",
                f"- 证据分数: `{rec['evidence_score']}`",
                f"- 风险分数: `{rec['risk_score']}`",
                "- 理由:",
            ]
        )
        lines.extend(f"  - {reason}" for reason in rec["reasons"])
        lines.append("- 风险:")
        lines.extend(f"  - {risk}" for risk in rec["risk_notes"])
        lines.append("- 复核清单:")
        lines.extend(f"  - {check}" for check in rec["review_checklist"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_text(path: str | Path, content: str) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build an intelligent advisory research report.")
    parser.add_argument("--as-of", required=True, help="Report date in YYYY-MM-DD format.")
    parser.add_argument("--cadence", required=True, choices=sorted(ALLOWED_CADENCES))
    parser.add_argument("--political-events", required=True, help="Political event CSV.")
    parser.add_argument("--political-watchlist", required=True, help="Political watchlist CSV.")
    parser.add_argument("--ai-signal", help="Saved AI shadow signal JSON.")
    parser.add_argument("--theme-momentum", help="Saved theme momentum snapshot JSON.")
    parser.add_argument("--market-confirmation", help="Optional point-in-time market confirmation CSV.")
    parser.add_argument("--max-items", "--max-candidates", dest="max_candidates", type=int, default=12)
    parser.add_argument("--output-json", required=True, help="Output JSON artifact path.")
    parser.add_argument("--output-md", required=True, help="Output Markdown report path.")
    parser.add_argument("--output-manifest", help="Output artifact manifest path. Defaults to <output-json>.manifest.json.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    report = build_advisory_report(
        as_of=args.as_of,
        cadence=args.cadence,
        political_events_path=args.political_events,
        political_watchlist_path=args.political_watchlist,
        ai_signal_path=args.ai_signal,
        theme_momentum_path=args.theme_momentum,
        market_confirmation_path=args.market_confirmation,
        max_candidates=args.max_candidates,
    )
    write_json(args.output_json, report)
    write_text(args.output_md, render_markdown(report))
    manifest_path = args.output_manifest or f"{args.output_json}.manifest.json"
    write_report_manifest(
        report=report,
        report_path=args.output_json,
        markdown_path=args.output_md,
        manifest_path=manifest_path,
        repository=os.environ.get("GITHUB_REPOSITORY"),
        git_sha=os.environ.get("GITHUB_SHA"),
        run_id=os.environ.get("GITHUB_RUN_ID"),
        run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"),
    )


if __name__ == "__main__":
    main()
