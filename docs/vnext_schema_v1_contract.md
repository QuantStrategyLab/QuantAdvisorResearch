# QAR clean-slate vNext identity schema v1

本契约是独立的 clean-slate namespace：`qar_vnext_identity.v1`。它不读取、迁移、猜测或回退到 legacy index、legacy filename、旧 publisher/recovery 输出；legacy 类型和旧 schema 不进入本路径。

## 固定版本

- 顶层 `schema_version` 固定为整数 `1`。
- 顶层 `namespace` 固定为 `qar_vnext_identity.v1`；entry 的 `binding_namespace` 固定为 `qar_vnext_binding.v1`。
- `semantic_fingerprint_version` 固定为 `semantic_fingerprint.v1.sha256`。
- `artifact_integrity_version` 固定为 `validated_report.v1.canonical-json.sha256`。
- 只接受当前 exact pair。未知、future、mismatch 或运行时可变版本一律 fail-closed；未来算法变化创建独立 schema/namespace，不做 registry、dual-read 或 migration。

## Entry 与 target

`report_schema_version` 必须是字符串 `5` 或 `6`，`contract_version` 必须由唯一 `contract_version_for_schema()` 严格匹配。所有 target 都包含 `as_of + cadence`：canonical 无 suffix，variant 的 json/html/md/manifest（只校验实际声明者）都使用完整 artifact digest suffix。md/manifest key omission 表示未请求；key present 必须是有效 basename string，显式 `null` 不等同 omission。

完整 index 每个 period 恰好一个 canonical；variant-only、多个 canonical、basename/digest collision、错误 period/schema/contract/class/status、legacy target 均拒绝。`display_primary` 每个 period 最多一个，`display_order` 每个 period 唯一且是 `0..2**53-1` 的非 bool integer。identity owner 与 display placement 分离，后续 PublicationPlan 可使用独立 display evidence。

## Pure boundary

`VNextIdentityBinding`、`VNextIdentityIndex`、allocation modes 和 `PublicationPlan` 均为 immutable/pure value objects。raw report、index、attachments、display placement 先校验；source basename 不决定 public target。CURRENT 空 period 才能 bootstrap canonical；occupied period 的 changed artifact 分配 variant；identical artifact 复用；HISTORICAL 无 canonical fail-closed；EXACT 只复用 exact。

本阶段不包含 filesystem/network/publisher/build/workflow/Pages/I/O、legacy compatibility/migration、真实发布或 N2。
