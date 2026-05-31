# 数据源与因子完善路线

[English](data_factor_roadmap.md) | [简体中文](data_factor_roadmap.zh-CN.md)

## 当前结论

`QuantAdvisorResearch` 当前应该继续做智慧投顾研究系统的最终合成仓库，而不是把所有量化因子仓库接进来。原因是现有组织里已经有两条性质不同的链路：

- 可回测、可执行链路：价格、技术、动量、波动、快照和策略仓库，最后可进入券商平台。
- 新闻、政策、公开事件、AI shadow 链路：证据不稳定、样本少、回测难，应该只进入非个性化智慧投顾研究和复盘。

因此本仓库短期只消费 `PoliticalEventTrackingResearch` 和 `ResearchSignalContextPipelines` 的研究产物；`UsEquitySnapshotPipelines`、`UsEquityStrategies`、`CryptoSnapshotPipelines`、`CryptoStrategies` 保持独立，只作为方法参考和未来人工复核资料来源。

## 现有数据源盘点

### PoliticalEventTrackingResearch

当前负责事件事实层，已有输入与适配器：

- 官方/半结构化记录：`official_records.csv`，支持政府、发行人、主社媒、财经媒体 lead。
- RSS/Atom：`fetch_rss_sources.py`，可拉取 SEC 等公开 feed。
- 原始文本抽取：`extract_source_mentions.py`，通过 alias map 抽取 ticker 相关事件。
- 事件研究：`run_event_study.py`，用本地日收盘价做小窗口事件回测。

当前事件类型：

- `disclosure_buy`
- `public_mention`
- `policy_capital`
- `market_reaction`

当前来源置信度：

- `high`：政府、官方披露、SEC/EDGAR、发行人等主来源。
- `medium`：发行人材料或可复核的一手资料。
- `low`：财经媒体 lead，必须先核验主来源。

稳定版暂不包含 X / Truth Social / Longbridge 登录态或社区采集；这些来源只能在未来有稳定官方接口、清晰合规边界和可回放 artifact 后再评估。

### ResearchSignalContextPipelines

当前负责 AI 长周期 shadow context：

- 输入为本地价格 CSV 或 Yahoo chart 下载。
- 生成价格上下文：趋势、63 日回撤、21 日实现波动、波动分层。
- 保存 `latest_signal.json` 和 `signal_history/YYYY-MM-DD.json`。
- replay 只用已保存的历史 artifact，不重新生成过去的 AI 判断。
- 当前示例 overlay 只允许降低风险暴露，不允许提高仓位。

这个仓库适合给本仓库提供长周期背景，例如市场 regime、风险 flags、候选方向偏好，但不应该直接生成下单或仓位。

### QuantAdvisorResearch

当前负责最终非个性化智慧投顾研究输出：

- 输入：事件 CSV、watchlist CSV、AI shadow JSON、可选主题动量、可选市场确认 CSV。
- 输出：`model_recommendations` JSON、Markdown、HTML、RSS。
- 推荐字段：推荐等级、推荐层级、适合周期、周期说明、来源可信度、理由、风险、复核清单。
- 合约禁止：目标仓位、目标股数、订单、券商、账户信息。

当前评分仍是 MVP 级确定性规则，主要围绕事件类型、来源置信度、AI shadow 偏好和风险 flags。

### UsEquitySnapshotPipelines / UsEquityStrategies

这条链路适合自动交易或可回测策略，不建议直接接入投顾推荐 MVP。

已有 US equity 因子和规则包括：

- Russell 1000 多因子：`mom_6_1`、`mom_12_1`、`sma200_gap`、`vol_63`、`maxdd_126`、ADV、sector 标准化、宽度防守。
- Global ETF rotation：13612W 动量、SMA250 趋势、canary basket、相对波动和置信门。
- TQQQ/SOXL 等趋势收入策略：RSI、Bollinger band、ATR / Chandelier、动态 RSI 分位、波动/回撤保护。
- Mega-cap leader rotation：动态 universe、leader rotation、频率和集中度研究。

这些因子可以作为未来人工解释或交叉验证材料，但不应让本仓库直接输出可执行 target allocation。

### CryptoSnapshotPipelines / CryptoStrategies

这条链路当前是 crypto leader rotation：

