/** 저장소 선택은 입력만 채운다. 실제 구독은 기존 폼 제출과 계정 확인을 거친다. */
export function mountRepositoryAutocomplete({ document, input, fetch, delay = 450 }) {
  const list = document.getElementById('account-repo-results');
  const status = document.getElementById('account-repo-search-status');
  let timer, controller, revision = 0, selected = -1, results = [], composing = false;
  const listeners = [];
  function listen(node, type, callback) {
    node.addEventListener(type, callback);
    listeners.push(() => node.removeEventListener(type, callback));
  }
  function clear() {
    revision++; clearTimeout(timer); controller?.abort(); controller = null;
    results = []; selected = -1; list.replaceChildren(); list.hidden = true;
    status.textContent = ''; input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
  }
  function choose(index) {
    const repo = results[index]?.full_name;
    if (!repo) return;
    input.value = repo; clear();
    input.dispatchEvent(new Event('input', { bubbles: true }));
    clear(); status.textContent = repo + ' 선택됨. 저장소 구독을 눌러주세요.';
    input.focus();
  }
  function highlight(index) {
    selected = index;
    [...list.children].forEach((node, i) => node.setAttribute('aria-selected', String(i === selected)));
    const option = list.children[selected];
    if (option) {
      input.setAttribute('aria-activedescendant', option.id);
      option.scrollIntoView?.({ block: 'nearest' });
    }
  }
  async function search(term, ticket) {
    controller = new AbortController();
    const request = controller, timeout = setTimeout(() => request.abort(), 12000);
    status.textContent = 'GitHub에서 검색 중입니다.';
    try {
      const q = encodeURIComponent(term + ' in:name is:public archived:false');
      const response = await fetch('https://api.github.com/search/repositories?q=' + q + '&per_page=8',
        { signal: request.signal, credentials: 'omit' });
      if (response.status === 403 || response.status === 429) throw Error('검색 한도에 도달했습니다. 잠시 후 다시 시도하거나 owner/repo를 직접 입력하세요.');
      if (!response.ok) throw Error('검색하지 못했습니다. 다시 시도하거나 주소를 직접 입력하세요.');
      const data = await response.json();
      if (!Array.isArray(data.items)) throw Error('검색 결과를 읽지 못했습니다. 다시 시도하세요.');
      if (ticket !== revision) return;
      results = data.items.filter(repo => repo.private === false && !repo.archived && repo.has_issues && typeof repo.full_name === 'string');
      for (const [index, repo] of results.entries()) {
        const option = document.createElement('li');
        option.id = 'account-repo-option-' + index;
        option.setAttribute('role', 'option'); option.setAttribute('aria-selected', 'false');
        const name = document.createElement('strong'), description = document.createElement('span');
        name.textContent = repo.full_name; description.textContent = repo.description || '설명 없음';
        option.append(name, description);
        option.addEventListener('mousedown', event => event.preventDefault());
        option.addEventListener('click', () => choose(index));
        list.append(option);
      }
      list.hidden = results.length === 0;
      input.setAttribute('aria-expanded', String(results.length > 0));
      status.textContent = results.length ? '검색 결과 ' + results.length + '개. 방향키와 Enter 또는 클릭으로 선택하세요.'
        : '검색 결과가 없습니다. 다른 이름이나 owner/repo를 직접 입력하세요.';
      if (data.incomplete_results) status.textContent += ' 일부 결과만 조회됐습니다.';
    } catch (error) {
      if (ticket === revision) status.textContent = error.name === 'AbortError'
        ? '검색 응답이 늦습니다. 다시 입력해 검색하거나 주소를 직접 입력하세요.'
        : error instanceof TypeError ? 'GitHub 연결을 확인하세요. 주소를 직접 입력할 수도 있습니다.' : error.message;
    } finally { clearTimeout(timeout); }
  }
  function changed() {
    clear();
    const term = input.value.trim();
    if (composing || !term || /^https?:\/\//i.test(term)) return;
    if (term.length < 2) { status.textContent = '두 글자 이상 입력하면 저장소를 검색합니다.'; return; }
    const ticket = revision;
    timer = setTimeout(() => search(term, ticket), delay);
  }
  listen(input, 'input', changed);
  listen(input, 'compositionstart', () => { composing = true; clear(); });
  listen(input, 'compositionend', () => { composing = false; changed(); });
  listen(input, 'keydown', event => {
    if (event.isComposing || composing) return;
    if (event.key === 'Escape' && !list.hidden) { event.preventDefault(); event.stopPropagation(); clear(); }
    else if (results.length && ['ArrowDown', 'ArrowUp'].includes(event.key)) {
      event.preventDefault();
      highlight((selected + (event.key === 'ArrowDown' ? 1 : selected < 0 ? 0 : -1) + results.length) % results.length);
    } else if (event.key === 'Enter' && selected >= 0) { event.preventDefault(); choose(selected); }
    else if (event.key === 'Tab') clear();
  });
  listen(input, 'blur', clear);
  return { clear, destroy() { clear(); listeners.forEach(remove => remove()); } };
}
