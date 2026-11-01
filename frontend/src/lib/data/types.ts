// Editor-facing types aligned with the 1.0.0 schemas. Ajv runtime validation
// is authoritative; these types do not replace it.
export type Cadence = 'daily' | 'weekly' | 'monthly';
export type Horizon = 'long' | 'medium' | 'short';
export type SourceSchema = '5' | '6';
export type InputStatus = 'verified' | 'partial' | 'unknown';
export type EmptyReason = null | 'threshold_unmet' | 'input_unavailable' | 'unknown';
export type LatestValidity = 'current' | 'expired' | 'unknown' | 'none';

export interface LocalizedText {
  'zh-CN': string;
  en: string | null;
}

export interface HorizonSummaryData {
  symbols: string[];
  empty_reason: EmptyReason;
}

export interface Summary {
  id: string;
  route: string;
  as_of: string;
  cadence: Cadence;
  source_schema: SourceSchema;
  title: LocalizedText;
  description: LocalizedText;
  generated_at: string;
  reference_time: string | null;
  expires_at: string | null;
  input_status: InputStatus;
  final_recommendation_count: number | null;
  horizons: Record<Horizon, HorizonSummaryData>;
  top_themes: LocalizedText[];
  legacy_summary_symbols: string[];
  legacy_horizon_symbols: Record<Horizon, string[]>;
}

export interface Card {
  rank: number;
  symbol: string;
  name: string | null;
  horizon_action: 'recommend' | 'watch' | 'unknown';
  selection_basis: 'primary_horizon' | 'long_fallback';
  window: LocalizedText;
  business_summary: LocalizedText | null;
  prospect_summary: LocalizedText | null;
  risk_summary: LocalizedText | null;
}

export interface Envelope<T> {
  $schema: string;
  contract_version: string;
  kind: 'index' | 'archive' | 'report' | 'feed' | 'manifest';
  release_id: string;
  built_at: string;
  default_locale: 'zh-CN';
  locales: string[];
  policy: Record<string, boolean>;
  data: T;
}

export interface IndexData {
  evaluated_at: string;
  latest: Summary | null;
  latest_validity: LatestValidity;
  recent: Summary[];
}

export interface ArchiveData {
  reports: Summary[];
}

export interface ReportData {
  summary: Summary;
  lead: LocalizedText[];
  cards: Record<Horizon, Card[]>;
  disclaimer: LocalizedText;
}

export interface FeedItem {
  report_id: string;
  title: LocalizedText;
  route: string;
  guid: string;
  published_at: string;
  description: LocalizedText;
}

export interface FeedData {
  title: LocalizedText;
  description: LocalizedText;
  home_url: string;
  feed_route: string;
  items: FeedItem[];
}

export interface ManifestFileEntry {
  path: string;
  kind: 'index' | 'archive' | 'report' | 'feed';
  sha256: string;
  bytes: number;
}

export interface ManifestData {
  files: ManifestFileEntry[];
  report_count: number;
}

export type IndexDoc = Envelope<IndexData>;
export type ArchiveDoc = Envelope<ArchiveData>;
export type ReportDoc = Envelope<ReportData>;
export type FeedDoc = Envelope<FeedData>;
export type ManifestDoc = Envelope<ManifestData>;

export interface SiteBundle {
  bundleDir: string;
  manifest: ManifestDoc;
  index: IndexDoc;
  archive: ArchiveDoc;
  feed: FeedDoc;
  reports: Map<string, ReportDoc>;
}
