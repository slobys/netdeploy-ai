/* Deterministic UI/theme tests: no browser, network or extra dependencies. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'app/static/theme.js'), 'utf8');
const css = fs.readFileSync(path.join(root, 'app/static/theme.css'), 'utf8');
const typography = fs.readFileSync(path.join(root, 'app/static/typography.css'), 'utf8');
const html = fs.readFileSync(path.join(root, 'app/static/index.html'), 'utf8');

function node(data = {}) {
  const attrs = {};
  const classes = new Set();
  const listeners = new Map();
  const element = {
    dataset:data,hidden:false,textContent:'',focused:false,
    classList: {
      toggle(name, active) {if(active)classes.add(name);else classes.delete(name);},
      contains(name) {return classes.has(name);},
    },
    setAttribute(key,value) {attrs[key]=value;},
    getAttribute(key) {return attrs[key]??null;},
    addEventListener(type,fn) {listeners.set(type,fn);},
    dispatch(type,ev={}) {listeners.get(type)?.(ev);},
    focus() {element.focused=true;},
    contains(target) {return element === target;},
  };
  return element;
}

function harness({stored={},osDark=false,throwStorage=false,legacyMedia=false}={}) {
  const storage = new Map(Object.entries(stored));
  const rootNode = node();
  const button = node();
  const menu = node();menu.hidden=true;
  const status = node();
  const control = node();
  const colorCodes = ['blue','violet','teal','emerald','rose','amber'];
  const modes = ['dark','light','system'];
  const fontSizes = ['standard','comfortable','large'];
  const modeButtons = modes.map(x=>node({themeMode:x}));
  const colorButtons = colorCodes.map(x=>node({themeColor:x}));
  const fontButtons = fontSizes.map(x=>node({themeFont:x}));
  const docs = new Map([
    ['theme-menu-button',button],['theme-menu',menu],['theme-control',control],['theme-status',status]
  ]);
  menu.querySelectorAll = selector => selector==='[data-theme-mode]'?modeButtons:
    selector==='[data-theme-color]'?colorButtons:
    selector==='[data-theme-font]'?fontButtons:[];
  control.contains = target => target===control||target===button||target===menu||
    colorButtons.includes(target)||modeButtons.includes(target)||fontButtons.includes(target);
  const docListeners = new Map();
  const winListeners = new Map();
  let systemDark = osDark;
  let onChange;
  const media = {get matches(){return systemDark;}};
  if(legacyMedia) media.addListener = cb => {onChange=cb;};
  else media.addEventListener = (type,cb) => {if(type==='change')onChange=cb;};
  const document = {
    readyState:'loading',documentElement:rootNode,
    getElementById:id=>docs.get(id)||null,
    addEventListener:(type,cb)=>docListeners.set(type,cb),
  };
  const window = {
    localStorage:{
      getItem(key){if(throwStorage)throw Error('blocked storage');return storage.get(key)||null;},
      setItem(key,value){if(throwStorage)throw Error('blocked storage');storage.set(key,value);},
      removeItem(key){if(throwStorage)throw Error('blocked storage');storage.delete(key);},
    },
    matchMedia:()=>media,
    addEventListener:(name,cb)=>winListeners.set(name,cb),
  };
  vm.runInNewContext(source,{document,window,console},{timeout:2000});
  const early={...rootNode.dataset};
  docListeners.get('DOMContentLoaded')?.();
  const pressed = (items,key)=>items.filter(x=>x.getAttribute('aria-pressed')==='true').map(x=>x.dataset[key]);
  return {
    root:rootNode,button,menu,status,control,modeButtons,colorButtons,fontButtons,stored:storage,early,
    pressedMode:()=>pressed(modeButtons,'themeMode'),
    pressedColor:()=>pressed(colorButtons,'themeColor'),
    pressedFont:()=>pressed(fontButtons,'themeFont'),
    chooseMode:value=>modeButtons.find(x=>x.dataset.themeMode===value).dispatch('click'),
    chooseColor:value=>colorButtons.find(x=>x.dataset.themeColor===value).dispatch('click'),
    chooseFont:value=>fontButtons.find(x=>x.dataset.themeFont===value).dispatch('click'),
    systemDark(value){systemDark=value;onChange?.({matches:value});},
    storageEvent:(key=null)=>winListeners.get('storage')?.({key}),
    clickOutside:target=>docListeners.get('pointerdown')?.({target}),
    escape:()=>docListeners.get('keydown')?.({key:'Escape',preventDefault(){}}),
  };
}

{
  const ui=harness();
  assert.deepEqual(ui.early,{appearance:'dark',themeMode:'dark',accent:'blue',fontSize:'comfortable'},
    'The current blue-black look must be applied before CSS is loaded');
  assert.deepEqual(ui.pressedMode(),['dark']);
  assert.deepEqual(ui.pressedColor(),['blue']);
  assert.deepEqual(ui.pressedFont(),['comfortable'],'Readable comfort size should be the default');
  assert.equal(ui.menu.hidden,true);
  assert.equal(ui.button.getAttribute('aria-expanded'),'false');
  ui.button.dispatch('click');
  assert.equal(ui.menu.hidden,false);
  assert.equal(ui.button.getAttribute('aria-expanded'),'true');
  ui.chooseMode('light');
  ui.chooseColor('rose');
  ui.chooseFont('large');
  assert.equal(ui.root.dataset.appearance,'light');
  assert.equal(ui.root.dataset.accent,'rose');
  assert.equal(ui.root.dataset.fontSize,'large');
  assert.equal(ui.stored.get('netdeploy-ui-mode-v1'),'light');
  assert.equal(ui.stored.get('netdeploy-ui-color-v1'),'rose');
  assert.equal(ui.stored.get('netdeploy-ui-font-size-v1'),'large');
  assert.deepEqual(ui.pressedMode(),['light']);
  assert.deepEqual(ui.pressedColor(),['rose']);
  assert.deepEqual(ui.pressedFont(),['large']);
  assert.equal(ui.status.textContent,'明亮 · 玫瑰粉');
  assert.equal(ui.menu.hidden,false,'Keep picker open for interactive color preview');
  ui.clickOutside(node());
  assert.equal(ui.menu.hidden,true,'Clicking outside must dismiss picker');
  ui.button.dispatch('click');
  ui.escape();
  assert.equal(ui.menu.hidden,true);
  assert.equal(ui.button.focused,true,'Escape returns keyboard focus to trigger');

  const reload=harness({stored:Object.fromEntries(ui.stored)});
  assert.equal(reload.early.appearance,'light');
  assert.equal(reload.early.accent,'rose');
  assert.equal(reload.early.fontSize,'large','Font size is restored before paint');
  assert.equal(reload.status.textContent,'明亮 · 玫瑰粉');
}

{
  const ui=harness({stored:{'netdeploy-ui-mode-v1':'system','netdeploy-ui-color-v1':'teal'},osDark:true});
  assert.equal(ui.root.dataset.appearance,'dark');
  assert.equal(ui.root.dataset.themeMode,'system');
  ui.systemDark(false);
  assert.equal(ui.root.dataset.appearance,'light');
  ui.systemDark(true);
  assert.equal(ui.root.dataset.appearance,'dark');
  ui.chooseMode('dark');
  ui.systemDark(false);
  assert.equal(ui.root.dataset.appearance,'dark','Explicit preference overrides OS change');
  ui.chooseMode('system');
  assert.equal(ui.root.dataset.appearance,'light');
}

{
  const ui=harness({osDark:false,legacyMedia:true});
  ui.chooseMode('system');
  ui.systemDark(true);
  assert.equal(ui.root.dataset.appearance,'dark','Legacy matchMedia listener still updates system mode');
  ui.stored.set('netdeploy-ui-mode-v1','light');
  ui.stored.set('netdeploy-ui-color-v1','amber');
  ui.stored.set('netdeploy-ui-font-size-v1','standard');
  ui.storageEvent('netdeploy-ui-color-v1');
  assert.equal(ui.root.dataset.appearance,'light');
  assert.equal(ui.root.dataset.accent,'amber');
  assert.equal(ui.root.dataset.fontSize,'standard','Cross-tab updates include font size');
  ui.stored.set('netdeploy-ui-mode-v1','bogus');
  ui.stored.set('netdeploy-ui-color-v1','url(javascript:evil)');
  ui.stored.set('netdeploy-ui-font-size-v1','calc(999px)');
  ui.storageEvent(null);
  assert.equal(ui.root.dataset.appearance,'dark','Tampered prefs are rejected');
  assert.equal(ui.root.dataset.accent,'blue');
  assert.equal(ui.root.dataset.fontSize,'comfortable','Tampered font preference must use default');
}

{
  const ui=harness({stored:{'netdeploy-ui-mode-v1':'invalid','netdeploy-ui-color-v1':'invalid'},throwStorage:true});
  assert.equal(ui.root.dataset.appearance,'dark');
  assert.equal(ui.root.dataset.accent,'blue');
  ui.chooseColor('emerald');
  ui.chooseMode('light');
  ui.chooseFont('large');
  assert.equal(ui.root.dataset.appearance,'light','Private storage mode still allows temporary changes');
  assert.equal(ui.root.dataset.fontSize,'large','Fonts work when localStorage is blocked');
  assert.equal(ui.root.dataset.accent,'emerald');
}

{
  assert(html.indexOf('/static/theme.js')<html.indexOf('/static/app.css'),
    'Theme must apply in head before CSS paints');
  assert(html.indexOf('/static/theme.css')>html.indexOf('/static/app-enhanced.css'),
    'Theme tokens need the final cascade');
  assert(html.indexOf('/static/typography.css')>html.indexOf('/static/theme.css'),
    'Readable type must override old 10–12px component CSS');
  assert(html.includes("script-src 'self'"),'No inline scripts needed under strict CSP');
  assert(html.includes('id="theme-menu-button"'));
  assert(html.includes('id="theme-menu"'));
  assert(html.includes('aria-expanded="false"')&&html.includes('aria-pressed="true"'));
  for(const accent of ['blue','violet','teal','emerald','rose','amber']){
    assert(html.includes('data-theme-color="'+accent+'"'));
    assert(css.includes('data-accent="'+accent+'"'));
    assert(css.includes('data-theme-color="'+accent+'"'));
  }
  for(const mode of ['dark','light','system'])assert(html.includes('data-theme-mode="'+mode+'"'));
  for(const size of ['standard','comfortable','large']){
    assert(html.includes('data-theme-font="'+size+'"'));
    assert(typography.includes('data-font-size="'+size+'"'));
  }
  for(const selector of ['.project h3','.project p','.stat small','.stat .top','.nav-item','.hero p',
      '.section-heading p','.form-group input','.modal-tip','.server-tab',
      '.setup-port-row','.cloud-provider-links a']){
    assert(typography.includes(selector),'Missing type coverage: '+selector);
  }
  assert(typography.includes('--ui-fs-body') && typography.includes('min-height:44px'));
  assert(typography.includes('@media(max-width:530px)'));
  for(const token of ['--theme-page','--theme-panel','--theme-title','--theme-action','--theme-line']){
    assert(css.includes(token));
  }
  for(const selector of ['.sidebar','.topbar','.stat','.project','.modal','.form-group input',
     '.server-tabs','.server-kpi','.xui-info-row','.fingerprint-verdict','.setup-port-row',
     '.cloud-provider-links a','.login-box','.hero']){
    assert(css.includes(selector),'Missing themed component: '+selector);
  }

  // Primary buttons use accessible white-on-color contrast in every palette.
  function luminance(hex){
    const rgb=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255)
      .map(v=>v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4);
    return .2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2];
  }
  for(const name of ['blue','violet','teal','emerald','rose','amber']){
    const selector=':root[data-accent="'+name+'"] {';
    const start=css.indexOf(selector);
    assert(start>=0,'Missing palette token: '+name);
    const cssRule=css.slice(start,css.indexOf('}',start)).match(/--theme-action:(#[0-9a-f]{6})/i);
    assert(cssRule,'Missing primary button color for '+name);
    const contrast=1.05/(luminance(cssRule[1])+0.05);
    assert(contrast>=4.5,'Primary button must have 4.5:1 white contrast: '+name+' '+contrast.toFixed(2));
  }
  assert(css.includes(':root[data-appearance="light"]'));
  assert(css.includes('@media(max-width:650px)'));
  assert(css.includes('@media(prefers-reduced-motion:reduce)'));
}
console.log('Theme smoke: six palettes, dark/light/system, persistence, OS/live storage, safe fallback, keyboard and CSS coverage OK');
