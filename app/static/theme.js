/* NetDeploy AI appearance controller. Runs synchronously in <head> before CSS.
   Only saves harmless local UI preferences; never touches application sessions. */
(() => {
  'use strict';
  const MODES = new Set(['dark', 'light', 'system']);
  const COLORS = new Set(['blue', 'violet', 'teal', 'emerald', 'rose', 'amber']);
  const MODE_KEY = 'netdeploy-ui-mode-v1';
  const COLOR_KEY = 'netdeploy-ui-color-v1';
  const DEFAULT_MODE = 'dark'; // Preserve the existing dark-blue appearance.
  const DEFAULT_COLOR = 'blue';
  const names = {
    blue: '经典蓝', violet: '极光紫', teal: '海洋青',
    emerald: '翡翠绿', rose: '玫瑰粉', amber: '暖日橙'
  };

  const root = document.documentElement;
  let media = null;
  try { media = window.matchMedia('(prefers-color-scheme: dark)'); } catch (_) { /* fallback */ }
  function read(key, allowed, fallback) {
    try {
      const value = window.localStorage.getItem(key);
      return allowed.has(value) ? value : fallback;
    } catch (_) {
      return fallback;
    }
  }
  function save(key, value) {
    try { window.localStorage.setItem(key, value); } catch (_) { /* private browsing */ }
  }
  let mode = read(MODE_KEY, MODES, DEFAULT_MODE);
  let color = read(COLOR_KEY, COLORS, DEFAULT_COLOR);

  function resolvedMode() {
    return mode === 'system' ? (media?.matches ? 'dark' : 'light') : mode;
  }
  function apply() {
    root.dataset.appearance = resolvedMode();
    root.dataset.themeMode = mode;
    root.dataset.accent = color;
  }
  apply(); // Prevent flash of the old theme on reload.

  function mount() {
    const button = document.getElementById('theme-menu-button');
    const panel = document.getElementById('theme-menu');
    const control = document.getElementById('theme-control');
    const status = document.getElementById('theme-status');
    if (!button || !panel || !control || !status) return;

    const modeButtons = [...panel.querySelectorAll('[data-theme-mode]')];
    const colorButtons = [...panel.querySelectorAll('[data-theme-color]')];
    function sync() {
      modeButtons.forEach((item) => {
        const selected = item.dataset.themeMode === mode;
        item.setAttribute('aria-pressed', String(selected));
        item.classList.toggle('selected', selected);
      });
      colorButtons.forEach((item) => {
        const selected = item.dataset.themeColor === color;
        item.setAttribute('aria-pressed', String(selected));
        item.classList.toggle('selected', selected);
      });
      const modeText = mode === 'system' ? '跟随系统' : mode === 'light' ? '明亮' : '暗黑';
      status.textContent = modeText + ' · ' + names[color];
      button.setAttribute('aria-label', '外观主题设置，当前' + status.textContent);
    }
    function open(value, restoreFocus = false) {
      panel.hidden = !value;
      button.setAttribute('aria-expanded', String(value));
      if (!value && restoreFocus) button.focus();
    }
    button.setAttribute('aria-expanded', String(!panel.hidden));
    button.addEventListener('click', () => open(panel.hidden));
    for (const item of modeButtons) {
      item.addEventListener('click', () => {
        const next = item.dataset.themeMode;
        if (!MODES.has(next)) return;
        mode = next;
        apply();
        save(MODE_KEY, mode);
        sync();
      });
    }
    for (const item of colorButtons) {
      item.addEventListener('click', () => {
        const next = item.dataset.themeColor;
        if (!COLORS.has(next)) return;
        color = next;
        apply();
        save(COLOR_KEY, color);
        sync();
      });
    }
    document.addEventListener('pointerdown', (event) => {
      if (!panel.hidden && !control.contains(event.target)) open(false);
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && !panel.hidden) {
        event.preventDefault();
        open(false, true);
      }
    });
    // OS theme changes work live only when system mode is selected.
    function onSystemChange() {
      if (mode === 'system') {
        apply();
        sync();
      }
    }
    if (media) {
      if (typeof media.addEventListener === 'function') media.addEventListener('change', onSystemChange);
      else if (typeof media.addListener === 'function') media.addListener(onSystemChange);
    }
    window.addEventListener('storage', (event) => {
      if (event.key !== MODE_KEY && event.key !== COLOR_KEY && event.key !== null) return;
      mode = read(MODE_KEY, MODES, DEFAULT_MODE);
      color = read(COLOR_KEY, COLORS, DEFAULT_COLOR);
      apply();
      sync();
    });
    sync();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount, {once:true});
  } else {
    mount();
  }
})();
