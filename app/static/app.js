/* NetDeploy AI v0.3.4 – no external JavaScript, no generated remote shell. */
const el = (s) => document.querySelector(s);
const escapeHtml = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {token:sessionStorage.getItem('nd_token')||'', hosts:[], jobs:[], catalog:{}, capabilities:{secure_password_storage:false}, section:'dashboard', activeJob:null, hostPanel:null, pendingFingerprint:null, loading:false, lastSnapshot:null};

async function api(path, opts={}) {
  const resp = await fetch('/api'+path,{...opts,headers:{'X-Admin-Token':state.token,...(opts.body?{'Content-Type':'application/json'}:{}),...(opts.headers||{})},cache:'no-store'});
  let data;
  try{data=await resp.json();}catch{data={detail:`HTTP ${resp.status}`};}
  if(!resp.ok){if(resp.status===401){sessionStorage.removeItem('nd_token');state.token='';el('#login').classList.remove('hidden');}throw Error(typeof data.detail==='string'?data.detail:`操作失败 (${resp.status})`);}
  return data;
}
let toastTimer=null;
function toast(message,bad=false){
 const t=el('#toast');
 if(!t)return;
 clearTimeout(toastTimer);
 const working=/^正在|^扫描中|^连接中/.test(message);
 t.textContent=(bad?'⚠  ':working?'◌  ':'✓  ')+message;
 t.className='toast'+(bad?' bad':working?' progress':'');
 t.setAttribute('role',bad?'alert':'status');
 t.setAttribute('aria-live',bad?'assertive':'polite');
 toastTimer=setTimeout(()=>t.classList.add('hidden'),bad?9500:5300);
}
function dialog(content){el('#modal-content').innerHTML=content;el('#modal').classList.remove('hidden');}
function closeDialog(){el('#modal').classList.add('hidden');el('#modal-content').innerHTML='';}
function modalHead(title,isRoot=false){const back=state.hostPanel&&!isRoot?`<button class="server-back" data-action="back-host" data-id="${state.hostPanel.id}">← 返回这台服务器</button>`:"";return `<div class="modal-header"><div><h2>${escapeHtml(title)}</h2>${back}</div><button class="close" type="button" data-action="close-modal" aria-label="关闭">×</button></div>`;}
async function loadAll(silent=false){
  if(state.loading||!state.token)return;
  state.loading=true;
  try {
    const [hosts,jobs,catalog,capabilities] = await Promise.all([api('/hosts'),api('/jobs'),api('/catalog'),api('/capabilities')]);
    const snapshot=JSON.stringify([hosts,jobs,catalog,capabilities]);
    const changed=snapshot!==state.lastSnapshot;
    state.hosts=hosts;state.jobs=jobs;state.catalog=catalog;state.capabilities=capabilities;state.lastSnapshot=snapshot;
    if(changed)render();
    if(!silent)toast('控制台已刷新');
    if(state.activeJob && !el('#modal').classList.contains('hidden')) {
      const active=state.jobs.find(j=>j.id===state.activeJob);
      if(active && ['running','queued','completed','partial','failed','interrupted','invalidated'].includes(active.status)){
        const logbox=el('#task-log'); if(logbox){
          logbox.textContent=active.logs || '还没有执行日志'; el('#job-state').textContent=stateText(active.status);
          if(['3x-ui','3x-ui-https'].includes(active.project)&&active.status==='completed'&&!el('[data-action="xui-access"]'))showJob(active.id);
        }
      }
    }
  } catch(err){if(!silent)toast(err.message,true);} finally{state.loading=false;}
}
function stateText(status){return ({planned:'等待审批',queued:'已排队',running:'正在执行',completed:'执行完成',failed:'执行失败',interrupted:'执行中断',partial:'3X-UI 已装，HTTPS 待修复',invalidated:'服务器已重装，计划失效'})[status]||status;}
function chip(status){const cls=status==='completed'?'success':status==='failed'||status==='interrupted'||status==='invalidated'?'error':'warn';return `<span class="chip ${cls}">${escapeHtml(stateText(status))}</span>`;}
const symbol={"3x-ui":"▣","3x-ui-https":"🔒","sing-box":"⬡","hysteria2":"ϟ","wg-easy":"◈"};
function render(){
 const {hosts,jobs,catalog}=state;
 el('#stats').innerHTML = [
  ['已添加服务器',hosts.length,'▤','已通过 SSH 扫描 '+hosts.filter(h=>!!h.facts).length+' 台'],
  ['项目模板',Object.values(catalog).filter(p=>!p.internal).length,'⬡','固定、可审核的部署计划'],
  ['完成任务',jobs.filter(j=>j.status==='completed').length,'✓','安装完成仍需业务配置'],
  ['待处理任务',jobs.filter(j=>['failed','interrupted','planned'].includes(j.status)).length,'⌁','需确认或排障的任务']
 ].map(([label,val,ico,desc])=>`<div class="stat"><div class="top"><span>${label}</span><span class="icon">${ico}</span></div><strong>${val}</strong><small>${desc}</small></div>`).join('');
 el('#project-grid').innerHTML = Object.entries(catalog).filter(([_,p])=>!p.internal).map(([key,p])=>`
 <div class="project"><div class="project-head"><div class="project-icon">${symbol[key]}</div><span class="project-kind">${escapeHtml(p.category)}</span></div>
 <h3>${escapeHtml(p.name)}</h3><p>${escapeHtml(p.subtitle)}</p><div class="project-footer">
 <span class="status ${p.deployment==='install'?'':'muted'}">${p.deployment==='install'?'自动安装 Beta':'方案引导'}</span>
 <button class="btn subtle" data-action="plan" data-project="${escapeHtml(key)}">${p.deployment==='install'?'部署项目':'查看方案'} →</button></div></div>`).join('');
 el('#host-list').innerHTML=hosts.length?hosts.map(h=>{
   const duplicate=hosts.filter(x=>x.hostname.toLowerCase()===h.hostname.toLowerCase()&&x.port===h.port).length;
   const status=!h.credential_ready?'需要登录凭据':h.facts?'最近检测成功':'待连接检测';
   const statusClass=!h.credential_ready?'error':h.facts?'success':'warn';
   return `<article class="host-item interactive-card" role="button" tabindex="0" data-action="host-console" data-id="${h.id}" aria-label="打开 ${escapeHtml(h.name)} 的服务器控制台">
      <div class="host-card-top"><div class="host-icon">▤</div><div class="host-title"><b>${escapeHtml(h.name)}</b><span class="chip ${statusClass}">${status}</span></div><span class="host-card-open">管理服务器 →</span></div>
      <div class="host-card-address">${escapeHtml(h.username)}@${escapeHtml(h.hostname)}:${h.port}</div>
      <div class="host-card-meta"><span>${h.facts?escapeHtml(h.facts.OS_ID)+' / '+escapeHtml(h.facts.ARCH):'等待系统识别'}</span><span>${h.auth_mode==='password'?(h.password_remembered?'密码已安全保存':'密码登录'):'密钥登录'}</span><span>${h.job_count||0} 条任务</span></div>
      ${duplicate>1?`<span class="host-card-hint">${duplicate} 条记录共用此 SSH 地址</span>`:''}
    </article>`;
 }).join(''):`<div class="empty"><span class="empty-icon">▤</span><span>还没有 VPS。添加后点击卡片，即可在同一个控制台管理连接、部署与端口。</span><button class="btn primary" data-action="add-host">＋ 添加第一台 VPS</button></div>`;
 el('#job-list').innerHTML=jobs.length?jobs.map(j=>{const p=catalog[j.project]||{};const host=hosts.find(h=>h.id===j.host_id);return `<div class="job-item"><div class="job-icon">${symbol[j.project]||'⋄'}</div><div class="job-main"><b>${escapeHtml(p.name||j.project)} · ${escapeHtml(host?.name||j.plan.hostname)}</b><small>${escapeHtml(j.created_at.replace('T',' ').slice(0,19))} UTC · 任务 #${escapeHtml(j.id)}</small></div>${chip(j.status)}<button class="btn subtle" data-action="job" data-id="${escapeHtml(j.id)}">查看详情</button>${["queued","running"].includes(j.status)?"":`<button class="btn subtle" data-action="delete-job" data-id="${escapeHtml(j.id)}">删除</button>`}</div>`;}).join(''):`<div class="empty"><span class="empty-icon">≡</span><span>还没有部署任务。选择项目即可生成审批计划。</span></div>`;
 renderSection();
}
function renderSection(){
 const navName={dashboard:['总览面板','运行概览','集中管理服务器与自动化部署任务'],projects:['项目中心','项目中心','所有项目均使用审计过的执行模板'],hosts:['服务器管理','服务器管理','通过 SSH 连接可信的 Linux VPS'],jobs:['部署任务','部署任务','所有任务状态、审批和执行日志']};
 const [title,heading,sub]=navName[state.section];el('#crumb-current').textContent=title;el('#section-title').textContent=heading;el('#section-subtitle').textContent=sub;
 document.querySelectorAll('[data-nav]').forEach(b=>b.classList.toggle('active',b.classList.contains('nav-item')&&b.dataset.nav===state.section));
 el('#hero').classList.toggle('hidden',state.section!=='dashboard');el('#stats').classList.toggle('hidden',state.section!=='dashboard');
 el('#projects-section').classList.toggle('hidden',!['dashboard','projects'].includes(state.section));
 el('#hosts-section').classList.toggle('hidden',!['dashboard','hosts'].includes(state.section));
 el('#jobs-section').classList.toggle('hidden',!['dashboard','jobs'].includes(state.section));
 el('#main-cta').classList.toggle('hidden',!['dashboard','hosts'].includes(state.section));
}
function hostTaskLink(job){
 return `<button class="server-history-item" data-action="job" data-id="${escapeHtml(job.id)}"><span>${escapeHtml(state.catalog[job.project]?.name||job.project)}</span>${chip(job.status)}<small>${escapeHtml(job.created_at.slice(0,16).replace('T',' '))}</small></button>`;
}
function openHostConsole(id,tab='overview'){
 const host=state.hosts.find(h=>h.id===id);if(!host){toast('VPS 已不存在，请刷新',true);return;}
 state.hostPanel={id,tab};state.activeJob=null;
 const tabs=[['overview','概览'],['deploy','项目部署'],['network','端口 / 防火墙'],['security','连接安全'],['settings','编辑 / 删除']];
 const connected=Boolean(host.facts);
 const related=state.jobs.filter(j=>j.host_id===id).slice(0,5);
 const card=(label,value)=>`<div class="server-kpi"><span>${label}</span><strong>${escapeHtml(value)}</strong></div>`;
 let content='';
 if(tab==='overview'){
   content=`<div class="server-panel-grid">
      ${card('服务器地址',host.hostname+':'+host.port)}
      ${card('SSH 登录',host.auth_mode==='password'?(host.password_remembered?'密码已保存在系统':'密码登录'):'私钥登录')}
      ${card('系统与架构',connected?(host.facts.OS_ID+' / '+host.facts.ARCH):'等待检测')}
      ${card('部署任务',String(host.job_count||0))}
    </div>
    <div class="server-action-grid">
     <button class="btn primary" data-action="host-check" data-id="${id}">↻ 检测 SSH 与系统</button>
     <button class="btn primary-soft" data-action="host-tab" data-id="${id}" data-tab="deploy">▣ 选择项目部署</button>
     <button class="btn subtle" data-action="host-tab" data-id="${id}" data-tab="network">◈ 放行指定端口</button>
     <button class="btn subtle" data-action="host-tab" data-id="${id}" data-tab="security">◇ 指纹与密码</button>
    </div>
    <div class="server-panel-section"><h3>最近的部署任务</h3>${related.length?related.map(hostTaskLink).join(''):'<p class="helptext">暂无部署历史。选择项目后，环境检查和配置会自动执行。</p>'}</div>`;
 }else if(tab==='deploy'){
   const visible=Object.entries(state.catalog).filter(([_,project])=>!project.internal);
   content=`<p class="helptext">只选择要安装的项目。NetDeploy 自动检测系统，识别已有安装，准备 HTTPS 和本机端口。执行前仅需一次确认。</p>
   <div class="server-project-grid">${visible.map(([key,project])=>`<button class="server-project-choice" data-action="server-install" data-id="${id}" data-project="${escapeHtml(key)}">
    <span class="project-choice-icon">${symbol[key]}</span><strong>${escapeHtml(project.name)}</strong><small>${escapeHtml(project.subtitle)}</small>
    <span class="project-choice-link">${project.deployment==='install'?'部署 / 继续配置':'查看方案'} →</span></button>`).join('')}</div>`;
 }else if(tab==='network'){
   content=`<div class="modal-tip"><b>仅管理 VPS 自身的 UFW 防火墙。</b> 你可以直接放行 TCP 或 UDP 端口，系统不会关闭整个防火墙。云厂商安全组必须单独允许入站流量，否则公网仍无法访问。</div>
    <div id="server-firewall-status" class="server-status-panel"><span class="inline-spinner"></span> 正在通过 SSH 读取 UFW 状态…</div>
    <form id="server-allow-form"><div class="form-2">
      <div class="form-group"><label>需要放行的端口</label><input name="port" type="number" min="1" max="65535" value="80" required/></div>
      <div class="form-group"><label>协议</label><select name="protocol"><option value="tcp">TCP</option><option value="udp">UDP</option></select></div>
    </div><div class="modal-actions"><button type="submit" class="btn primary">放行该端口</button></div></form>
    <p class="helptext">3X-UI 自动部署时，会尝试为证书验证放行本机 TCP 80，并在证书验证成功后放行管理端口。云厂商安全组不受本机 UFW 控制。</p>`;
 }else if(tab==='security'){
   content=`<p class="helptext">同一 IP/端口的服务器记录共用 SSH 主机指纹。VPS 重装后不需要清空 known_hosts，只需独立核对新的指纹。</p>
   <div class="server-action-grid">
      <button class="btn primary" data-action="fingerprint" data-id="${id}">核对指纹 / 服务器重装</button>
      <button class="btn subtle" data-action="credentials" data-id="${id}">修改 SSH 登录密码或密钥</button>
      <button class="btn subtle" data-action="host-check" data-id="${id}">测试 SSH 连接</button>
   </div><div class="modal-tip warning">如果服务器返回的主机指纹发生变化，必须通过 VPS 云厂商的独立控制台核对，不能为了省步骤而自动覆盖。</div>`;
 }else{
   content=`<div class="server-action-grid">
      <button class="btn subtle" data-action="edit-host" data-id="${id}">编辑 VPS 名称与连接信息</button>
      <button class="btn danger" data-action="delete-host" data-id="${id}">删除本地 VPS 记录</button>
   </div><div class="modal-tip">删除 VPS 不会卸载远端程序。存在部署历史时，需明确确认是否一并删除历史与日志。</div>`;
 }
 const header=`<div class="server-console"><div class="server-console-head"><div><span class="server-eyebrow">VPS WORKSPACE</span>
   <h3>${escapeHtml(host.name)}</h3><p>${escapeHtml(host.username)}@${escapeHtml(host.hostname)}:${host.port}</p></div>
   <span class="chip ${host.credential_ready?(connected?'success':'warn'):'error'}">${host.credential_ready?(connected?'环境曾检测通过':'待检测'):'凭据不可用'}</span></div>
   <nav class="server-tabs" aria-label="服务器操作">${tabs.map(([name,label])=>`<button type="button" class="server-tab ${tab===name?'active':''}" data-action="host-tab" data-id="${id}" data-tab="${name}">${label}</button>`).join('')}</nav>
   <div class="server-tab-content">${content}</div></div>`;
 dialog(modalHead('VPS 服务器控制台',true)+header);
 if(tab==='network'){
   refreshFirewallUI(id);
   el('#server-allow-form')?.addEventListener('submit',async e=>{
     e.preventDefault();const form=e.currentTarget;const fd=new FormData(form);
     const btn=form.querySelector('button[type="submit"]');btn.disabled=true;btn.classList.add('is-loading');
     const port=Number(fd.get('port'));const protocol=String(fd.get('protocol'));
     toast(`正在设置 UFW ${port}/${protocol}…`);
     try{const res=await api(`/hosts/${id}/firewall/allow`,{method:'POST',body:JSON.stringify({port,protocol,confirmation:true})});
       toast(res.mode==='active'?`UFW 已放行 ${port}/${protocol}，云安全组仍需单独放行`:'UFW 未启用或不可用，无需新增本机规则；仍需确认云安全组');
       await refreshFirewallUI(id);
     }catch(err){toast(err.message,true);}finally{if(btn.isConnected){btn.disabled=false;btn.classList.remove('is-loading');}}
   });
 }
}
async function refreshFirewallUI(id){
 const target=el('#server-firewall-status');if(!target)return;
 try{const result=await api(`/hosts/${id}/firewall`);
   if(!target.isConnected)return;
   const headline={active:'UFW 已启用',inactive:'UFW 未启用',unavailable:'未安装 UFW',unknown:'无法确认 UFW 状态'}[result.status]||'未知状态';
   target.innerHTML=`<strong>${headline}</strong><pre class="pre">${escapeHtml(result.details)}</pre><p class="helptext">${escapeHtml(result.cloud_notice)}</p>`;
 }catch(err){if(target.isConnected)target.innerHTML=`<div class="modal-tip warning">${escapeHtml(err.message)}</div>`;}
}
async function checkHostInConsole(id){
 const target=el('.server-tab-content');if(target)target.insertAdjacentHTML('afterbegin','<div class="modal-tip server-check-running">正在通过已验证的 SSH 读取服务器环境…</div>');
 try{await api(`/hosts/${id}/preflight`,{method:'POST'});await loadAll(true);openHostConsole(id,'overview');toast('连接检测成功，系统信息已更新');}
 catch(err){el('.server-check-running')?.remove();toast(err.message,true);}
}
async function createHostPlan(id,project){
 const host=state.hosts.find(h=>h.id===id);if(!host)return;
 const source=project==='3x-ui'?state.jobs.find(j=>j.project==='3x-ui'&&j.host_id===id&&['completed','partial'].includes(j.status)&& (j.plan.trust_epoch||0)===(host.trust_epoch||0)):null;
 if(source){
   const upgraded=source.status==='completed'&&source.plan.options?.access_mode==='https'||
     state.jobs.some(j=>j.project==='3x-ui-https'&&j.host_id===id&&j.status==='completed'&&j.plan.options?.source_job_id===source.id);
   if(upgraded){showJob(source.id);toast('检测到已完成的 3X-UI，打开现有部署记录');return;}
   await xuiUpgrade(source.id);return;
 }
 toast('正在自动检测环境并生成安全方案…');
 try{const payload={host_id:id,project};if(project==='3x-ui'){payload.panel_port=24443;payload.access_mode='https';}
   const job=await api('/jobs',{method:'POST',body:JSON.stringify(payload)});state.activeJob=null;
   await loadAll(true);if(!state.jobs.some(j=>j.id===job.id))state.jobs.unshift(job);showJob(job.id);
 }catch(err){toast(err.message,true);}
}
function authSelect(current='password',remembered=false) {
 const native=state.capabilities.secure_password_storage;
 const rememberUI=native
   ? `<label class="check"><input type="checkbox" name="remember_password" ${remembered?'checked':''}/> 保存到 Windows 系统凭据库（以后更新、重启免输密码）</label>`
   : '<div class="modal-tip">此设备没有可用的 Windows 凭据保管库，密码仅保存在当前进程内存；建议使用 SSH 密钥登录。</div>';
 return `<div class="form-group"><label>SSH 登录方式</label><select name="auth_mode" id="auth-mode"><option value="password" ${current==='password'?'selected':''}>SSH 密码登录</option><option value="key" ${current==='key'?'selected':''}>SSH 私钥登录</option></select></div>
 <div class="form-group" id="password-field" ${current==='key'?'hidden':''}><label>SSH 登录密码</label><input id="ssh-password" type="password" name="password" maxlength="1024" autocomplete="new-password" placeholder="输入 VPS SSH 登录密码" ${current==='password'?'required':''}/>${rememberUI}</div>`;
}
function enableAuthToggle(){
 const select=el('#auth-mode');const password=el('#ssh-password');const field=el('#password-field');
 function toggle(){field.hidden=select.value!=='password';password.required=select.value==='password';if(select.value!=='password')password.value='';}
 select.addEventListener('change',toggle);toggle();
}
function addHost(){
 dialog(modalHead('添加 Linux VPS 服务器')+`<p class="helptext">SSH 密码可以选择保存到 Windows 系统凭据库，更新和重启后自动恢复；新机器仍需要首次确认 SSH 主机指纹。</p>
 <form id="add-host-form"><div class="form-group"><label>服务器名称</label><input name="name" placeholder="例如：香港 VPS 01" required maxlength="60"/></div>
 <div class="form-group"><label>服务器公网 IP 或域名</label><input name="hostname" placeholder="203.0.113.10" required/></div>
 <div class="form-2"><div class="form-group"><label>SSH 用户名</label><input name="username" value="root" required/></div><div class="form-group"><label>SSH 端口</label><input name="port" type="number" min="1" max="65535" value="22" required/></div></div>
 ${authSelect()}
 <div class="modal-tip">首次连接仍需通过云厂商控制台核对 SSH 主机指纹。密码认证需要 VPS 允许 SSH PasswordAuthentication；root 登录还受 PermitRootLogin 配置约束。请通过本机访问或 HTTPS 安全连接面板。</div>
 <div class="modal-actions"><button type="button" class="btn ghost" data-action="close-modal">取消</button><button class="btn primary" type="submit">添加服务器</button></div></form>`);
 enableAuthToggle();
 el('#add-host-form').addEventListener('submit',async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(e.currentTarget));d.port=Number(d.port);d.remember_password=d.remember_password==='on';if(d.auth_mode!=='password')delete d.password;const existing=state.hosts.find(h=>h.hostname.toLowerCase()===String(d.hostname).toLowerCase()&&h.port===d.port);if(existing){closeDialog();editHost(existing.id);toast('此 IP/端口已经添加过，请直接使用已有 VPS；重装可在“指纹 / 重装”中重新验证。');return;}const btn=e.currentTarget.querySelector('button[type="submit"]');if(btn){btn.disabled=true;btn.classList.add('is-loading');}try{toast('正在添加服务器…');await api('/hosts',{method:'POST',body:JSON.stringify(d)});closeDialog();await loadAll(true);toast('服务器已添加。请先核对 SSH 主机指纹，再进行环境检测。');}catch(err){toast(err.message,true);}finally{if(btn?.isConnected){btn.disabled=false;btn.classList.remove('is-loading');}}});
}
function editHost(id){
 const host=state.hosts.find(h=>h.id===id);if(!host)return;
 const locked=Boolean(host.job_count);
 dialog(modalHead('编辑 VPS 服务器')+`<p class="helptext">编辑服务器信息；有部署历史的 VPS 为保护旧任务，只允许修改名称。</p>
 <form id="edit-host-form"><div class="form-group"><label>显示名称</label><input name="name" maxlength="60" required value="${escapeHtml(host.name)}"/></div>
 <div class="form-group"><label>服务器公网 IP 或域名</label><input name="hostname" required value="${escapeHtml(host.hostname)}" ${locked?'readonly':''}/></div>
 <div class="form-2"><div class="form-group"><label>SSH 用户名</label><input name="username" required value="${escapeHtml(host.username)}" ${locked?'readonly':''}/></div>
 <div class="form-group"><label>SSH 端口</label><input name="port" type="number" min="1" max="65535" required value="${host.port}" ${locked?'readonly':''}/></div></div>
 <div class="modal-tip">${locked?`已有 ${host.job_count} 条部署历史；连接地址保持锁定。如 VPS 仅重装，使用“指纹 / 重装”，无需修改 IP 或重新添加。`:'修改 IP、SSH 端口或用户名将清除旧环境检测状态及本机缓存密码。再次连接需要重新验证新地址的 SSH 主机指纹。'}</div>
 <div class="modal-actions"><button type="button" class="btn ghost" data-action="close-modal">取消</button><button class="btn primary" type="submit">保存修改</button></div></form>`);
 el('#edit-host-form').addEventListener('submit',async e=>{
   e.preventDefault();const form=e.currentTarget;const d=Object.fromEntries(new FormData(form));d.port=Number(d.port);
   const submit=form.querySelector('button[type="submit"]');if(submit){submit.disabled=true;submit.classList.add('is-loading');}
   toast('正在保存服务器信息…');
   try{await api(`/hosts/${id}`,{method:'PUT',body:JSON.stringify(d)});closeDialog();await loadAll(true);toast('服务器信息已更新');}
   catch(err){toast(err.message,true);}finally{if(submit?.isConnected){submit.disabled=false;submit.classList.remove('is-loading');}}
 });
}
function deleteHost(id){
 const host=state.hosts.find(h=>h.id===id);if(!host)return;
 dialog(modalHead('删除 VPS 记录')+`<div class="modal-tip warning"><b>只删除 NetDeploy AI 的本地记录，不卸载 VPS 软件。</b> SSH 指纹若被其他服务器条目共用，会继续保留。关联部署任务、日志和面板快捷入口将在明确确认后删除，无法从面板恢复。</div>
 <p class="helptext">${escapeHtml(host.name)} · ${escapeHtml(host.hostname)}:${host.port} · ${host.job_count||0} 条部署历史</p>
 <form id="delete-host-form"><div class="form-group"><label>输入确认语句：DELETE VPS ${id}</label><input name="confirmation" required autocomplete="off" placeholder="DELETE VPS ${id}"/></div>
 ${host.job_count?`<label class="check"><input type="checkbox" name="delete_local_history" required/> 我确认同步删除该 VPS 的 ${host.job_count} 条本地任务历史及日志（不会删除远端软件）</label>`:''}
 <div class="modal-actions"><button class="btn ghost" type="button" data-action="close-modal">取消</button><button class="btn danger" type="submit">删除本地服务器记录</button></div></form>`);
 el('#delete-host-form').addEventListener('submit',async e=>{
   e.preventDefault();const form=e.currentTarget;const fd=new FormData(form);
   const payload={confirmation:String(fd.get('confirmation')),delete_local_history:fd.get('delete_local_history')==='on'};
   const submit=form.querySelector('button[type="submit"]');if(submit){submit.disabled=true;submit.classList.add('is-loading');}
   toast('正在安全删除本地 VPS 记录…');
   try{const res=await api(`/hosts/${id}`,{method:'DELETE',body:JSON.stringify(payload)});
     closeDialog();await loadAll(true);toast(`本地 VPS 已删除（清理 ${res.deleted_jobs} 条任务）；未修改远端服务器`);}
   catch(err){toast(err.message,true);}finally{if(submit?.isConnected){submit.disabled=false;submit.classList.remove('is-loading');}}
 });
}
function credentials(id){
 const host=state.hosts.find(h=>h.id===id);
 if(!host)return;
 dialog(modalHead('设置 SSH 登录方式')+`<p class="helptext">${escapeHtml(host.name)}（${escapeHtml(host.username)}@${escapeHtml(host.hostname)}:${host.port}）</p>
 <form id="credentials-form">${authSelect(host.auth_mode||'key',host.password_remembered)}
 <div class="modal-tip">${host.credential_ready?'目前已有可用凭据':'当前无可用登录凭据'}。仅更换 SSH 登录方式才会清空旧检测结果；同方式重填密码不会清空。创建部署计划时会自动进行只读检测。</div>
 <div class="modal-actions"><button type="button" class="btn ghost" data-action="close-modal">取消</button><button class="btn primary" type="submit">保存登录方式</button></div></form>`);
 enableAuthToggle();
 el('#credentials-form').addEventListener('submit',async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(e.currentTarget));d.remember_password=d.remember_password==='on';if(d.auth_mode!=='password')delete d.password;const btn=e.currentTarget.querySelector('button[type="submit"]');if(btn){btn.disabled=true;btn.classList.add('is-loading');}try{toast('正在安全更新登录凭据…');await api(`/hosts/${id}/credentials`,{method:'PUT',body:JSON.stringify(d)});closeDialog();await loadAll(true);toast('登录凭据已更新；生成部署方案时会自动检测环境');}catch(err){toast(err.message,true);}finally{if(btn?.isConnected){btn.disabled=false;btn.classList.remove('is-loading');}}});
}
async function fingerprint(id){
 const host=state.hosts.find(h=>h.id===id);if(!host)return;
 dialog(modalHead('SSH 身份与主机指纹')+`<p class="helptext">正在扫描 ${escapeHtml(host.hostname)}:${host.port} 的 SSH 公钥。此步骤无需密码。</p>
 <div class="modal-tip">首次连接和每次 VPS 重装后，都必须在云厂商的独立控制台核对指纹。扫描本身并不能证明服务器身份。</div>
 <div id="fingerprint-data" class="scan-state"><span class="inline-spinner"></span> 正在进行 SSH 握手和指纹比对…</div>`);
 try {
   const res=await api(`/hosts/${id}/fingerprint`,{method:'POST'});
   if(!el('#fingerprint-data'))return;
   state.pendingFingerprint={hostId:id,...res};
   const type=String(res.key_type||'ssh-ed25519');
   const keyFile=type==='ssh-ed25519'?'ed25519':type.startsWith('ecdsa-')?'ecdsa':'rsa';
   const old=(res.previous_fingerprints||[]);
   const oldHtml=old.length?`<div class="form-group"><label>原来已信任的主机指纹</label>${old.map(x=>`<div class="pre">${escapeHtml(x.key_type)} · ${escapeHtml(x.fingerprint)}</div>`).join('')}</div>`:'';
   const changed=Boolean(res.changed);
   const status=changed?'<div class="modal-tip warning"><b>检测到主机密钥变化！</b> 如果 VPS 确实重装，必须独立确认新指纹后才允许更新，禁止直接跳过验证。</div>':
      old.length?'<div class="modal-tip success-note">当前指纹与保存记录匹配，无需重复信任。</div>':'<div class="modal-tip">首次信任：请先独立核对云控制台中的 SHA-256 指纹。</div>';
   const shared=res.shared_host_count>1?`<div class="modal-tip">发现 ${res.shared_host_count} 条 VPS 记录使用同一个 IP 和端口。重装后更新指纹将同时影响这些记录，并使旧部署计划失效。</div>`:'';
   const action=changed?`<button class="btn danger" data-action="prepare-rekey" data-id="${id}">服务器已重装 → 更新信任</button>`:
      old.length?'':`<button class="btn primary" data-action="trust" data-id="${id}" data-fingerprint="${escapeHtml(res.fingerprint)}">首次确认并信任</button>`;
   el('#fingerprint-data').innerHTML=status+shared+`<div class="form-group"><label>当前服务器公钥指纹（${escapeHtml(type)}）</label>
      <div class="pre key-fingerprint">${escapeHtml(res.fingerprint)}</div><p class="helptext">在 VPS 云厂商的网页控制台执行并与上面逐字比对：</p>
      <div class="pre">ssh-keygen -lf /etc/ssh/ssh_host_${keyFile}_key.pub -E sha256</div></div>${oldHtml}
      ${action?`<label class="check"><input type="checkbox" id="verified-key"/> 我已在独立可信的 VPS 控制台核对当前新指纹</label>`:''}
      <div class="modal-actions"><button class="btn ghost" data-action="close-modal">关闭</button>${action}</div>`;
 }catch(err){
   const target=el('#fingerprint-data');
   if(target)target.innerHTML=`<div class="modal-tip warning">${escapeHtml(err.message)}</div>
     <p class="helptext">扫描未进入密码认证。请从运行 NetDeploy 的主机验证：</p>
     <div class="pre">Test-NetConnection -ComputerName ${escapeHtml(host.hostname)} -Port ${Number(host.port)}</div>`;
   toast(err.message,true);
 }
}
function prepareRekey(id){
 const pending=state.pendingFingerprint;
 const host=state.hosts.find(h=>h.id===id);
 if(!host||!pending||pending.hostId!==id||!pending.changed)return;
 if(!el('#verified-key')?.checked){toast('请先在云厂商控制台独立核对新指纹并勾选确认',true);return;}
 const phrase=`REKEY ${host.hostname}:${host.port}`;
 dialog(modalHead('确认 VPS 重装后的新身份')+`<div class="modal-tip warning"><b>将替换这一 IP/端口旧的 SSH 信任记录。</b>
 不会删除其他服务器的密钥；同一 SSH 地址的 ${pending.shared_host_count} 条 VPS 记录都会更新，旧审批计划会失效。</div>
 <div class="form-group"><label>新指纹（必须与云控制台一致）</label><div class="pre">${escapeHtml(pending.fingerprint)}</div></div>
 <form id="rekey-form"><div class="form-group"><label>输入确认语句：${escapeHtml(phrase)}</label>
 <input name="confirmation" required autocomplete="off" placeholder="${escapeHtml(phrase)}"/></div>
 <div class="modal-actions"><button class="btn ghost" type="button" data-action="close-modal">取消</button>
 <button class="btn danger" type="submit">已独立确认，更新此 VPS 的 SSH 信任</button></div></form>`);
 el('#rekey-form').addEventListener('submit',async e=>{
   e.preventDefault();const form=e.currentTarget;const submit=form.querySelector('button[type="submit"]');
   if(submit){submit.disabled=true;submit.classList.add('is-loading');}
   const confirmation=String(new FormData(form).get('confirmation'));toast('正在确认新指纹并安全更新信任记录…');
   try{const result=await api(`/hosts/${id}/rekey`,{method:'POST',body:JSON.stringify({
      fingerprint:pending.fingerprint,previous_fingerprints:pending.previous_fingerprints.map(x=>x.fingerprint),
      confirmed_out_of_band:true,confirmation
   })});state.pendingFingerprint=null;closeDialog();await loadAll(true);
      toast(`新指纹已安全信任，影响 ${result.affected_host_records} 条记录；请重新检测系统并核对 SSH 登录密码`);
   }catch(err){toast(err.message,true);}finally{if(submit?.isConnected){submit.disabled=false;submit.classList.remove('is-loading');}}
 });
}
async function preflight(id){
 const host=state.hosts.find(h=>h.id===id);toast('正在通过 SSH 扫描 '+host.name);
 try{const result=await api(`/hosts/${id}/preflight`,{method:'POST'});await loadAll(true);const f=result.facts;
  dialog(modalHead('环境检测成功')+`<p class="helptext">${escapeHtml(result.name)}：${escapeHtml(result.hostname)}</p>
  <div class="checks">${Object.entries(f).map(([k,v])=>`<div class="check">${escapeHtml(k)} <b class="right">${escapeHtml(v)}</b></div>`).join('')}</div><div class="modal-tip">此结果用于部署方案筛选；审批时还会重新预检以防环境发生变化。</div><div class="modal-actions"><button class="btn primary" data-action="close-modal">完成</button></div>`);
 }catch(err){toast(err.message,true);}
}
function chooseHost(project){
 const p=state.catalog[project];
 if(!state.hosts.length){addHost();return;}
 dialog(modalHead(`${p.deployment==='install'?'部署':'部署规划'} ${p.name}`)+`<form id="plan-form"><p class="helptext">选择目标 VPS，点击生成方案时会自动进行最新的只读环境检测，无需提前手动扫描。</p>
 <div class="form-group"><label>目标服务器</label><select name="host_id" id="plan-host-id" required>${state.hosts.map(h=>`<option value="${h.id}">${escapeHtml(h.name)} (${escapeHtml(h.hostname)})</option>`).join('')}</select></div>
 ${project==='3x-ui'?`<details><summary class="mini">高级设置（可选）：面板端口，默认 24443</summary><div class="form-group"><label>3X-UI 管理端口</label><input name="panel_port" type="number" min="1024" max="65535" value="24443" required/></div></details>
 <div class="modal-tip"><b id="cert-type-preview">证书类型自动识别中</b> —  填公网 IPv4 自动申请 IP 短期证书（160 小时），填域名自动申请域名证书。已有 3X-UI 时只升级 HTTPS、不重装。公网 TCP 80 必须允许 Let’s Encrypt 验证；失败时会显示具体原因，并保持原本的本机安全监听。</div>`:''}
 <div class="modal-tip">仅生成可审查的部署计划；确认所有步骤和风险后仍需单独审批执行。</div>
 <div class="modal-actions"><button type="button" class="btn ghost" data-action="close-modal">取消</button><button class="btn primary">自动检测并生成方案 →</button></div></form>`);
 if(project==='3x-ui'){
   const target=el('#plan-host-id');
   const preview=()=>{
     const host=state.hosts.find(h=>h.id===Number(target?.value));
     if(!host)return;
     const parts=host.hostname.split('.');
     const ip=parts.length===4&&parts.every(x=>/^\d{1,3}$/.test(x)&&Number(x)<=255);
     const indicator=el('#cert-type-preview');
     if(indicator)indicator.textContent=ip?'识别为公网 IPv4：自动申请短期 IP 证书':'识别为域名：自动申请域名证书';
   };
   target?.addEventListener('change',preview);
   preview();
 }
 el('#plan-form').addEventListener('submit',async e=>{e.preventDefault();const fd=new FormData(e.currentTarget);const request={host_id:Number(fd.get('host_id')),project};if(project==='3x-ui'){
  const existing=state.jobs.find(j=>j.project==='3x-ui'&&j.host_id===request.host_id&&['completed','partial'].includes(j.status)&& (j.plan.trust_epoch||0)===(state.hosts.find(h=>h.id===j.host_id)?.trust_epoch||0));
  if(existing){
    const upgraded=(existing.status==='completed'&&existing.plan.options?.access_mode==='https')||
      state.jobs.some(j=>j.project==='3x-ui-https'&&j.host_id===request.host_id&&j.status==='completed'&&j.plan.options?.source_job_id===existing.id);
    if(upgraded){closeDialog();showJob(existing.id);toast('已部署 HTTPS，可直接查看面板登录信息');return;}
    await xuiUpgrade(existing.id);return;
  }
  request.panel_port=Number(fd.get('panel_port'));
  request.access_mode='https';
}try{toast('正在读取 VPS 最新环境信息');const job=await api('/jobs',{method:'POST',body:JSON.stringify(request)});state.activeJob=null;await loadAll(true);if(!state.jobs.some(j=>j.id===job.id))state.jobs.unshift(job);showJob(job.id);}catch(err){toast(err.message,true);}});
}
function showJob(id){
 const job=state.jobs.find(j=>j.id===id);if(!job){toast('任务不存在，请刷新',true);return;}
 state.activeJob=id;
 const p=job.plan,host=state.hosts.find(h=>h.id===job.host_id);
 const stale=(p.trust_epoch||0)!==(host?.trust_epoch||0);
 let html=modalHead(`${p.name} · 部署任务`)+`<div class="toolbar">${chip(job.status)}<span class="chip">${escapeHtml(host?.name||p.hostname)}</span><span class="chip">${escapeHtml(p.options?.panel_port||'')}${p.options?.panel_port?' / TCP':''}</span></div>`;
 if(stale)html+='<div class="modal-tip warning">此任务属于服务器重装前的系统。旧登录信息和审批计划已失效，必须重新检测并创建新的部署方案。</div>';
 if(p.issues.length)html+=`<div class="modal-tip warning">${p.issues.map(escapeHtml).join('；')}</div>`;
 if(job.status==='planned'&&p.executable&&!stale){
   const isXui=job.project==='3x-ui'||job.project==='3x-ui-https';
   html+=`<div class="plan-overview"><h3>${isXui?'准备部署 3X-UI + HTTPS':'准备部署 '+escapeHtml(p.name)}</h3>
     <p>目标：${escapeHtml(host?.hostname||p.hostname)} · ${p.steps.length} 个受控执行阶段 · 风险：${escapeHtml(p.risk)}</p>
     <div class="modal-tip warning">审批一次后将执行已固定的安装步骤；包括 APT 依赖处理、证书签发（如果需要）和所需的本机 UFW 端口规则。云厂商安全组仍需另行放行；建议先备份 VPS。</div></div>
     <form id="approve-form"><div class="modal-actions plan-primary-actions">
       <button type="button" class="btn subtle" data-action="regenerate-plan" data-id="${escapeHtml(job.id)}">重新检测方案</button>
       <button type="button" class="btn ghost" data-action="close-modal">暂不部署</button>
       <button class="btn primary" type="submit">确认并一键部署</button>
     </div></form>`;
 }else{
   html+=`<h3>部署状态及日志</h3><div id="job-state" class="log-status">${escapeHtml(stateText(job.status))}</div>
      <pre id="task-log" class="pre">${escapeHtml(job.logs||'暂无执行日志')}</pre>
      <div class="modal-actions modal-action-wrap">
       ${job.project==='3x-ui'&&!stale&&['completed','partial'].includes(job.status)?`<button class="btn primary" data-action="xui-access" data-id="${escapeHtml(job.id)}">查看面板</button>${(p.options?.access_mode==='https'&&job.status==='completed')||state.jobs.some(x=>x.project==='3x-ui-https'&&x.plan.options?.source_job_id===job.id&&['completed','queued','running'].includes(x.status))?'':`<button class="btn subtle" data-action="xui-upgrade" data-id="${escapeHtml(job.id)}">继续完成 HTTPS</button>`}`:''}
       ${job.project==='3x-ui-https'&&!stale&&job.status==='completed'?`<button class="btn primary" data-action="xui-access" data-id="${escapeHtml(p.options?.source_job_id)}">打开 HTTPS 面板</button>`:''}
       ${job.project==='3x-ui-https'&&job.status==='failed'?`<button class="btn subtle" data-action="regenerate-plan" data-id="${escapeHtml(job.id)}">修复后重新生成证书方案</button>`:''}
       <button class="btn subtle" data-action="diagnose" data-id="${escapeHtml(job.id)}">AI 只读排障</button>
       ${['queued','running'].includes(job.status)?'':`<button class="btn danger" data-action="delete-job" data-id="${escapeHtml(job.id)}">删除记录</button>`}
       <button class="btn subtle" data-action="close-modal">关闭</button>
     </div><div id="ai-response"></div>`;
 }
 html+=`<details class="plan-technical"><summary>展开技术详情、风险说明和实际执行命令（${p.steps.length} 步）</summary>
   <h3>环境要求</h3><ul class="notice-list">${p.requires.map(v=>`<li>${escapeHtml(v)}</li>`).join('')}</ul>
   <h3>风险提示</h3><ul class="notice-list">${p.warnings.map(v=>`<li>${escapeHtml(v)}</li>`).join('')}</ul>
   ${p.steps.map((step,i)=>`<div class="step"><span class="num">${i+1}</span><div><b>${escapeHtml(step.label)}</b><small>超时上限 ${step.timeout} 秒</small>
      <details><summary class="mini">查看固定脚本</summary><pre class="pre">${escapeHtml(step.script)}</pre></details></div></div>`).join('')}
   <a class="external" href="${escapeHtml(p.docs)}" target="_blank" rel="noopener noreferrer">官方安装文档</a></details>`;
 dialog(html);
 const form=el('#approve-form');if(form)form.addEventListener('submit',async e=>{
   e.preventDefault();const btn=form.querySelector('button[type="submit"]');btn.disabled=true;btn.classList.add('is-loading');
   toast('正在复核服务器并执行已批准的方案…');
   try{await api(`/jobs/${job.id}/approve`,{method:'POST',body:JSON.stringify({confirmed_risk:true})});
       await loadAll(true);showJob(id);toast('任务已开始，将自动完成后续安装和验证');}
   catch(err){toast(err.message,true);}finally{if(btn.isConnected){btn.disabled=false;btn.classList.remove('is-loading');}}
 });
}
function confirmDeleteJob(id){
 const job=state.jobs.find(j=>j.id===id);
 if(!job){toast('任务记录不存在，请刷新列表',true);return;}
 if(['queued','running'].includes(job.status)){toast('排队或执行中的任务不能删除',true);return;}
 state.activeJob=null;
 dialog(modalHead('删除本地任务记录')+
   `<div class="modal-tip warning"><b>删除仅作用于 NetDeploy AI 的任务历史。</b>
   不会卸载 VPS 上已安装的软件、不会关闭远端服务，也不会清除 VPS、SSH 指纹或系统凭据库里的密码。
   删除成功后这条任务的部署日志和本地访问入口将不可恢复。若 HTTPS 升级引用了这条任务，必须先删除升级任务。</div>
   <p class="helptext">任务：${escapeHtml(job.project)} · ${escapeHtml(job.id)}（${escapeHtml(stateText(job.status))}）</p>
   <div class="modal-actions"><button class="btn ghost" data-action="close-modal">取消</button>
   <button class="btn danger" data-action="confirm-delete-job" data-id="${escapeHtml(id)}">仅删除本地记录</button></div>`);
}
async function deleteJobRecord(id){
 const button=el('[data-action="confirm-delete-job"]');
 if(button)button.disabled=true;
 try{
   await api(`/jobs/${id}`,{method:'DELETE',body:JSON.stringify({confirmation:`DELETE ${id}`})});
   state.activeJob=null;closeDialog();await loadAll(true);
   toast('任务历史已删除，VPS 上的软件与配置未改变');
 }catch(err){toast(err.message,true);}
 finally{if(button?.isConnected)button.disabled=false;}
}
async function regeneratePlan(id){
 const oldJob=state.jobs.find(j=>j.id===id);
 if(!oldJob){toast('原部署任务不存在，请刷新',true);return;}
 const host=state.hosts.find(h=>h.id===oldJob.host_id);
 if(!host){toast('原服务器不存在，请刷新',true);return;}
 const button=el('[data-action="regenerate-plan"]');
 if(button)button.disabled=true;
 try{
   const payload={host_id:host.id,project:oldJob.project};
   if(oldJob.project==='3x-ui'){payload.panel_port=oldJob.plan.options?.panel_port||24443;payload.access_mode=oldJob.plan.options?.access_mode||'https';}
   if(oldJob.project==='3x-ui-https')payload.source_job_id=oldJob.plan.options?.source_job_id;
   const newJob=await api('/jobs',{method:'POST',body:JSON.stringify(payload)});
   state.activeJob=null;
   await loadAll(true);
   if(!state.jobs.some(j=>j.id===newJob.id))state.jobs.unshift(newJob);
   showJob(newJob.id);
   toast('已重新检测并生成新部署计划；请检查步骤并再次审批');
 }catch(err){toast(err.message,true);}
 finally{if(button?.isConnected)button.disabled=false;}
}
async function diagnoseJob(id){
 const target=el('#ai-response');if(!target)return;
 target.innerHTML='<div class="modal-tip">Codex 正在进行只读分析。不会获得 SSH 私钥或远程执行权限。</div>';
 try{const res=await api(`/jobs/${id}/diagnose`,{method:'POST'});target.innerHTML='<h3>Codex 诊断建议</h3><pre class="pre">'+escapeHtml(res.message)+'</pre>';}
 catch(err){target.innerHTML='<div class="modal-tip warning">'+escapeHtml(err.message)+'</div>';}
}
async function xuiUpgrade(id){
 const source=state.jobs.find(j=>j.id===id&&j.project==='3x-ui'&&['completed','partial'].includes(j.status)&& (j.plan.trust_epoch||0)===(state.hosts.find(h=>h.id===j.host_id)?.trust_epoch||0));
 if(!source){toast('请先完成 3X-UI 安装',true);return;}
 try{
   const body={project:'3x-ui-https',host_id:source.host_id,source_job_id:source.id};
   toast('正在自动检查现有 3X-UI 环境');
   const job=await api('/jobs',{method:'POST',body:JSON.stringify(body)});
   state.activeJob=null;await loadAll(true);
   if(!state.jobs.some(j=>j.id===job.id))state.jobs.unshift(job);
   showJob(job.id);toast('HTTPS 升级计划已生成，请检查证书签发和公网暴露风险后单独审批');
 }catch(err){toast(err.message,true);}
}
async function copyXuiField(field,label){
 const node=el('#'+field);if(!node)return;
 try{await navigator.clipboard.writeText(node.value||node.textContent);toast(label+'已复制');}
 catch{toast('无法访问系统剪贴板，请手动复制',true);}
}
async function xuiAccess(id){
 dialog(modalHead('3X-UI 安全登录')+'<p class="helptext">正在从 VPS 读取账号和地址；不会将密码写入 NetDeploy 数据库或任务日志。</p>');
 try{
   const res=await api(`/jobs/${id}/access`);
   const url=res.direct_url||res.local_url;
   const tip=res.direct_url
     ? `<div class="modal-tip">HTTPS 证书及续期服务已经通过 VPS 本机校验。可直接点击打开管理面板；若外部访问失败，请检查云安全组是否允许 TCP ${escapeHtml(res.port)}。建议设置 2FA 和来源 IP 白名单。</div>`
     : `<div class="modal-tip warning">面板目前仅绑定 VPS 127.0.0.1，暂未启用公网 HTTPS。请先运行 SSH 隧道，或返回已完成安装任务点击“启用 HTTPS 直连”。</div>`;
   const tunnel=res.ssh_tunnel?`<div class="form-group"><label>SSH 隧道命令（在另一个 PowerShell 窗口执行）</label><div class="pre">${escapeHtml(res.ssh_tunnel)}</div><button class="btn subtle" data-action="copy-xui-tunnel">复制 SSH 命令</button><textarea id="xui-tunnel" hidden>${escapeHtml(res.ssh_tunnel)}</textarea></div>`:'';
   const openText=res.direct_url?'直接打开 HTTPS 管理面板 ↗':'建立 SSH 隧道后打开本机面板 ↗';
   dialog(modalHead('3X-UI 登录信息')+tip+tunnel+`<div class="form-group"><label>管理面板地址</label><input id="xui-url" readonly autocomplete="off" value="${escapeHtml(url)}"/><div class="modal-actions"><button class="btn subtle" data-action="copy-xui-url">复制面板地址</button><a class="external" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${openText}</a></div></div>
   <div class="form-group"><label>管理员用户名</label><input id="xui-username" readonly autocomplete="off" value="${escapeHtml(res.username)}"/><button class="btn subtle" data-action="copy-xui-username">复制用户名</button></div>
   <div class="form-group"><label>管理员密码（仅本次弹窗显示）</label><input id="xui-password" type="password" readonly autocomplete="off" value="${escapeHtml(res.password)}"/></div>
   <div class="modal-actions"><button class="btn subtle" data-action="toggle-xui-password">显示 / 隐藏密码</button><button class="btn subtle" data-action="copy-xui-password">复制密码</button><button class="btn primary" data-action="close-modal">关闭</button></div>`);
 }catch(err){dialog(modalHead('无法安全读取登录信息')+`<div class="modal-tip warning">${escapeHtml(err.message)}</div><div class="modal-actions"><button class="btn primary" data-action="close-modal">关闭</button></div>`);}
}
function go(section){state.section=section;renderSection();const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;window.scrollTo({top:0,behavior:reduced?'auto':'smooth'});}
async function tryLocalLogin(){
 try {
   const response=await fetch('/api/local-session',{cache:'no-store',headers:{'X-NetDeploy-Local':'1'}});
   if(!response.ok)return false;
   const result=await response.json();
   if(typeof result.token!=='string'||result.token.length<24)return false;
   state.token=result.token;
   sessionStorage.setItem('nd_token',result.token);
   return true;
 }catch{return false;}
}
async function start(){
 if(state.token){
   try{await api('/auth');el('#login').classList.add('hidden');await loadAll(true);return;}
   catch{state.token='';sessionStorage.removeItem('nd_token');}
 }
 if(await tryLocalLogin()){
   el('#login').classList.add('hidden');await loadAll(true);return;
 }
 el('#login').classList.remove('hidden');
}
el('#login-form').addEventListener('submit',async e=>{e.preventDefault();state.token=el('#admin-token').value;try{await api('/auth');sessionStorage.setItem('nd_token',state.token);el('#login').classList.add('hidden');el('#admin-token').value='';await loadAll(true);}catch(err){toast(err.message,true);}});
document.addEventListener('click',async e=>{
 const t=e.target.closest('[data-action],[data-nav]');if(!t)return;
 if(t.dataset.nav){go(t.dataset.nav);return;}
 const id=t.dataset.id,act=t.dataset.action;
 const asyncActions=new Set(['fingerprint','trust','preflight','host-check','server-install','confirm-delete-job','diagnose','regenerate-plan','xui-upgrade','xui-access','copy-xui-url','copy-xui-username','copy-xui-password','copy-xui-tunnel']);
 if(t.dataset.busy==='1')return;
 const busy=asyncActions.has(act);
 if(busy){t.dataset.busy='1';t.disabled=true;t.classList.add('is-loading');t.setAttribute('aria-busy','true');}
 try{
  if(act==='close-modal'){closeDialog();state.activeJob=null;state.hostPanel=null;state.pendingFingerprint=null;}
  else if(act==='host-console')openHostConsole(Number(id));
  else if(act==='back-host')openHostConsole(Number(id),state.hostPanel?.tab||'overview');
  else if(act==='host-tab')openHostConsole(Number(id),t.dataset.tab||'overview');
  else if(act==='host-check')await checkHostInConsole(Number(id));
  else if(act==='server-install')await createHostPlan(Number(id),t.dataset.project);
  else if(act==='add-host')addHost();
  else if(act==='edit-host')editHost(Number(id));
  else if(act==='delete-host')deleteHost(Number(id));
  else if(act==='fingerprint')await fingerprint(Number(id));
  else if(act==='prepare-rekey')prepareRekey(Number(id));
  else if(act==='credentials')credentials(Number(id));
  else if(act==='preflight')await preflight(Number(id));
  else if(act==='plan')chooseHost(t.dataset.project);
  else if(act==='job')showJob(id);
  else if(act==='delete-job')confirmDeleteJob(id);
  else if(act==='confirm-delete-job')await deleteJobRecord(id);
  else if(act==='diagnose')await diagnoseJob(id);
  else if(act==='regenerate-plan')await regeneratePlan(id);
  else if(act==='xui-upgrade')await xuiUpgrade(id);
  else if(act==='copy-xui-url')await copyXuiField('xui-url','面板地址');
  else if(act==='copy-xui-username')await copyXuiField('xui-username','管理员用户名');
  else if(act==='copy-xui-tunnel')await copyXuiField('xui-tunnel','SSH 隧道命令');
  else if(act==='xui-access')await xuiAccess(id);
  else if(act==='toggle-xui-password'){const field=el('#xui-password');if(field)field.type=field.type==='password'?'text':'password';}
  else if(act==='copy-xui-password')await copyXuiField('xui-password','管理员密码');
  else if(act==='trust'){
    if(!el('#verified-key')?.checked){toast('必须通过 VPS 云控制台独立核对指纹',true);return;}
    try{const result=await api(`/hosts/${id}/trust`,{method:'POST',body:JSON.stringify({fingerprint:t.dataset.fingerprint,confirmed_out_of_band:true})});
       state.pendingFingerprint=null;closeDialog();await loadAll(true);
       toast(result.already_trusted?'主机指纹与已信任记录一致':'已信任新的服务器指纹，可以继续检测环境');}
    catch(err){toast(err.message,true);}
  }
 }catch(err){toast(err.message||'操作失败，请重试',true);}finally{
    if(busy&&t.isConnected){t.disabled=false;delete t.dataset.busy;t.classList.remove('is-loading');t.removeAttribute('aria-busy');}
 }
});
/* Pointer glow adds depth only for hover-capable devices. */
if(window.matchMedia('(hover: hover) and (prefers-reduced-motion: no-preference)').matches){
 document.addEventListener('pointermove',event=>{
   if(event.pointerType==='touch')return;
   const card=event.target.closest?.('.host-item,.project');
   if(!card)return;
   const rect=card.getBoundingClientRect();
   const x=Math.max(0,Math.min(100,((event.clientX-rect.left)/rect.width)*100));
   const y=Math.max(0,Math.min(100,((event.clientY-rect.top)/rect.height)*100));
   card.style.setProperty('--hover-x',x+'%');
   card.style.setProperty('--hover-y',y+'%');
 },{passive:true});
}
document.addEventListener('keydown',e=>{const card=e.target.closest?.('[data-action="host-console"]');if(card&&(e.key==='Enter'||e.key===' ')){e.preventDefault();openHostConsole(Number(card.dataset.id));}});
el('#refresh').addEventListener('click',async e=>{const button=e.currentTarget;button.classList.add('is-loading');button.disabled=true;try{await loadAll();}finally{button.classList.remove('is-loading');button.disabled=false;}});
el('#logout').addEventListener('click',()=>{sessionStorage.removeItem('nd_token');state.token='';el('#login').classList.remove('hidden');});
setInterval(()=>{if(state.token)loadAll(true);},5000);
start();
