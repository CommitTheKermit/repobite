/** 실행: node --test test_account_ui.mjs. 브라우저/실제 계정/발송을 사용하지 않는다. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { mountAccountUI } from './account-ui.mjs';

class Element {
  constructor(tag = 'div') {
    this.tagName = tag; this.children = []; this.listeners = new Map(); this.attributes = new Map();
    this.textContent = ''; this.value = ''; this.checked = false; this.hidden = false; this.disabled = false;
    this.open = false;
  }
  removeAttribute(key) { this.attributes.delete(key); }
  set innerHTML(value) { throw new Error('HTML 문자열 삽입 금지'); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(key, value) { this.attributes.set(key, value); }
  addEventListener(name, listener) {
    if (!this.listeners.has(name)) this.listeners.set(name, new Set());
    this.listeners.get(name).add(listener);
  }
  removeEventListener(name, listener) { this.listeners.get(name)?.delete(listener); }
  querySelectorAll(tag) { return this.children.flatMap(child => [
    ...(child.tagName === tag ? [child] : []), ...child.querySelectorAll(tag)]); }
  showModal() { this.open = true; }
  close() { this.open = false; }
  async emit(name) {
    await Promise.all([...this.listeners.get(name) ?? []].map(listener => listener({ preventDefault() {} })));
  }
}

function dom() {
  const elements = new Map();
  for (const id of ['status', 'login', 'dialog-login', 'open', 'dialog', 'close', 'message', 'email-form',
    'email', 'delivery', 'repo-form', 'repo', 'repo-results', 'repo-search-status', 'subscriptions', 'logout']) {
    elements.set('account-' + id, new Element());
  }
  for (const id of ['email-form', 'repo-form']) elements.get('account-' + id).append(new Element('button'));
  const feed = new Element(); feed.textContent = '공개 탐색과 검색 결과';
  return { getElementById: id => elements.get(id), createElement: tag => new Element(tag), feed,
    get: id => elements.get('account-' + id) };
}
function memoryStorage(initial = []) {
  const values = new Map(initial);
  return { values, getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key) };
}
const signedIn = (id = '10', subscriptions = [], email = '', delivery = false) => ({ authenticated: true,
  user: { id, login: 'user-' + id }, preferences: { email, delivery_enabled: delivery, daily_limit: 3 }, subscriptions });
const response = (body, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};
function mount(transport, options = {}) {
  const document = dom(), storage = options.storage ?? memoryStorage(), calls = [], changes = [];
  const controller = mountAccountUI({ document, storage, location: options.location ?? { search: '' },
    fetch: async (url, init) => { const call = { action: new URL(url, 'https://repobite.vercel.app').searchParams.get('action'),
      ...init, payload: init.body === undefined ? undefined : JSON.parse(init.body) }; calls.push(call); return transport(call); },
    onSubscriptionsChanged: (subscriptions, account) => changes.push({ subscriptions, account }) });
  return { document, storage, controller, calls, changes };
}
const input = async (document, id, value) => { document.get(id).value = value; await document.get(id).emit('input'); };
const allText = node => [node.textContent, ...node.children.map(allText)].join(' ');

test('계정 API 장애와 익명 로그인 유도는 공개 탐색 결과를 바꾸지 않는다', async () => {
  const app = mount(() => response({ error: '일시 장애' }, 503));
  assert.equal(await app.controller.ready, false);
  assert.equal(app.document.feed.textContent, '공개 탐색과 검색 결과');
  assert.equal(app.controller.getState().stateUnknown, true);
  assert.equal(await app.controller.toggleSubscription('Owner/Repo'), false);
  assert.equal(app.document.get('repo').value, 'Owner/Repo');
  assert.equal(app.document.get('dialog').open, true);
  assert.match(app.document.get('message').textContent, /GitHub 로그인/);
  assert.equal(app.calls.length, 1);
  assert.equal(app.document.get('dialog-login').href, '/api/account?action=start');
});

test('로그인 이동 전 입력은 세션 저장소에 보관하고 복귀 후 자동 구독 없이 복원한다', async () => {
  const storage = memoryStorage();
  const anonymous = mount(() => response({ authenticated: false }), { storage });
  await anonymous.controller.ready;
  await input(anonymous.document, 'email', 'draft@example.com');
  anonymous.document.get('delivery').checked = true;
  await anonymous.document.get('delivery').emit('change');
  await anonymous.controller.toggleSubscription('Owner/Repo');
  await anonymous.document.get('dialog-login').emit('click');
  assert.equal(storage.values.size, 1);
  const restored = mount(() => response(signedIn()), { storage, location: { search: '?auth=success' } });
  await restored.controller.ready;
  assert.equal(restored.document.get('email').value, 'draft@example.com');
  assert.equal(restored.document.get('delivery').checked, true);
  assert.equal(restored.document.get('repo').value, 'Owner/Repo');
  assert.equal(restored.calls.length, 1);
  assert.equal(restored.calls[0].method, 'GET');
  assert.equal(storage.values.size, 0);
});

test('취소된 로그인도 익명 입력을 복원하고 실패 안내를 표시한다', async () => {
  const storage = memoryStorage([['repobite:account-draft:v1', JSON.stringify({
    email: 'draft@example.com', delivery_enabled: false, repo: 'Owner/Repo', owner_id: null })]]);
  const app = mount(() => response({ authenticated: false }), { storage, location: { search: '?auth=failed' } });
  await app.controller.ready;
  assert.equal(app.document.get('repo').value, 'Owner/Repo');
  assert.equal(app.document.get('email').value, 'draft@example.com');
  assert.match(app.document.get('message').textContent, /완료하지 못했습니다/);
  assert.equal(app.document.get('dialog').open, true);
});

for (const status of [400, 503, 401]) {
  test(`이메일 저장 ${status} 실패 시 이메일과 구독 입력을 보존한다`, async () => {
    const app = mount(call => call.method === 'GET' ? response(signedIn('10', ['Owner/Old']))
      : response({ error: '저장하지 못했습니다.' }, status));
    await app.controller.ready;
    await input(app.document, 'email', 'draft@example.com');
    await input(app.document, 'repo', 'Owner/New');
    app.document.get('delivery').checked = true;
    await app.document.get('email-form').emit('submit');
    assert.equal(app.document.get('email').value, 'draft@example.com');
    assert.equal(app.document.get('repo').value, 'Owner/New');
    assert.equal(app.document.get('delivery').checked, true);
    assert.equal(app.document.get('email').disabled, false);
    assert.match(app.document.get('message').textContent, /저장하지 못했습니다/);
    assert.equal(app.calls.length, 2);
    if (status === 401) {
      assert.equal(app.controller.getState().authenticated, false);
      assert.deepEqual(app.controller.getState().subscriptions, []);
    }
  });
}

test('구독 저장 응답 뒤 세션 반영을 확인하기 전에는 성공으로 표시하지 않는다', async () => {
  const app = mount(call => call.method === 'GET' ? response(signedIn()) : response({ repo: 'Owner/Repo', created: true }, 201));
  await app.controller.ready;
  assert.equal(await app.controller.toggleSubscription('Owner/Repo'), false);
  assert.deepEqual(app.calls.map(call => call.method), ['GET', 'POST', 'GET']);
  assert.equal(app.document.get('repo').value, 'Owner/Repo');
  assert.match(app.document.get('message').textContent, /결과를 확인하지 못했습니다/);
  assert.deepEqual(app.controller.getState().subscriptions, []);
});

test('구독과 해지는 서버에 반영된 개인 목록으로 확인하고 HTML 문자열을 해석하지 않는다', async () => {
  let subscriptions = [];
  const repo = 'Owner/<script>alert(1)</script>';
  const app = mount(call => {
    if (call.method === 'GET') return response(signedIn('10', [...subscriptions]));
    subscriptions = call.method === 'POST' ? [repo] : [];
    return response({ repo, created: call.method === 'POST', removed: call.method === 'DELETE' });
  });
  await app.controller.ready;
  assert.equal(await app.controller.toggleSubscription(repo), true);
  assert.deepEqual(app.controller.getState().subscriptions, [repo]);
  assert.match(allText(app.document.get('subscriptions')), /<script>/);
  assert.equal(app.document.get('repo').value, '');
  assert.equal(await app.controller.toggleSubscription(repo), true);
  assert.deepEqual(app.controller.getState().subscriptions, []);
  assert.match(app.document.get('message').textContent, /해지했습니다/);
  assert.equal(app.document.feed.textContent, '공개 탐색과 검색 결과');
});

test('이메일 저장 성공도 세션 이메일과 수신 동의 재조회로 확인한다', async () => {
  let saved = false;
  const app = mount(call => {
    if (call.method === 'GET') return response(signedIn('10', [], saved ? 'draft@example.com' : '', saved));
    saved = true; return response({ preferences: { email: 'draft@example.com', delivery_enabled: true, daily_limit: 3 } });
  });
  await app.controller.ready;
  await input(app.document, 'email', 'draft@example.com');
  app.document.get('delivery').checked = true;
  await app.document.get('email-form').emit('submit');
  assert.deepEqual(app.calls.map(call => call.action), ['session', 'preferences', 'session']);
  assert.equal(app.document.get('email').value, 'draft@example.com');
  assert.match(app.document.get('message').textContent, /설정을 저장했습니다/);
});

test('세션 재조회 실패는 저장 성공 응답 이후에도 입력을 보존한다', async () => {
  let gets = 0;
  const app = mount(call => call.method === 'GET'
    ? ++gets === 1 ? response(signedIn()) : response({ error: '재조회 실패' }, 503)
    : response({ repo: 'Owner/New', created: true }));
  await app.controller.ready;
  assert.equal(await app.controller.toggleSubscription('Owner/New'), false);
  assert.equal(app.document.get('repo').value, 'Owner/New');
  assert.match(app.document.get('message').textContent, /재조회 실패/);
});

test('GitHub 계정이 바뀌면 이전 계정의 개인 입력과 구독을 새 계정에 넘기지 않는다', async () => {
  let account = signedIn('10', ['Owner/A'], 'account-a@example.com', true);
  const app = mount(() => response(account));
  await app.controller.ready;
  await input(app.document, 'email', 'account-a-draft@example.com');
  await input(app.document, 'repo', 'Owner/PrivateDraft');
  await app.document.get('login').emit('click');
  account = signedIn('20', ['Owner/B'], 'account-b@example.com');
  await app.controller.refresh();
  assert.equal(app.document.get('email').value, 'account-b@example.com');
  assert.equal(app.document.get('repo').value, '');
  assert.deepEqual(app.controller.getState().subscriptions, ['Owner/B']);
  assert.equal(app.storage.values.size, 0);
});

test('이전 계정에 묶인 로그인 복원값은 다른 계정으로 로그인했을 때 삭제한다', async () => {
  const storage = memoryStorage([['repobite:account-draft:v1', JSON.stringify({
    email: 'previous@example.com', delivery_enabled: true, repo: 'Owner/Old', owner_id: '10' })]]);
  const app = mount(() => response(signedIn('20', [], 'new@example.com')), { storage });
  await app.controller.ready;
  assert.equal(app.document.get('email').value, 'new@example.com');
  assert.equal(app.document.get('repo').value, '');
  assert.equal(storage.values.size, 0);
});

test('로그아웃은 개인정보와 복원값을 지우고 늦은 이전 세션 응답을 무시한다', async () => {
  const late = deferred();
  let gets = 0, loggedOut = false;
  const app = mount(call => {
    if (call.action === 'logout') { loggedOut = true; return response({ authenticated: false }); }
    if (++gets === 2) return late.promise;
    return response(loggedOut ? { authenticated: false } : signedIn('10', ['Owner/A'], 'private@example.com', true));
  });
  await app.controller.ready;
  await app.document.get('login').emit('click');
  const refresh = app.controller.refresh();
  assert.equal(await app.controller.logout(), true);
  late.resolve(response(signedIn('10', ['Owner/A'], 'private@example.com', true)));
  assert.equal(await refresh, false);
  assert.equal(app.document.get('email').value, '');
  assert.equal(app.document.get('repo').value, '');
  assert.equal(app.document.get('delivery').checked, false);
  assert.equal(app.storage.values.size, 0);
  assert.deepEqual(app.controller.getState().subscriptions, []);
  assert.equal(app.controller.getState().authenticated, false);
  assert.equal(app.document.feed.textContent, '공개 탐색과 검색 결과');
});

test('진행 중 구독 저장 응답이 로그아웃 뒤 도착해도 개인 상태를 복원하지 않는다', async () => {
  const late = deferred(); let loggedOut = false;
  const app = mount(call => {
    if (call.action === 'subscriptions') return late.promise;
    if (call.action === 'logout') { loggedOut = true; return response({ authenticated: false }); }
    return response(loggedOut ? { authenticated: false } : signedIn());
  });
  await app.controller.ready;
  const save = app.controller.toggleSubscription('Owner/New');
  await app.controller.logout();
  const count = app.calls.length;
  late.resolve(response({ repo: 'Owner/New', created: true }, 201));
  assert.equal(await save, false);
  assert.equal(app.calls.length, count);
  assert.equal(app.document.get('repo').value, '');
  assert.equal(app.controller.getState().authenticated, false);
});

test('로그아웃 장애가 나도 개인 입력을 지우며 재시도 동작을 남긴다', async () => {
  const app = mount(call => call.method === 'GET' ? response(signedIn('10', ['Owner/A'], 'private@example.com', true))
    : response({ error: '로그아웃 재시도 필요' }, 503));
  await app.controller.ready;
  assert.equal(await app.controller.logout(), false);
  assert.equal(app.document.get('email').value, '');
  assert.deepEqual(app.controller.getState().subscriptions, []);
  assert.equal(app.controller.getState().stateUnknown, true);
  assert.equal(app.document.get('logout').hidden, false);
});

test('세션 저장소를 쓸 수 없어도 계정 조회와 로그인 링크는 동작한다', async () => {
  const storage = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); },
    removeItem() { throw new Error('blocked'); } };
  const app = mount(() => response({ authenticated: false }), { storage });
  assert.equal(await app.controller.ready, true);
  await app.document.get('login').emit('click');
  assert.equal(app.document.get('login').href, '/api/account?action=start');
});


test('기존 구독 해지는 아직 저장하지 않은 새 저장소 입력을 덮어쓰지 않는다', async () => {
  let subscriptions = ['Owner/Old'];
  const app = mount(call => {
    if (call.method === 'GET') return response(signedIn('10', [...subscriptions]));
    subscriptions = []; return response({ repo: 'Owner/Old', removed: true });
  });
  await app.controller.ready;
  await input(app.document, 'repo', 'Owner/Unsaved');
  assert.equal(await app.controller.toggleSubscription('Owner/Old'), true);
  assert.equal(app.document.get('repo').value, 'Owner/Unsaved');
});

test('저장소 입력 폼도 저장과 세션 재조회가 끝난 뒤 구독 목록을 갱신한다', async () => {
  let subscriptions = [];
  const app = mount(call => {
    if (call.method === 'GET') return response(signedIn('10', [...subscriptions]));
    subscriptions = [call.payload.repo]; return response({ repo: call.payload.repo, created: true }, 201);
  });
  await app.controller.ready;
  await input(app.document, 'repo', 'Owner/New');
  await app.document.get('repo-form').emit('submit');
  assert.deepEqual(app.controller.getState().subscriptions, ['Owner/New']);
  assert.equal(app.document.get('repo').value, '');
});


test('브라우저가 sessionStorage 속성 접근을 차단해도 기본 마운트는 동작한다', async () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage');
  try {
    Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, get() { throw new Error('blocked'); } });
    const document = dom();
    const controller = mountAccountUI({ document, fetch: async () => response({ authenticated: false }), location: { search: '' } });
    assert.equal(await controller.ready, true);
    await document.get('login').emit('click');
    assert.equal(document.get('login').href, '/api/account?action=start');
  } finally {
    if (previous) Object.defineProperty(globalThis, 'sessionStorage', previous);
    else delete globalThis.sessionStorage;
  }
});

test('무편집 로그인 복원은 기존 이메일과 수신 동의를 기본 빈값으로 덮어쓰지 않는다', async () => {
  const storage = memoryStorage();
  const anonymous = mount(() => response({ authenticated: false }), { storage });
  await anonymous.controller.ready;
  await anonymous.document.get('login').emit('click');
  const existing = mount(() => response(signedIn('10', [], 'saved@example.com', true)), { storage });
  await existing.controller.ready;
  assert.equal(existing.document.get('email').value, 'saved@example.com');
  assert.equal(existing.document.get('delivery').checked, true);
});

test('편집정보 없는 이전 빈 복원값도 기존 계정 설정을 가리지 않는다', async () => {
  const storage = memoryStorage([['repobite:account-draft:v1', JSON.stringify({
    email: '', delivery_enabled: false, repo: '', owner_id: null })]]);
  const app = mount(() => response(signedIn('10', [], 'saved@example.com', true)), { storage });
  await app.controller.ready;
  assert.equal(app.document.get('email').value, 'saved@example.com');
  assert.equal(app.document.get('delivery').checked, true);
});

test('이메일만 편집한 로그인 입력은 편집하지 않은 수신 동의를 덮어쓰지 않는다', async () => {
  const storage = memoryStorage();
  const anonymous = mount(() => response({ authenticated: false }), { storage });
  await anonymous.controller.ready;
  await input(anonymous.document, 'email', 'draft@example.com');
  await anonymous.document.get('login').emit('click');
  const existing = mount(() => response(signedIn('10', [], 'saved@example.com', true)), { storage });
  await existing.controller.ready;
  assert.equal(existing.document.get('email').value, 'draft@example.com');
  assert.equal(existing.document.get('delivery').checked, true);
});

test('의도적으로 비운 이메일과 해제한 수신 동의는 같은 계정 로그인 후 복원한다', async () => {
  const storage = memoryStorage();
  const before = mount(() => response(signedIn('10', [], 'saved@example.com', true)), { storage });
  await before.controller.ready;
  await input(before.document, 'email', '');
  before.document.get('delivery').checked = false;
  await before.document.get('delivery').emit('change');
  await before.document.get('login').emit('click');
  const restored = mount(() => response(signedIn('10', [], 'saved@example.com', true)), { storage });
  await restored.controller.ready;
  assert.equal(restored.document.get('email').value, '');
  assert.equal(restored.document.get('delivery').checked, false);
});

test('다른 탭의 계정 전환은 저장 계정 조건으로 거절하고 새 계정 이메일을 바꾸지 않는다', async () => {
  let backend = signedIn('10', [], 'a@example.com', true);
  let requestPayload;
  const app = mount(call => {
    if (call.method === 'GET') return response(backend);
    requestPayload = call.payload;
    if (call.payload.expected_user_id !== backend.user.id) return response({ code: 'account_changed', error: '로그인 계정이 바뀌었습니다.' }, 409);
    backend = signedIn(backend.user.id, [], call.payload.email, call.payload.delivery_enabled);
    return response({ preferences: backend.preferences });
  });
  await app.controller.ready;
  await input(app.document, 'email', 'a-draft@example.com');
  backend = signedIn('20', [], 'b@example.com', true);
  await app.document.get('email-form').emit('submit');
  assert.equal(requestPayload.expected_user_id, '10');
  assert.equal(backend.preferences.email, 'b@example.com');
  assert.equal(app.controller.getState().authenticated, false);
  assert.match(app.document.get('message').textContent, /계정이 바뀌었습니다/);
});
