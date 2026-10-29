// No browser, network, VPS or third-party packages required.
// A minimal DOM harness exercises real NetDeploy UI functions instead of only
// checking text fragments. Desktop and Windows CI both run this smoke test.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const javascript = fs.readFileSync(path.join(root, 'app/static/app.js'), 'utf8');
const css = fs.readFileSync(path.join(root, 'app/static/app-enhanced.css'), 'utf8');
const made = new Map();
function makeElement() {
  const classes = new Set();
  const handlers = new Map();
  return {
    className: '',
    innerHTML: '',
    textContent: '',
    value: '',
    disabled: false,
    dataset: {},
    classList: {
      add: name => classes.add(name),
      remove: name => classes.delete(name),
      contains: name => classes.has(name),
      toggle: (name,yes) => {if(yes)classes.add(name);else classes.delete(name);},
    },
    addEventListener: (kind, fn) => handlers.set(kind, fn),
    async dispatch(kind,event) {return handlers.get(kind)?.(event);},
    formValues: {},
    isConnected:true,
    setAttribute() {},
    removeAttribute() {},
    querySelector() { return makeElement(); },
    insertAdjacentHTML() {},
  };
}
for (const selector of ['#modal-content','#modal','#login','#refresh','#logout','#login-form',
  '#toast','#admin-token']) made.set(selector, makeElement());
