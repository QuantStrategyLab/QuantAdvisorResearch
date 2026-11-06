// Generates synthetic site JSON bundles for local build and render checks.
// All content is fabricated for testing; nothing here is published research.
// Output: tests/fixtures/bundles/<name>/{manifest.json,index.json,archive.json,feed.json,reports/*.json}
import { createHash } from 'node:crypto';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const OUT_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../tests/fixtures/bundles',
);

const SCHEMA_BASE =
  'https://quantstrategylab.github.io/QuantAdvisorResearch/schemas/site/1.0.0';
const POLICY = {
  non_personalized_recommendations_allowed: true,
  execution_allowed: false,
  portfolio_allocation_allowed: false,
  personalized_advice_allowed: false,
  account_specific_advice_allowed: false,
};

const loc = (zh) => ({ 'zh-CN': zh, en: null });

function summary({
  asOf,
  cadence,
  sourceSchema,
  title,
  description,
  generatedAt,
  referenceTime,
  expiresAt,
  inputStatus,
  finalCount,
  horizons,
  themes = [],
  legacySummary = [],
  legacyHorizons = { long: [], medium: [], short: [] },
}) {
  const id = `${asOf}-${cadence}`;
  return {
    id,
    route: `${id}-model-recommendations.html`,
    as_of: asOf,
    cadence,
    source_schema: sourceSchema,
    title: loc(title),
    description: loc(description),
    generated_at: generatedAt,
    reference_time: referenceTime,
    expires_at: expiresAt,
    input_status: inputStatus,
    final_recommendation_count: finalCount,
    horizons,
    top_themes: themes.map(loc),
    legacy_summary_symbols: legacySummary,
    legacy_horizon_symbols: legacyHorizons,
  };
}

function horizon(symbols, emptyReason = null) {
  return { symbols, empty_reason: emptyReason };
}

function card({ rank, symbol, name, window, business, prospect, risk, action = 'recommend', basis = 'primary_horizon' }) {
  return {
    rank,
    symbol,
    name,
    horizon_action: action,
    selection_basis: basis,
    window: loc(window),
    business_summary: business === null ? null : loc(business),
    prospect_summary: prospect === null ? null : loc(prospect),
    risk_summary: risk === null ? null : loc(risk),
  };
}

function envelope(kind, doc, shared) {
  return {
    $schema: `${SCHEMA_BASE}/${kind}.schema.json`,
    contract_version: '1.0.0',
    kind,
    ...shared,
    ...doc,
  };
}

function serialize(value) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

function writeBundle(name, shared, payloads) {
  const dir = path.join(OUT_ROOT, name);
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(path.join(dir, 'reports'), { recursive: true });

  const files = [];
  for (const { relPath, value } of payloads) {
    const bytes = Buffer.from(serialize(value), 'utf8');
    writeFileSync(path.join(dir, relPath), bytes);
    files.push({
      path: relPath,
      kind: value.kind,
      sha256: createHash('sha256').update(bytes).digest('hex'),
      bytes: bytes.byteLength,
    });
  }
  const reportCount = files.filter((f) => f.path.startsWith('reports/')).length;
  const manifest = envelope('manifest', { data: { files, report_count: reportCount } }, shared);
  writeFileSync(path.join(dir, 'manifest.json'), serialize(manifest), 'utf8');
  console.log(`wrote ${name}: ${files.length} payloads + manifest (report_count=${reportCount})`);
}