- 数据源：Binance Spot `exchangeInfo`、symbol metadata、daily klines、本地缓存。
- 因子：趋势质量、持久性、流动性、流动性稳定度、相对 BTC 强度、风险调整动量、ATR 风控。
- 当前外部数据 track 仍是实验，不是默认生产路径。

Crypto 可作为跨资产风险情绪参考，但暂时不应混入 US equity 推荐结果，除非未来明确做跨资产投顾版。

## 需要补强的数据源

优先级从高到低：

1. 主来源政策与披露
   - SEC press releases、EDGAR / issuer release、White House、Federal Register、Congress、OGE、DoD contracts、DOE / CHIPS、Treasury sanctions、USAspending 或 SAM.gov。
   - 目标：提高 `high` confidence 事件比例。

2. 主社媒
   - Truth Social、X verified accounts、政府/公司官方账号。
   - 目标：把社媒从“话题噪声”变成可审计事件来源。

3. 财经媒体 lead
   - 只做 `low` confidence lead。
   - 目标：发现线索，但必须通过官方、发行人或主社媒二次确认后才能升级。

4. 实时市场确认
   - 日内或日频价格、成交量、相对行业/指数表现、跳空、异常成交量。
   - 目标：判断事件是否已经被市场确认或过度透支。

5. 基本面与估值
   - 市值、流通市值、行业、营收增长、利润率、负债、forward PE / EV sales、盈利日期。
   - 目标：区分政策催化的短中线交易和真正可持有的价值/成长标的。

6. 宏观与风险环境
   - VIX、利率、美元、信用利差、油价、期限结构、板块 beta。
   - 目标：避免在不合适 regime 里把事件催化误判成推荐。

## 推荐因子分层

### 事件证据因子

- 来源权威度：官方 > 主社媒 > 媒体 lead。
- 来源新鲜度：越接近 `as_of` 越高。
- 多来源确认：同一事件被官方、公司、主社媒交叉确认时加分。
- 事件方向：利好、利空、中性、待核验。
- 事件类型强度：政策资金/采购/监管批准通常强于普通 mention。
- 事件滞后窗口：事件后 1/5/20/60 个交易日的表现用于后续复盘。

### 政策催化因子

- 资金规模或订单规模。
- 政策持续时间。
- 受益链条清晰度：直接受益 > 供应链受益 > 概念受益。
- 政策执行概率。
- 竞争格局：是否只有少数公司能拿到订单或资格。

### 社媒与新闻因子

- 发言人权重：政策制定者、监管者、公司高管、关键人物。
- 文本意图：点名、支持、批评、采购、制裁、监管。
- 传播强度：重复提及、多账号扩散、媒体跟进。
- 噪声惩罚：只来自媒体 lead 且无主来源时不能升级推荐。

### 市场确认因子

- 相对收益：相对 SPY / QQQ / 行业 ETF 的异常表现。
- 异常成交量：相对 20 日/60 日均量。
- 趋势状态：价格相对 50/200 日均线。
- 回撤状态：避免追入已大幅透支的事件。
- 波动状态：高波动标的默认降低推荐层级或标注短线风险。

### 价值与质量因子

- 营收和利润质量。
- 现金流和资产负债表。
- 估值相对行业是否过高。
- 盈利日期和 guidance 风险。
- 是否有长期政策/产业逻辑支撑。

### AI shadow 因子

- regime：risk_on、mixed、risk_off。
- confidence：只作为背景强弱，不作为直接下单信号。
- risk_flags：波动、流动性、盈利集中、宏观冲击。
- candidate bias：用于解释候选标的的长周期背景。
- theme bias：用于表达跨板块长期主题背景，例如 AI compute、HBM、国防、能源、医疗政策、金融基础设施等。
- symbol theme exposure：由静态 taxonomy 决定，不能因为近期热门表现临时加入或改权重。
- model/version/source：必须可审计，保留历史 artifact。

## 低风险实施顺序

1. 先让 `QuantAdvisorResearch` 稳定输出最终推荐：
   - 保留 `theme_first_candidates[]` 作为 JSON/Markdown 审计材料，不在公开页面默认展示。
   - 公开 HTML/RSS/Telegram 默认只显示最终推荐、股票背景、推荐理由、周期和风险。
   - 中线主题动量用于解释和排序候选，事件证据作为置信度与风险提示输入。
   - 避免让“主题候选池”被误读为买入清单。