const modal = made.get('#modal-content');
const fingerprintTarget = makeElement();
const approveForm = makeElement();
const document = {
  querySelector(selector) {
    if (selector === '#fingerprint-data') {
      return modal.innerHTML.includes('id="fingerprint-data"') ? fingerprintTarget : null;
    }
    if (selector === '#approve-form') {
      return modal.innerHTML.includes('id="approve-form"') ? approveForm : null;
    }
    if (selector === '#job-state'){
      const match=modal.innerHTML.match(/id="job-state"[^>]*data-current-status="([^"]+)"/);
      if(!match)return null;
      if(!made.has(selector))made.set(selector,makeElement());
      made.get(selector).dataset.currentStatus=match[1];
      return made.get(selector);
    }
    if(selector==='#task-log'&&!modal.innerHTML.includes('id="task-log"'))return null;
    if (selector === '#verified-key') return trustCheck?{checked:true}:null;
    if (!made.has(selector)) made.set(selector, makeElement());
    return made.get(selector);
  },
  querySelectorAll() { return []; },
  addEventListener(kind,fn) {domHandlers.set(kind,fn);},
};
const host = {
  id: 1, name:'Test VPS', hostname:'45.32.35.195', port:22,username:'root',
  auth_mode:'password',password_remembered:true,credential_ready:true,trust_epoch:0,
  job_count:1,facts:{OS_ID:'ubuntu',ARCH:'x86_64'},
};
const domHandlers=new Map();
let trustCheck=false;
let preflightRequests=0;
let trustRequests=0;
let storedHosts=[host];
let firewallReadCount=0;
let firewallAllowCount=0;
let firewallDisableCount=0;
let rekeyCount=0;
let firewallMode='active';
class FakeFormData{
  constructor(form){this.values=form.formValues||{};}
  get(k){return this.values[k]??null;}
  [Symbol.iterator](){return Object.entries(this.values)[Symbol.iterator]();}
}
const freshJob = {
  id:'a1b2c3d4e5f6a7b8',host_id:1,project:'3x-ui',status:'planned',
  created_at:new Date().toISOString(),
  plan: {
    trust_epoch:0, project:'3x-ui',name:'3X-UI',risk:'高',
    executable:true,options:{panel_port:24443},issues:[],requires:[],warnings:[],steps:[{label:'check',timeout:10,script:'echo safe'}],
  },
};
let mockFingerprint = null;
let fingerprintRequests = 0;
let planCreations = 0;
let xuiStatus = {installed:false,service:'absent',managed:false,port:null,access_mode:'unavailable'};
let returnedJobs=null;
let runtimeVersion='0.3.12';
let xuiReadRequests=0;
const context = vm.createContext({
  console,
  document,
  window:{matchMedia:()=>({matches:false}),scrollTo(){}},
  sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},
  navigator:{clipboard:{writeText:async()=>{}}},
  setInterval(){},
  FormData:FakeFormData,
  clearTimeout(){},
  setTimeout(){return 1;},
  fetch:async (url,opts={})=>{
    if (url==='/api/local-session') return {ok:false,status:403,json:async()=>({})};
    if (/^\/api\/hosts\/\d+\/fingerprint$/.test(url)) {
      fingerprintRequests++;
      return {ok:true,status:200,json:async()=>mockFingerprint};
    }
    if(/^\/api\/hosts\/\d+\/rekey$/.test(url)){
      const body=JSON.parse(opts.body||'{}');
      assert.equal(opts.method,'POST');
      assert.equal(body.confirmed_out_of_band,true);
      assert.equal(body.fingerprint,mockFingerprint.fingerprint);
      assert.deepEqual(body.previous_fingerprints,mockFingerprint.previous_fingerprints.map(x=>x.fingerprint));
      assert.equal(body.confirmation,'REKEY 45.32.35.195:22');
      rekeyCount++;
      return {ok:true,status:200,json:async()=>({affected_host_records:1,old_plans_invalidated:true})};
    }
    if(/^\/api\/hosts\/\d+\/firewall$/.test(url)){
      firewallReadCount++;
      return {ok:true,status:200,json:async()=>({status:firewallMode,cloud_notice:'cloud security group separate',details:'Status: active'})};
    }
    if(/^\/api\/hosts\/\d+\/firewall\/allow$/.test(url)){
      const body=JSON.parse(opts.body||'{}');
      assert.equal(opts.method,'POST');
      assert.equal(body.confirmation,true);
      assert.equal(body.port,8443);
      assert.equal(body.protocol,'tcp');
      firewallAllowCount++;
      return {ok:true,status:200,json:async()=>({mode:'active',port:8443,protocol:'tcp',ok:true})};
    }
    if(/^\/api\/hosts\/\d+\/firewall\/toggle$/.test(url)){
      const body=JSON.parse(opts.body||'{}');
      assert.equal(body.mode,'disable');
      assert.equal(body.confirmed_risk,true);
      firewallDisableCount++;firewallMode='inactive';
      return {ok:true,status:200,json:async()=>({ok:true,mode:'inactive'})};
    }
    if(/^\/api\/hosts\/\d+\/trust$/.test(url)){
      const request=JSON.parse(opts.body||'{}');
      assert.equal(request.confirmed_out_of_band,true);
      assert.equal(request.fingerprint,mockFingerprint.fingerprint);
      trustRequests++;
      return {ok:true,status:200,json:async()=>({already_trusted:false})};
    }
    if(/^\/api\/hosts\/\d+\/preflight$/.test(url)){
      preflightRequests++;
      return {ok:true,status:200,json:async()=>({
        id:2,name:'VIP1',hostname:'45.32.35.196',
        facts:{OS_ID:'ubuntu',OS_VERSION:'26.10',ARCH:'x86_64'}
      })};
    }
    if(url==='/api/hosts/1/3x-ui'){
      return {ok:true,status:200,json:async()=>xuiStatus};
    }
    if(url==='/api/hosts/1/3x-ui/access'){
      xuiReadRequests++;
      return {ok:true,status:200,json:async()=>({
        username:'InitialAdmin88',password:'InitialPassword88',port:24443,
        local_url:'http://127.0.0.1:24443/SecretRoute123',web_path:'SecretRoute123',
        ssh_tunnel:'ssh -N -p 22 -L 24443:127.0.0.1:24443 root@45.32.35.195',
        access_mode:'local'
      })};
    }
    if(url==='/api/health')return {ok:true,status:200,json:async()=>({ok:true,version:runtimeVersion})};
    if(url==='/api/hosts'&&opts.method==='POST'){
      const data=JSON.parse(opts.body);
      const created={...data,id:2,hostname:data.hostname,tls_domain:data.tls_domain,
        credential_ready:true,job_count:0,trust_epoch:0,auth_mode:data.auth_mode};
      storedHosts=[created,host];
      return {ok:true,status:200,json:async()=>created};
    }
    if(url==='/api/hosts')return {ok:true,status:200,json:async()=>storedHosts};
    if(url==='/api/catalog')return {ok:true,status:200,json:async()=>({
      '3x-ui':{name:'3X-UI',subtitle:'Xray 管理面板',deployment:'install',category:'面板'}
    })};
    if(url==='/api/capabilities')return {ok:true,status:200,json:async()=>({secure_password_storage:false})};
    if(url==='/api/jobs'&&returnedJobs)
      return {ok:true,status:200,json:async()=>returnedJobs};
    if (url==='/api/jobs') planCreations++;
    throw new Error('Unexpected network attempt: '+url);
  },
  fixtures:{host,freshJob},
});
vm.runInContext(javascript, context, {timeout:3000});
function evaluate(code) {return vm.runInContext(code,context,{timeout:3000});}
function fill(job=freshJob){
  context.fixtures.freshJob=job;
  evaluate("state.hosts=[fixtures.host];state.jobs=[fixtures.freshJob];"+
    "state.catalog={'3x-ui':{name:'3X-UI',deployment:'install',subtitle:'Xray 管理面板'}};");
}
function fingerprintFor(label) {
  return {
    fingerprint:label,
    key_type:'ssh-ed25519',
    previous_fingerprints:[{key_type:'ssh-ed25519',fingerprint:'SHA256:OldPinnedFingerprintAAA'}],
    changed:label!=='SHA256:OldPinnedFingerprintAAA',
    shared_host_count:1,
  };
}

