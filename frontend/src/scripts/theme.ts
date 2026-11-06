// Theme preference behavior. Runs only as a module after the pre-paint inline
// script in SiteShell has applied any stored explicit theme.
const STORAGE_KEY = 'quantadvisor-theme';

function showStorageFailure(): void {
  const note = document.querySelector<HTMLElement>('.theme-storage-failure');
  if (note) note.classList.add('visible');
}

function init(): void {
  const radios = Array.from(
    document.querySelectorAll<HTMLInputElement>('input[name="theme-preference"]'),
  );
  if (radios.length === 0) return;

  const explicit = document.documentElement.dataset.theme;
  const initial = explicit === 'light' || explicit === 'dark' ? explicit : 'system';
  for (const radio of radios) {
    radio.checked = radio.value === initial;
    radio.addEventListener('change', () => {
      if (!radio.checked) return;
      if (radio.value === 'system') {
        delete document.documentElement.dataset.theme;
      } else {
        document.documentElement.dataset.theme = radio.value;
      }
      try {
        localStorage.setItem(STORAGE_KEY, radio.value);
      } catch {
        showStorageFailure();
      }
    });
  }

  try {
    const probe = `${STORAGE_KEY}-probe`;
    localStorage.setItem(probe, '1');
    localStorage.removeItem(probe);
  } catch {
    showStorageFailure();
  }
}

init();