2. 继续补 `PoliticalEventTrackingResearch` 的稳定真实源：
   - RSS feed 配置。
   - 官方公告、SEC/EDGAR、公司 IR、政策和采购来源。
   - alias map 和 source registry。
   - X / Truth Social / 社区内容暂不作为稳定默认源。

3. 在 `QuantAdvisorResearch` 增加 market confirmation 输入，但保持可选：
   - 当前 CSV 字段为 `symbol,as_of,return_5d,return_20d,return_63d,relative_return_20d,relative_return_63d,volume_zscore,drawdown_63d,volatility_21d,market_score,data_source,price_observation_count,warnings`。
   - `scripts/build_market_confirmation.py` 已能自动从 watchlist、信号上下文和主题动量快照收集标的，线上 workflow 默认生成该 CSV。
   - 支持 `--proxy-urls`、`--proxy-list`、`--proxy-pool-url` 和仓库变量 `MARKET_DATA_PROXY_URLS` / `MARKET_DATA_PROXY_POOL_URL` 作为免费公共代理池补充。
   - 如果免费行情接口不可用，脚本会退回到 `theme_momentum_snapshot.json` 中的价格动量字段；报告继续生成，但短线结论会更保守。
   - 该输入只影响 `final_decisions` 的短/中/长线审计评分，不包含目标仓位或交易指令。

4. 增加事件复盘结果输入：
   - `event_id,symbol,event_date,window,absolute_return,benchmark_relative_return`。
   - 用于日/周/月回顾，不用于自动交易。

5. 增加基本面/估值快照输入：
   - 独立 CSV artifact，不直接依赖策略仓库。
   - 先只用于风险提示和推荐解释。

6. 最后再考虑跨仓库只读参考：
   - 只读 `UsEquitySnapshotPipelines` 的公开 artifact 摘要。
   - 不读取策略 target、broker runtime、账户持仓或订单。
   - 输出仍然是推荐文本，不是仓位。

## 不建议现在做的事

- 不要把 `UsEquityStrategies` 的策略信号直接合并成本仓库推荐分数。
- 不要把 `QuantAdvisorResearch` 的推荐推给券商平台执行。
- 不要让 AI 生成目标仓位、买卖数量、订单类型或账户级建议。
- 不要把财经媒体 lead 当成高置信来源。
- 不要为了“AI 化”放弃 point-in-time artifact 和 replay。

## 验证方式

- schema 测试：每次输出都必须通过 `contracts.py` 校验。
- fixture 测试：保留合成样例，验证低置信来源不会升级成推荐。
- 日/周/月回顾：跟踪推荐后的 1/5/20/60 交易日相对表现。
- 来源质量报表：统计 high/medium/low/mixed 推荐命中率。
- 人工复核清单：任何一级推荐必须能追溯到来源、事件、AI context 和风险说明。

短期真正要补的是源和复核数据，不是把自动交易仓库接进来。等真实数据积累后，再决定哪些新闻/政策因子值得转成可回测的独立策略。

## 防过拟合主题设计

长期有效的投顾研究不应该只追逐 AI 热点。建议把主题分成静态 taxonomy，并在 `ResearchSignalContextPipelines` 维护：

```text
config/theme_taxonomy.csv
config/symbol_theme_exposure.csv
```

第一版跨板块覆盖：

- AI compute / HBM / foundry / AI server
- 数据中心电力、清洁电网、核电可选项
- 网络安全
- 国防航天
- 能源安全
- 金融和市场基础设施
- 医疗政策
- 消费平台、工业自动化、crypto 基础设施、EV/汽车

防过拟合规则：

1. theme membership 先固定，再观察后续表现。
2. AI 只能输出 `theme_bias` 和 shadow context，不能输出目标仓位。
3. Advisor 可以把主题 bias 和主题动量作为最终推荐的解释输入；主题候选池只作为审计材料，公开输出默认只展示最终推荐。
4. 每次规则、taxonomy、universe 变更都要记录版本，后续 walk-forward 只能 replay 已保存 artifact。
5. 不因为 MU、INTC、DELL 或任何短期热门标的临时调权重；如果它们长期有 SEC/IR/政策/需求证据，会通过固定规则自然上升。
