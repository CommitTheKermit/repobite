import test from 'node:test';
import assert from 'node:assert/strict';
import { mountRepositoryAutocomplete } from './repository-autocomplete.mjs';
class Node extends EventTarget {
  children = []; attributes = new Map(); value = ''; textContent = ''; hidden = false;
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(k, v) { this.attributes.set(k, v); }
  removeAttribute(k) { this.attributes.delete(k); }
  focus() {}
}
const pause = () => new Promise(resolve => setTimeout(resolve, 10));
const result = name => ({ private: false, archived: false, has_issues: true, full_name: name });
const response = items => ({ ok: true, json: async () => ({ items }) });
function setup(fetch) {
  const input = new Node(), list = new Node(), status = new Node();
  const controller = mountRepositoryAutocomplete({ input, fetch, delay: 0,
    document: { getElementById: id => id.endsWith('results') ? list : status, createElement: () => new Node() } });
  const type = value => { input.value = value; input.dispatchEvent(new Event('input')); };
  const key = value => { const e = new Event('keydown', { cancelable: true }); e.key = value; input.dispatchEvent(e); return e; };
  return { input, list, status, controller, type, key };
}
test('지연된 이전 검색 응답을 무시하고 키보드 선택은 저장 없이 입력만 채운다', async () => {
  let resolveOld;
  const app = setup(url => url.includes('old') ? new Promise(resolve => { resolveOld = resolve; }) : Promise.resolve(response([result('owner/new')])));
  app.type('old'); await pause(); app.type('new'); await pause();
  resolveOld(response([result('owner/old')])); await pause();
  assert.equal(app.list.children[0].children[0].textContent, 'owner/new');
  assert.equal(app.key('ArrowDown').defaultPrevented, true);
  assert.equal(app.input.attributes.get('aria-activedescendant'), 'account-repo-option-0');
  app.key('Enter'); assert.equal(app.input.value, 'owner/new'); assert.equal(app.list.hidden, true);
  app.controller.destroy();
});
test('빈 결과와 요청 제한을 구분하고 주소 입력은 검색 요청을 보내지 않는다', async () => {
  let count = 0;
  const app = setup(async () => ++count === 1 ? response([]) : { ok: false, status: 429 });
  app.type('https://github.com/owner/repo'); await pause(); assert.equal(count, 0);
  app.type('none'); await pause(); assert.match(app.status.textContent, /검색 결과가 없습니다/);
  app.type('limit'); await pause(); assert.match(app.status.textContent, /검색 한도/);
  assert.equal(app.input.value, 'limit'); app.controller.destroy();
});
test('Escape와 창 정리는 진행 중 요청의 늦은 응답을 표시하지 않는다', async () => {
  let resolve;
  const app = setup(() => new Promise(done => { resolve = done; }));
  app.type('repo'); await pause(); app.controller.clear(); resolve(response([result('owner/repo')])); await pause();
  assert.equal(app.list.hidden, true); assert.equal(app.status.textContent, ''); app.controller.destroy();
});
