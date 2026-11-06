// Downgrade-only expiry update: a current build label may become expired when
// the client clock is strictly after the supplied expires_at. It never upgrades
// unknown/expired labels, alters dates, counts, links or content.
function init(): void {
  const nodes = Array.from(
    document.querySelectorAll<HTMLElement>('[data-validity="current"][data-expires-at]'),
  );
  for (const node of nodes) {
    const expiresRaw = node.dataset.expiresAt ?? '';
    const expires = new Date(expiresRaw);
    if (Number.isNaN(expires.getTime())) continue;
    if (Date.now() <= expires.getTime()) continue;
    const label = node.dataset.labelExpired ?? '';
    if (node.textContent && label) {
      const text = node.querySelector<HTMLElement>('.validity-text') ?? node;
      text.textContent = label;
    }
    node.dataset.validity = 'expired';
    if ('state' in node.dataset) node.dataset.state = 'expired';
  }
}

init();
