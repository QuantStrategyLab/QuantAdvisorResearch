export const SITE_ORIGIN = 'https://quantstrategylab.github.io';
export const SITE_BASE = '/QuantAdvisorResearch';

// Same approved external target as the current published site.
export const METHOD_URL =
  'https://github.com/QuantStrategyLab/QuantAdvisorResearch/blob/main/docs/system-design.zh-CN.md';

export const RESERVED_ROUTES = new Set(['index', 'archive', '404', 'feed']);

export function canonicalUrl(relative: string): string {
  if (relative === '' || relative === '/') return `${SITE_ORIGIN}${SITE_BASE}/`;
  return `${SITE_ORIGIN}${SITE_BASE}/${relative.replace(/^\/+/, '')}`;
}

export function assertSafeReportSlug(slug: string): void {
  const expected = /^\d{4}-\d{2}-\d{2}-(daily|weekly|monthly)-model-recommendations$/;
  if (!expected.test(slug)) {
    throw new Error(`Report slug "${slug}" does not match the contract route pattern`);
  }
  const stem = slug.replace(/-model-recommendations$/, '');
  if (RESERVED_ROUTES.has(stem)) {
    throw new Error(`Report slug "${slug}" collides with a reserved route`);
  }
}
