/** 실행: node --test test_contribution_ui.mjs. 실제 계정/깃허브/메일은 사용하지 않는다. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { mountContributionUI } from './contribution-ui.mjs';

class Element {
  constructor(tag = 'div') {
    this.tagName = tag; this.children = []; this.listeners = new Map(); this.attributes = new Map();
    this.textContent = ''; this.value = ''; this.hidden = false; this.disabled = false;
  }
  set innerHTML(value) { throw new Error('HTML 문자열 삽입 금지'); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(name, value) { this.attributes.set(name, value); }
  addEventListener(name, fn) { if (!this.listeners.has(name)) this.listeners.set(name, new Set()); this.listeners.get(name).add(fn); }
  removeEventListener(name, fn) { this.listeners.get(name)?.delete(fn); }
  querySelectorAll(tag) { return this.children.flatMap(child => [...(child.tagName === tag ? [child] : []), ...child.querySelectorAll(tag)]); }
  async emit(name) { await Promise.all([...this.listeners.get(name) ?? []].map(fn => fn({ preventDefault() {} }))); }
}
function dom() {
  const elements = new Map();
  for (const id of ['status', 'message', 'login', 'refresh', 'selected', 'start', 'cancel', 'resume',
    'pr-form', 'pr', 'delivery', 'prs', 'records', 'deliveries', 'summary']) elements.set('contribution-' + id, new Element());
  elements.get('contribution-pr-form').append(new Element('button'));
  return { get: id => elements.get('contribution-' + id), getElementById: id => elements.get(id), createElement: tag => new Element(tag) };
}
function memoryStorage(initial = []) { const values = new Map(initial); return { values, getItem: key => values.get(key) ?? null,
  setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }; }
const response = (body, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
const user = id => ({ authenticated: true, user: { id, login: 'user-' + id } });
const ISSUE = { repo: 'Owner/Repo', number: 123, title: '작업할 실제 이슈' };
const record = (changes = {}) => ({ repo: 'owner/repo', number: 123, activity: 'not_started', pull_requests: {},
  events: [], created_at: '2026-10-21T00:00:00+00:00', updated_at: '2026-10-21T00:00:00+00:00',
  delivery_linkage: { status: 'not_connected', delivery_id: null }, ...changes });
const delivery = (id, items = [{ repo: 'owner/repo', number: 123 }]) => ({ id, day: '2026-10-21', items,
  confirmed_at: '2026-10-21T01:00:00+00:00', state: 'operator_confirmed', attestation_basis: 'operator_confirmation', provider_delivery_verified: false });
const data = (records = [], deliveries = []) => ({ records, deliveries,
  summary: { tracked_issues: records.length, merged_pr_count: records.flatMap(row => Object.values(row.pull_requests)).filter(pr => pr.merged_at).length,
    operator_confirmed_digest_count: deliveries.length, provider_delivery_verified: false } });
const allText = node => [node.textContent, ...node.children.map(allText)].join(' ');
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
function mount(transport = () => response(data()), options = {}) {
  const document = dom(), calls = [], logins = [], storage = options.storage ?? memoryStorage();
  const controller = mountContributionUI({ document, storage,
    fetch: async (url, init) => { const parsed = new URL(url, 'https://repobite.vercel.app');
      const call = { ...init, expectedReadUser: parsed.searchParams.get('expected_user_id'), action: parsed.searchParams.get('action'),
        payload: init.body ? JSON.parse(init.body) : undefined }; calls.push(call); return transport(call); },
    onLoginRequired: value => { logins.push(value); options.onLoginRequired?.(value); },
    onAccountChanged: options.onAccountChanged });
  return { document, calls, logins, storage, controller };
}
async function input(app, value) { app.document.get('pr').value = value; await app.document.get('pr').emit('input'); }
async function choose(app, value) { app.document.get('delivery').value = value; await app.document.get('delivery').emit('change'); }

test('익명은 API를 호출하지 않고 로그인 안내와 선택 이슈/PR 입력을 유지한다', async () => {
  const app = mount(); await app.controller.refresh({ authenticated: false }); app.controller.selectIssue(ISSUE);
  await input(app, 'https://github.com/owner/repo/pull/7');
  await app.document.get('start').emit('click');
  assert.equal(app.calls.length, 0);
  assert.equal(app.logins[0].issue.repo, 'owner/repo');
  assert.equal(app.logins[0].pr_url, 'https://github.com/owner/repo/pull/7');
  assert.equal(app.document.get('pr').value, 'https://github.com/owner/repo/pull/7');
  assert.equal(app.storage.values.size, 1);
  assert.match(app.document.get('message').textContent, /GitHub 로그인/);
});

test('OAuth 페이지 왕복 후 선택 이슈와 PR 입력만 복원하며 자동 저장하지 않는다', async () => {
  const storage = memoryStorage();
  const before = mount(undefined, { storage }); await before.controller.refresh({ authenticated: false }); before.controller.selectIssue(ISSUE);
  await input(before, 'https://github.com/owner/repo/pull/7'); await before.document.get('login').emit('click');
  const after = mount(undefined, { storage }); await after.controller.refresh(user('10'));
  assert.match(after.document.get('selected').textContent, /owner\/repo #123/);
  assert.equal(after.document.get('pr').value, 'https://github.com/owner/repo/pull/7');
  assert.equal(after.calls.length, 1); assert.equal(after.calls[0].method, 'GET');
  assert.equal(after.calls[0].expectedReadUser, '10'); assert.equal(storage.values.size, 0);
});

test('다른 계정에 묶인 저장 입력은 복원하지 않는다', async () => {
  const storage = memoryStorage([['repobite:contribution-draft:v1', JSON.stringify({ issue: ISSUE, owner_id: '10',
    pr_url: 'https://github.com/owner/repo/pull/7', delivery_id: '' })]]);
  const app = mount(undefined, { storage }); await app.controller.refresh(user('20'));
  assert.equal(app.document.get('pr').value, ''); assert.equal(storage.values.size, 0);
  assert.doesNotMatch(app.document.get('selected').textContent, /#123/);
});

test('착수 취소 재개는 계정 조건과 독립 이벤트 ID를 보내고 재조회로 확정한다', async () => {
  let saved;
  const app = mount(call => {
    if (call.method === 'GET') return response(data(saved ? [saved] : []));
    saved = record({ activity: call.action === 'cancel' ? 'cancelled' : 'active',
      events: [...saved?.events ?? [], { type: call.action, event_id: call.payload.event_id }] });
    return response({ record: saved, changed: true, replayed: false });
  });
  await app.controller.refresh(user('10')); app.controller.selectIssue(ISSUE);
  for (const action of ['start', 'cancel', 'resume']) await app.document.get(action).emit('click');
  const writes = app.calls.filter(call => call.method === 'POST');
  assert.deepEqual(writes.map(call => call.action), ['start', 'cancel', 'resume']);
  assert.ok(writes.every(call => call.payload.expected_user_id === '10' && call.payload.repo === 'owner/repo' && call.payload.number === 123));
  assert.ok(writes.every(call => /^[a-f0-9]{32}$/.test(call.payload.event_id)));
  assert.equal(new Set(writes.map(call => call.payload.event_id)).size, 3);
  assert.deepEqual(app.calls.map(call => call.method), ['GET', 'POST', 'GET', 'POST', 'GET', 'POST', 'GET']);
  assert.equal(app.document.get('cancel').hidden, false); assert.equal(app.document.get('resume').hidden, true);
  assert.match(allText(app.document.get('records')), /진행 중/);
});

test('본인 PR 제출과 재검증은 GitHub 근거를 표시하며 이슈 자동 종료를 주장하지 않는다', async () => {
  const url = 'https://github.com/owner/repo/pull/7'; let saved;
  const app = mount(call => {
    if (call.method === 'GET') return response(data(saved ? [saved] : []));
    const pr = { url, state: call.action === 'verify_pr' ? 'closed' : 'open',
      merged_at: call.action === 'verify_pr' ? '2026-10-21T02:00:00+00:00' : null, provider_checked_at: '2026-10-21T03:00:00+00:00' };
    saved = record({ pull_requests: { [url]: pr }, events: [...saved?.events ?? [], { event_id: call.payload.event_id }] });
    return response({ record: saved, changed: true, replayed: false });
  });
  await app.controller.refresh(user('10')); app.controller.selectIssue(ISSUE); await input(app, url);
  await app.document.get('pr-form').emit('submit');
  assert.equal(app.calls[1].payload.pr_url, url); assert.match(allText(app.document.get('prs')), /GitHub에서 열림/);
  await app.document.get('prs').querySelectorAll('button')[0].emit('click');
  assert.equal(app.calls[3].action, 'verify_pr'); assert.equal(app.calls[3].payload.pr_url, url);
  assert.match(allText(app.document.get('prs')), /GitHub 병합 확인/);
  assert.match(allText(app.document.get('prs')), /사용자 신고이며 이슈 자동 종료는 확인하지 않았습니다/);
  assert.match(app.document.get('summary').textContent, /GitHub 병합 확인 PR 1건/);
});

for (const status of [400, 503, 401]) test(`기여 기록 저장 ${status} 실패 시 선택 이슈와 PR 입력을 유지한다`, async () => {
  const app = mount(call => call.method === 'GET' ? response(data()) : response({ error: '기여 저장 실패' }, status));
  await app.controller.refresh(user('10')); app.controller.selectIssue(ISSUE); await input(app, 'https://github.com/owner/repo/pull/7');
  await app.document.get('pr-form').emit('submit');
  assert.equal(app.document.get('pr').value, 'https://github.com/owner/repo/pull/7');
  assert.match(app.document.get('selected').textContent, /#123/); assert.match(app.document.get('message').textContent, /기여 저장 실패/);
  assert.equal(app.document.get('pr').disabled, false); assert.equal(app.calls.length, 2);
  if (status === 401) assert.equal(app.document.get('login').hidden, false);
});

test('서버 503 뒤 같은 요청을 재시도할 때 이벤트 ID를 재사용하고 replay 후 현재 상태를 재조회한다', async () => {
  let posts = 0, originalId, current = record({ activity: 'cancelled' });
  const app = mount(call => {
    if (call.method === 'GET') return response(data(posts ? [current] : []));
    if (++posts === 1) { originalId = call.payload.event_id; return response({ error: '응답 유실' }, 503); }
    assert.equal(call.payload.event_id, originalId);
    return response({ record: record({ activity: 'active' }), changed: true, replayed: true });
  });
  await app.controller.refresh(user('10')); app.controller.selectIssue(ISSUE);
  await app.document.get('start').emit('click'); await app.document.get('start').emit('click');
  assert.equal(app.calls.at(-1).method, 'GET');
  assert.equal(app.document.get('resume').hidden, false); assert.equal(app.document.get('cancel').hidden, true);
  assert.match(app.document.get('message').textContent, /이전 요청을 재확인했습니다/);
  assert.match(app.document.get('message').textContent, /취소됨/);
});

test('저장 응답 후 GET 실패를 성공으로 표시하지 않고 입력과 이벤트를 보존한다', async () => {
  let gets = 0, saved, id;
  const app = mount(call => {
    if (call.method === 'GET') return ++gets === 2 ? response({ error: '재조회 실패' }, 503) : response(data(saved ? [saved] : []));
    if (!id) id = call.payload.event_id; else assert.equal(call.payload.event_id, id);
    const replayed = !!saved; saved = record({ activity: 'active', events: [{ event_id: id }] });
    return response({ record: saved, changed: true, replayed });
  });
  await app.controller.refresh(user('10')); app.controller.selectIssue(ISSUE); await input(app, 'https://github.com/owner/repo/pull/7');
  await app.document.get('start').emit('click');
  assert.match(app.document.get('message').textContent, /재조회 실패/); assert.equal(app.document.get('pr').value, 'https://github.com/owner/repo/pull/7');
  await app.document.get('start').emit('click'); assert.match(app.document.get('message').textContent, /이전 요청/);
});

test('성공 응답만 있고 재조회 결과에 해당 이벤트가 없으면 성공으로 표시하지 않는다', async () => {
  const app = mount(call => call.method === 'GET' ? response(data([record()]))
    : response({ record: record({ activity: 'active' }), changed: true, replayed: false }));
  await app.controller.refresh(user('10')); app.controller.selectIssue(ISSUE); await app.document.get('start').emit('click');
  assert.match(app.document.get('message').textContent, /저장 결과를 확인하지 못했습니다/);
});

test('늦게 도착한 이전 계정 GET은 새 계정의 기록과 입력을 덮어쓰지 않는다', async () => {
  const late = deferred();
  const app = mount(call => call.expectedReadUser === '10' ? late.promise : response(data([record({ repo: 'other/repo', number: 22 })])));
  const old = app.controller.refresh(user('10')); app.controller.selectIssue(ISSUE); await input(app, 'old-private-input');
  await app.controller.refresh(user('20'));
  late.resolve(response(data([record({ activity: 'active' })]))); assert.equal(await old, false);
  assert.match(allText(app.document.get('records')), /other\/repo #22/);
  assert.doesNotMatch(allText(app.document.get('records')), /owner\/repo #123/);
  assert.equal(app.document.get('pr').value, '');
});

test('계정 전환 뒤 도착한 이전 계정 POST는 추가 조회나 화면 갱신을 하지 않는다', async () => {
  const late = deferred();
  const app = mount(call => call.method === 'POST' ? late.promise : response(data(call.expectedReadUser === '20'
    ? [record({ repo: 'other/repo', number: 22 })] : [])));
  await app.controller.refresh(user('10')); app.controller.selectIssue(ISSUE);
  const write = app.document.get('start').emit('click'); await app.controller.refresh(user('20'));
  const before = app.calls.length;
  late.resolve(response({ record: record({ activity: 'active' }), changed: true, replayed: false })); await write;
  assert.equal(app.calls.length, before); assert.match(allText(app.document.get('records')), /other\/repo #22/);
});

test('전달 기록은 선택 이슈에 해당하는 본인 기록만 표시하고 자동 연결하지 않는다', async () => {
  const deliveries = [delivery('digest-one'), delivery('digest-two'), delivery('unrelated-one', [{ repo: 'owner/other', number: 7 }])];
  let saved;
  const app = mount(call => {
    if (call.method === 'GET') return response(data(saved ? [saved] : [], deliveries));
    saved = record({ activity: call.action === 'cancel' ? 'cancelled' : 'active', events: [...saved?.events ?? [], { event_id: call.payload.event_id }] });
    return response({ record: saved, changed: true, replayed: false });
  });
  await app.controller.refresh(user('10')); app.controller.selectIssue(ISSUE);
  assert.deepEqual(app.document.get('delivery').children.map(option => option.value), ['', 'digest-one', 'digest-two']);
  assert.equal(app.document.get('delivery').value, '');
  await app.document.get('start').emit('click'); assert.equal(Object.hasOwn(app.calls[1].payload, 'delivery_id'), false);
  await choose(app, 'digest-two'); await app.document.get('cancel').emit('click');
  assert.equal(app.calls[3].payload.delivery_id, 'digest-two');
  assert.match(allText(app.document.get('deliveries')), /운영자 발송 확인/);
  assert.match(allText(app.document.get('deliveries')), /메일 도착 여부는 확인되지 않았습니다/);
});

test('인증 만료 뒤 같은 계정으로 재조회하면 명시한 전달 선택과 PR 입력을 유지한다', async () => {
  const app = mount(call => call.method === 'GET' ? response(data([], [delivery('digest-one')])) : response({ error: '로그인 만료' }, 401));
  await app.controller.refresh(user('10')); app.controller.selectIssue(ISSUE); await input(app, 'https://github.com/owner/repo/pull/7'); await choose(app, 'digest-one');
  await app.document.get('start').emit('click'); await app.controller.refresh(user('10'));
  assert.equal(app.document.get('delivery').value, 'digest-one'); assert.equal(app.document.get('pr').value, 'https://github.com/owner/repo/pull/7');
});

test('GET 계정 조건 오류는 개인 목록을 비우고 로그인 확인 안내를 남긴다', async () => {
  let changed = false, notifications = 0;
  const app = mount(() => changed ? response({ error: '계정이 바뀌었습니다', code: 'account_changed' }, 409) : response(data([record()])), {
    onAccountChanged() {
      notifications++;
      assert.doesNotMatch(allText(app.document.get('records')), /owner\/repo #123/);
      assert.equal(app.document.get('login').hidden, false);
    }
  });
  await app.controller.refresh(user('10')); changed = true; await app.controller.refresh(user('10'));
  assert.doesNotMatch(allText(app.document.get('records')), /owner\/repo #123/);
  assert.equal(app.document.get('login').hidden, false); assert.match(app.document.get('message').textContent, /계정이 바뀌었습니다/);
  assert.equal(notifications, 1); assert.equal(app.calls.length, 2);
  await app.document.get('refresh').emit('click'); assert.equal(notifications, 1); assert.equal(app.calls.length, 2);
});

test('계정 전환 콜백은 POST 계정 조건 오류에서만 호출하고 상태 충돌에는 호출하지 않는다', async () => {
  let notifications = 0, accountChanged = false;
  const app = mount(call => call.method === 'GET' ? response(data()) : response({ error: '저장 거절',
    code: accountChanged ? 'account_changed' : 'state_conflict' }, 409), { onAccountChanged() { notifications++; } });
  await app.controller.refresh(user('10')); app.controller.selectIssue(ISSUE);
  await app.document.get('start').emit('click'); assert.equal(notifications, 0);
  accountChanged = true; await app.document.get('start').emit('click'); assert.equal(notifications, 1);
  assert.equal(app.document.get('login').hidden, false);
});

test('이슈를 바꿨다가 돌아오면 입력을 해당 이슈별로 복원한다', async () => {
  const app = mount(); await app.controller.refresh(user('10')); app.controller.selectIssue(ISSUE); await input(app, 'first-pr-draft');
  app.controller.selectIssue({ repo: 'owner/other', number: 7 }); assert.equal(app.document.get('pr').value, ''); await input(app, 'second-pr-draft');
  app.controller.selectIssue(ISSUE); assert.equal(app.document.get('pr').value, 'first-pr-draft');
});

test('로그아웃 identity는 개인 기록과 입력, 저장된 복원값을 제거한다', async () => {
  const app = mount(() => response(data([record()], [delivery('digest-one')])));
  await app.controller.refresh(user('10')); app.controller.selectIssue(ISSUE); await input(app, 'private-draft'); await app.document.get('login').emit('click');
  await app.controller.refresh({ authenticated: false });
  assert.equal(app.document.get('pr').value, ''); assert.equal(app.storage.values.size, 0);
  assert.doesNotMatch(allText(app.document.get('records')), /owner\/repo #123/); assert.doesNotMatch(allText(app.document.get('deliveries')), /digest-one/);
});

test('서버 상태 충돌은 계정 로그아웃으로 해석하지 않고 입력을 보존한다', async () => {
  const app = mount(call => call.method === 'GET' ? response(data()) : response({ error: '현재 상태를 다시 확인하세요', code: 'state_conflict' }, 409));
  await app.controller.refresh(user('10')); app.controller.selectIssue(ISSUE); await input(app, 'typed-pr'); await app.document.get('start').emit('click');
  assert.equal(app.document.get('login').hidden, true); assert.equal(app.document.get('pr').value, 'typed-pr');
  assert.match(app.document.get('message').textContent, /현재 상태/);
});

test('선택 제목과 비정상 PR 링크는 HTML이나 실행 가능한 링크로 해석하지 않는다', async () => {
  const app = mount(() => response(data([record({ pull_requests: { unsafe: { url: 'javascript:alert(1)', state: 'open', merged_at: null } } })])));
  await app.controller.refresh(user('10')); app.controller.selectIssue({ ...ISSUE, title: '<script>alert(1)</script>' });
  assert.match(app.document.get('selected').textContent, /<script>/);
  assert.equal(app.document.get('prs').querySelectorAll('a').length, 0);
});

test('스토리지 접근 오류나 로그인 콜백 오류가 개인 입력 흐름 밖으로 전파되지 않는다', async () => {
  const storage = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }, removeItem() { throw new Error('blocked'); } };
  const app = mount(undefined, { storage, onLoginRequired() { throw new Error('callback'); } });
  await app.controller.refresh({ authenticated: false }); app.controller.selectIssue(ISSUE); await input(app, 'draft'); await app.document.get('login').emit('click');
  assert.equal(app.document.get('pr').value, 'draft'); assert.equal(app.logins.length, 1);
});

test('destroy 뒤 늦게 도착한 조회는 개인 기록을 복원하지 않는다', async () => {
  const late = deferred(); const app = mount(() => late.promise);
  const read = app.controller.refresh(user('10')); app.controller.destroy(); late.resolve(response(data([record()])));
  assert.equal(await read, false); assert.doesNotMatch(allText(app.document.get('records')), /owner\/repo #123/);
});
