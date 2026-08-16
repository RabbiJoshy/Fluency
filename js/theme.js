// App-wide appearance preference. The tiny synchronous bootstrap in
// index.html applies the initial theme before CSS paints; this module owns
// changes after boot, Settings controls, system-theme updates, and tab sync.

export const THEME_STORAGE_KEY = 'fluency_theme_preference_v1';
export const THEME_PREFERENCES = Object.freeze(['dark', 'light', 'system']);

export function normalizeThemePreference(value) {
    return THEME_PREFERENCES.includes(value) ? value : 'dark';
}

export function resolveTheme(preference, prefersLight = false) {
    const normalized = normalizeThemePreference(preference);
    return normalized === 'system' ? (prefersLight ? 'light' : 'dark') : normalized;
}

const browserWindow = typeof window === 'undefined' ? null : window;
const browserDocument = typeof document === 'undefined' ? null : document;
const systemLightQuery = browserWindow?.matchMedia?.('(prefers-color-scheme: light)') || null;

function readThemePreference() {
    try {
        return normalizeThemePreference(browserWindow?.localStorage.getItem(THEME_STORAGE_KEY));
    } catch (_) {
        return 'dark';
    }
}

function updateThemeControls(preference) {
    if (!browserDocument) return;
    browserDocument.querySelectorAll('.theme-preference-btn').forEach(button => {
        const selected = button.dataset.themePreference === preference;
        button.classList.toggle('selected', selected);
        button.setAttribute('aria-checked', selected ? 'true' : 'false');
        button.tabIndex = selected ? 0 : -1;
    });
}

export function applyThemePreference(preference, { persist = false, announce = true } = {}) {
    const normalized = normalizeThemePreference(preference);
    const resolved = resolveTheme(normalized, Boolean(systemLightQuery?.matches));

    if (persist) {
        try { browserWindow?.localStorage.setItem(THEME_STORAGE_KEY, normalized); } catch (_) {}
    }

    if (browserDocument) {
        const root = browserDocument.documentElement;
        root.dataset.themePreference = normalized;
        root.dataset.theme = resolved;
        root.style.colorScheme = resolved;
        const meta = browserDocument.querySelector('meta[name="theme-color"]');
        if (meta) meta.content = resolved === 'light' ? '#eef2f5' : '#0a0e14';
        updateThemeControls(normalized);

        if (announce) {
            browserWindow?.dispatchEvent(new CustomEvent('fluency-theme-change', {
                detail: { preference: normalized, theme: resolved }
            }));
        }
    }

    return { preference: normalized, theme: resolved };
}

function moveThemeControlFocus(currentButton, direction) {
    const buttons = Array.from(browserDocument?.querySelectorAll('.theme-preference-btn') || []);
    const currentIndex = buttons.indexOf(currentButton);
    if (currentIndex < 0 || buttons.length === 0) return;
    const nextIndex = (currentIndex + direction + buttons.length) % buttons.length;
    const nextButton = buttons[nextIndex];
    applyThemePreference(nextButton.dataset.themePreference, { persist: true });
    nextButton.focus();
}

function setupThemeControls() {
    if (!browserDocument) return;
    browserDocument.querySelectorAll('.theme-preference-btn').forEach(button => {
        button.addEventListener('click', () => {
            applyThemePreference(button.dataset.themePreference, { persist: true });
        });
        button.addEventListener('keydown', event => {
            if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
                event.preventDefault();
                moveThemeControlFocus(button, -1);
            } else if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
                event.preventDefault();
                moveThemeControlFocus(button, 1);
            } else if (event.key === 'Home' || event.key === 'End') {
                event.preventDefault();
                const buttons = Array.from(browserDocument.querySelectorAll('.theme-preference-btn'));
                const target = event.key === 'Home' ? buttons[0] : buttons.at(-1);
                applyThemePreference(target.dataset.themePreference, { persist: true });
                target.focus();
            }
        });
    });
}

function handleSystemThemeChange() {
    if (readThemePreference() === 'system') applyThemePreference('system');
}

function handleStoredThemeChange(event) {
    if (event.key === THEME_STORAGE_KEY) applyThemePreference(event.newValue);
}

function initializeTheme() {
    if (!browserWindow || !browserDocument) return;
    setupThemeControls();
    applyThemePreference(readThemePreference(), { announce: false });
    if (systemLightQuery?.addEventListener) systemLightQuery.addEventListener('change', handleSystemThemeChange);
    else systemLightQuery?.addListener?.(handleSystemThemeChange);
    browserWindow.addEventListener('storage', handleStoredThemeChange);
}

initializeTheme();

if (browserWindow) {
    browserWindow.applyThemePreference = applyThemePreference;
}
