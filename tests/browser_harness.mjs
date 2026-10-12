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
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, { id, textContent: '', className: '', innerHTML: '', style: {},
        classList: { toggle() {} }, remove() {}, appendChild() {}, addEventListener() {} });
      return elements.get(id);
    },
    createElement(tag) { return { tag, style: {}, classList: { add() {}, remove() {} }, appendChild() {} }; },
    body: { appendChild() {}, insertBefore() {}, replaceChildren() {}, firstChild: null },
    addEventListener() {},
    querySelectorAll() { return []; },
  };
  const window = { location: { reload() {} } };
  const context = vm.createContext({ document, window, fetch: fetchImpl, AbortController, AbortSignal,
    Date, URLSearchParams, setTimeout, clearTimeout, setInterval() {}, console, JSON, Math, String, Object,
    Promise, Error, TypeError, DOMException, Headers, Response, crypto: webcrypto });
  vm.runInContext(bundle, context, { filename: 'dashboard.js' });
  return { context, elements };
}
