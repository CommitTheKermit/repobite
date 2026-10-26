/** 개인 기여 기록. GitHub 선점이나 이메일 도착으로 표현하지 않는다. */
const DRAFT_KEY = 'repobite:contribution-draft:v1';
const ACTIVITY = { not_started: '착수 전', active: '진행 중', cancelled: '취소됨' };
const IDS = ['status', 'message', 'login', 'refresh', 'selected', 'start', 'cancel', 'resume',
  'pr-form', 'pr', 'delivery', 'prs', 'records', 'deliveries', 'summary'];
function browserStorage() { try { return globalThis.sessionStorage; } catch { return null; } }
function issueValue(value) {
  if (!value || typeof value.repo !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9-]{0,38}\/[A-Za-z0-9_.-]{1,100}$/.test(value.repo)
      || ['.', '..'].includes(value.repo.split('/')[1]) || !Number.isSafeInteger(value.number) || value.number <= 0) return null;
  return { repo: value.repo.toLowerCase(), number: value.number,
    title: typeof value.title === 'string' ? value.title.slice(0, 500) : '' };
}
const issueKey = issue => issue ? issue.repo + '/' + issue.number : '';
const label = issue => issue.repo + ' #' + issue.number;
class ContributionError extends Error {
  constructor(message, status = 0, code = '') { super(message); this.status = status; this.code = code; }
}
function responseValue(value) {
  if (!Array.isArray(value?.records) || !Array.isArray(value.deliveries) || typeof value.summary !== 'object' || !value.summary
      || !value.records.every(row => issueValue(row) && Object.hasOwn(ACTIVITY, row.activity)
        && row.pull_requests && typeof row.pull_requests === 'object' && !Array.isArray(row.pull_requests) && Array.isArray(row.events))
      || !value.deliveries.every(row => typeof row.id === 'string' && typeof row.day === 'string'
        && typeof row.confirmed_at === 'string' && Array.isArray(row.items) && row.items.every(issueValue))) {
    throw new ContributionError('기여 기록 응답을 확인하지 못했습니다. 입력을 유지하고 다시 조회하세요.');
  }
  return value;
}
function eventId() {
  const bytes = new Uint8Array(16);
  if (!globalThis.crypto?.getRandomValues) throw new ContributionError('이 브라우저에서 요청 식별자를 만들지 못했습니다.');
  globalThis.crypto.getRandomValues(bytes);
  return Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
}