(async()=>{
  fill();
  evaluate('openHostConsole(1)');
  assert(modal.innerHTML.includes('继续审批部署'), 'Primary action must be visible');
  assert(modal.innerHTML.includes('部署方案已准备好'), 'Must explain pending approval');
  assert(modal.innerHTML.indexOf('继续审批部署') < modal.innerHTML.indexOf('最近部署任务'),
    'Approval must come before routine history');
  assert(modal.innerHTML.includes('安装软件'), 'Use understandable tab labels');
  assert(!modal.innerHTML.includes('四项权限确认'), 'No unnecessary confirmations');

  evaluate("showJob('a1b2c3d4e5f6a7b8')");
  assert(modal.innerHTML.includes('id="approve-form"'), 'Approval must be reachable');
  assert(modal.innerHTML.includes('确认并一键部署'), 'Only one approval action');

  // Selecting the same project must open the existing pending plan, not create
  // duplicate SSH tasks and waste a second user's approval.
  await evaluate("createHostPlan(1,'3x-ui')");
  assert.equal(planCreations,0,'Pending plans must be reused');

  // A cached browser page and a still-running old server must be reported.
  // They are not proof that the new HTTPS recipe has failed.
  evaluate("state.token='test'");
  runtimeVersion='0.3.8';
  returnedJobs=[freshJob];
  await evaluate('loadAll(true)');
  assert(made.get('.tag.alpha').textContent.includes('版本不一致'));
  assert(made.get('.tag.alpha').textContent.includes('0.3.8'));
  runtimeVersion='0.3.12';
  await evaluate('loadAll(true)');
  assert(made.get('.tag.alpha').textContent==='ALPHA v0.3.12');
  returnedJobs=null;
  evaluate("state.token=''");

  // After a Git update, an approval generated for the old shell recipe is
  // flagged before the user can accidentally approve stale code.
  fill({...freshJob,needs_refresh:true});
  evaluate('openHostConsole(1)');
  assert(modal.innerHTML.includes('旧版代码'));
  assert(modal.innerHTML.includes('data-action="regenerate-plan"'));
  evaluate("showJob('a1b2c3d4e5f6a7b8')");
  assert(modal.innerHTML.includes('这份审批计划来自更新前的版本'));
  assert(!modal.innerHTML.includes('id="approve-form"'),
    'Old script plans must not have a direct approval button');
  assert(modal.innerHTML.includes('更新为最新 HTTPS 修复方案'));

  // A failed HTTPS job created by a previous NetDeploy release should
  // suggest generating a fresh 4-step HTTPS-only plan, not imply that the
  // current code has already failed. No approval is granted by this button.
  fill({...freshJob,project:'3x-ui-https',status:'failed',historical_script:true,
    plan:{...freshJob.plan,project:'3x-ui-https'}});
  evaluate('openHostConsole(1)');
  assert(modal.innerHTML.includes('生成最新版 HTTPS 修复方案'));
  assert(modal.innerHTML.includes('data-action="regenerate-plan"'));
  evaluate("showJob('a1b2c3d4e5f6a7b8')");
  assert(modal.innerHTML.includes('这条 HTTPS 失败记录来自旧版本脚本'));
  assert(!modal.innerHTML.includes('id="approve-form"'));
  assert(modal.innerHTML.includes('原任务执行日志'));

  fill({...freshJob,created_at:new Date(Date.now()-12*60*1000).toISOString()});
  evaluate('openHostConsole(1)');
  assert(modal.innerHTML.includes('部署计划已过期'));
  assert(modal.innerHTML.includes('data-action="regenerate-plan"'));
  evaluate("showJob('a1b2c3d4e5f6a7b8')");
  assert(!modal.innerHTML.includes('id="approve-form"'), 'Expired plan cannot be approved');
  assert(modal.innerHTML.includes('更新方案并继续审批'));

  fill();
  evaluate("openHostConsole(1,'security')");
  mockFingerprint=fingerprintFor('SHA256:OldPinnedFingerprintAAA');
  await evaluate('fingerprint(1)');
  assert.equal(fingerprintTarget.className,'fingerprint-result',
    'Results must not use a horizontal loading flex class');
  assert(fingerprintTarget.innerHTML.includes('SSH 主机身份验证通过'));
  assert(fingerprintTarget.innerHTML.includes('不需要重复信任'));
  assert(!fingerprintTarget.innerHTML.includes('id="verified-key"'),
    'Matching fingerprints should not require repeat confirmation');
  assert(fingerprintTarget.innerHTML.includes('data-action="back-host"'));

  mockFingerprint=fingerprintFor('SHA256:ChangedFingerprintBBB');
  await evaluate('fingerprint(1)');
  assert(fingerprintTarget.innerHTML.includes('服务器指纹发生变化'));
  assert(fingerprintTarget.innerHTML.includes('id="verified-key"'));
  assert(fingerprintTarget.innerHTML.includes('data-action="prepare-rekey"'));
  assert(fingerprintTarget.innerHTML.includes('独立控制台'));
  assert.equal(fingerprintRequests,2);

  // Confirming a VPS reinstallation no longer requires typing REKEY words.
  // First the new host key must still be checked via an independent channel.
  trustCheck=false;
  evaluate('prepareRekey(1)');
  assert(!modal.innerHTML.includes('id="rekey-form"'));
  assert.equal(rekeyCount,0);
  trustCheck=true;
  evaluate('prepareRekey(1)');
  assert(modal.innerHTML.includes('id="rekey-form"'));
  assert(modal.innerHTML.includes('无需再复制或输入确认语句'));
  assert(!modal.innerHTML.includes('name="confirmation"'));
  const rekeyForm=made.get('#rekey-form');
  await rekeyForm.dispatch('submit',{preventDefault(){},currentTarget:rekeyForm});
  assert.equal(rekeyCount,1,'Explicit confirmation after independent verification should update trust once');
  trustCheck=false;

  // An existing 3X-UI must open read-only information without a new plan.
  fill({...freshJob,status:'planned',plan:{...freshJob.plan,executable:false,steps:[],
    issues:['已存在 x-ui 安装，禁止覆盖'],preflight_baseline:{XUI_PRESENT:'yes'}}});
  evaluate("showJob('a1b2c3d4e5f6a7b8')");
  assert(!modal.innerHTML.includes('id="approve-form"'));
  assert(modal.innerHTML.includes('查看现有 3X-UI 面板'));
  xuiStatus={installed:true,service:'active',managed:true,port:24443,access_mode:'local'};
  await evaluate("createHostPlan(1,'3x-ui')");
  assert(modal.innerHTML.includes('已安装，无需重新部署'));
  assert(modal.innerHTML.includes('id="xui-username"'));
  assert(modal.innerHTML.includes('id="xui-password"'));
  assert(modal.innerHTML.includes('data-action="existing-xui-https"'));
  assert.equal(xuiReadRequests,1);
  assert.equal(planCreations,0,'Existing installation must not create a new install task');

  // A running job becoming completed via polling must immediately grow its
  // "查看面板信息" action in the currently open modal, no reopening required.
  const running={...freshJob,status:'running',logs:'Started',plan:{...freshJob.plan}};
  fill(running);
  evaluate("state.token='test';showJob('a1b2c3d4e5f6a7b8')");
  assert(modal.innerHTML.includes('data-current-status="running"'));
  assert(!modal.innerHTML.includes('查看面板信息'));
  returnedJobs=[{...running,status:'completed',logs:'Done'}];
  await evaluate('loadAll(true)');
  assert(modal.innerHTML.includes('查看面板信息'),
    'Polling must render the panel info button in the open task view');
  assert(modal.innerHTML.includes('data-current-status="completed"'));
  returnedJobs=null;
  evaluate("state.token='';");


  // A new VPS must stay inside one 5-step flow, using the IP for SSH and
  // an independent optional domain for ACME. Only the FIRST host-key trust
  // requires explicit out-of-band verification.
  fill();
  evaluate("state.token='test';state.activeJob=null;");
  evaluate('addHost()');
  assert(modal.innerHTML.includes('服务器公网 IPv4'));
  assert(modal.innerHTML.includes('name="tls_domain"'));
  assert(modal.innerHTML.includes('服务器信息'));
  assert.equal(evaluate("isIpv4Input('panel.example.com')"),false);
  assert.equal(evaluate("isIpv4Input('45.32.35.196')"),true);
  const addForm=made.get('#add-host-form');
  addForm.formValues={
    name:'VIP1',hostname:'45.32.35.196',port:'22',username:'root',
    auth_mode:'key',tls_domain:'panel.example.com'
  };
  const createdRequestsBefore=fingerprintRequests;
  mockFingerprint={
    fingerprint:'SHA256:FreshTestHostKeyXYZ',
    key_type:'ssh-ed25519',previous_fingerprints:[],
    changed:false,shared_host_count:1
  };
  await addForm.dispatch('submit',{preventDefault(){},currentTarget:addForm});
  assert.equal(evaluate('state.setupFlowId'),2);
  assert.equal(fingerprintRequests,createdRequestsBefore+1);
  assert(modal.innerHTML.includes('第 2 步 · SSH 主机指纹'));
  assert(fingerprintTarget.innerHTML.includes('确认指纹，下一步检测连接'));
  assert.equal(preflightRequests,0,'first-use host key cannot auto-trust or connect');
  trustCheck=true;
  const trustButton=makeElement();
  trustButton.dataset={action:'trust',id:'2',fingerprint:mockFingerprint.fingerprint};
  trustButton.closest=()=>trustButton;
  await domHandlers.get('click')({target:trustButton});
  assert.equal(trustRequests,1,'new SSH host must be independently approved once');
  assert.equal(preflightRequests,1);
  assert(modal.innerHTML.includes('第 3 步 · 连接检测通过'));
  assert(modal.innerHTML.includes('下一步：端口与防火墙'));
  assert(modal.innerHTML.includes('域名证书'));
  assert.equal(firewallAllowCount,0);
  assert.equal(firewallDisableCount,0);
  await evaluate('setupFirewall(2)');
  assert(modal.innerHTML.includes('第 4 步 · 端口与防火墙'));
  assert(modal.innerHTML.includes('放行所填端口'));
  assert(modal.innerHTML.includes('关闭 UFW（需确认风险）'));
  assert(modal.innerHTML.includes('跳过此步，下一步：选择软件'));
  assert.equal(firewallReadCount,1);
  assert.equal(firewallAllowCount,0,'Showing the optional firewall step must not modify rules');
  evaluate('setupProjects(2)');
  assert(modal.innerHTML.includes('第 5 步 · 选择要安装的软件'));
  assert.equal(firewallAllowCount,0,'Skipping the optional step cannot create any rule');
  assert.equal(firewallDisableCount,0,'Skipping the optional step cannot disable UFW');
  await evaluate('setupFirewall(2)');
  const allowForm=made.get('#setup-allow-form');
  allowForm.formValues={port:'8443',protocol:'tcp'};
  await allowForm.dispatch('submit',{preventDefault(){},currentTarget:allowForm});
  assert.equal(firewallAllowCount,1,'Explicit allow action should use the fixed backend API once');
  assert(modal.innerHTML.includes('UFW 已放行 8443/tcp'));
  assert(modal.innerHTML.includes('下一步：选择软件'));
  evaluate('setupProjects(2)');
  assert(modal.innerHTML.includes('第 5 步 · 选择要安装的软件'));
  assert(modal.innerHTML.includes('panel.example.com'));
  assert(modal.innerHTML.includes('data-action="server-install"'));

  // Global UFW disable remains a separate HIGH-RISK opt-in action, never an
  // automatic onboarding step or side effect of viewing the status.
  await evaluate('setupFirewall(2)');
  assert.equal(firewallDisableCount,0);
  evaluate("confirmUfwToggle(2,'disable')");
  assert(modal.innerHTML.includes('关闭整台 VPS'));
  assert.equal(firewallDisableCount,0,'Opening the risk confirmation does not disable UFW');
  await evaluate("applyUfwToggle(2,'disable')");
  assert.equal(firewallDisableCount,1);
  assert(modal.innerHTML.includes('UFW 已手动关闭'));
  assert(modal.innerHTML.includes('下一步：选择软件'));
  await evaluate('setupFirewall(2)');
  assert(made.get('[data-action="toggle-ufw"][data-mode="disable"]').disabled,
    'Already-inactive UFW must not advertise another disable operation');
  evaluate('setupProjects(2)');
  assert(modal.innerHTML.includes('第 5 步 · 选择要安装的软件'));
  assert.equal(firewallDisableCount,1,'Skip next step must not disable UFW a second time');

  // A known, unchanged pinned fingerprint can proceed straight to SSH
  // detection, without making the user tick the same checkbox twice.
  mockFingerprint={
    fingerprint:'SHA256:FreshTestHostKeyXYZ',key_type:'ssh-ed25519',
    previous_fingerprints:[{key_type:'ssh-ed25519',fingerprint:'SHA256:FreshTestHostKeyXYZ'}],
    changed:false,shared_host_count:1
  };
  await evaluate('beginServerSetup(2)');
  assert.equal(trustRequests,1);
  assert.equal(preflightRequests,2);
  assert(modal.innerHTML.includes('连接检测通过'));
  evaluate("state.setupFlowId=null;state.token='';");

  assert(css.includes('.fingerprint-result{display:flex;flex-direction:column'),
    'Fingerprint results must stack vertically');
  assert(css.includes('.fingerprint-value{display:block;'),
    'Full SHA256 fingerprints must occupy their own line');
  assert(css.includes('overflow-wrap:anywhere'),
    'Long fingerprints must not force horizontal layout overflow');
  assert(css.includes('.server-next-action.pending'),
    'Pending approval must have a prominent next-action area');
  assert(css.includes('prefers-reduced-motion'),
    'Animation must respect reduced motion settings');
  console.log('UI smoke: pending approval, plan expiry, duplicate prevention, fingerprint states and responsive CSS OK');
})().catch(err=>{console.error(err);process.exitCode=1;});
