/* The installed client owns update URLs, downloads and installer execution. */
(() => {
  const bridge = window.netdeployDesktop && window.chrome?.webview;
  const versionButton = document.querySelector('#desktop-version');
  let status = 'idle', release = null, detail = '', received = 0, total = 0;
  const isOpen = () => !!document.querySelector('#desktop-update-panel');
  const send = action => bridge?.postMessage({type:'netdeploy-update', action, manual:action !== 'auto'});
  const size = bytes => (Number(bytes || 0) / 1048576).toFixed(1) + ' MB';
  const notes = text => String(text || '包含功能改进与问题修复。')
    .replace(/^#{1,6}\s+/gm, '').replace(/\*\*([^*]+)\*\*/g, '$1');

  function render() {
    let title = '检查更新', content = '', actions = '';
    if (!bridge) {
      content = '<p>在线更新在 Windows 客户端内使用。网页和源码用户可在 GitHub 下载最新安装包或按文档更新。</p>';
      actions = '<a class="btn primary" href="https://github.com/slobys/netdeploy-ai/releases/latest" target="_blank" rel="noopener noreferrer">查看最新版本 ↗</a>';
    } else if (status === 'checking' || status === 'idle') {
      content = '<p role="status">正在检查 GitHub 上的最新版本…</p>';
    } else if (status === 'available') {
      title = '发现新版本 v' + release.version;
      content = `<p>当前版本 v${escapeHtml(CLIENT_VERSION)} · 更新包 ${size(release.size)}</p>
        <div class="update-notes">${escapeHtml(notes(release.notes))}</div>
        <p class="helptext">更新前会备份本机数据，安装完成后自动重启。VPS、任务、ChatGPT 登录和窗口大小会保留。</p>`;
      actions = '<button type="button" class="btn subtle" data-update-action="later">稍后再说</button><button type="button" class="btn primary" data-update-action="install">下载并更新</button>';
    } else if (status === 'downloading') {
      title = '正在下载更新';
      const percent = total ? Math.min(100, Math.round(received / total * 100)) : 0;
      content = `<p id="update-progress-text" role="status">${size(received)} / ${size(total)} · ${percent}%</p>
        <progress id="update-progress" class="update-progress" value="${percent}" max="100" aria-label="更新下载进度">${percent}%</progress>
        <p class="helptext">下载完成后校验安装包，再备份、安装并重启客户端。</p>`;
      actions = '<button type="button" class="btn subtle" data-update-action="cancel">取消下载</button>';
    } else if (status === 'installing') {
      title = '正在安装更新';
      content = '<p role="status">正在备份并安装新版，客户端将自动关闭、重新打开。</p><p class="helptext">请稍候，数据和登录信息会保留。</p>';
    } else if (status === 'current') {
      title = '已是最新版本';
      content = `<p>你正在使用 NetDeploy AI v${escapeHtml(CLIENT_VERSION)}。</p><p class="helptext">每次打开客户端会自动检查，也可以随时点击顶部版本号。</p>`;
      actions = '<button type="button" class="btn subtle" data-update-action="check">重新检查</button>';
    } else {
      title = status === 'cancelled' ? '已取消下载' : '暂时无法更新';
      content = `<p class="${status === 'cancelled' ? '' : 'update-error'}" role="status">${escapeHtml(detail || '下载已取消，当前版本可以继续使用。')}</p>`;
      actions = status === 'cancelled' && release
        ? '<button type="button" class="btn primary" data-update-action="install">重新下载</button>'
        : '<button type="button" class="btn primary" data-update-action="check">重新检查</button>';
    }
    if (!['available','installing','downloading'].includes(status) || !bridge)
      actions += '<button type="button" class="btn subtle" data-update-action="later">关闭</button>';
    dialog(modalHead(title, true) + `<section id="desktop-update-panel" class="desktop-update-panel">${content}<div class="modal-actions">${actions}</div></section>`);
  }

  function check() {
    if (['downloading','installing'].includes(status)) { render(); return; }
    state.activeJob = null;
    status = 'checking'; detail = ''; render();
    if (bridge) send('check');
  }

  versionButton?.addEventListener('click', () => {
    if (status === 'available') { state.activeJob = null; render(); }
    else check();
  });
  document.addEventListener('click', event => {
    const action = event.target.closest('[data-update-action]')?.dataset.updateAction;
    if (!action) return;
    if (action === 'later') closeDialog();
    else if (action === 'check') check();
    else if (action === 'cancel') send('cancel');
    else if (action === 'install' && !['downloading','installing'].includes(status)) {
      status = 'downloading'; received = 0; total = release?.size || 0; render(); send('install');
    }
  });
  if (!bridge) return;
  bridge.addEventListener('message', event => {
    const message = event.data;
    if (message?.type !== 'netdeploy-update' || message.status === 'busy') return;
    status = message.status;
    if (status === 'available') {
      release = message.info;
      if (!release || !/^\d+\.\d+\.\d+$/.test(release.version)) return;
      versionButton?.classList.add('has-update');
      versionButton?.setAttribute('title', `发现新版本 v${release.version}，点击更新`);
    }
    if (status === 'current') {
      release = null; versionButton?.classList.remove('has-update');
      versionButton?.setAttribute('title', '检查更新');
    }
    if (status === 'downloading') { received = message.info?.received || 0; total = message.info?.total || 0; }
    if (status === 'error') detail = message.info?.message || '请检查网络连接后重试。';
    if (status === 'cancelled') detail = '';
    if (isOpen() && status === 'downloading' && document.querySelector('#update-progress')) {
      document.querySelector('#update-progress').value = total ? Math.min(100, Math.round(received / total * 100)) : 0;
      document.querySelector('#update-progress-text').textContent = `${size(received)} / ${size(total)} · ${document.querySelector('#update-progress').value}%`;
    }
    else if (isOpen()) render();
    else if (status === 'available' && document.querySelector('#modal')?.classList.contains('hidden')) render();
    else if (status === 'available') toast(`发现新版本 v${release.version}，可点击顶部版本号更新`);
    else if (status === 'error' && message.manual) toast(detail, true);
  });
  // The native window deduplicates this check across page reloads.
  setTimeout(() => bridge.postMessage({type:'netdeploy-update',action:'check',manual:false}), 1500);
})();