// ---------- Bundle 1: populated, current latest, mixed legacy ----------
{
  const shared = {
    release_id: '6f1d2a3b-4c5d-4e6f-8a7b-9c0d1e2f3a4b',
    built_at: '2026-10-25T01:00:00Z',
    default_locale: 'zh-CN',
    locales: ['zh-CN'],
    policy: POLICY,
  };

  const current = summary({
    asOf: '2026-10-24',
    cadence: 'weekly',
    sourceSchema: '6',
    title: '需求韧性与产业周期 <script>alert(1)</script>',
    description: '合成测试内容：本期研究覆盖需求、供给与估值三条线索。<img src=x onerror=alert(1)>',
    generatedAt: '2026-10-24T12:00:00Z',
    referenceTime: '2026-10-25T00:00:00Z',
    expiresAt: '2026-10-31T12:00:00Z',
    inputStatus: 'verified',
    finalCount: 4,
    horizons: {
      long: horizon(['NVDA', '<img src=x onerror=alert(1)>']),
      medium: horizon(['NVDA', 'XOM']),
      short: horizon(['QQQ']),
    },
    themes: ['算力资本开支', '能源现金流'],
    legacySummary: ['NVDA', 'QQQ', 'XOM'],
    legacyHorizons: { long: ['NVDA'], medium: ['XOM'], short: [] },
  });

  const previous = summary({
    asOf: '2026-10-17',
    cadence: 'weekly',
    sourceSchema: '6',
    title: '利率路径与估值锚（合成）',
    description: '合成测试内容：上一期周报，已过有效期。',
    generatedAt: '2026-10-17T12:00:00Z',
    referenceTime: '2026-10-18T00:00:00Z',
    expiresAt: '2026-10-24T12:00:00Z',
    inputStatus: 'verified',
    finalCount: 0,
    horizons: {
      long: horizon([], 'threshold_unmet'),
      medium: horizon([], 'threshold_unmet'),
      short: horizon([], 'threshold_unmet'),
    },
    legacySummary: [],
  });

  const legacy = summary({
    asOf: '2026-09-26',
    cadence: 'weekly',
    sourceSchema: '5',
    title: '旧版契约样例（v5，合成）',
    description: '合成测试内容：v5 来源无参考时间与有效期，时效状态应为未知。',
    generatedAt: '2026-09-26T09:00:00Z',
    referenceTime: null,
    expiresAt: null,
    inputStatus: 'unknown',
    finalCount: null,
    horizons: {
      long: horizon(['MRVL']),
      medium: horizon([], 'unknown'),
      short: horizon([], 'input_unavailable'),
    },
    legacySummary: ['MRVL'],
    legacyHorizons: { long: ['MRVL'], medium: [], short: [] },
  });

  const reportDocs = (s, lead, cards, disclaimer) => ({
    relPath: `reports/${s.id}.json`,
    value: envelope(
      'report',
      { data: { summary: s, lead, cards, disclaimer: loc(disclaimer) } },
      shared,
    ),
  });

  const leadCurrent = [
    loc('合成摘要第一段：长期窗口关注需求韧性，风险集中于资本开支节奏。'),
    loc('合成摘要第二段：综合各周期，本期的整体阅读要点是风险优先。', ),
  ];
  const cardsCurrent = {
    long: [
      card({
        rank: 1,
        symbol: 'NVDA',
        name: '合成公司甲',
        window: '6–12 个月',
        business: '合成公司背景：数据中心硬件供应商。',
        prospect: '合成研究理由：需求指引与订单结构。',
        risk: '合成风险：估值对利率敏感。',
      }),
      card({
        rank: 2,
        symbol: '<img src=x onerror=alert(1)>',
        name: null,
        window: '6–12 个月',
        business: null,
        prospect: '合成研究理由：仅有依据字段。',
        risk: null,
        basis: 'long_fallback',
        action: 'watch',
      }),
    ],
    medium: [
      card({
        rank: 1,
        symbol: 'NVDA',
        name: '合成公司甲',
        window: '1–3 个月',
        business: '合成公司背景：同长期列公司，标的在多个周期重复出现。',
        prospect: '合成研究理由：中期景气数据。',
        risk: '合成风险：库存周期反转。',
      }),
      card({
        rank: 2,
        symbol: 'XOM',
        name: '合成公司乙',
        window: '1–3 个月',
        business: '合成公司背景：综合能源公司。',
        prospect: '合成研究理由：现金流与分红能力。',
        risk: '合成风险：商品价格波动。',
      }),
    ],
    short: [
      card({
        rank: 1,
        symbol: 'QQQ',
        name: '合成指数工具',
        window: '1–4 周',
        business: '合成公司背景：宽基指数ETF。',
        prospect: '合成研究理由：短周期拥挤度指标。',
        risk: '合成风险：流动性冲击。',
      }),
    ],
  };

  const leadPrevious = [loc('合成摘要：上期三条周期均未达入选阈值。')];
  const leadLegacy = [loc('合成摘要：旧版契约样例，仅保留公开列。')];

  const feedItems = [current, previous, legacy].map((s) => ({
    report_id: s.id,
    title: s.title,
    route: s.route,
    guid: `https://quantstrategylab.github.io/QuantAdvisorResearch/${s.route}`,
    published_at: s.generated_at,
    description: s.description,
  }));

  writeBundle('populated-current', shared, [
    {
      relPath: 'index.json',
      value: envelope(
        'index',
        {
          data: {
            evaluated_at: '2026-10-25T00:00:00Z',
            latest: current,
            latest_validity: 'current',
            recent: [previous, legacy],
          },
        },
        shared,
      ),
    },
    {
      relPath: 'archive.json',
      value: envelope('archive', { data: { reports: [current, previous, legacy] } }, shared),
    },
    {
      relPath: 'feed.json',
      value: envelope(
        'feed',
        {
          data: {
            title: loc('QuantAdvisorResearch 合成订阅'),
            description: loc('合成测试频道：仅供研究，不构成投资建议。'),
            home_url: 'https://quantstrategylab.github.io/QuantAdvisorResearch/',
            feed_route: 'feed.xml',
            items: feedItems,
          },
        },
        shared,
      ),
    },
    reportDocs(current, leadCurrent, cardsCurrent, '合成免责声明：本内容仅供研究，不构成投资建议。'),
    reportDocs(
      previous,
      leadPrevious,
      { long: [], medium: [], short: [] },
      '合成免责声明：本内容仅供研究，不构成投资建议。',
    ),
    reportDocs(
      legacy,
      leadLegacy,
      {
        long: [
          card({
            rank: 1,
            symbol: 'MRVL',
            name: '合成公司丙',
            window: '6–12 个月',
            business: '合成公司背景：网络芯片设计。',
            prospect: '合成研究理由：客户资本开支。',
            risk: '合成风险：客户集中。',
          }),
        ],
        medium: [],
        short: [],
      },
      '合成免责声明：旧版样例，仅供研究。',
    ),
  ]);
}

