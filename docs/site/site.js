/* Small, local-only handbook features. No analytics or remote scripts. */
(function () {
  'use strict';
  const $ = (selector) => document.querySelector(selector);
  const themeButton = $('#theme-toggle');
  const menu = $('#menu-toggle');
  const sidebar = $('#sidebar');
  const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  let remembered = null;
  try { remembered = localStorage.getItem('netdeploy-docs-theme'); } catch (_) { /* optional */ }
  function setTheme(mode) {
    document.documentElement.dataset.theme = mode;
    themeButton.setAttribute('aria-pressed', String(mode === 'dark'));
    themeButton.setAttribute('aria-label', mode === 'dark' ? '切换浅色主题' : '切换深色主题');
  }
  setTheme(['light', 'dark'].includes(remembered) ? remembered : (prefersDark ? 'dark' : 'light'));
  themeButton.addEventListener('click', function () {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    try { localStorage.setItem('netdeploy-docs-theme', next); } catch (_) { /* optional */ }
  });
  function closeMenu() {
    sidebar.classList.remove('is-open');
    menu.setAttribute('aria-expanded', 'false');
  }
  menu.addEventListener('click', function () {
    menu.setAttribute('aria-expanded', String(sidebar.classList.toggle('is-open')));
  });
  document.addEventListener('click', function (event) {
    if (!sidebar.contains(event.target) && !menu.contains(event.target)) closeMenu();
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && sidebar.classList.contains('is-open')) closeMenu();
  });
  for (const block of document.querySelectorAll('pre')) {
    const code = block.querySelector('code');
    if (!code) continue;
    const button = document.createElement('button');
    button.className = 'copy-button';
    button.type = 'button';
    button.textContent = '复制命令';
    button.setAttribute('aria-label', '复制代码块');
    block.prepend(button);
    button.addEventListener('click', async function () {
      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(code.textContent);
        } else {
          const range = document.createRange();
          range.selectNodeContents(code);
          const selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          if (!document.execCommand('copy')) throw Error('Clipboard unavailable');
          selection.removeAllRanges();
        }
        button.textContent = '已复制 ✓';
      } catch (_) {
        button.textContent = '请选中代码手动复制';
      }
      window.setTimeout(function () { button.textContent = '复制命令'; }, 2200);
    });
  }
  const searchDialog = $('#search-dialog');
  const searchInput = $('#search-input');
  const results = $('#search-results');
  const status = $('#search-status');
  let searchPromise = null;
  let currentSearch = 0;
  async function index() {
    if (!searchPromise) {
      searchPromise = fetch('search-index.json').then(function (response) {
        if (!response.ok) throw Error('Search index could not be loaded');
        return response.json();
      }).catch(function (error) { searchPromise = null; throw error; });
    }
    return searchPromise;
  }
  function openSearch() {
    closeMenu();
    if (!searchDialog.open) searchDialog.showModal();
    searchInput.focus();
    if (searchInput.value.trim()) search();
  }
  for (const node of document.querySelectorAll('[data-search-open]')) node.addEventListener('click', openSearch);
  $('#search-close').addEventListener('click', function () { searchDialog.close(); });
  searchDialog.addEventListener('click', function (event) {
    if (event.target === searchDialog) {
      const rect = searchDialog.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right ||
          event.clientY < rect.top || event.clientY > rect.bottom) searchDialog.close();
    }
  });
  document.addEventListener('keydown', function (event) {
    const editing = event.target.closest && event.target.closest('input, textarea, select, [contenteditable]');
    if ((event.key.toLowerCase() === 'k' && (event.ctrlKey || event.metaKey)) ||
        (event.key === '/' && !editing && !searchDialog.open)) {
      event.preventDefault();
      openSearch();
    }
  });
  const normalize = (value) => String(value || '').normalize('NFKC').toLowerCase();
  function searchTerms(value) {
    const phrases = normalize(value).match(/[\p{L}\p{N}]+/gu) || [];
    const terms = [];
    for (const phrase of phrases) {
      terms.push(phrase);
      if (/[\u3400-\u9fff]/u.test(phrase) && Array.from(phrase).length > 2) {
        const chars = Array.from(phrase);
        for (let i = 0; i < chars.length - 1; i++) terms.push(chars[i] + chars[i + 1]);
      }
    }
    return [...new Set(terms)];
  }
  async function search() {
    const searchId = ++currentSearch;
    const query = searchInput.value.trim();
    results.replaceChildren();
    if (!query) { status.textContent = '输入关键词查找步骤'; return; }
    status.textContent = '正在搜索…';
    try {
      const entries = await index();
      if (searchId !== currentSearch) return;
      const terms = searchTerms(query);
      const matches = entries.map(function (item) {
        const heading = normalize(item.title + ' ' + item.section);
        const body = normalize(item.text);
        const score = terms.reduce(function (sum, term) {
          return sum + (heading.includes(term) ? 24 : 0) + (body.includes(term) ? 3 : 0);
        }, 0);
        return {item: item, score: score};
      }).filter(function (item) { return item.score > 0; })
        .sort(function (a, b) { return b.score - a.score; }).slice(0, 12);
      status.textContent = matches.length ? '找到 ' + matches.length + ' 个相关章节' : '没有找到结果，可以换个短关键词试试';
      for (const match of matches) {
        const item = match.item;
        const link = document.createElement('a');
        link.href = item.url;
        link.className = 'search-result';
        const label = document.createElement('small');
        label.textContent = item.title;
        const title = document.createElement('strong');
        title.textContent = item.section;
        const excerpt = document.createElement('p');
        excerpt.textContent = item.text.slice(0, 120) + (item.text.length > 120 ? '…' : '');
        link.append(label, title, excerpt);
        results.append(link);
      }
    } catch (_) {
      if (searchId === currentSearch) status.textContent = '搜索加载失败，请使用左侧目录直接阅读。';
    }
  }
  searchInput.addEventListener('input', search);
  searchDialog.addEventListener('keydown', function (event) {
    const links = [...results.querySelectorAll('a')];
    const position = links.indexOf(document.activeElement);
    if (event.key === 'ArrowDown' && links.length) {
      event.preventDefault();
      links[(position + 1) % links.length].focus();
    } else if (event.key === 'ArrowUp' && links.length) {
      event.preventDefault();
      if (position <= 0) searchInput.focus();
      else links[position - 1].focus();
    } else if (event.key === 'Enter' && document.activeElement === searchInput && links.length) {
      event.preventDefault();
      links[0].click();
    }
  });
})();