/** refresh identity는 {authenticated,user:{id,login}}이고 selectIssue 입력은 {repo,number,title?}다. */
export function mountContributionUI({ document, fetch, onLoginRequired = () => {}, onAccountChanged = () => {}, storage = browserStorage() }) {
  const el = Object.fromEntries(IDS.map(id => {
    const node = document.getElementById('contribution-' + id);
    if (!node) throw new Error('기여 UI 요소가 없습니다: contribution-' + id);
    return [id, node];
  }));
  let identity = { authenticated: false }, selected = null, inputOwner = null, deliveryChoice = '';
  let snapshot = { records: [], deliveries: [], summary: {} };
  let revision = 0, destroyed = false, busy = false, restored = false;
  const drafts = new Map(), pendingEvents = new Map(), listeners = [];
  const active = ticket => !destroyed && ticket === revision;
  const message = text => { el.message.textContent = text; };
  const listen = (node, event, fn) => { node.addEventListener(event, fn); listeners.push(() => node.removeEventListener(event, fn)); };
  const removeStored = () => { try { storage?.removeItem(DRAFT_KEY); } catch {} };
  const ownerKey = () => identity.user?.id ?? inputOwner ?? 'anonymous';
  const draftKey = issue => ownerKey() + ':' + issueKey(issue);
  const matchingRecord = issue => snapshot.records.find(row => issueKey(issueValue(row)) === issueKey(issue));
  const matchingDeliveries = issue => issue ? snapshot.deliveries.filter(row => row.state === 'operator_confirmed'
    && row.items.some(item => issueKey(issueValue(item)) === issueKey(issue))) : [];

  function storeInput() {
    if (selected) drafts.set(draftKey(selected), { pr_url: el.pr.value, delivery_id: deliveryChoice });
  }
  function persistInput() {
    if (!selected) return;
    const draft = { issue: selected, owner_id: identity.user?.id ?? inputOwner,
      pr_url: el.pr.value, delivery_id: deliveryChoice };
    try { storage?.setItem(DRAFT_KEY, JSON.stringify(draft)); } catch {}
  }
  function restoreInput() {
    if (restored) return;
    let draft;
    try { draft = JSON.parse(storage?.getItem(DRAFT_KEY) ?? 'null'); } catch {}
    if (!draft || !issueValue(draft.issue) || typeof draft.pr_url !== 'string' || typeof draft.delivery_id !== 'string'
        || !(draft.owner_id === null || typeof draft.owner_id === 'string')) {
      restored = true; removeStored(); return;
    }
    if (draft.owner_id && draft.owner_id !== identity.user?.id) {
      if (identity.authenticated) { restored = true; removeStored(); }
      return;
    }
    selected = issueValue(draft.issue); inputOwner = identity.user?.id ?? draft.owner_id;
    drafts.set(draftKey(selected), { pr_url: draft.pr_url, delivery_id: draft.delivery_id });
    el.pr.value = draft.pr_url; deliveryChoice = draft.delivery_id; el.delivery.value = deliveryChoice;
    restored = true; removeStored();
  }
  function clearPrivate() {
    drafts.clear(); pendingEvents.clear(); inputOwner = null; el.pr.value = ''; deliveryChoice = ''; el.delivery.value = '';
    snapshot = { records: [], deliveries: [], summary: {} }; removeStored();
  }
  function button(text, fn) {
    const node = document.createElement('button'); node.type = 'button'; node.textContent = text;
    node.disabled = busy; node.addEventListener('click', fn); return node;
  }
  function appendText(parent, text, tag = 'span') {
    const node = document.createElement(tag); node.textContent = text; parent.append(node); return node;
  }
  function render() {
    const record = matchingRecord(selected), activity = record?.activity ?? 'not_started';
    el.status.textContent = identity.authenticated ? (identity.user.login ?? identity.user.id) + '님의 개인 기여 기록'
      : '개인 기여 기록은 GitHub 로그인 후 이용할 수 있습니다.';
    el.login.hidden = identity.authenticated; el.refresh.disabled = busy || !identity.authenticated;
    el.selected.textContent = selected ? label(selected) + (selected.title ? ' - ' + selected.title : '') : '기여를 기록할 이슈를 선택하세요.';
    for (const action of ['start', 'cancel', 'resume']) {
      el[action].hidden = action === 'start' ? activity !== 'not_started' : action === 'cancel' ? activity !== 'active' : activity !== 'cancelled';
      el[action].disabled = busy || !selected;
    }
    el.pr.disabled = busy || !selected;
    for (const node of el['pr-form'].querySelectorAll('button')) node.disabled = busy || !selected;
    const chosenDelivery = deliveryChoice;
    el.delivery.replaceChildren();
    const none = document.createElement('option'); none.value = ''; none.textContent = '전달 기록 연결 안 함'; el.delivery.append(none);
    const choices = matchingDeliveries(selected);
    for (const delivery of choices) {
      const option = document.createElement('option'); option.value = delivery.id;
      option.textContent = delivery.day + ' 운영자 발송 확인 (' + delivery.id + ')'; el.delivery.append(option);
    }
    el.delivery.value = choices.some(row => row.id === chosenDelivery) ? chosenDelivery : '';
    el.delivery.disabled = busy || !selected || !identity.authenticated;
    el.prs.replaceChildren();
    for (const pr of Object.values(record?.pull_requests ?? {})) {
      const row = document.createElement('li');
      if (typeof pr.url === 'string' && /^https:\/\/github\.com\/[A-Za-z0-9-]+\/[A-Za-z0-9_.-]+\/pull\/[1-9][0-9]*$/.test(pr.url)) {
        const link = document.createElement('a'); link.href = pr.url; link.textContent = pr.url;
        link.target = '_blank'; link.rel = 'noopener noreferrer'; row.append(link);
      } else appendText(row, 'PR 주소 확인 필요');
      appendText(row, pr.merged_at ? 'GitHub 병합 확인: ' + pr.merged_at : pr.state === 'closed' ? 'GitHub에서 닫힘, 병합 미확인' : 'GitHub에서 열림');
      appendText(row, 'GitHub 조회: ' + (pr.provider_checked_at ?? '미확인'));
      appendText(row, '이슈 연결은 사용자 신고이며 이슈 자동 종료는 확인하지 않았습니다.');
      if (typeof pr.url === 'string') row.append(button('PR 상태 다시 검증', () => mutate('verify_pr', pr.url)));
      el.prs.append(row);
    }
    if (!el.prs.children.length) appendText(el.prs, '선택한 이슈에 제출한 PR이 없습니다.', 'li');
    el.records.replaceChildren();
    for (const row of snapshot.records) {
      const item = document.createElement('li');
      const choose = button(label(row) + ' - ' + ACTIVITY[row.activity], () => selectIssue(row));
      if (issueKey(issueValue(row)) === issueKey(selected)) choose.setAttribute('aria-current', 'true');
      item.append(choose); appendText(item, '갱신: ' + (row.updated_at ?? '미확인')); el.records.append(item);
    }
    if (!snapshot.records.length) appendText(el.records, identity.authenticated ? '아직 개인 기여 기록이 없습니다.' : '로그인 후 내 기록을 볼 수 있습니다.', 'li');
    el.deliveries.replaceChildren();
    for (const delivery of snapshot.deliveries) {
      const row = document.createElement('li');
      appendText(row, delivery.day + ' 운영자 발송 확인: ' + delivery.confirmed_at);
      appendText(row, '메일 도착 여부는 확인되지 않았습니다.');
      for (const issue of delivery.items) row.append(button(label(issue), () => selectIssue(issue)));
      el.deliveries.append(row);
    }
    if (!snapshot.deliveries.length) appendText(el.deliveries, '운영자가 발송을 확인한 개인 전달 기록이 없습니다.', 'li');
    const count = key => Number.isSafeInteger(snapshot.summary[key]) && snapshot.summary[key] >= 0 ? snapshot.summary[key] : 0;
    el.summary.textContent = identity.authenticated ? '기록한 이슈 ' + count('tracked_issues') + '건, GitHub 병합 확인 PR '
      + count('merged_pr_count') + '건, 운영자 발송 확인 ' + count('operator_confirmed_digest_count') + '건. 메일 도착 여부는 미확인입니다.' : '';
  }

  async function api(method, userId, action, payload) {
    let response, value;
    try {
      const query = method === 'GET' ? '?expected_user_id=' + encodeURIComponent(userId) : '?action=' + action;
      response = await fetch('/api/contributions' + query, { method, credentials: 'same-origin', cache: 'no-store',
        ...(payload ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) } : {}) });
    } catch { throw new ContributionError('기여 기록 서버에 연결하지 못했습니다. 입력을 유지하고 다시 시도하세요.'); }
    try { value = await response.json(); }
    catch { throw new ContributionError('기여 기록 응답을 확인하지 못했습니다. 입력을 유지하고 다시 시도하세요.'); }
    if (!response.ok) throw new ContributionError(typeof value?.error === 'string' ? value.error.slice(0, 300)
      : '기여 기록 요청을 처리하지 못했습니다.', response.status, value?.code);
    return value;
  }
  function fail(error, ticket) {
    if (!active(ticket)) return;
    if (error.status === 401 || (error.status === 409 && error.code === 'account_changed')) {
      snapshot = { records: [], deliveries: [], summary: {} }; identity = { authenticated: false };
    }
    message(error instanceof ContributionError ? error.message : '기여 기록을 확인하지 못했습니다. 입력을 유지하고 다시 시도하세요.');
    if (error.status === 409 && error.code === 'account_changed') {
      busy = false; render();
      try { Promise.resolve(onAccountChanged()).catch(() => {}); } catch {}
    }
  }
  function requestLogin() {
    persistInput(); message('GitHub 로그인 후 개인 기여 기록을 저장할 수 있습니다. 입력은 유지됩니다.');
    try { onLoginRequired({ issue: selected ? { ...selected } : null, pr_url: el.pr.value, delivery_id: deliveryChoice }); } catch {}
    return false;
  }
  async function refresh(nextIdentity = identity) {
    if (destroyed) return false;
    storeInput(); const previousOwner = identity.user?.id ?? inputOwner;
    const next = nextIdentity?.authenticated === true && typeof nextIdentity.user?.id === 'string' && /^[1-9][0-9]*$/.test(nextIdentity.user.id)
      ? { authenticated: true, user: { ...nextIdentity.user } } : { authenticated: false };
    if (previousOwner && next.user?.id !== previousOwner) clearPrivate();
    const anonymousDraft = !previousOwner && selected ? drafts.get('anonymous:' + issueKey(selected)) : null;
    identity = next; inputOwner = next.user?.id ?? null;
    if (anonymousDraft && next.authenticated) drafts.set(draftKey(selected), anonymousDraft);
    restoreInput();
    snapshot = { records: [], deliveries: [], summary: {} };
    const ticket = ++revision; busy = identity.authenticated; render();
    if (!identity.authenticated) { message(''); return true; }
    try {
      const value = responseValue(await api('GET', identity.user.id));
      if (!active(ticket)) return false;
      snapshot = value; message('개인 기여 기록을 불러왔습니다.'); return true;
    } catch (error) { fail(error, ticket); return false; }
    finally { if (active(ticket)) { busy = false; render(); } }
  }
  function selectIssue(issue) {
    if (destroyed) return false;
    storeInput(); selected = issueValue(issue);
    const draft = selected ? drafts.get(draftKey(selected)) : null;
    el.pr.value = draft?.pr_url ?? ''; deliveryChoice = draft?.delivery_id ?? ''; el.delivery.value = deliveryChoice;
    message(''); render(); return !!selected;
  }
  async function mutate(action, prUrl) {
    if (destroyed || !selected) return false;
    storeInput();
    if (!identity.authenticated) return requestLogin();
    const issue = { ...selected }, userId = identity.user.id;
    const deliveryId = matchingDeliveries(issue).some(row => row.id === deliveryChoice) ? deliveryChoice : '';
    const payload = { expected_user_id: userId, repo: issue.repo, number: issue.number,
      ...(prUrl === undefined ? {} : { pr_url: prUrl }), ...(deliveryId ? { delivery_id: deliveryId } : {}) };
    const fingerprint = JSON.stringify([userId, action, issueKey(issue), prUrl ?? null, deliveryId]);
    let id = pendingEvents.get(fingerprint);
    try { if (!id) { id = eventId(); pendingEvents.set(fingerprint, id); } }
    catch (error) { message(error.message); return false; }
    payload.event_id = id;
    const ticket = ++revision; busy = true; message('개인 기록 저장 결과를 확인하고 있습니다.'); render();
    try {
      const result = await api('POST', userId, action, payload);
      if (!active(ticket)) return false;
      if (!issueValue(result?.record) || issueKey(issueValue(result.record)) !== issueKey(issue)
          || typeof result.changed !== 'boolean' || typeof result.replayed !== 'boolean') {
        throw new ContributionError('저장 응답을 확인하지 못했습니다. 입력을 유지하고 다시 시도하세요.');
      }
      const value = responseValue(await api('GET', userId));
      if (!active(ticket)) return false;
      const saved = value.records.find(row => issueKey(issueValue(row)) === issueKey(issue));
      if (!saved || (result.changed && !result.replayed && !saved.events.some(event => event.event_id === id))) {
        throw new ContributionError('저장 결과를 확인하지 못했습니다. 입력을 유지하고 다시 조회하세요.');
      }
      snapshot = value; pendingEvents.delete(fingerprint); removeStored();
      message((result.replayed ? '이전 요청을 재확인했습니다. ' : '') + label(issue) + '의 현재 기록을 불러왔습니다: ' + ACTIVITY[saved.activity]);
      return true;
    } catch (error) {
      if (active(ticket) && error.status >= 400 && error.status < 500) pendingEvents.delete(fingerprint);
      fail(error, ticket); return false;
    } finally { if (active(ticket)) { busy = false; render(); } }
  }
  listen(el.login, 'click', requestLogin);
  listen(el.refresh, 'click', () => refresh());
  for (const action of ['start', 'cancel', 'resume']) listen(el[action], 'click', () => mutate(action));
  listen(el['pr-form'], 'submit', event => { event.preventDefault(); return mutate('submit_pr', el.pr.value); });
  listen(el.pr, 'input', storeInput); listen(el.delivery, 'change', () => { deliveryChoice = el.delivery.value; storeInput(); });
  render();
  return { refresh, selectIssue,
    destroy() { destroyed = true; revision++; listeners.forEach(remove => remove()); clearPrivate(); identity = { authenticated: false }; render(); }
  };
}
