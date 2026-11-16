'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const script = fs.readFileSync('app/static/desktop-updates.js', 'utf8');
function harness(desktop = true) {
  let html = '', hidden = true, receiver, click, timer, source = '/';
  const sent = [], classes = new Set();
  const button = {classList:{add:x=>classes.add(x),remove:x=>classes.delete(x)},setAttribute(){},
    addEventListener:(_,fn)=>{button.click=fn;}};
  const progress = {}, progressText = {};
  const state = {activeJob:'existing-job'};
  const context = {window:{netdeployDesktop:desktop,chrome:{webview:{postMessage:x=>sent.push(x),addEventListener:(_,fn)=>{receiver=fn;}}}},
    CLIENT_VERSION:'0.3.42', state, setTimeout:fn=>{timer=fn;},
    document:{querySelector:s=>s==='#desktop-version'?button:s==='#modal'?{classList:{contains:()=>hidden}}:
      s==='#desktop-update-panel'?(html.includes('id="desktop-update-panel"')?{}:null):
      s==='#update-progress'?(html.includes('id="update-progress"')?progress:null):
      s==='#update-progress-text'?progressText:null,addEventListener:(_,fn)=>{click=fn;}},
    dialog:text=>{html=text;hidden=false;}, closeDialog:()=>{html='';hidden=true;}, toast:()=>{},
    modalHead:title=>'<h2>'+title+'</h2>',
    escapeHtml:v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))};
  vm.runInNewContext(script, context);
  return {button, sent, get html(){return html;}, classes, progress,
    auto:()=>timer?.(), otherDialog:()=>{html='<p>Existing deployment</p>';hidden=false;},
    message:(status,info,manual=false)=>receiver({data:{type:'netdeploy-update',status,info,manual}}),
    act:action=>click({target:{closest:()=>({dataset:{updateAction:action}})}}),
    get state(){return state;}, get source(){return source;}};
}
const update = {version:'0.3.43',size:10*1048576,notes:'## 更新说明\n<img src=x onerror=alert(1)>\n修复问题'};
const ui = harness();
ui.auto(); assert.equal(ui.sent[0].action,'check'); assert.equal(ui.sent[0].manual,false);
ui.message('current'); assert.equal(ui.html,'');
ui.message('error',{message:'offline'}); assert.equal(ui.html,'');
ui.message('available',update); assert.match(ui.html,/下载并更新/); assert.match(ui.html,/&lt;img/);
assert.ok(!ui.html.includes('<img src')); assert.ok(ui.classes.has('has-update'));
ui.act('later'); assert.equal(ui.html,'');
ui.otherDialog(); ui.message('available',update); assert.match(ui.html,/Existing deployment/);
ui.button.click(); assert.match(ui.html,/稍后再说/); assert.equal(ui.state.activeJob,null);
ui.act('install'); assert.equal(ui.sent.at(-1).action,'install');
ui.message('downloading',{received:5*1048576,total:10*1048576}); assert.equal(ui.progress.value,50);
ui.act('cancel'); assert.equal(ui.sent.at(-1).action,'cancel');
ui.message('cancelled'); assert.match(ui.html,/重新下载/);
ui.act('install'); ui.message('error',{message:'SHA-256 校验失败'}); assert.match(ui.html,/SHA-256/);
ui.act('check'); ui.message('current',null,true); assert.match(ui.html,/已是最新版本/);
assert.equal(ui.source,'/');
const web = harness(false); web.button.click(); assert.match(web.html,/GitHub/); assert.equal(web.sent.length,0);
console.log('Desktop updates UI: startup, manual, deferred modal, escaped notes, progress, cancel, retry and browser fallback OK');
