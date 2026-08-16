import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import test from 'node:test';

const root = resolve(import.meta.dirname, '..');
const text = path => readFile(resolve(root, path), 'utf8');

function luminance(hex) {
    const channels = hex.slice(1).match(/../g).map(value => {
        const channel = parseInt(value, 16) / 255;
        return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrast(foreground, background) {
    const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
    return (values[0] + 0.05) / (values[1] + 0.05);
}

test('appearance is applied before CSS and defaults safely to dark', async () => {
    const [html, main, serviceWorker] = await Promise.all([
        text('index.html'), text('js/main.js'), text('service-worker.js')
    ]);
    const bootstrap = html.indexOf("var key = 'fluency_theme_preference_v1'");
    const baseCss = html.indexOf('href="css/style.css?v=');
    const lightCss = html.indexOf('href="css/light-theme.css?v=');

    assert.ok(bootstrap > 0 && bootstrap < baseCss, 'theme bootstrap must run before CSS');
    assert.ok(baseCss < lightCss, 'light overrides must load after the base theme');
    assert.match(html, /var preference = 'dark'/);
    assert.match(html, /saved === 'dark' \|\| saved === 'light' \|\| saved === 'system'/);
    assert.match(html, /matchMedia\('\(prefers-color-scheme: light\)'\)/);
    assert.match(html, /root\.dataset\.theme = theme/);
    assert.match(html, /rel="modulepreload" href="js\/theme\.js\?v=/);
    assert.match(main, /^import '\.\/theme\.js\?v=/m);
    assert.match(serviceWorker, /`\/css\/light-theme\.css\?v=\$\{ASSET_VERSION\}`/);
    assert.match(serviceWorker, /`\/js\/theme\.js\?v=\$\{ASSET_VERSION\}`/);
});

test('Settings exposes an accessible three-way appearance choice', async () => {
    const html = await text('index.html');
    assert.match(html, /class="appearance-settings-card"[^>]*aria-labelledby="appearanceSettingsTitle"/);
    assert.match(html, /class="group-size-selector settings-toggle appearance-selector"\s+role="radiogroup"/);
    for (const preference of ['dark', 'light', 'system']) {
        assert.match(html, new RegExp(`data-theme-preference="${preference}"[^>]*role="radio"`));
    }
    assert.match(html, /System follows this device’s light or dark setting/);
});

test('light appearance is a semantic palette rather than an inversion', async () => {
    const [css, ui] = await Promise.all([text('css/light-theme.css'), text('js/ui.js')]);
    const variable = name => {
        const match = css.match(new RegExp(`--${name}:\\s*(#[0-9a-f]{6})`, 'i'));
        assert.ok(match, `missing --${name}`);
        return match[1];
    };

    assert.doesNotMatch(css, /filter:\s*invert/i);
    assert.match(css, /:root\[data-theme="light"\] body\.artist-mode \.card-face::after/);
    assert.match(css, /:root\[data-theme="light"\] #authModal/);
    assert.match(css, /:root\[data-theme="light"\] \.study-radial-picker/);
    assert.match(css, /:root\[data-theme="light"\] \.meaning-pos-section \.meaning-row/);
    assert.match(css, /:root\[data-theme="light"\] \.pos-noun/);
    assert.match(css, /:root\[data-theme="light"\] \.setup-step/);
    assert.match(css, /:root\[data-theme="light"\] \.study-set-dot/);
    assert.match(ui, /const onLightAccent = '#17212b'/);

    const card = variable('bg-card');
    assert.equal(variable('bg-primary'), '#eef2f5', 'light canvas should use a cool daylight neutral');
    assert.equal(card, '#ffffff', 'primary working surfaces should remain crisp white');
    for (const name of ['text-primary', 'text-secondary', 'text-muted', 'success', 'error', 'warning']) {
        assert.ok(contrast(variable(name), card) >= 4.5, `${name} must meet WCAG AA on cards`);
    }
    assert.ok(contrast(variable('text-muted'), variable('bg-tertiary')) >= 4.5,
        'muted text must remain readable on the darkest light-theme neutral');
    assert.ok(contrast('#17212b', '#ffcc00') >= 4.5, 'dark ink must remain readable on Spanish yellow');

    const posColours = [...css.matchAll(/\.pos-[\w-]+\s*\{[^}]*color:\s*(#[0-9a-f]{6})\s*!important/gi)];
    assert.equal(posColours.length, 21, 'every light POS family must defeat dark-mode white text specificity');
    for (const [, colour] of posColours) {
        assert.ok(contrast(colour, card) >= 4.5, `${colour} POS ink must meet WCAG AA on light cards`);
    }
});

test('light appearance replaces dark-only white chrome on every major sheet', async () => {
    const css = await text('css/light-theme.css');
    const requiredOverrides = [
        '.flag-menu-sense',
        '.cbs-return',
        '.cbp-pip.is-current',
        '.deck-progress-segment.is-current',
        '.knowledge-overview-sheet',
        '.syn-headword',
        '.syn-tab.selected',
        '.conj-mood-toggle-btn.conj-mood-toggle-active',
        '.conj-table tr.conj-active .conj-ending',
        '.provenance-panel .prov-meta code',
        '.link-btn',
        '.breakdown-btn'
    ];

    for (const selector of requiredOverrides) {
        assert.ok(css.includes(`:root[data-theme="light"] ${selector}`), `missing light contrast override for ${selector}`);
    }
});

test('theme module persists choices, follows the system, and synchronizes controls', async () => {
    const saved = new Map();
    const windowListeners = {};
    const mediaListeners = {};
    const events = [];
    const media = {
        matches: false,
        addEventListener(type, listener) { mediaListeners[type] = listener; }
    };

    class FakeButton {
        constructor(preference) {
            this.dataset = { themePreference: preference };
            this.classes = new Set(['theme-preference-btn']);
            this.attributes = {};
            this.listeners = {};
            this.tabIndex = -1;
            this.classList = {
                toggle: (name, enabled) => enabled ? this.classes.add(name) : this.classes.delete(name)
            };
        }
        addEventListener(type, listener) { this.listeners[type] = listener; }
        setAttribute(name, value) { this.attributes[name] = value; }
        focus() { this.focused = true; }
    }

    const buttons = ['dark', 'light', 'system'].map(value => new FakeButton(value));
    const meta = { content: '#0a0e14' };
    const documentElement = { dataset: {}, style: {} };

    globalThis.window = {
        localStorage: {
            getItem: key => saved.get(key) ?? null,
            setItem: (key, value) => saved.set(key, value)
        },
        matchMedia: () => media,
        addEventListener(type, listener) { windowListeners[type] = listener; },
        dispatchEvent(event) { events.push(event); }
    };
    globalThis.document = {
        documentElement,
        querySelector: selector => selector === 'meta[name="theme-color"]' ? meta : null,
        querySelectorAll: selector => selector === '.theme-preference-btn' ? buttons : []
    };
    globalThis.CustomEvent = class {
        constructor(type, options) { this.type = type; this.detail = options.detail; }
    };

    try {
        const moduleUrl = `${pathToFileURL(resolve(root, 'js/theme.js')).href}?runtime-test`;
        const theme = await import(moduleUrl);

        assert.deepEqual(theme.resolveTheme('system', true), 'light');
        assert.deepEqual(theme.resolveTheme('system', false), 'dark');
        assert.equal(theme.normalizeThemePreference('unknown'), 'dark');
        assert.equal(documentElement.dataset.theme, 'dark');
        assert.equal(buttons[0].attributes['aria-checked'], 'true');

        buttons[1].listeners.click();
        assert.equal(saved.get(theme.THEME_STORAGE_KEY), 'light');
        assert.equal(documentElement.dataset.theme, 'light');
        assert.equal(documentElement.style.colorScheme, 'light');
        assert.equal(meta.content, '#eef2f5');
        assert.equal(buttons[1].attributes['aria-checked'], 'true');

        buttons[2].listeners.click();
        assert.equal(documentElement.dataset.themePreference, 'system');
        assert.equal(documentElement.dataset.theme, 'dark');
        media.matches = true;
        mediaListeners.change();
        assert.equal(documentElement.dataset.theme, 'light');

        windowListeners.storage({ key: theme.THEME_STORAGE_KEY, newValue: 'dark' });
        assert.equal(documentElement.dataset.theme, 'dark');
        assert.ok(events.some(event => event.type === 'fluency-theme-change'));
    } finally {
        delete globalThis.window;
        delete globalThis.document;
        delete globalThis.CustomEvent;
    }
});
