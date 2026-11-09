'use strict';

// The opener is needed only for the browser to copy same-origin session storage.
window.opener = null;

(async function launchHiddify() {
  const status = document.querySelector('#launch-status');
  try {
    const job = window.location.hash.slice(1);
    if (!/^[a-f0-9]{16}$/.test(job)) throw new Error('任务编号无效，请从 NetDeploy 的部署任务打开管理面板。');
    const token = sessionStorage.getItem('nd_token');
    if (!token) throw new Error('请登录 NetDeploy 后，从部署任务打开管理面板。');

    const response = await fetch('/api/jobs/' + job + '/hiddify-admin', {
      headers: {'X-Admin-Token': token}, cache: 'no-store',
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(typeof result.detail === 'string' ? result.detail : '无法读取 Hiddify 管理链接。');
    }
    const url = new URL(result.url);
    if (url.protocol !== 'https:' || url.username || url.password) throw new Error('Hiddify 管理链接格式无效。');

    status.textContent = result.tls_verified === false ? '浏览器可能提示证书风险。' : '正在打开 Hiddify…';
    window.location.replace(url.href);
  } catch (error) {
    status.textContent = error.message;
  }
})();
