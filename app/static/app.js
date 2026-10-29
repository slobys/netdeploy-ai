/* NetDeploy AI v0.2.0 – no external JavaScript, no generated remote shell. */
const el = (s) => document.querySelector(s);
const escapeHtml = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {token:sessionStorage.getItem('nd_token')||'', hosts:[], jobs:[], catalog:{}, section:'dashboard', activeJob:null, pendingFingerprint:null, loading:false};

async function api(path, opts={}) {
  const resp = await fetch('/api'+path,{...opts,headers:{'X-Admin-Token':state.token,...(opts.body?{'Content-Type':'application/json'}:{}),...(opts.headers||{})},cache:'no-store'});
  let data;
  try{data=await resp.json();}catch{data={detail:`HTTP ${resp.status}`};}
  if(!resp.ok){if(resp.status===401){sessionStorage.removeItem('nd_token');state.token='';el('#login').classList.remove('hidden');}throw Error(typeof data.detail==='string'?data.detail:`操作失败 (${resp.status})`);}
  return data;
}
function toast(message,bad=false){const t=el('#toast');t.textContent=message;t.className='toast'+(bad?' bad':'');setTimeout(()=>t.classList.add('hidden'),6000);}
function dialog(content){el('#modal-content').innerHTML=content;el('#modal').classList.remove('hidden');}
function closeDialog(){el('#modal').classList.add('hidden');el('#modal-content').innerHTML='';}
function modalHead(title){return `<div class="modal-header"><h2>${escapeHtml(title)}</h2><button class="close" type="button" data-action="close-modal" aria-label="关闭">×</button></div>`;}
async function loadAll(silent=false){
  if(state.loading||!state.token)return;
  state.loading=true;
  try {
    const [hosts,jobs,catalog] = await Promise.all([api('/hosts'),api('/jobs'),api('/catalog')]);
    state.hosts=hosts;state.jobs=jobs;state.catalog=catalog;
    render();
    if(!silent)toast('控制台已刷新');
    if(state.activeJob && !el('#modal').classList.contains('hidden')) {
      const active=state.jobs.find(j=>j.id===state.activeJob);
      if(active && ['running','queued','completed','failed','interrupted'].includes(active.status)){
        const logbox=el('#task-log'); if(logbox){
          logbox.textContent=active.logs || '还没有执行日志'; el('#job-state').textContent=stateText(active.status);
          if(active.project==='3x-ui'&&active.status==='completed'&&!el('[data-action="xui-access"]'))showJob(active.id);
        }
      }
    }
  } catch(err){if(!silent)toast(err.message,true);} finally{state.loading=false;}
}
function stateText(status){return ({planned:'等待审批',queued:'已排队',running:'正在执行',completed:'执行完成',failed:'执行失败',interrupted:'执行中断'})[status]||status;}
function chip(status){const cls=status==='completed'?'success':status==='failed'||status==='interrupted'?'error':'warn';return `<span class="chip ${cls}">${escapeHtml(stateText(status))}</span>`;}
const symbol={"3x-ui":"▣","sing-box":"⬡","hysteria2":"ϟ","wg-easy":"◈"};
function render(){
 const {hosts,jobs,catalog}=state;
 el('#stats').innerHTML = [
  ['已添加服务器',hosts.length,'▤','已通过 SSH 扫描 '+hosts.filter(h=>!!h.facts).length+' 台'],
  ['项目模板',Object.keys(catalog).length,'⬡','固定、可审核的部署计划'],
  ['完成任务',jobs.filter(j=>j.status==='completed').length,'✓','安装完成仍需业务配置'],
  ['待处理任务',jobs.filter(j=>['failed','interrupted','planned'].includes(j.status)).length,'⌁','需确认或排障的任务']
 ].map(([label,val,ico,desc])=>`<div class="stat"><div class="top"><span>${label}</span><span class="icon">${ico}</span></div><strong>${val}</strong><small>${desc}</small></div>`).join('');
 el('#project-grid').innerHTML = Object.entries(catalog).map(([key,p])=>`
 <div class="project"><div class="project-head"><div class="project-icon">${symbol[key]}</div><span class="project-kind">${escapeHtml(p.category)}</span></div>
 <h3>${escapeHtml(p.name)}</h3><p>${escapeHtml(p.subtitle)}</p><div class="project-footer">
 <span class="status ${p.deployment==='install'?'':'muted'}">${p.deployment==='install'?'自动安装 Beta':'方案引导'}</span>
 <button class="btn subtle" data-action="plan" data-project="${escapeHtml(key)}">${p.deployment==='install'?'部署项目':'查看方案'} →</button></div></div>`).join('');
 el('#host-list').innerHTML=hosts.length?hosts.map(h=>`
 <div class="host-item"><div class="host-icon">▤</div><div class="host-main"><b>${escapeHtml(h.name)}</b><small>${escapeHtml(h.username)}@${escapeHtml(h.hostname)}:${h.port}${h.facts?' · '+escapeHtml(h.facts.OS_ID)+' / '+escapeHtml(h.facts.ARCH):''} · ${h.auth_mode==='password'?'密码登录':'密钥登录'}</small></div><span class="chip ${!h.credential_ready?'error':h.facts?'success':'warn'}">${!h.credential_ready?'需设置凭据':h.facts?'已预检':'待验证'}</span><div class="host-actions"><button class="btn subtle" data-action="credentials" data-id="${h.id}">登录方式</button><button class="btn subtle" data-action="fingerprint" data-id="${h.id}">SSH 指纹</button><button class="btn subtle" data-action="preflight" data-id="${h.id}">环境检测</button></div></div>`).join(''):`<div class="empty"><span class="empty-icon">▤</span><span>尚无 VPS 服务器。添加后进行指纹验证与环境检测。</span><button class="btn subtle" data-action="add-host">＋ 添加服务器</button></div>`;
 el('#job-list').innerHTML=jobs.length?jobs.map(j=>{const p=catalog[j.project]||{};const host=hosts.find(h=>h.id===j.host_id);return `<div class="job-item"><div class="job-icon">${symbol[j.project]||'⋄'}</div><div class="job-main"><b>${escapeHtml(p.name||j.project)} · ${escapeHtml(host?.name||j.plan.hostname)}</b><small>${escapeHtml(j.created_at.replace('T',' ').slice(0,19))} UTC · 任务 #${escapeHtml(j.id)}</small></div>${chip(j.status)}<button class="btn subtle" data-action="job" data-id="${escapeHtml(j.id)}">查看详情</button></div>`;}).join(''):`<div class="empty"><span class="empty-icon">≡</span><span>还没有部署任务。选择项目即可生成审批计划。</span></div>`;
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
function authSelect(current='password') {
 return `<div class="form-group"><label>SSH 登录方式</label><select name="auth_mode" id="auth-mode"><option value="password" ${current==='password'?'selected':''}>SSH 密码登录（推荐入门）</option><option value="key" ${current==='key'?'selected':''}>SSH 私钥登录</option></select></div>
 <div class="form-group" id="password-field" ${current==='key'?'hidden':''}><label>SSH 登录密码</label><input id="ssh-password" type="password" name="password" maxlength="1024" autocomplete="new-password" placeholder="输入 VPS 的 SSH 登录密码" ${current==='password'?'required':''}/></div>`;
}
function enableAuthToggle(){
 const select=el('#auth-mode');const password=el('#ssh-password');const field=el('#password-field');
 function toggle(){field.hidden=select.value!=='password';password.required=select.value==='password';if(select.value!=='password')password.value='';}
 select.addEventListener('change',toggle);toggle();
}
function addHost(){
 dialog(modalHead('添加 Linux VPS 服务器')+`<p class="helptext">可以使用 VPS 的 SSH 登录密码，无需提前配置公钥。密码仅存在服务端运行内存，重启后需要重新输入。</p>
 <form id="add-host-form"><div class="form-group"><label>服务器名称</label><input name="name" placeholder="例如：香港 VPS 01" required maxlength="60"/></div>
 <div class="form-group"><label>服务器公网 IP 或域名</label><input name="hostname" placeholder="203.0.113.10" required/></div>
 <div class="form-2"><div class="form-group"><label>SSH 用户名</label><input name="username" value="root" required/></div><div class="form-group"><label>SSH 端口</label><input name="port" type="number" min="1" max="65535" value="22" required/></div></div>
 ${authSelect()}
 <div class="modal-tip">首次连接仍需通过云厂商控制台核对 SSH 主机指纹。密码认证需要 VPS 允许 SSH PasswordAuthentication；root 登录还受 PermitRootLogin 配置约束。请通过本机访问或 HTTPS 安全连接面板。</div>
 <div class="modal-actions"><button type="button" class="btn ghost" data-action="close-modal">取消</button><button class="btn primary">添加服务器</button></div></form>`);
 enableAuthToggle();
 el('#add-host-form').addEventListener('submit',async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(e.currentTarget));d.port=Number(d.port);if(d.auth_mode!=='password')delete d.password;try{await api('/hosts',{method:'POST',body:JSON.stringify(d)});closeDialog();await loadAll(true);toast('服务器已添加。请先核对 SSH 主机指纹，再进行环境检测。');}catch(err){toast(err.message,true);}});
}
function credentials(id){
 const host=state.hosts.find(h=>h.id===id);
 if(!host)return;
 dialog(modalHead('设置 SSH 登录方式')+`<p class="helptext">${escapeHtml(host.name)}（${escapeHtml(host.username)}@${escapeHtml(host.hostname)}:${host.port}）</p>
 <form id="credentials-form">${authSelect(host.auth_mode||'key')}
 <div class="modal-tip">${host.credential_ready?'目前已有可用凭据':'当前无可用登录凭据'}。更新后将清除旧环境检测结果，需要重新检测。密码只在当前服务运行期间保存在内存中，服务重启后需重填；密钥登录需在服务端配置私钥。</div>
 <div class="modal-actions"><button type="button" class="btn ghost" data-action="close-modal">取消</button><button class="btn primary">保存登录方式</button></div></form>`);
 enableAuthToggle();
 el('#credentials-form').addEventListener('submit',async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(e.currentTarget));if(d.auth_mode!=='password')delete d.password;try{await api(`/hosts/${id}/credentials`,{method:'PUT',body:JSON.stringify(d)});closeDialog();await loadAll(true);toast('登录凭据已更新，请重新执行环境检测');}catch(err){toast(err.message,true);}});
}
function fingerprint(id){
 const host=state.hosts.find(h=>h.id===id);
 dialog(modalHead('核对 SSH 主机指纹')+`<p class="helptext">正在查询 <b>${escapeHtml(host.hostname)}</b> 的 SSH 主机公钥（支持 Ed25519、ECDSA、RSA）。</p><div class="modal-tip warning">重要：扫描只能取得对方声明的公钥，并不能证明服务器身份。必须在 VPS 云厂商控制台，或通过已有可信会话独立确认。</div><div id="fingerprint-data" class="mini">扫描中...</div>`);
 api(`/hosts/${id}/fingerprint`,{method:'POST'}).then(res=>{
  const type=String(res.key_type||'ssh-ed25519');
  const keyFile=type==='ssh-ed25519'?'ed25519':type.startsWith('ecdsa-')?'ecdsa':'rsa';
  el('#fingerprint-data').innerHTML=`<div class="form-group"><label>SSH 主机公钥指纹（${escapeHtml(type)}）</label><div class="pre">${escapeHtml(res.fingerprint)}</div><p class="helptext">在 VPS 云厂商的网页控制台运行以下命令并比对：</p><div class="pre">ssh-keygen -lf /etc/ssh/ssh_host_${keyFile}_key.pub -E sha256</div></div>
  <label class="check"><input type="checkbox" id="verified-key"/> 我已通过独立可信渠道核实这个指纹</label>
  <div class="modal-actions"><button class="btn ghost" data-action="close-modal">取消</button><button class="btn primary" data-action="trust" data-id="${id}" data-fingerprint="${escapeHtml(res.fingerprint)}">确认并信任</button></div>`;
 }).catch(err=>{el('#fingerprint-data').innerHTML=`<div class="modal-tip warning">${escapeHtml(err.message)}</div><p class="helptext">此时还未开始密码认证。从运行本面板的 Windows 电脑执行以下只读检查；如果面板运行在 NAS / Docker，请从实际运行面板的主机检测：</p><pre class="pre">Test-NetConnection -ComputerName ${escapeHtml(host.hostname)} -Port ${Number(host.port)}</pre><p class="helptext">TcpTestSucceeded 为 False 时，请检查 VPS IP、端口、云厂商安全组及 SSH 服务。若为 True 但仍无法扫描，请使用 VPS 厂商控制台检查 sshd 日志及 SSH 算法兼容性。</p>`;toast(err.message,true);});
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
 dialog(modalHead(`${p.deployment==='install'?'部署':'部署规划'} ${p.name}`)+`<form id="plan-form"><p class="helptext">选择目标 VPS，将结合其最近一次环境检测生成固定部署方案。</p>
 <div class="form-group" class="mt20"><label>目标服务器</label><select name="host_id" required>${state.hosts.map(h=>`<option value="${h.id}">${escapeHtml(h.name)} (${escapeHtml(h.hostname)}) ${h.facts?'✓ 已检测':'· 需先检测'}</option>`).join('')}</select></div>
 ${project==='3x-ui'?`<div class="form-group"><label>3X-UI 管理面板端口（1024–65535）</label><input name="panel_port" type="number" min="1024" max="65535" value="24443" required/></div><div class="modal-tip">固定官方 v3.11.0，自动生成强随机账号与密码，跳过公网 TLS 配置；面板仅允许本机访问，需通过 SSH 隧道登录。不会开放公网面板端口。</div>`:''}
 <div class="modal-tip">此步骤只生成计划，不修改服务器。执行前将展示固定命令、风险提醒和明确审批。</div>
 <div class="modal-actions"><button type="button" class="btn ghost" data-action="close-modal">取消</button><button class="btn primary">生成部署方案 →</button></div></form>`);
 el('#plan-form').addEventListener('submit',async e=>{e.preventDefault();const formData=new FormData(e.currentTarget);const h=Number(formData.get('host_id'));const request={host_id:h,project};if(project==='3x-ui')request.panel_port=Number(formData.get('panel_port'));try{const job=await api('/jobs',{method:'POST',body:JSON.stringify(request)});await loadAll(true);showJob(job.id);}catch(err){toast(err.message,true);}});
}
function showJob(id){
 const job=state.jobs.find(j=>j.id===id);if(!job){toast('未找到任务，请刷新',true);return;}
 state.activeJob=id;const p=job.plan;const host=state.hosts.find(h=>h.id===job.host_id);
 const approval=`DEPLOY ${job.project} TO ${host?.hostname||p.hostname}`;
 let html=modalHead(`${escapeHtml(p.name)} · 部署任务`)+`<div class="toolbar">${chip(job.status)}<span class="chip">风险等级：${escapeHtml(p.risk)}</span><span class="chip">${p.executable?'自动部署':'引导模式'}</span></div>
 <p class="helptext" class="mt14">目标服务器：${escapeHtml(host?.name||p.hostname)} · 任务编号 ${escapeHtml(job.id)}</p>
 ${job.project==='3x-ui'?`<div class="modal-tip">3X-UI v3.11.0 · TCP 端口 ${escapeHtml(p.options?.panel_port||'未知')} · 仅本机 HTTP · SSH 隧道访问 · 安装结果不会自动暴露公网</div>`:''}
 <h3>部署前置要求</h3><div class="checks">${p.requires.map(req=>`<div class="check">✓ ${escapeHtml(req)}</div>`).join('')}</div>
 <h3>风险提示</h3><ul class="notice-list">${p.warnings.map(w=>`<li>${escapeHtml(w)}</li>`).join('')}</ul>`;
 if(p.issues.length)html+=`<h3>兼容性 / 支持限制</h3><div class="checks">${p.issues.map(i=>`<div class="check fail">${escapeHtml(i)}</div>`).join('')}</div>`;
 if(p.steps.length)html+=`<h3>受控执行步骤（${p.steps.length} 项）</h3>${p.steps.map((s,i)=>`<div class="step"><span class="num">${i+1}</span><div><b>${escapeHtml(s.label)}</b><small>最长 ${s.timeout} 秒</small><details><summary class="mini" class="smalllink">查看实际 SSH 脚本</summary><pre class="pre">${escapeHtml(s.script)}</pre></details></div></div>`).join('')}`;
 html+=`<a class="external" target="_blank" rel="noopener noreferrer" href="${escapeHtml(p.docs)}">查看官方安装文档 ↗</a>`;
 if(job.status==='planned'&&p.executable)html+=`<form id="approve-form"><div class="modal-tip warning"><b>高权限操作确认</b>：SSH 执行器会运行上方固定脚本，可能修改远端软件包或创建容器。自动回滚暂不可用。请先核对风险和命令。</div>
 <div class="form-group"><label>请完整输入以下确认语句</label><div class="pre">${escapeHtml(approval)}</div><input name="confirmation" required autocomplete="off" placeholder="输入上方确认语句"/></div>
 <div class="modal-actions"><button type="button" class="btn ghost" data-action="close-modal">取消</button><button class="btn primary">审批并开始部署</button></div></form>`;
 else html+=`<h3>执行日志</h3><div id="job-state" class="log-status">${escapeHtml(stateText(job.status))}</div><pre class="pre" id="task-log">${escapeHtml(job.logs||'等待日志...')}</pre><div class="modal-actions"><button class="btn subtle" data-action="diagnose" data-id="${escapeHtml(job.id)}">AI 只读诊断</button>${job.project==='3x-ui'&&job.status==='completed'?`<button class="btn primary" data-action="xui-access" data-id="${escapeHtml(job.id)}">查看面板登录信息</button>`:''}<button class="btn primary" data-action="close-modal">关闭</button></div><div id="ai-response"></div>`;
 dialog(html);
 const form=el('#approve-form');if(form)form.addEventListener('submit',async e=>{e.preventDefault();const confirmation=new FormData(form).get('confirmation');try{await api(`/jobs/${job.id}/approve`,{method:'POST',body:JSON.stringify({confirmation})});await loadAll(true);showJob(id);toast('任务已获批准并启动执行');}catch(err){toast(err.message,true);}});
}
async function diagnoseJob(id){
 const target=el('#ai-response');if(!target)return;
 target.innerHTML='<div class="modal-tip">Codex 正在进行只读分析。不会获得 SSH 私钥或远程执行权限。</div>';
 try{const res=await api(`/jobs/${id}/diagnose`,{method:'POST'});target.innerHTML='<h3>Codex 诊断建议</h3><pre class="pre">'+escapeHtml(res.message)+'</pre>';}
 catch(err){target.innerHTML='<div class="modal-tip warning">'+escapeHtml(err.message)+'</div>';}
}
async function xuiAccess(id){
 dialog(modalHead('3X-UI 安全登录')+'<p class="helptext">正在通过 SSH 读取 VPS 上仅 root 可访问的登录凭据。不保存到部署日志或浏览器存储。</p>');
 try{
   const res=await api(`/jobs/${id}/access`);
   dialog(modalHead('3X-UI 登录信息')+`<div class="modal-tip warning">该面板只绑定 VPS 的 127.0.0.1。请先在你自己的 PowerShell 窗口建立 SSH 隧道，然后再打开下方本机网址。不要将面板账号或密码公开传播。</div>
   <div class="form-group"><label>SSH 隧道命令（需要另开 PowerShell 执行）</label><div class="pre">${escapeHtml(res.ssh_tunnel)}</div></div>
   <div class="form-group"><label>本机面板地址</label><div class="pre">${escapeHtml(res.local_url)}</div><a class="external" href="${escapeHtml(res.local_url)}" target="_blank" rel="noopener noreferrer">SSH 隧道建立后打开面板 ↗</a></div>
   <div class="form-group"><label>管理员用户名</label><div class="pre">${escapeHtml(res.username)}</div></div>
   <div class="form-group"><label>管理员密码（仅本次弹窗显示）</label><input id="xui-password" type="password" readonly autocomplete="off" value="${escapeHtml(res.password)}"/></div>
   <div class="modal-actions"><button class="btn subtle" data-action="toggle-xui-password">显示 / 隐藏密码</button><button class="btn subtle" data-action="copy-xui-password">复制密码</button><button class="btn primary" data-action="close-modal">关闭</button></div>`);
 }catch(err){dialog(modalHead('无法读取登录信息')+`<div class="modal-tip warning">${escapeHtml(err.message)}</div><div class="modal-actions"><button class="btn primary" data-action="close-modal">关闭</button></div>`);}
}
function go(section){state.section=section;renderSection();window.scrollTo({top:0,behavior:'smooth'});}
async function start(){if(state.token){try{await api('/auth');el('#login').classList.add('hidden');await loadAll(true);return;}catch{state.token='';sessionStorage.removeItem('nd_token');}}el('#login').classList.remove('hidden');}
el('#login-form').addEventListener('submit',async e=>{e.preventDefault();state.token=el('#admin-token').value;try{await api('/auth');sessionStorage.setItem('nd_token',state.token);el('#login').classList.add('hidden');el('#admin-token').value='';await loadAll(true);}catch(err){toast(err.message,true);}});
document.addEventListener('click',async e=>{const t=e.target.closest('[data-action],[data-nav]');if(!t)return;
 if(t.dataset.nav){go(t.dataset.nav);return;}
 const id=t.dataset.id,act=t.dataset.action;
 if(act==='close-modal'){closeDialog();state.activeJob=null;}
 else if(act==='add-host')addHost();
 else if(act==='fingerprint')fingerprint(Number(id));
 else if(act==='credentials')credentials(Number(id));
 else if(act==='preflight')await preflight(Number(id));
 else if(act==='plan')chooseHost(t.dataset.project);
 else if(act==='job')showJob(id);
 else if(act==='diagnose')await diagnoseJob(id);
 else if(act==='xui-access')await xuiAccess(id);
 else if(act==='toggle-xui-password'){const field=el('#xui-password');if(field)field.type=field.type==='password'?'text':'password';}
 else if(act==='copy-xui-password'){const field=el('#xui-password');try{if(field){await navigator.clipboard.writeText(field.value);toast('密码已复制，请勿转发');}}catch{toast('复制失败：请手动显示并复制密码',true);}}
 else if(act==='trust'){
   if(!el('#verified-key')?.checked){toast('请先通过 VPS 云控制台独立核实指纹',true);return;}
   try{const result=await api(`/hosts/${id}/trust`,{method:'POST',body:JSON.stringify({fingerprint:t.dataset.fingerprint,confirmed_out_of_band:true})});closeDialog();toast(result.already_trusted?'主机密钥与已保存记录一致，无需重复信任，可以继续环境检测':'主机公钥已固定，现在可以进行环境检测');}catch(err){toast(err.message,true);}
 }
});
el('#refresh').addEventListener('click',()=>loadAll());
el('#logout').addEventListener('click',()=>{sessionStorage.removeItem('nd_token');state.token='';el('#login').classList.remove('hidden');});
setInterval(()=>{if(state.token)loadAll(true);},5000);
start();
