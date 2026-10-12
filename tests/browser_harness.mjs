import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';

export const source = readFileSync(new URL('../src/rshelper/dashboard/scripts.py', import.meta.url), 'utf8');
const scripts = ['SCRIPT_CORE', 'SCRIPT_CHARTS', 'SCRIPT_VIEWS'].map(name => {
  const match = source.match(new RegExp(`${name} = r"""([\\s\\S]*?)"""`));
  assert.ok(match, `${name} exists`);
  return match[1];
});
const bundle = scripts.join('\n').replace(
  /initializeAccess\(\)\.then\(\(\)=>\{fetchData\(\);if\(authenticated\)subscribeSSE\(\);\}\);\s*setInterval\(tick,1000\);\s*$/,
  '');

export function harness(fetchImpl) {
  const elements = new Map();
  const listeners = new Map();
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, { id, textContent: '', className: '', innerHTML: '', style: {},
        attributes:{},setAttribute(name,value){this.attributes[name]=String(value);},getAttribute(name){return this.attributes[name]??null;},focus(){document.activeElement=this;},
        classList: { toggle() {} }, remove() {}, appendChild() {}, addEventListener() {}, querySelectorAll(){return [];} });
      return elements.get(id);
    },
    createElement(tag) { return { tag, style: {}, classList: { add() {}, remove() {} }, appendChild() {} }; },
    body: { appendChild() {}, insertBefore() {}, replaceChildren() {}, firstChild: null },
    addEventListener(name,listener) { listeners.set(name,listener); },
    querySelectorAll() { return []; },
    querySelector() { return null; },
  };
  const storage=new Map();
  const window = { location: { pathname:'/',search:'',hash:'',reload() {} },addEventListener(){},
    localStorage:{getItem(key){return storage.get(key)??null;},setItem(key,value){storage.set(key,value);},removeItem(key){storage.delete(key);}},
    history:{pushState(state,title,url){window.location.hash=url.includes('#')?'#'+url.split('#')[1]:'';},replaceState(state,title,url){this.pushState(state,title,url);}} };
  const context = vm.createContext({ document, window, fetch: fetchImpl, AbortController, AbortSignal,
    Date, URLSearchParams, setTimeout, clearTimeout, setInterval() {}, console, JSON, Math, String, Object,
    Promise, Error, TypeError, DOMException, Headers, Response, crypto: webcrypto });
  vm.runInContext(bundle, context, { filename: 'dashboard.js' });
  return { context, elements, listeners };
}