// ---------- Bundle 2: initialized empty site ----------
{
  const shared = {
    release_id: '1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d',
    built_at: '2026-11-01T00:00:00Z',
    default_locale: 'zh-CN',
    locales: ['zh-CN'],
    policy: POLICY,
  };
  writeBundle('empty-site', shared, [
    {
      relPath: 'index.json',
      value: envelope(
        'index',
        {
          data: {
            evaluated_at: '2026-11-01T00:00:00Z',
            latest: null,
            latest_validity: 'none',
            recent: [],
          },
        },
        shared,
      ),
    },
    { relPath: 'archive.json', value: envelope('archive', { data: { reports: [] } }, shared) },
    {
      relPath: 'feed.json',
      value: envelope(
        'feed',
        {
          data: {
            title: loc('QuantAdvisorResearch 合成订阅'),
            description: loc('合成测试频道：仅供研究，不构成投资建议。'),
            home_url: 'https://quantstrategylab.github.io/QuantAdvisorResearch/',
            feed_route: 'feed.xml',
            items: [],
          },
        },
        shared,
      ),
    },
  ]);
}

// ---------- Bundle 3: expired latest with all-empty horizons, single report ----------
{
  const shared = {
    release_id: '9f8e7d6c-5b4a-4321-8765-43210fedcba9',
    built_at: '2026-08-10T00:00:00Z',
    default_locale: 'zh-CN',
    locales: ['zh-CN'],
    policy: POLICY,
  };
  const stale = summary({
    asOf: '2026-08-01',
    cadence: 'daily',
    sourceSchema: '6',
    title: '过期样例（合成日报）',
    description: '合成测试内容：全部周期为空且已过有效期。',
    generatedAt: '2026-08-01T06:00:00Z',
    referenceTime: '2026-08-02T00:00:00Z',
    expiresAt: '2026-08-08T06:00:00Z',
    inputStatus: 'partial',
    finalCount: 0,
    horizons: {
      long: horizon([], 'threshold_unmet'),
      medium: horizon([], 'input_unavailable'),
      short: horizon([], 'unknown'),
    },
    legacySummary: ['SPY'],
    legacyHorizons: { long: [], medium: ['SPY'], short: [] },
  });
  writeBundle('expired-empty', shared, [
    {
      relPath: 'index.json',
      value: envelope(
        'index',
        {
          data: {
            evaluated_at: '2026-08-10T00:00:00Z',
            latest: stale,
            latest_validity: 'expired',
            recent: [],
          },
        },
        shared,
      ),
    },
    {
      relPath: 'archive.json',
      value: envelope('archive', { data: { reports: [stale] } }, shared),
    },
    {
      relPath: 'feed.json',
      value: envelope(
        'feed',
        {
          data: {
            title: loc('QuantAdvisorResearch 合成订阅'),
            description: loc('合成测试频道：仅供研究，不构成投资建议。'),
            home_url: 'https://quantstrategylab.github.io/QuantAdvisorResearch/',
            feed_route: 'feed.xml',
            items: [
              {
                report_id: stale.id,
                title: stale.title,
                route: stale.route,
                guid: `https://quantstrategylab.github.io/QuantAdvisorResearch/${stale.route}`,
                published_at: stale.generated_at,
                description: stale.description,
              },
            ],
          },
        },
        shared,
      ),
    },
    {
      relPath: `reports/${stale.id}.json`,
      value: envelope(
        'report',
        {
          data: {
            summary: stale,
            lead: [loc('合成摘要：全部周期为空，三种原因各占一列。')],
            cards: { long: [], medium: [], short: [] },
            disclaimer: loc('合成免责声明：本内容仅供研究，不构成投资建议。'),
          },
        },
        shared,
      ),
    },
  ]);
}
