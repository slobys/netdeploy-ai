/* NetDeploy AI v0.3.14 – no external JavaScript, no generated remote shell. */
const el = (s) => document.querySelector(s);
const CLIENT_VERSION = '0.3.14';
const escapeHtml = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {token:sessionStorage.getItem('nd_token')||'', hosts:[], jobs:[], catalog:{}, capabilities:{secure_password_storage:false}, section:'dashboard', activeJob:null, hostPanel:null, pendingFingerprint:null, loading:false, lastSnapshot:null,versionMismatchShown:false,setupFlowId:null,setupFirewallStatus:'unknown',setupFirewallBusy:false,setupFailedFirewallRules:[]};

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
    const [hosts,jobs,catalog,capabilities,health] = await Promise.all([
      api('/hosts'),api('/jobs'),api('/catalog'),api('/capabilities'),api('/health')
    ]);
    const serverVersion=String(health?.version||'');
    const versionTag=el('.tag.alpha');
    if(serverVersion&&serverVersion!==CLIENT_VERSION){
      if(versionTag){versionTag.textContent='版本不一致 · 后端 '+serverVersion;versionTag.title='页面版本 '+CLIENT_VERSION+'，服务端 '+serverVersion;}
      if(!state.versionMismatchShown){
        toast('页面与运行中的服务版本不一致。请停止旧 PowerShell 服务，重新运行桌面更新脚本并按 Ctrl+F5。',true);
        state.versionMismatchShown=true;
      }
    }else{
      if(versionTag)versionTag.textContent='ALPHA v'+CLIENT_VERSION;
      state.versionMismatchShown=false;
    }
    const snapshot=JSON.stringify([hosts,jobs,catalog,capabilities]);
    const changed=snapshot!==state.lastSnapshot;
    state.hosts=hosts;state.jobs=jobs;state.catalog=catalog;state.capabilities=capabilities;state.lastSnapshot=snapshot;
    if(changed)render();
    if(!silent)toast('控制台已刷新');
    if(state.activeJob && !el('#modal').classList.contains('hidden')) {
      const active=state.jobs.find(j=>j.id===state.activeJob);
      const statusNode=el('#job-state'),logbox=el('#task-log');
      if(active&&statusNode&&logbox){
        const before=statusNode.dataset.currentStatus||'';
        if(before!==active.status&&['completed','partial','failed','interrupted','invalidated'].includes(active.status)){
          // Replace the open task panel once on state transition; completed
          // install/HTTPS actions become visible without reopening the modal.
          showJob(active.id);
          toast(active.status==='completed'?'任务已完成，可以直接查看面板信息':'任务状态已更新，请查看错误或后续操作',active.status==='failed');
        }else{
          logbox.textContent=active.logs||'还没有执行日志';
          statusNode.textContent=stateText(active.status);
          statusNode.dataset.currentStatus=active.status;
        }
      }
    }
  } catch(err){if(!silent)toast(err.message,true);} finally{state.loading=false;}
}
function stateText(status){return ({planned:'等待审批',queued:'已排队',running:'正在执行',completed:'执行完成',failed:'执行失败',interrupted:'执行中断',partial:'3X-UI 已装，HTTPS 待修复',invalidated:'服务器已重装，计划失效'})[status]||status;}
function chip(status){const cls=status==='completed'?'success':status==='failed'||status==='interrupted'||status==='invalidated'?'error':'warn';return `<span class="chip ${cls}">${escapeHtml(stateText(status))}</span>`;}
const symbol={"3x-ui":"▣","3x-ui-https":"🔒","sing-box":"⬡","hysteria2":"ϟ","wg-easy":"◈","s-ui":"⬡"};
function render(){
 const {hosts,jobs,catalog}=state;
 const loneInstalledXui=hosts.length===1&&hosts[0].facts?.XUI_PRESENT==='yes';
 const loneInstalledSui=hosts.length===1&&hosts[0].facts?.SUI_PRESENT==='yes';
 el('#stats').innerHTML = [
  ['已添加服务器',hosts.length,'▤','已通过 SSH 扫描 '+hosts.filter(h=>!!h.facts).length+' 台'],
  ['项目模板',Object.values(catalog).filter(p=>!p.internal).length,'⬡','固定、可审核的部署计划'],
  ['完成任务',jobs.filter(j=>j.status==='completed').length,'✓','安装完成仍需业务配置'],
  ['待处理任务',jobs.filter(j=>['failed','interrupted'].includes(j.status)||(j.status==='planned'&&j.plan?.executable)).length,'⌁','需确认或排障的任务']
 ].map(([label,val,ico,desc])=>`<div class="stat"><div class="top"><span>${label}</span><span class="icon">${ico}</span></div><strong>${val}</strong><small>${desc}</small></div>`).join('');
 el('#project-grid').innerHTML = Object.entries(catalog).filter(([_,p])=>!p.internal).map(([key,p])=>`
 <div class="project"><div class="project-head"><div class="project-icon">${symbol[key]}</div><span class="project-kind">${escapeHtml(p.category)}</span></div>
 <h3>${escapeHtml(p.name)}</h3><p>${escapeHtml(p.subtitle)}</p><div class="project-footer">
 <span class="status ${p.deployment==='install'?'':'muted'}">${(key==='3x-ui'&&loneInstalledXui)||(key==='s-ui'&&loneInstalledSui)?'已安装 · 无需审批':p.deployment==='install'?'自动安装 Beta':'方案引导'}</span>
 <button class="btn subtle" data-action="${key==='3x-ui'&&loneInstalledXui?'installed-xui':key==='s-ui'&&loneInstalledSui?'installed-sui':'plan'}" ${(key==='3x-ui'&&loneInstalledXui)||(key==='s-ui'&&loneInstalledSui)?'data-id="'+hosts[0].id+'"':'data-project="'+escapeHtml(key)+'"'}>${(key==='3x-ui'&&loneInstalledXui)||(key==='s-ui'&&loneInstalledSui)?'查看已安装面板':p.deployment==='install'?'部署项目':'查看方案'} →</button></div></div>`).join('');
 el('#host-list').innerHTML=hosts.length?hosts.map(h=>{
   const duplicate=hosts.filter(x=>x.hostname.toLowerCase()===h.hostname.toLowerCase()&&x.port===h.port).length;
   const status=!h.credential_ready?'需要登录凭据':h.facts?'最近检测成功':'待连接检测';
   const statusClass=!h.credential_ready?'error':h.facts?'success':'warn';
   return `<article class="host-item interactive-card" role="button" tabindex="0" data-action="host-console" data-id="${h.id}" aria-label="打开 ${escapeHtml(h.name)} 的服务器控制台">
      <div class="host-card-top"><div class="host-icon">▤</div><div class="host-title"><b>${escapeHtml(h.name)}</b><span class="chip ${statusClass}">${status}</span></div><span class="host-card-open">管理服务器 →</span></div>
      <div class="host-card-address">${escapeHtml(h.username)}@${escapeHtml(h.hostname)}:${h.port}</div>
      <div class="host-card-meta"><span>${h.facts?escapeHtml(h.facts.OS_ID)+' / '+escapeHtml(h.facts.ARCH):'等待系统识别'}</span><span>${h.auth_mode==='password'?(h.password_remembered?'密码已安全保存':'密码登录'):'密钥登录'}</span><span>${h.job_count||0} 条任务</span><span class="host-cert-detail">${h.tls_domain?'域名证书 '+escapeHtml(h.tls_domain):'IP 证书（未填域名）'}</span>${h.facts?.XUI_PRESENT==='yes'?'<span class="host-installed-xui">3X-UI 已安装</span>':''}${h.facts?.SUI_PRESENT==='yes'?'<span class="host-installed-xui">S-UI 已安装</span>':''}</div>
      ${duplicate>1?`<span class="host-card-hint">${duplicate} 条记录共用此 SSH 地址</span>`:''}
      <button class="host-card-delete" type="button" data-action="delete-host" data-id="${h.id}" aria-label="删除 ${escapeHtml(h.name)} 的本地服务器记录">删除服务器</button>
    </article>`;
 }).join(''):`<div class="empty"><span class="empty-icon">▤</span><span>还没有 VPS。添加后点击卡片，即可在同一个控制台管理连接、部署与端口。</span><button class="btn primary" data-action="add-host">＋ 添加第一台 VPS</button></div>`;
 el('#job-list').innerHTML=jobs.length?jobs.map(j=>{const p=catalog[j.project]||{};const host=hosts.find(h=>h.id===j.host_id);return `<div class="job-item"><div class="job-icon">${symbol[j.project]||'⋄'}</div><div class="job-main"><b>${escapeHtml(p.name||j.project)} · ${escapeHtml(host?.name||j.plan.hostname)}</b><small>${escapeHtml(j.created_at.replace('T',' ').slice(0,19))} UTC · 任务 #${escapeHtml(j.id)}</small></div>${isExistingXuiPlan(j)?'<span class="chip success">已安装 · 无需审批</span>':chip(j.status)}<button class="btn ${j.status==='planned'?'primary':'subtle'}" data-action="${isExistingXuiPlan(j)?'installed-xui':historicalHttpsFailure(j)?'regenerate-plan':planNeedsUpdate(j)&&j.plan?.executable?'regenerate-plan':'job'}" data-id="${escapeHtml(isExistingXuiPlan(j)?j.host_id:j.id)}">${escapeHtml(jobNextAction(j))} →</button>${["queued","running"].includes(j.status)?"":`<button class="btn subtle" data-action="delete-job" data-id="${escapeHtml(j.id)}">删除</button>`}</div>`;}).join(''):`<div class="empty"><span class="empty-icon">≡</span><span>还没有部署任务。选择项目即可生成审批计划。</span></div>`;
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
function isPlanExpired(job){
 if(job.status!=='planned')return false;
 const timestamp=Date.parse(job.created_at);
 return Number.isFinite(timestamp)&&Date.now()-timestamp>10*60*1000;
}
function planNeedsUpdate(job){
 return job.status==='planned'&&(job.needs_refresh===true||isPlanExpired(job));
}
function isExistingXuiPlan(job){
 const host=state.hosts.find(h=>h.id===job.host_id);
 return job.project==='3x-ui'&&job.status==='planned'&&!job.plan?.executable&&
   !job.plan?.steps?.length&&job.plan?.issues?.some(v=>v.includes('x-ui'))&&
   (job.plan?.preflight_baseline?.XUI_PRESENT==='yes'||host?.facts?.XUI_PRESENT==='yes');
}
function jobLabel(job){
 if(isExistingXuiPlan(job))return '已安装 · 无需审批';
 if(job.status==='planned'&&!job.plan?.executable)return '当前不能自动部署';
 return stateText(job.status);
}
function historicalHttpsFailure(job){
 return job.project==='3x-ui-https'&&job.status==='failed'&&job.historical_script===true;
}
function jobNextAction(job){
 if(isExistingXuiPlan(job))return '查看已安装面板';
 if(historicalHttpsFailure(job))return '生成最新版 HTTPS 修复方案';
 if(job.status==='planned'&&!job.plan?.executable)return '查看原因';
 if(job.status==='planned'&&job.needs_refresh===true)return '更新为最新安全部署方案';
 if(isPlanExpired(job))return '更新方案，继续审批';
 return ({planned:'继续审批部署',queued:'查看等待进度',running:'查看部署进度',
   partial:'继续完成配置',failed:'查看失败原因',completed:'查看结果 / 面板',
   invalidated:'查看旧任务记录',interrupted:'查看中断原因'})[job.status]||'查看任务';
}
function hostTaskLink(job){
 const host=state.hosts.find(h=>h.id===job.host_id);
 const stale=(job.plan?.trust_epoch||0)!==(host?.trust_epoch||0);
 const action=stale?'查看旧任务':jobNextAction(job);
 const openExisting=!stale&&isExistingXuiPlan(job);
 const updateFailedHttps=!stale&&historicalHttpsFailure(job);
 const name=state.catalog[job.project]?.name||job.project;
 return `<button type="button" class="server-history-item ${job.status==='planned'&&job.plan?.executable&&!stale?'is-pending':''}" data-action="${openExisting?'installed-xui':updateFailedHttps?'regenerate-plan':planNeedsUpdate(job)&&!stale&&job.plan?.executable?'regenerate-plan':'job'}" data-id="${escapeHtml(openExisting?job.host_id:job.id)}"
    aria-label="${escapeHtml(name)}，${escapeHtml(stale?'已失效':jobLabel(job))}，${escapeHtml(action)}">
   <span class="server-task-icon" aria-hidden="true">${symbol[job.project]||'▣'}</span>
   <span class="server-task-title"><strong>${escapeHtml(name)}</strong><small>${escapeHtml(stale?'服务器重装前的历史':isExistingXuiPlan(job)?'面板已存在，不需要执行安装审批':historicalHttpsFailure(job)?'旧版脚本的失败记录，不代表新版仍存在相同问题':isPlanExpired(job)&&job.plan?.executable?'审批计划已过期':jobLabel(job))} · ${escapeHtml(job.created_at.slice(0,16).replace('T',' '))}</small></span>
   <span class="server-task-next">${escapeHtml(action)} <span aria-hidden="true">→</span></span></button>`;
}
function openHostConsole(id,tab='overview'){
 const host=state.hosts.find(h=>h.id===id);if(!host){toast('服务器记录不存在，请刷新',true);return;}
 state.hostPanel={id,tab};state.activeJob=null;
 const tabs=[['overview','概览'],['deploy','安装软件'],['network','网络端口'],['security','SSH 安全'],['settings','服务器设置']];
 const connected=Boolean(host.facts);
 const related=state.jobs.filter(j=>j.host_id===id).sort((a,b)=>b.created_at.localeCompare(a.created_at)).slice(0,5);
 const active=related.find(j=>['running','queued'].includes(j.status))
    ||(!host.facts||host.facts.XUI_PRESENT!=='yes'?related.find(j=>j.status==='planned'&&!isPlanExpired(j)&&j.plan?.executable&&(j.plan?.trust_epoch||0)===(host.trust_epoch||0)):null)
    ||(!host.facts||host.facts.XUI_PRESENT!=='yes'?related.find(j=>j.status==='planned'&&j.plan?.executable&&(j.plan?.trust_epoch||0)===(host.trust_epoch||0)):null)
    ||related.find(j=>['partial','failed','interrupted'].includes(j.status));
 const ready=host.credential_ready&&connected;
 const installedXui=host.facts?.XUI_PRESENT==='yes';
 let content='';
 if(tab==='overview'){
   let next='';
   if(installedXui&&!related.some(j=>['running','queued'].includes(j.status))){
     next=`<section class="server-next-action is-ready"><span class="server-next-kicker">已安装 · 无需部署审批</span>
       <h3>检测到 3X-UI 已安装</h3><p>直接查看现有面板的登录地址与已保存的初始账号信息。若 HTTPS 尚未完成，可在面板详情中继续配置，不会重新安装。</p>
       <button type="button" class="btn primary" data-action="installed-xui" data-id="${id}">查看 3X-UI 面板信息 →</button>
     </section>`;
   }else if(active){
     const pending=active.status==='planned',running=['queued','running'].includes(active.status);
     const header=pending?(active.needs_refresh?'此部署方案来自旧版代码，需要刷新':isPlanExpired(active)?'部署计划已过期，刷新后继续':'部署方案已准备好，等待你的批准'):running?'部署正在执行':'上次部署需要处理';
     const detail=pending?(active.needs_refresh?'GitHub 已更新经过审核的固定脚本。请生成最新方案，避免继续执行旧版 HTTPS 命令；更新方案不会直接修改 VPS。':isPlanExpired(active)?'计划创建超过 10 分钟，出于安全考虑必须重新检测。点击即可生成最新方案，不会直接安装。':'目前还未开始在 VPS 上安装。点击下面按钮，核对目标和风险后即可一次确认启动。'):
        running?'可直接查看安装进度，无需重复创建部署任务。':'查看具体失败原因或继续完成后续配置，无需重复安装已部署的软件。';
     next=`<section class="server-next-action ${pending?'pending':''}" aria-label="当前待办任务">
       <span class="server-next-kicker">${pending?'下一步 · 待审批':running?'正在执行 · 任务进度':'需要处理 · 部署任务'}</span>
       <h3>${header}</h3><p>${detail}</p>
       <button type="button" class="btn primary" data-action="${planNeedsUpdate(active)?'regenerate-plan':'job'}" data-id="${escapeHtml(active.id)}">${jobNextAction(active)} →</button>
     </section>`;
   }else if(!ready){
     next=`<section class="server-next-action"><span class="server-next-kicker">下一步 · 连接服务器</span>
       <h3>检查 SSH 连接与服务器环境</h3><p>首次使用先确认主机指纹，随后检测系统。之后创建部署任务时会自动复核，无须每次手动检测。</p>
       <button type="button" class="btn primary" data-action="host-tab" data-id="${id}" data-tab="security">检查 SSH 身份 →</button>
     </section>`;
   }else{
     next=`<section class="server-next-action is-ready"><span class="server-next-kicker">可以继续</span>
       <h3>这台 VPS 已有可用的连接信息</h3><p>直接选择开源项目，系统会自动检查运行环境并生成部署方案。</p>
       <button type="button" class="btn primary" data-action="host-tab" data-id="${id}" data-tab="deploy">选择软件，一键部署 →</button>
     </section>`;
   }
   content=`${next}
    <div class="server-simple-status">
      <div><span>服务器</span><strong>${escapeHtml(host.hostname)}:${host.port}</strong></div>
      <div><span>运行环境</span><strong>${connected?escapeHtml(host.facts.OS_ID)+' / '+escapeHtml(host.facts.ARCH):'尚未检测'}</strong></div>
      <div><span>连接方式</span><strong>${host.auth_mode==='password'?'SSH 密码'+(host.password_remembered?' · 已安全保存':''):'SSH 私钥'}</strong></div>
    </div>
    <div class="server-panel-section"><div class="server-subheading"><h3>最近部署任务</h3><p>点击任务就能继续审批、查看进度或处理失败，无需重新安装。</p></div>
      ${related.length?related.map(hostTaskLink).join(''):'<p class="helptext">还没有部署任务。点击上面的“选择软件，一键部署”开始。</p>'}
    </div>
    <details class="server-advanced-actions"><summary>其他管理操作（连接检测、端口、安全设置）</summary>
      <div class="server-action-grid">
        <button type="button" class="btn subtle" data-action="host-check" data-id="${id}">重新检测连接</button>
        <button type="button" class="btn subtle" data-action="host-tab" data-id="${id}" data-tab="network">配置防火墙端口</button>
      </div></details>`;
 }else if(tab==='deploy'){
   const visible=Object.entries(state.catalog).filter(([_,project])=>!project.internal);
   const pending=related.filter(j=>j.status==='planned'&&j.plan?.executable&&(j.plan?.trust_epoch||0)===(host.trust_epoch||0)&&!installedXui);
   content=`<div class="server-tab-intro"><h3>安装或继续配置软件</h3>
     <p>只需要选择项目。系统会自动检测、生成安全计划并识别已有安装，安装前仅需批准一次。</p></div>
     ${pending.length?`<div class="server-pending-shortcut"><strong>你有 ${pending.length} 个等待审批的计划</strong>
       <button class="btn primary" data-action="${planNeedsUpdate(pending[0])?'regenerate-plan':'job'}" data-id="${escapeHtml(pending[0].id)}">${planNeedsUpdate(pending[0])?'刷新方案并继续':'立即继续审批'} →</button></div>`:''}
     <div class="server-project-grid">${visible.map(([key,project])=>`<button class="server-project-choice" data-action="server-install" data-id="${id}" data-project="${escapeHtml(key)}">
       <span class="project-choice-icon">${symbol[key]||'▣'}</span><strong>${escapeHtml(project.name)}</strong>${(key==='3x-ui'&&installedXui)||(key==='s-ui'&&host.facts?.SUI_PRESENT==='yes')?'<span class="chip success">已安装</span>':''}<small>${escapeHtml(project.subtitle)}</small>
       <span class="project-choice-link">${(key==='3x-ui'&&installedXui)||(key==='s-ui'&&host.facts?.SUI_PRESENT==='yes')?'已安装 · 查看面板信息':project.deployment==='install'?'安装 / 继续配置':'查看部署方案'} →</span>
     </button>`).join('')}</div>`;
 }else if(tab==='network'){
   content=`<div class="server-tab-intro"><h3>开放服务器需要使用的端口</h3><p>例如 HTTPS 证书验证需要 TCP 80，3X-UI 默认管理端口是 TCP 24443。这里只有本机 UFW，云平台安全组仍须另行允许。</p></div>
     <div id="server-firewall-status" class="server-status-panel"><span class="inline-spinner" aria-hidden="true"></span>正在检查 UFW…</div>
     <form id="server-allow-form"><div class="form-2">
       <div class="form-group"><label>要放行的端口</label><input name="port" type="number" min="1" max="65535" value="80" required/></div>
       <div class="form-group"><label>协议</label><select name="protocol"><option value="tcp">TCP</option><option value="udp">UDP</option></select></div>
     </div><div class="modal-actions"><button type="submit" class="btn primary">放行本机防火墙端口</button></div></form>
     <p class="helptext">仅设置 VPS 内的 UFW。云厂商安全组不受本功能影响。</p>
     ${cloudFirewallHelp()}
     <div class="firewall-toggle-panel">
       <h4>本机防火墙开关（高级操作）</h4>
       <p>关闭 UFW 会取消整台 VPS 的本机端口过滤，但不会关闭云厂商安全组。仅用于确认排障需要时手动操作。</p>
       <div class="firewall-toggle-actions"><button class="btn danger" data-action="toggle-ufw" data-id="${id}" data-mode="disable" type="button">关闭 VPS 本机防火墙</button>
         <button class="btn subtle" data-action="toggle-ufw" data-id="${id}" data-mode="enable" type="button">重新启用 UFW</button></div>
     </div>`;
 }else if(tab==='security'){
   content=`<div class="server-tab-intro"><h3>SSH 身份与登录安全</h3><p>SSH 指纹用于确认连接的是原来的服务器；登录密码用于身份认证。VPS 重装后若指纹变化，应独立核对后更新，不能直接跳过。</p></div>
     <div class="server-action-grid">
       <button class="btn primary" data-action="fingerprint" data-id="${id}">查看或更新 SSH 指纹</button>
       <button class="btn subtle" data-action="credentials" data-id="${id}">修改 SSH 登录密码</button>
       <button class="btn subtle" data-action="host-check" data-id="${id}">测试 SSH 连接</button>
     </div>`;
 }else{
   content=`<div class="server-tab-intro"><h3>编辑或移除服务器</h3><p>修改名称不会影响 VPS。删除只清理本地记录和所选历史，不会卸载远端软件。</p></div>
     <div class="server-action-grid">
       <button class="btn primary-soft" data-action="edit-host" data-id="${id}">修改服务器信息</button>
       <button class="btn danger" data-action="delete-host" data-id="${id}">删除本地服务器记录</button>
     </div>`;
 }
 const header=`<div class="server-console"><div class="server-console-head"><div><span class="server-eyebrow">VPS 工作台</span>
   <h3>${escapeHtml(host.name)}</h3><p>${escapeHtml(host.username)}@${escapeHtml(host.hostname)}:${host.port}</p></div>
   <span class="chip ${host.credential_ready?(connected?'success':'warn'):'error'}">${host.credential_ready?(connected?'曾通过环境检测':'待检测'):'需补充登录凭据'}</span></div>
   <nav class="server-tabs" aria-label="服务器管理分类">${tabs.map(([name,label])=>`<button type="button" class="server-tab ${tab===name?'active':''}" data-action="host-tab" data-id="${id}" data-tab="${name}" aria-current="${tab===name?'page':'false'}">${label}</button>`).join('')}</nav>
   <div class="server-tab-content">${content}</div></div>`;
 dialog(modalHead('VPS 服务器控制台',true)+header);
 if(tab==='network'){
   refreshFirewallUI(id);
   el('#server-allow-form')?.addEventListener('submit',async e=>{
     e.preventDefault();const form=e.currentTarget;const fd=new FormData(form);
     const btn=form.querySelector('button[type="submit"]');btn.disabled=true;btn.classList.add('is-loading');
     const port=Number(fd.get('port')),protocol=String(fd.get('protocol'));
     toast(`正在为 UFW 放行 ${port}/${protocol}…`);
     try{const res=await api(`/hosts/${id}/firewall/allow`,{method:'POST',body:JSON.stringify({port,protocol,confirmation:true})});
        toast(res.mode==='active'?`VPS 本机 UFW 已放行 ${port}/${protocol}；云厂商安全组仍需单独检查`:'UFW 未启用或不可用，无需新增本机规则；仍需检查云安全组');
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
   const disable=el('[data-action="toggle-ufw"][data-mode="disable"]');
   const enable=el('[data-action="toggle-ufw"][data-mode="enable"]');
   if(disable)disable.disabled=result.status!=='active';
   if(enable)enable.disabled=result.status!=='inactive';
 }catch(err){if(target.isConnected)target.innerHTML=`<div class="modal-tip warning">${escapeHtml(err.message)}</div>`;}
}
function confirmUfwToggle(id,mode){
 const host=state.hosts.find(h=>h.id===id);if(!host)return;
 const disabling=mode==='disable';
 const guided=state.setupFlowId===id;
 if(guided&&disabling&&state.setupFirewallStatus!=='active'){
   toast('当前 UFW 未处于已启用状态，不需要执行关闭操作；可跳过本步',true);return;
 }
 dialog(modalHead(disabling?'关闭 VPS 本机防火墙':'重新启用 VPS 本机防火墙')+`
   <div class="modal-tip warning"><b>${disabling?'此操作会关闭整台 VPS 的 UFW 本机防火墙。':'重新启用 UFW 前会先放行当前 SSH 端口。'}</b>
   ${disabling?'所有端口将不再受到 UFW 过滤，可能暴露管理接口或其他服务。云安全组依旧独立生效。':'已有的 UFW 规则和默认拒绝策略将重新生效；某些端口可能再次被拦截。'}
   请确认正在管理的是 ${escapeHtml(host.name)}（${escapeHtml(host.hostname)}）。</div>
   ${guided?setupProgress(4):''}
   <div class="modal-actions"><button class="btn ghost" data-action="${guided?'setup-firewall':'back-host'}" data-id="${id}">取消</button>
   <button class="btn ${disabling?'danger':'primary'}" data-action="apply-ufw-toggle" data-id="${id}" data-mode="${mode}">
     ${disabling?'确认关闭 UFW':'确认重新启用 UFW'}</button></div>`);
}
async function applyUfwToggle(id,mode){
 toast('正在通过可信 SSH 切换 UFW 状态…');
 try{
   const result=await api(`/hosts/${id}/firewall/toggle`,{method:'POST',
     body:JSON.stringify({mode,confirmed_risk:true})});
   const message=result.mode==='inactive'?'UFW 已手动关闭，VPS 本机端口不再受其过滤':'UFW 已重新启用，SSH TCP 端口已预先放行';
   if(state.setupFlowId===id)setupFirewallResult(id,message);
   else openHostConsole(id,'network');
   toast(message+'；云服务商安全组不受影响');
 }catch(err){toast(err.message,true);}
}
async function checkHostInConsole(id){
 const target=el('.server-tab-content');if(target)target.insertAdjacentHTML('afterbegin','<div class="modal-tip server-check-running">正在通过已验证的 SSH 读取服务器环境…</div>');
 try{await api(`/hosts/${id}/preflight`,{method:'POST'});await loadAll(true);openHostConsole(id,'overview');toast('连接检测成功，系统信息已更新');}
 catch(err){el('.server-check-running')?.remove();toast(err.message,true);}
}
async function createHostPlan(id,project,panelPort=null,absenceVerified=false){
 const host=state.hosts.find(h=>h.id===id);if(!host)return;
 if(state.setupFlowId===id){state.setupFlowId=null;state.hostPanel={id,tab:'deploy'};}
 // Always inspect the *live* VPS before an installation, not old task records.
 if(project==='3x-ui'&&!absenceVerified){
   toast('正在只读检查现有 3X-UI 安装…');
   try{
     const status=await api('/hosts/'+id+'/3x-ui');
     if(status.installed){await showExistingXui(id,status);return;}
   }catch(err){toast('无法安全确认现有安装，已阻止覆盖：'+err.message,true);return;}
 }
 if(project==='s-ui'){
   toast('正在只读检查 S-UI 是否已经安装…');
   try{
     const status=await api('/hosts/'+id+'/s-ui');
     if(status.installed){await showExistingSui(id,status);return;}
   }catch(err){toast('无法安全核对现有 S-UI 安装，已阻止覆盖：'+err.message,true);return;}
 }
 const existing=state.jobs.find(j=>j.project===project&&j.host_id===id&&
   (j.plan?.trust_epoch||0)===(host.trust_epoch||0)&&j.plan?.executable&&
   j.plan?.steps?.length>0&&['planned','queued','running'].includes(j.status)&&!planNeedsUpdate(j));
 if(existing){showJob(existing.id);toast(existing.status==='planned'?'已有审批方案，直接继续即可':'已有执行中的任务，无需重复创建');return;}
 if(project==='3x-ui'&&panelPort===null){
   const detectedHost=certHost(host);
   const ip=!host.tls_domain&&isIpv4Input(host.hostname);
   dialog(modalHead('安装 3X-UI · 自定义面板端口')+`
     <div class="xui-port-config"><span class="chip">${ip?'公网 IP · 自动申请 IP 证书':'域名 · 自动申请域名证书'}</span>
       <p>SSH 服务器：${escapeHtml(host.hostname)}；HTTPS 证书：${escapeHtml(detectedHost)}。证书类型将自动识别，不需要再次选择或单独安装 HTTPS。</p>
       <form id="xui-custom-port-form"><div class="form-group">
         <label>3X-UI 管理端口（可自行修改）</label>
         <input name="port" type="number" min="1024" max="65535" value="24443" required/>
         <p class="helptext">允许 1024–65535，不能与 SSH 端口 ${host.port} 相同。程序会预检端口占用。</p>
       </div><div class="modal-actions"><button class="btn ghost" type="button" data-action="back-host" data-id="${id}">返回</button>
         <button class="btn primary" type="submit">生成安装与 HTTPS 方案 →</button></div></form>
     </div>`);
   const form=el('#xui-custom-port-form');
   form.addEventListener('submit',async e=>{
     e.preventDefault();const port=Number(new FormData(form).get('port'));
     if(!Number.isInteger(port)||port<1024||port>65535||port===host.port){
       toast('端口必须为 1024–65535，且不能与 SSH 端口相同',true);return;
     }
     const button=form.querySelector('button[type="submit"]');button.disabled=true;button.classList.add('is-loading');
     try{await createHostPlan(id,'3x-ui',port,true);}
     finally{if(button.isConnected){button.disabled=false;button.classList.remove('is-loading');}}
   });
   return;
 }
 toast('正在检测 VPS 并生成部署计划…');
 try{
   const payload={host_id:id,project};
   if(project==='3x-ui'){payload.panel_port=panelPort;payload.access_mode='https';}
   const job=await api('/jobs',{method:'POST',body:JSON.stringify(payload)});
   state.activeJob=null;await loadAll(true);
   if(!state.jobs.some(j=>j.id===job.id))state.jobs.unshift(job);
   showJob(job.id);
 }catch(err){toast(err.message,true);}
}

async function showExistingSui(id,known=null){
 const host=state.hosts.find(h=>h.id===id);if(!host)return;
 state.hostPanel={id,tab:'deploy'};state.activeJob=null;
 dialog(modalHead('S-UI · 已安装面板')+'<div class="xui-loading"><span class="inline-spinner"></span>正在通过已信任 SSH 检查 S-UI 服务…</div>');
 try{
   const status=known||await api('/hosts/'+id+'/s-ui');
   if(!status.installed){
     dialog(modalHead('S-UI · 尚未安装')+
       '<div class="modal-tip">未检测到 S-UI；可返回选择官方 v1.6.6 的固定安装方案。</div>'+
       '<div class="modal-actions"><button class="btn primary" data-action="server-install" data-id="'+id+'" data-project="s-ui">创建安装方案 →</button>'+
       '<button class="btn ghost" data-action="back-host" data-id="'+id+'">返回</button></div>');
     return;
   }
   if(status.service!=='active'||!status.managed||status.access_mode!=='local'){
     dialog(modalHead('S-UI · 状态需要检查')+
       '<div class="modal-tip warning">检测到 S-UI 文件，但服务未运行、缺少受保护的安装记录或本机监听未验证。为保护现有数据，不会覆盖重装或猜测账号。请通过 VPS 控制台检查 systemctl status s-ui。</div>'+
       '<div class="modal-actions"><button class="btn subtle" data-action="back-host" data-id="'+id+'">返回</button></div>');
     return;
   }
   const details=await api('/hosts/'+id+'/s-ui/access');
   const row=(label,field,value,action)=>'<div class="xui-info-row"><label>'+label+'</label>'+
     '<input id="'+field+'" readonly autocomplete="off" value="'+escapeHtml(value)+'"/>'+
     '<button type="button" class="btn subtle" data-action="'+action+'">复制</button></div>';
   const credentials='<div class="xui-info-grid">'+
      row('本地面板地址','sui-url',details.local_url,'copy-sui-url')+
      row('初始管理员用户名','sui-username',details.username,'copy-sui-username')+
      '<div class="xui-info-row"><label>初始管理员密码</label>'+
        '<input id="sui-password" type="password" readonly autocomplete="off" value="'+escapeHtml(details.password)+'"/>'+
        '<button type="button" class="btn subtle" data-action="toggle-sui-password">显示 / 隐藏</button>'+
        '<button type="button" class="btn subtle" data-action="copy-sui-password">复制密码</button></div>'+
      row('PowerShell SSH 隧道命令','sui-tunnel',details.ssh_tunnel,'copy-sui-tunnel')+
      '</div>';
   dialog(modalHead('S-UI · 已安装面板')+
     '<section class="xui-existing"><div class="xui-existing-state"><span class="chip success">已安装 · 运行正常</span><span class="chip">仅 VPS 本机访问</span></div>'+
     '<h3>S-UI 已安装，无需重复部署</h3>'+
     '<p class="xui-existing-meta">管理端口：2095/TCP · 本机 127.0.0.1 · 如需访问请先在 PowerShell 执行下方 SSH 隧道命令。</p>'+
     credentials+
     '<p class="helptext">初始密码仅按你主动点击从 VPS 受保护文件读取，NetDeploy 不会写入任务日志。如在 S-UI 中改过密码，以当前设置为准。未配置可信 TLS 前不建议公网开放 2095。</p>'+
     '<div class="modal-actions"><button type="button" class="btn subtle" data-action="back-host" data-id="'+id+'">返回服务器</button></div></section>');
 }catch(err){
   dialog(modalHead('S-UI · 无法读取面板信息')+
     '<div class="modal-tip warning">'+escapeHtml(err.message)+'</div>'+
     '<div class="modal-actions"><button type="button" class="btn subtle" data-action="back-host" data-id="'+id+'">返回</button></div>');
   toast(err.message,true);
 }
}

async function showExistingXui(id,known=null){
 const host=state.hosts.find(h=>h.id===id);if(!host)return;
 state.hostPanel={id,tab:'deploy'};state.activeJob=null;
 dialog(modalHead('3X-UI · 现有面板')+'<div class="xui-loading"><span class="inline-spinner"></span>正在通过已验证的 SSH 读取当前面板状态…</div>');
 try{
   const status=known||await api('/hosts/'+id+'/3x-ui');
   if(!status.installed){
     dialog(modalHead('3X-UI · 尚未安装')+'<section class="xui-existing"><span class="chip warn">未安装</span>' +
       '<h3>这台 VPS 还没有 3X-UI</h3><p>可生成一次安装方案，包含后续 HTTPS 配置。</p>' +
       '<div class="modal-actions"><button class="btn ghost" data-action="back-host" data-id="'+id+'">返回</button>' +
       '<button class="btn primary" data-action="install-new-xui" data-id="'+id+'">创建安装方案 →</button></div></section>');
     return;
   }
   const active=status.service==='active', managed=status.managed;
   const local=status.access_mode==='local', https=status.access_mode==='https';
   let content='';
   if(active&&managed&&(local||https)){
     try{
       const result=await api('/hosts/'+id+'/3x-ui/access');
       const url=result.direct_url||result.local_url;
       const urlLink=result.direct_url?
         '<a class="btn primary" href="'+escapeHtml(result.direct_url)+'" rel="noopener noreferrer" target="_blank">直接打开 HTTPS 面板 ↗</a>':
         '<span class="xui-note">当前仅监听 VPS 本机。直接公网访问需先完成 HTTPS。</span>';
       content='<div class="xui-info-grid">'+
         '<div class="xui-info-row"><label>面板地址</label><input id="xui-url" readonly autocomplete="off" value="'+escapeHtml(url)+'"/>' +
           '<button class="btn subtle" data-action="copy-xui-url">复制地址</button>'+urlLink+'</div>'+
         '<div class="xui-info-row"><label>初始管理员用户名</label><input id="xui-username" readonly autocomplete="off" value="'+escapeHtml(result.username)+'"/>' +
           '<button class="btn subtle" data-action="copy-xui-username">复制用户名</button></div>'+
         '<div class="xui-info-row"><label>初始管理员密码</label><input id="xui-password" type="password" readonly autocomplete="off" value="'+escapeHtml(result.password)+'"/>' +
           '<button class="btn subtle" data-action="toggle-xui-password">显示 / 隐藏</button>'+
           '<button class="btn subtle" data-action="copy-xui-password">复制密码</button></div>';
       if(result.ssh_tunnel){
         content+='<div class="xui-info-row"><label>本机访问需要的 SSH 隧道命令</label><code class="xui-tunnel">'+escapeHtml(result.ssh_tunnel)+'</code>'+
           '<textarea id="xui-tunnel" hidden>'+escapeHtml(result.ssh_tunnel)+'</textarea>'+
           '<button class="btn subtle" data-action="copy-xui-tunnel">复制 SSH 命令</button></div>';
       }
       content+='</div><p class="helptext">上述凭据来自安装时的受保护记录；若曾在 3X-UI 中修改账号密码，当前设置可能不同。</p>';
     }catch(err){content='<div class="modal-tip warning">检测到已安装面板，但初始凭据无法安全读取：'+escapeHtml(err.message)+'。不会重装或猜测密码。</div>';}
   }else if(!managed){
     content='<div class="modal-tip">已安装 3X-UI，但没有可信的初始化记录，暂无法读取管理员密码或准确访问路径。'+
       '请在 VPS 云厂商控制台执行 <code>x-ui settings</code> 查看或更新当前登录信息；不会覆盖安装。</div>';
   }else if(!active){
     content='<div class="modal-tip warning">检测到 3X-UI，但服务未运行。可在 VPS 控制台执行 <code>systemctl status x-ui</code> 排查。</div>';
   }else{
     content='<div class="modal-tip warning">已安装面板的监听地址或 TLS 证书尚未通过校验，不能生成不安全的直连链接。</div>';
   }
   const scheme=https?'已验证 HTTPS':local?'本机监听 / SSH 隧道':'访问方式待核验';
   const upgrade=active&&managed&&local?
     '<button class="btn primary" data-action="existing-xui-https" data-id="'+id+'">继续完成 HTTPS →</button>':'';
   const html=modalHead('3X-UI · 已安装面板')+'<section class="xui-existing">'+
     '<div class="xui-existing-state"><span class="chip '+(active?'success':'warn')+'">已安装'+(active?' · 正在运行':' · 服务未运行')+'</span>'+
      (managed?'<span class="chip">安装记录可读取</span>':'<span class="chip warn">原始凭据未找到</span>')+'</div>'+
     '<h3>3X-UI 已安装，无需重新部署</h3><p>查看面板信息属于只读操作，不需要安装审批。</p>'+
     (status.port?'<p class="xui-existing-meta">安装端口：'+status.port+' / TCP · '+scheme+'</p>':'')+
     content+'<div class="modal-actions xui-existing-actions"><button class="btn ghost" data-action="back-host" data-id="'+id+'">返回服务器</button>'+upgrade+'</div></section>';
   dialog(html);
 }catch(err){
   dialog(modalHead('无法读取现有 3X-UI')+'<div class="modal-tip warning">'+escapeHtml(err.message)+'</div>'+
     '<div class="modal-actions"><button class="btn ghost" data-action="back-host" data-id="'+id+'">返回</button></div>');
   toast(err.message,true);
 }
}
async function continueExistingXuiHttps(id){
 const host=state.hosts.find(h=>h.id===id);if(!host)return;
 const pending=state.jobs.find(j=>j.project==='3x-ui-https'&&j.host_id===id&&
   (j.plan?.trust_epoch||0)===(host.trust_epoch||0)&&j.plan?.executable&&j.plan?.steps?.length>0&&
   ['planned','queued','running'].includes(j.status)&&!planNeedsUpdate(j));
 if(pending){showJob(pending.id);return;}
 toast('正在检查当前端口并生成 HTTPS 续接方案…');
 try{
   const job=await api('/jobs',{method:'POST',body:JSON.stringify({host_id:id,project:'3x-ui-https'})});
   state.activeJob=null;await loadAll(true);
   if(!state.jobs.some(j=>j.id===job.id))state.jobs.unshift(job);
   showJob(job.id);
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
function isIpv4Input(value){const parts=String(value||'').split('.');return parts.length===4&&parts.every(v=>/^\d{1,3}$/.test(v)&&String(Number(v))===v&&Number(v)<=255);}
function certHost(host){return host.tls_domain||host.hostname;}
function certLabel(host){return host.tls_domain||!isIpv4Input(host.hostname)?`域名证书 · ${escapeHtml(certHost(host))}`:`IP 证书 · ${escapeHtml(host.hostname)}`;}
function setupProgress(step){
 const steps=['服务器信息','SSH 指纹','连接检测','网络端口','选择软件'];
 return `<ol class="setup-progress" aria-label="服务器添加进度">${steps.map((text,i)=>`<li class="${i+1===step?'current':i+1<step?'finished':''}" ${i+1===step?'aria-current="step"':''}>
   <span class="setup-step-number">${i+1<step?'✓':i+1}</span><span>${text}</span></li>`).join('')}</ol>`;
}
async function beginServerSetup(id){
 state.setupFlowId=id;
 state.hostPanel={id,tab:'overview'};
 await fingerprint(id);
}
async function setupPreflight(id){
 const host=state.hosts.find(h=>h.id===id);if(!host)return;
 state.setupFlowId=id;
 dialog(modalHead('第 3 步 · 检查 SSH 与系统')+setupProgress(3)+
  '<div class="setup-loading"><span class="inline-spinner" aria-hidden="true"></span>正在使用已验证的 SSH 指纹登录并检测系统…</div>');
 try{
   const checked=await api(`/hosts/${id}/preflight`,{method:'POST'});
   await loadAll(true);
   if(state.setupFlowId!==id)return;
   const facts=checked.facts||{};
   dialog(modalHead('第 3 步 · 连接检测通过')+setupProgress(3)+
    `<section class="setup-result"><span class="chip success">SSH 已验证 · 连接成功</span>
      <h3>${escapeHtml(checked.name)} 已准备好</h3>
      <p>${escapeHtml(facts.OS_ID||'Linux')} · ${escapeHtml(facts.OS_VERSION||'')} · ${escapeHtml(facts.ARCH||'未知架构')}</p>
      <p>${certLabel(state.hosts.find(h=>h.id===id)||checked)}；创建部署方案时仍会自动进行安全复核。</p></section>
    <div class="modal-actions"><button class="btn ghost" data-action="back-host" data-id="${id}">稍后操作</button>
      <button class="btn primary" data-action="setup-firewall" data-id="${id}">下一步：端口与防火墙（可跳过） →</button></div>`);
   toast('SSH 连接及服务器环境检测通过');
 }catch(err){
   dialog(modalHead('连接检测未通过')+setupProgress(3)+
     `<div class="modal-tip warning">${escapeHtml(err.message)}</div>
      <div class="modal-actions"><button class="btn ghost" data-action="back-host" data-id="${id}">返回服务器</button>
       <button class="btn subtle" data-action="credentials" data-id="${id}">修改 SSH 密码</button>
       <button class="btn primary" data-action="setup-retry" data-id="${id}">重试连接检测</button></div>`);
   toast(err.message,true);
 }
}

function setupPortRow(port='',protocol='tcp'){
 return `<div class="setup-port-row" data-setup-port-row>
   <div class="form-group"><label>端口</label>
     <input name="port" type="number" inputmode="numeric" min="1" max="65535" required
       placeholder="例如：8443" value="${escapeHtml(port)}"/></div>
   <div class="form-group"><label>协议</label>
     <select name="protocol"><option value="tcp" ${protocol==='tcp'?'selected':''}>TCP</option>
       <option value="udp" ${protocol==='udp'?'selected':''}>UDP</option></select></div>
   <button class="btn ghost setup-remove-port" type="button" data-action="setup-remove-port" aria-label="删除这一行端口">删除</button>
 </div>`;
}
function setupPortCount(){
 const rows=el('#setup-port-rows');
 const count=rows?.querySelectorAll('[data-setup-port-row]').length||0;
 const indicator=el('#setup-port-count');
 if(indicator)indicator.textContent=`已添加 ${count} / 20 个端口`;
 return count;
}
function addSetupPort(){
 const rows=el('#setup-port-rows');if(!rows)return;
 if(setupPortCount()>=20){toast('每次最多添加 20 个端口，请分批操作',true);return;}
 rows.insertAdjacentHTML('beforeend',setupPortRow());
 setupPortCount();
 rows.querySelector('[data-setup-port-row]:last-child input[name="port"]')?.focus();
}
function removeSetupPort(button){
 const row=button.closest('[data-setup-port-row]');
 if(!row)return;
 if(setupPortCount()<=1){toast('请至少保留一个端口输入框，或直接跳过此步',true);return;}
 row.remove();setupPortCount();
}
function collectSetupPorts(form){
 const data=new FormData(form),ports=data.getAll('port'),protocols=data.getAll('protocol');
 if(!ports.length||ports.length>20||protocols.length!==ports.length)
   throw Error('请添加 1–20 条完整端口规则');
 const seen=new Set();
 return ports.map((raw,i)=>{
   const value=String(raw).trim(),protocol=String(protocols[i]).toLowerCase();
   const port=Number(value);
   if(!/^\d+$/.test(value)||!Number.isInteger(port)||port<1||port>65535)
     throw Error(`第 ${i+1} 行端口不合法，请填写 1–65535 的整数`);
   if(!['tcp','udp'].includes(protocol))
     throw Error(`第 ${i+1} 行协议不合法，只能选择 TCP 或 UDP`);
   const key=port+'/'+protocol;
   if(seen.has(key))throw Error(`第 ${i+1} 行端口 ${key} 已重复；同一个端口可以分别选择 TCP 和 UDP`);
   seen.add(key);
   return {port,protocol};
 });
}
async function submitSetupPorts(id,rules,submit=null){
 if(state.setupFirewallBusy){toast('端口操作正在执行，请勿重复提交',true);return;}
 if(state.setupFlowId!==id)return;
 state.setupFirewallBusy=true;
 if(submit){submit.disabled=true;submit.classList.add('is-loading');}
 const next=el('[data-action="setup-projects"]');if(next)next.disabled=true;
 toast(`正在依次放行 ${rules.length} 个端口…`);
 try{
   const result=await api(`/hosts/${id}/firewall/allow-batch`,{
     method:'POST',body:JSON.stringify({rules,confirmation:true})
   });
   if(state.setupFlowId===id){
     setupFirewallResult(id,result);
     toast(result.failed?
       `${result.allowed} 个端口已放行，${result.failed} 个失败；可仅重试失败项`:
       result.mode==='active'?`已成功放行 ${result.allowed} 个端口`:
       'UFW 未启用或不可用：没有更改本机防火墙规则',result.failed>0);
   }
 }catch(err){
   const box=el('#setup-port-error');
   if(box)box.textContent='⚠ '+err.message+'；如网络连接中断，请先检查 VPS 现有规则，不要盲目重复提交';
   toast(err.message,true);
 }finally{
   state.setupFirewallBusy=false;
   if(submit?.isConnected){submit.disabled=false;submit.classList.remove('is-loading');}
   if(next?.isConnected)next.disabled=false;
 }
}
async function retryFailedSetupPorts(id){
 const rules=state.setupFailedFirewallRules||[];
 if(state.setupFlowId!==id||!rules.length)return;
 await submitSetupPorts(id,rules);
}

function setupFirewallResult(id,message){
 const host=state.hosts.find(h=>h.id===id);if(!host||state.setupFlowId!==id)return;

 if(message&&typeof message==='object'&&Array.isArray(message.results)){
   const result=message;
   state.setupFailedFirewallRules=result.results.filter(x=>x.status==='failed')
     .map(x=>({port:x.port,protocol:x.protocol}));
   const headline=result.failed?
     `已放行 ${result.allowed} 项，失败 ${result.failed} 项`:
     result.mode==='active'?`已放行 ${result.allowed} 个端口`:
     'UFW 未启用或未安装，端口规则未修改';
   const statusText={allowed:'已放行',failed:'失败',skipped:'未修改'};
   const rows=result.results.map(x=>
      `<li class="setup-port-result ${x.status==='allowed'?'allowed':x.status==='failed'?'failed':'skipped'}">
       <strong>${escapeHtml(x.port)}/${escapeHtml(x.protocol.toUpperCase())}</strong>
       <span>${statusText[x.status]||'未验证'}</span></li>`).join('');
   dialog(modalHead('第 4 步 · 批量端口放行结果')+setupProgress(4)+
     `<section class="setup-result">
        <span class="chip ${result.failed?'warn':'success'}">${result.failed?'部分端口未放行':'网络步骤已完成'}</span>
        <h3>${escapeHtml(headline)}</h3>
        <p>${escapeHtml(result.cloud_notice||'仅修改本机 UFW；云厂商安全组需要另外设置')}</p>
        <ul class="setup-port-results">${rows}</ul>
        ${result.failed?'<p class="setup-batch-warning">失败的端口没有被视为成功。仅重试失败项，不会重复提交已放行端口。</p>':''}
      </section>
      <div class="modal-actions">
       <button type="button" class="btn subtle" data-action="setup-firewall" data-id="${id}">返回网络设置</button>
       ${result.failed?`<button type="button" class="btn primary-soft" data-action="setup-retry-failed" data-id="${id}">仅重试失败的 ${result.failed} 项</button>`:''}
       <button type="button" class="btn primary" data-action="setup-projects" data-id="${id}">下一步：选择软件 →</button>
      </div>`);
   return;
 }
 dialog(modalHead('第 4 步 · 网络设置完成')+setupProgress(4)+
  `<section class="setup-result"><span class="chip success">网络步骤已完成</span>
    <h3>${escapeHtml(message)}</h3>
    <p>仅操作 VPS 自身的 UFW；云服务商安全组仍需另行允许相应入站端口。</p></section>
    <div class="modal-actions"><button type="button" class="btn subtle" data-action="setup-firewall" data-id="${id}">返回网络设置</button>
    <button type="button" class="btn primary" data-action="setup-projects" data-id="${id}">下一步：选择软件 →</button></div>`);
}
function cloudFirewallHelp(){return `<details class="cloud-firewall-help">
      <summary>云厂商安全组 · 快速打开官方控制台（可选）</summary>
      <p>仅本机 UFW 放行，不代表云防火墙已放行。打开你购买 VPS 的云控制台，选择正确地域与实例，找到关联的安全组或 VPC 入站规则。</p>
      <div class="cloud-provider-links">
        <a href="https://ecs.console.aliyun.com/" target="_blank" rel="noopener noreferrer" aria-label="打开阿里云 ECS 控制台安全组">阿里云 ECS <span>安全组 ↗</span></a>
        <a href="https://console.cloud.tencent.com/cvm/securitygroup" target="_blank" rel="noopener noreferrer" aria-label="打开腾讯云 CVM 安全组控制台">腾讯云 CVM <span>安全组 ↗</span></a>
        <a href="https://console.cloud.google.com/networking/firewalls/list" target="_blank" rel="noopener noreferrer" aria-label="打开 Google Cloud VPC 防火墙控制台">Google Cloud <span>VPC 防火墙 ↗</span></a>
        <a href="https://console.aws.amazon.com/ec2/" target="_blank" rel="noopener noreferrer" aria-label="打开 AWS EC2 控制台">AWS EC2 <span>Security Groups ↗</span></a>
      </div>
      <p class="cloud-security-note">按实际需要添加 <strong>入站</strong> TCP/UDP 规则；SSH 与管理面板端口建议只允许你的固定管理 IP。登录状态、地域和云账号仍由各平台负责，NetDeploy 不代你修改云安全组。</p>
      <p class="helptext">如果登录后停留在首页：阿里云在「网络与安全 → 安全组」，AWS 在 EC2 左侧选择 Security Groups。请确认地域和实例。</p>
    </details>`;}

async function setupFirewall(id){
 const host=state.hosts.find(h=>h.id===id);if(!host)return;
 state.setupFlowId=id;state.setupFirewallStatus='unknown';
 state.hostPanel={id,tab:'network'};
 dialog(modalHead('第 4 步 · 端口与防火墙（可跳过）')+setupProgress(4)+
  `<div class="server-tab-intro"><h3>按需放行端口，或选择跳过</h3>
    <p>推荐只放行需要的 TCP/UDP 端口，例如 HTTPS 验证使用 TCP 80。无需安装前关闭防火墙；也可以直接跳过。下方只修改 VPS 本机 UFW，云厂商安全组仍需单独设置。</p></div>
    <div class="server-status-panel" id="setup-firewall-status" role="status">
      <span class="inline-spinner" aria-hidden="true"></span> 正在只读检查 VPS 的 UFW 状态…</div>
    <form id="setup-allow-form"><div class="setup-port-form-heading"><strong>需要放行的端口</strong>
      <span id="setup-port-count">已添加 1 / 20 个端口</span></div>
      <div id="setup-port-rows" class="setup-port-rows">${setupPortRow('80','tcp')}</div>
      <p id="setup-port-error" class="setup-port-error" role="alert" aria-live="assertive"></p>
      <div class="setup-port-actions">
        <button type="button" class="btn subtle" data-action="setup-add-port">＋ 添加端口</button>
        <button class="btn primary-soft" type="submit">一次放行全部端口</button>
      </div>
      <p class="helptext">可添加最多 20 项。每项单独选择 TCP/UDP；相同端口与协议自动检查重复。</p>
    </form>
    ${cloudFirewallHelp()}
    <div class="firewall-toggle-panel"><h4>高级操作：关闭整台 VPS 的本机防火墙</h4>
      <p>此操作会停止 UFW 对所有端口的过滤，可能让管理服务暴露公网；仅在你明确需要时操作。关闭前还会再次确认风险。</p>
      <div class="firewall-toggle-actions"><button type="button" class="btn danger" data-action="toggle-ufw" data-mode="disable" data-id="${id}" disabled>关闭 UFW（需确认风险）</button></div></div>
    <div class="modal-actions"><button type="button" class="btn ghost" data-action="back-host" data-id="${id}">稍后操作</button>
      <button type="button" class="btn primary" data-action="setup-projects" data-id="${id}">跳过此步，下一步：选择软件 →</button></div>`);
 const form=el('#setup-allow-form');
 form?.addEventListener('submit',async e=>{
   e.preventDefault();
   if(state.setupFlowId!==id){toast('当前引导步骤已经变化，请重新打开网络设置',true);return;}
   let rules;
   try{
     rules=collectSetupPorts(form);
     const error=el('#setup-port-error');if(error)error.textContent='';
   }catch(err){
     const error=el('#setup-port-error');if(error)error.textContent=err.message;
     toast(err.message,true);return;
   }
   await submitSetupPorts(id,rules,form.querySelector('button[type="submit"]'));
 });
 try{
   const status=await api(`/hosts/${id}/firewall`);
   const target=el('#setup-firewall-status');
   if(state.setupFlowId!==id||!target)return;
   state.setupFirewallStatus=status.status;
   const statusText={active:'UFW 正在运行',inactive:'UFW 未启用，当前无需放行本机端口',unavailable:'未安装 UFW，无本机 UFW 规则需修改',unknown:'当前 UFW 状态不明确'}[status.status]||'无法识别状态';
   target.innerHTML=`<strong>${escapeHtml(statusText)}</strong><p class="helptext">${escapeHtml(status.cloud_notice||'云服务商安全组需要单独设置')}</p>`;
   const disable=el('[data-action="toggle-ufw"][data-mode="disable"]');
   if(disable)disable.disabled=status.status!=='active';
 }catch(err){
   const target=el('#setup-firewall-status');
   if(state.setupFlowId===id&&target)target.innerHTML=`<div class="modal-tip warning">UFW 状态检查失败：${escapeHtml(err.message)}。你可以跳过本步，或稍后重试。出于安全考虑不提供关闭操作。</div>`;
   state.setupFirewallStatus='unknown';
 }
}
function setupProjects(id){
 const host=state.hosts.find(h=>h.id===id);if(!host)return;
 state.setupFlowId=id;
 state.hostPanel={id,tab:'deploy'};
 const visible=Object.entries(state.catalog).filter(([key,p])=>!p.internal);
 dialog(modalHead('第 5 步 · 选择要安装的软件')+setupProgress(5)+
  `<div class="setup-result"><span class="chip success">服务器 ${escapeHtml(host.name)} 已连接</span>
    <h3>接下来想在 VPS 上安装什么？</h3><p>${certLabel(host)}。系统会自动识别已有软件、检查环境并生成安装方案；真正安装前只需要批准一次。</p></div>
    <div class="server-project-grid">${visible.map(([key,project])=>`<button class="server-project-choice" data-action="server-install" data-id="${id}" data-project="${escapeHtml(key)}">
      <span class="project-choice-icon">${symbol[key]||'▣'}</span><strong>${escapeHtml(project.name)}</strong>
      <small>${escapeHtml(project.subtitle)}</small><span class="project-choice-link">${project.deployment==='install'?'选择并继续':'查看方案'} →</span>
     </button>`).join('')}</div>
    <div class="modal-actions"><button class="btn ghost" data-action="back-host" data-id="${id}">完成，稍后部署</button></div>`);
}
function addHost(){
 state.setupFlowId=null;
 state.hostPanel=null;
 dialog(modalHead('第 1 步 · 添加 Linux VPS')+setupProgress(1)+
  `<p class="helptext">SSH 用服务器公网 IPv4 连接；域名是可选的 HTTPS 证书地址，不能代替 SSH IP。保存后直接进入指纹验证，不再返回首页。</p>
  <form id="add-host-form"><div class="form-group"><label>服务器名称</label><input name="name" placeholder="例如：日本 VPS 01" required maxlength="60"/></div>
  <div class="form-group"><label>服务器公网 IPv4（用于 SSH 连接）</label><input name="hostname" placeholder="例如：45.32.35.195" required inputmode="decimal"/></div>
  <div class="form-group"><label>HTTPS 证书域名（可选，不填就申请 IP 证书）</label>
    <input name="tls_domain" placeholder="例如：ts.example.com" autocomplete="off"/>
    <p class="helptext">如果填写域名，请先将其 DNS A 记录指向上面的 VPS IPv4。部署时自动验证，无需再选择证书类型。</p></div>
  <div class="form-2"><div class="form-group"><label>SSH 用户名</label><input name="username" value="root" required/></div>
    <div class="form-group"><label>SSH 端口</label><input name="port" type="number" min="1" max="65535" value="22" required/></div></div>
  ${authSelect()}
  <div class="modal-tip">首次连接仍需通过 VPS 云控制台独立核对一次 SSH 指纹。密码可保存到 Windows 系统凭据库；以后不必反复输入。</div>
  <div class="modal-actions"><button type="button" class="btn ghost" data-action="close-modal">取消</button>
    <button class="btn primary" type="submit">添加并验证服务器 →</button></div></form>`);
 enableAuthToggle();
 el('#add-host-form').addEventListener('submit',async e=>{
   e.preventDefault();const form=e.currentTarget;
   const d=Object.fromEntries(new FormData(form));
   d.port=Number(d.port);d.tls_domain=String(d.tls_domain||'').trim()||null;
   d.remember_password=d.remember_password==='on';
   if(d.auth_mode!=='password')delete d.password;
   if(!isIpv4Input(String(d.hostname).trim())){toast('SSH 地址请填写 VPS 公网 IPv4；如果有域名，请填写下方的可选 HTTPS 证书域名框',true);return;}
   const existing=state.hosts.find(h=>h.hostname.toLowerCase()===String(d.hostname).toLowerCase()&&h.port===d.port);
   if(existing){
     if((existing.tls_domain||'')!==(d.tls_domain||'')){
       editHost(existing.id);toast('该 IP 已添加，请在服务器编辑中修改可选证书域名，不会重置 SSH 信任');
     }else{await beginServerSetup(existing.id);}
     return;
   }
   const btn=form.querySelector('button[type="submit"]');if(btn){btn.disabled=true;btn.classList.add('is-loading');}
   try{
     toast('正在保存 VPS 和本机 SSH 凭据…');
     const created=await api('/hosts',{method:'POST',body:JSON.stringify(d)});
     // Server response is authoritative. Reconcile it immediately so a
     // concurrent 5-second dashboard refresh cannot hide the new VPS before
     // the next SSH fingerprint step begins.
     state.hosts=[created,...state.hosts.filter(h=>h.id!==created.id)];
     await loadAll(true);
     if(!state.hosts.some(h=>h.id===created.id))state.hosts.unshift(created);
     toast('服务器已添加，下一步核对 SSH 指纹');
     await beginServerSetup(created.id);
   }catch(err){toast(err.message,true);}
   finally{if(btn?.isConnected){btn.disabled=false;btn.classList.remove('is-loading');}}
 });
}
function editHost(id){
 const host=state.hosts.find(h=>h.id===id);if(!host)return;
 const locked=Boolean(host.job_count);
 dialog(modalHead('编辑 VPS 服务器')+`<p class="helptext">SSH 地址建议填写公网 IPv4；HTTPS 域名可以单独编辑，不会影响 SSH 连接与已信任的主机指纹。</p>
 <form id="edit-host-form"><div class="form-group"><label>显示名称</label><input name="name" maxlength="60" required value="${escapeHtml(host.name)}"/></div>
 <div class="form-group"><label>服务器公网 IPv4（SSH 地址）</label><input name="hostname" required value="${escapeHtml(host.hostname)}" ${locked?'readonly':''}/></div>
 <div class="form-group"><label>HTTPS 证书域名（可选，不填使用服务器 IP）</label>
   <input name="tls_domain" value="${escapeHtml(host.tls_domain||'')}" placeholder="例如：ts.example.com"/>
   <p class="helptext">此项可单独修改；有待审批的 HTTPS 计划时会使旧计划失效，避免用旧域名部署。</p></div>
 <div class="form-2"><div class="form-group"><label>SSH 用户名</label><input name="username" required value="${escapeHtml(host.username)}" ${locked?'readonly':''}/></div>
 <div class="form-group"><label>SSH 端口</label><input name="port" type="number" min="1" max="65535" required value="${host.port}" ${locked?'readonly':''}/></div></div>
 <div class="modal-tip">${locked?`已有 ${host.job_count} 条部署历史，因此 SSH IP、端口和用户名保持锁定；但可修改显示名称和 HTTPS 证书域名。`:'修改 SSH IP、端口或用户名将清除旧环境检测状态及本机缓存密码，并需要重新验证 SSH 指纹。'}</div>
 <div class="modal-actions"><button type="button" class="btn ghost" data-action="close-modal">取消</button><button class="btn primary" type="submit">保存修改</button></div></form>`);
 el('#edit-host-form').addEventListener('submit',async e=>{
   e.preventDefault();const form=e.currentTarget;const d=Object.fromEntries(new FormData(form));d.port=Number(d.port);d.tls_domain=String(d.tls_domain||'').trim()||null;
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
 <form id="delete-host-form"><p class="helptext">点击下方删除按钮即可确认，不需要手动输入英文确认语句。</p>
 ${host.job_count?`<label class="check"><input type="checkbox" name="delete_local_history" required/> 我确认同步删除该 VPS 的 ${host.job_count} 条本地任务历史及日志（不会删除远端软件）</label>`:''}
 <div class="modal-actions"><button class="btn ghost" type="button" data-action="close-modal">取消</button><button class="btn danger" type="submit">删除本地服务器记录</button></div></form>`);
 el('#delete-host-form').addEventListener('submit',async e=>{
   e.preventDefault();const form=e.currentTarget;const fd=new FormData(form);
   const payload={confirmation:`DELETE VPS ${id}`,delete_local_history:fd.get('delete_local_history')==='on'};
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
 el('#credentials-form').addEventListener('submit',async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(e.currentTarget));d.remember_password=d.remember_password==='on';if(d.auth_mode!=='password')delete d.password;const btn=e.currentTarget.querySelector('button[type="submit"]');if(btn){btn.disabled=true;btn.classList.add('is-loading');}try{toast('正在安全更新登录凭据…');await api(`/hosts/${id}/credentials`,{method:'PUT',body:JSON.stringify(d)});closeDialog();await loadAll(true);toast('登录凭据已更新；生成部署方案时会自动检测环境');if(state.setupFlowId===id)await setupPreflight(id);}catch(err){toast(err.message,true);}finally{if(btn?.isConnected){btn.disabled=false;btn.classList.remove('is-loading');}}});
}
async function fingerprint(id){
 const host=state.hosts.find(h=>h.id===id);if(!host)return;
 dialog(modalHead('第 2 步 · SSH 主机指纹')+(state.setupFlowId===id?setupProgress(2):'')+`<div class="fingerprint-workflow">
   <p class="helptext">${escapeHtml(host.name)} · ${escapeHtml(host.hostname)}:${host.port}</p>
   <div id="fingerprint-data" class="fingerprint-loading" role="status"><span class="inline-spinner" aria-hidden="true"></span><span>正在读取主机公钥并比对本机信任记录…</span></div>
 </div>`);
 try{
   const res=await api(`/hosts/${id}/fingerprint`,{method:'POST'});
   const target=el('#fingerprint-data');if(!target)return;
   const old=res.previous_fingerprints||[];
   const changed=Boolean(res.changed);
   const matched=old.length>0&&!changed;
   const algorithm=String(res.key_type||'ssh-ed25519');
   const keyFile=algorithm==='ssh-ed25519'?'ed25519':algorithm.startsWith('ecdsa-')?'ecdsa':'rsa';
   state.pendingFingerprint={hostId:id,...res};
   target.className='fingerprint-result';
   const currentCard=`<div class="fingerprint-key-card"><span class="fingerprint-label">当前主机指纹 · ${escapeHtml(algorithm)}</span>
     <code class="fingerprint-value">${escapeHtml(res.fingerprint)}</code></div>`;
   const closeAction=`<button class="btn primary" data-action="back-host" data-id="${id}">返回服务器控制台</button>`;
   if(matched){
     target.innerHTML=`<div class="fingerprint-verdict verified" role="status"><span class="fingerprint-verdict-icon" aria-hidden="true">✓</span>
       <div><strong>SSH 主机身份验证通过</strong><p>当前指纹与此前保存的记录完全一致，不需要重复信任。</p></div></div>
       ${currentCard}
       <details class="fingerprint-guide"><summary>如何在云厂商控制台再次核对？</summary>
         <p>仅在首次连接、怀疑服务器被替换或重装时需要独立核对：</p>
         <code class="fingerprint-command">ssh-keygen -lf /etc/ssh/ssh_host_${keyFile}_key.pub -E sha256</code>
       </details><div class="fingerprint-actions">${closeAction}</div>`;
     if(state.setupFlowId===id){toast('SSH 指纹已验证，自动进入连接检测');await setupPreflight(id);}
     return;
   }
   const status=changed
     ?'<div class="fingerprint-verdict changed" role="alert"><span class="fingerprint-verdict-icon" aria-hidden="true">!</span><div><strong>服务器指纹发生变化</strong><p>若 VPS 已重装，请先在云厂商的独立控制台核对新指纹，不能直接跳过验证。</p></div></div>'
     :'<div class="fingerprint-verdict first" role="status"><span class="fingerprint-verdict-icon" aria-hidden="true">i</span><div><strong>首次连接，需要核对指纹</strong><p>扫描只能获取公钥，不能独立证明对方身份。</p></div></div>';
   const oldCard=changed&&old.length?`<div class="fingerprint-key-card previous"><span class="fingerprint-label">之前信任的指纹</span>
     ${old.map(x=>`<code class="fingerprint-value">${escapeHtml(x.key_type)} · ${escapeHtml(x.fingerprint)}</code>`).join('')}</div>`:'';
   const shared=changed&&res.shared_host_count>1?`<p class="fingerprint-shared">提示：${res.shared_host_count} 条 VPS 记录共用此 IP 和 SSH 端口，确认更新会使这些记录的旧部署计划失效。</p>`:'';
   const button=changed
      ?`<button class="btn danger" data-action="prepare-rekey" data-id="${id}">已核实 VPS 重装，更新信任</button>`
      :`<button class="btn primary" data-action="trust" data-id="${id}" data-fingerprint="${escapeHtml(res.fingerprint)}">${state.setupFlowId===id?'确认指纹，下一步检测连接 →':'核对一致，首次信任'}</button>`;
   target.innerHTML=`${status}<div class="fingerprint-key-stack">${currentCard}${oldCard}</div>
     <div class="fingerprint-guide always"><strong>核对方式</strong><p>进入 VPS 云厂商的网页控制台，执行下面的命令。核对结果必须与当前指纹一致。</p>
       <code class="fingerprint-command">ssh-keygen -lf /etc/ssh/ssh_host_${keyFile}_key.pub -E sha256</code></div>
     ${shared}<label class="fingerprint-confirm"><input type="checkbox" id="verified-key"/> 我已通过独立控制台核对，确认当前指纹一致</label>
     <div class="fingerprint-actions"><button class="btn ghost" data-action="back-host" data-id="${id}">返回</button>${button}</div>`;
 }catch(err){
   const target=el('#fingerprint-data');
   if(target){target.className='fingerprint-result';target.innerHTML=`<div class="fingerprint-verdict changed" role="alert">
      <div><strong>无法获取 SSH 主机公钥</strong><p>${escapeHtml(err.message)}</p></div></div>
      <details class="fingerprint-guide"><summary>查看网络排查命令</summary>
        <code class="fingerprint-command">Test-NetConnection -ComputerName ${escapeHtml(host.hostname)} -Port ${Number(host.port)}</code>
      </details><div class="fingerprint-actions"><button class="btn primary" data-action="fingerprint" data-id="${id}">重新扫描</button><button class="btn subtle" data-action="back-host" data-id="${id}">返回服务器</button></div>`;}
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
 <p class="helptext">你已勾选独立核对指纹，无需再复制或输入确认语句。点击按钮后还会重新验证服务器公钥，确认一致才会更新。</p>
 <form id="rekey-form">
 <div class="modal-actions"><button class="btn ghost" type="button" data-action="fingerprint" data-id="${id}">返回核对指纹</button>
 <button class="btn danger" type="submit">确认更新 SSH 信任</button></div></form>`);
 el('#rekey-form').addEventListener('submit',async e=>{
   e.preventDefault();const form=e.currentTarget;const submit=form.querySelector('button[type="submit"]');
   if(state.pendingFingerprint!==pending||state.pendingFingerprint.hostId!==id){toast('主机指纹信息已变化，请重新扫描并独立核对',true);return;}
   if(submit){submit.disabled=true;submit.classList.add('is-loading');}
   const confirmation=phrase;toast('正在确认新指纹并安全更新信任记录…');
   try{const result=await api(`/hosts/${id}/rekey`,{method:'POST',body:JSON.stringify({
      fingerprint:pending.fingerprint,previous_fingerprints:pending.previous_fingerprints.map(x=>x.fingerprint),
      confirmed_out_of_band:true,confirmation
   })});state.pendingFingerprint=null;closeDialog();await loadAll(true);
      toast(`新指纹已安全信任，影响 ${result.affected_host_records} 条记录；请重新检测系统并核对 SSH 登录密码`);
      if(state.setupFlowId===id)await setupPreflight(id);
      else openHostConsole(id,'security');
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
 <div class="modal-tip"><b id="cert-type-preview">证书类型自动识别中</b> —  SSH 使用 VPS IP；证书按“服务器设置”中可选的 HTTPS 域名决定：不填域名就申请 IP 短期证书，填写域名则申请域名证书。已有 3X-UI 只升级 HTTPS，不重装。公网 TCP 80 必须允许 Let’s Encrypt 验证；失败时会显示具体原因，并保持原本的本机安全监听。</div>`:''}
 <div class="modal-tip">仅生成可审查的部署计划；确认所有步骤和风险后仍需单独审批执行。</div>
 <div class="modal-actions"><button type="button" class="btn ghost" data-action="close-modal">取消</button><button class="btn primary">自动检测并生成方案 →</button></div></form>`);
 if(project==='3x-ui'){
   const target=el('#plan-host-id');
   const preview=()=>{
     const host=state.hosts.find(h=>h.id===Number(target?.value));
     if(!host)return;
     const ip=!host.tls_domain&&isIpv4Input(host.hostname);
     const indicator=el('#cert-type-preview');
     if(indicator)indicator.textContent=ip?`不填域名：使用 ${host.hostname} 申请 IP 证书`:`已设置 ${host.tls_domain}：自动申请域名证书`;
   };
   target?.addEventListener('change',preview);
   preview();
 }
 el('#plan-form').addEventListener('submit',async e=>{
  e.preventDefault();const form=e.currentTarget,fd=new FormData(form);
  const hostId=Number(fd.get('host_id'));
  if(project==='3x-ui'){await createHostPlan(hostId,project,Number(fd.get('panel_port')));return;}
  const request={host_id:hostId,project};
  const submit=form.querySelector('button[type="submit"]');if(submit){submit.disabled=true;submit.classList.add('is-loading');}
  try{
    toast('正在检查 VPS 并生成方案…');
    const job=await api('/jobs',{method:'POST',body:JSON.stringify(request)});
    state.activeJob=null;await loadAll(true);
    if(!state.jobs.some(j=>j.id===job.id))state.jobs.unshift(job);
    showJob(job.id);
  }catch(err){toast(err.message,true);}
  finally{if(submit?.isConnected){submit.disabled=false;submit.classList.remove('is-loading');}}
 });
}
function showJob(id){
 const job=state.jobs.find(j=>j.id===id);if(!job){toast('任务不存在，请刷新',true);return;}
 state.activeJob=id;
 const p=job.plan,host=state.hosts.find(h=>h.id===job.host_id);
 const stale=(p.trust_epoch||0)!==(host?.trust_epoch||0);
 let html=modalHead(`${p.name} · 部署任务`)+`<div class="toolbar">${chip(job.status)}<span class="chip">${escapeHtml(host?.name||p.hostname)}</span><span class="chip">${escapeHtml(p.options?.panel_port||'')}${p.options?.panel_port?' / TCP':''}</span></div>`;
 if(stale)html+='<div class="modal-tip warning">此任务属于服务器重装前的系统。旧登录信息和审批计划已失效，必须重新检测并创建新的部署方案。</div>';
 if(p.issues.length&&!isExistingXuiPlan(job))html+=`<div class="modal-tip warning">${p.issues.map(escapeHtml).join('；')}</div>`;
 if(job.status==='planned'&&p.executable&&!stale&&job.needs_refresh===true){
   html+=`<section class="server-next-action pending"><span class="server-next-kicker">旧脚本已更新</span>
     <h3>这份审批计划来自更新前的版本</h3><p>3X-UI HTTPS 命令已修复，旧计划不能直接用。点击下面按钮重新检测并生成当前版本的固定方案；不会立即改动 VPS。</p>
     <button class="btn primary" data-action="regenerate-plan" data-id="${escapeHtml(job.id)}">更新为最新 HTTPS 修复方案 →</button>
   </section>`;
 }else if(job.status==='planned'&&p.executable&&!stale&&isPlanExpired(job)){
   html+=`<section class="server-next-action pending"><span class="server-next-kicker">需要更新计划</span>
     <h3>部署计划已超过 10 分钟</h3><p>为防止服务器环境发生变化，点击下方按钮重新检测并生成最新计划。此操作不会直接安装软件。</p>
     <button class="btn primary" data-action="regenerate-plan" data-id="${escapeHtml(job.id)}">更新方案并继续审批 →</button>
   </section>`;
 }else if(job.status==='planned'&&p.executable&&!stale){
   const isXui=job.project==='3x-ui'||job.project==='3x-ui-https';
   html+=`<div class="plan-overview"><h3>${job.project==='3x-ui-https'?'继续配置已安装的 3X-UI HTTPS（不重装）':isXui?'一键安装 3X-UI 并配置 HTTPS':'准备部署 '+escapeHtml(p.name)}</h3>
     <p>目标：${escapeHtml(host?.hostname||p.hostname)} · ${p.steps.length} 个受控执行阶段 · 风险：${escapeHtml(p.risk)}</p>
     <div class="modal-tip warning">审批一次后将执行已固定的安装步骤；包括 APT 依赖处理、证书签发（如果需要）和所需的本机 UFW 端口规则。云厂商安全组仍需另行放行；建议先备份 VPS。</div></div>
     <form id="approve-form"><div class="modal-actions plan-primary-actions">
       <button type="button" class="btn subtle" data-action="regenerate-plan" data-id="${escapeHtml(job.id)}">重新检测方案</button>
       <button type="button" class="btn ghost" data-action="close-modal">暂不部署</button>
       <button class="btn primary" type="submit">${job.project==='3x-ui-https'?'确认继续 HTTPS（不重装）':'确认并一键部署'}</button>
     </div></form>`;
 }else if(isExistingXuiPlan(job)&&!stale){
   html+=`<section class="server-next-action is-ready"><span class="server-next-kicker">已安装 · 无需审批</span>
     <h3>3X-UI 已存在，不需要重新安装</h3><p>此历史方案没有安装步骤，因此无法执行。直接通过已验证 SSH 读取现有面板信息；仅在修改配置时才需要确认。</p>
     <button class="btn primary" data-action="installed-xui" data-id="${job.host_id}">查看现有 3X-UI 面板 →</button>
   </section>`;
 }else if(historicalHttpsFailure(job)&&!stale){
   html+=`<section class="server-next-action pending"><span class="server-next-kicker">旧版执行记录 · 当前模板已修复</span>
     <h3>这条 HTTPS 失败记录来自旧版本脚本</h3>
     <p>历史任务的固定命令与当前 NetDeploy AI 代码不一致，不能据此认定新版仍然失败。3X-UI 和现有证书保持不变，点击只会重新生成当前版本的 HTTPS 配置方案，不会直接重装或执行。</p>
     <button class="btn primary" data-action="regenerate-plan" data-id="${escapeHtml(job.id)}">生成最新版 HTTPS 修复方案 →</button>
   </section>`;
   html+=`<h3>原任务执行日志</h3><div id="job-state" class="log-status" data-current-status="${escapeHtml(job.status)}">${escapeHtml(stateText(job.status))}</div>
     <pre id="task-log" class="pre">${escapeHtml(job.logs||'暂无执行日志')}</pre>
     <div class="modal-actions"><button class="btn subtle" data-action="installed-xui" data-id="${job.host_id}">查看已安装 3X-UI</button>
       <button class="btn subtle" data-action="close-modal">关闭</button></div>`;
 }else{
   html+=`<h3>部署状态及日志</h3><div id="job-state" class="log-status" data-current-status="${escapeHtml(job.status)}">${escapeHtml(stateText(job.status))}</div>
      <pre id="task-log" class="pre">${escapeHtml(job.logs||'暂无执行日志')}</pre>
      <div class="modal-actions modal-action-wrap">
       ${job.project==='3x-ui'&&!stale&&['completed','partial'].includes(job.status)?`<button class="btn primary" data-action="installed-xui" data-id="${job.host_id}">查看面板信息</button>${(p.options?.access_mode==='https'&&job.status==='completed')||state.jobs.some(x=>x.project==='3x-ui-https'&&x.plan.options?.source_job_id===job.id&&['completed','queued','running'].includes(x.status))?'':`<button class="btn subtle" data-action="xui-upgrade" data-id="${escapeHtml(job.id)}">继续完成 HTTPS</button>`}`:''}
       ${job.project==='s-ui'&&!stale&&job.status==='completed'?`<button class="btn primary" data-action="installed-sui" data-id="${job.host_id}">查看 S-UI 面板信息</button>`:''}
       ${job.project==='3x-ui-https'&&!stale&&job.status==='completed'?`<button class="btn primary" data-action="installed-xui" data-id="${job.host_id}">查看 HTTPS 面板信息</button>`:''}
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
 const existing=state.jobs.find(j=>j.project==='3x-ui-https'&&j.host_id===source.host_id&&
   j.plan?.options?.source_job_id===source.id&&
   ['planned','queued','running'].includes(j.status)&&!planNeedsUpdate(j));
 if(existing){
   showJob(existing.id);
   toast(existing.status==='planned'?'已有 HTTPS 待审批方案，可直接继续':'HTTPS 配置任务已启动，可直接查看进度');
   return;
 }
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
 const asyncActions=new Set(['installed-xui','existing-xui-https','install-new-xui','fingerprint','trust','preflight','host-check','setup-firewall','server-install','confirm-delete-job','diagnose','regenerate-plan','xui-upgrade','xui-access','copy-xui-url','copy-xui-username','copy-xui-password','copy-xui-tunnel']);
 if(t.dataset.busy==='1')return;
 const busy=asyncActions.has(act)||act==='apply-ufw-toggle';
 if(busy){t.dataset.busy='1';t.disabled=true;t.classList.add('is-loading');t.setAttribute('aria-busy','true');}
 try{
  if(act==='close-modal'){closeDialog();state.activeJob=null;state.hostPanel=null;state.pendingFingerprint=null;state.setupFlowId=null;}
  else if(act==='setup-add-port')addSetupPort();
  else if(act==='setup-remove-port')removeSetupPort(t);
  else if(act==='setup-retry-failed')await retryFailedSetupPorts(Number(id));
  else if(act==='setup-firewall')await setupFirewall(Number(id));
  else if(act==='setup-projects')setupProjects(Number(id));
  else if(act==='setup-retry')await setupPreflight(Number(id));
  else if(act==='host-console')openHostConsole(Number(id));
  else if(act==='back-host'){state.setupFlowId=null;openHostConsole(Number(id),state.hostPanel?.tab||'overview');}
  else if(act==='host-tab')openHostConsole(Number(id),t.dataset.tab||'overview');
  else if(act==='toggle-ufw')confirmUfwToggle(Number(id),t.dataset.mode);
  else if(act==='apply-ufw-toggle')await applyUfwToggle(Number(id),t.dataset.mode);
  else if(act==='host-check')await checkHostInConsole(Number(id));
  else if(act==='installed-sui')await showExistingSui(Number(id));
  else if(act==='toggle-sui-password'){const field=el('#sui-password');if(field)field.type=field.type==='password'?'text':'password';}
  else if(act==='copy-sui-url')await copyXuiField('sui-url','S-UI 面板地址');
  else if(act==='copy-sui-username')await copyXuiField('sui-username','S-UI 管理员用户名');
  else if(act==='copy-sui-password')await copyXuiField('sui-password','S-UI 管理员密码');
  else if(act==='copy-sui-tunnel')await copyXuiField('sui-tunnel','S-UI SSH 隧道命令');
  else if(act==='installed-xui')await showExistingXui(Number(id));
  else if(act==='existing-xui-https')await continueExistingXuiHttps(Number(id));
  else if(act==='install-new-xui')await createHostPlan(Number(id),'3x-ui');
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
       toast(result.already_trusted?'主机指纹与已信任记录一致':'已信任新的服务器指纹，可以继续检测环境');
       if(state.setupFlowId===Number(id))await setupPreflight(Number(id));}
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
document.addEventListener('keydown',e=>{const card=e.target.closest?.('[data-action="host-console"]');if(card&&e.target===card&&(e.key==='Enter'||e.key===' ')){e.preventDefault();openHostConsole(Number(card.dataset.id));}});
el('#refresh').addEventListener('click',async e=>{const button=e.currentTarget;button.classList.add('is-loading');button.disabled=true;try{await loadAll();}finally{button.classList.remove('is-loading');button.disabled=false;}});
el('#logout').addEventListener('click',()=>{sessionStorage.removeItem('nd_token');state.token='';el('#login').classList.remove('hidden');});
setInterval(()=>{if(state.token)loadAll(true);},5000);
start();
