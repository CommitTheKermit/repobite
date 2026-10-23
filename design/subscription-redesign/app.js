// RepoBite 연결 프로토타입: 탐색 메인, 4단계 구독 온보딩(분야 > 저장소 > 난이도 > 알림), 내 구독. 저장은 화면 상태로만 흉내 낸다.
const TOPICS = [
  ['ai-ml', 'AI · 머신러닝', 'brain'], ['agents-automation', '에이전트', 'bot'], ['search-knowledge', '검색 · 지식', 'search'],
  ['dev-tools', '개발 도구', 'wrench'], ['web-framework', '웹 프레임워크', 'globe'], ['ui-design-system', 'UI · 디자인', 'palette'],
  ['backend-api', '백엔드 · API', 'server'], ['security-identity', '보안 · 인증', 'shield-check'], ['database', '데이터베이스', 'database'],
  ['ide-terminal', '에디터 · 터미널', 'square-terminal'], ['desktop-app', '데스크톱 앱', 'monitor'], ['observability', '모니터링', 'activity'],
  ['infra-cloud', '인프라', 'cloud'], ['productivity', '생산성', 'list-checks'], ['media-creative', '미디어', 'clapperboard'], ['mobile', '모바일', 'smartphone'],
];
const TOPIC_NAME = Object.fromEntries(TOPICS.map(([key, name]) => [key, name]));
// 화면 난이도 이름은 쉬움·보통·어려움만 쓴다. 판정 기준(본문 충분도)을 난이도 설명으로 노출하지 않는다.
const LEVELS = ['쉬움', '보통', '어려움'];
const EXPERIENCES = [['new', '오픈 소스 기여가 처음입니다', 1], ['project', '프로젝트 개발 경험이 있습니다', 2], ['experienced', '오픈 소스 기여 경험이 있습니다', 3]];
const GROUPS = [['AI', 'ai-ml agents-automation'], ['프레임워크', 'web-framework ui-design-system backend-api'], ['데이터', 'database search-knowledge'],
  ['개발 도구', 'dev-tools ide-terminal testing-quality cicd-release'], ['인프라', 'infra-cloud observability networking-systems'], ['보안', 'security-identity'],
  ['앱', 'desktop-app mobile productivity'], ['미디어', 'media-creative games-graphics']];
const STEPS = [['topics', 'TOPIC'], ['repos', 'REPO'], ['level', 'LV'], ['mail', 'MAIL']];

// 저장소는 구독하는 순간 바로 수집한다("담기"나 정기 수집 대기 개념은 없다).
// OTHERS: 다른 사용자가 이미 구독해 수집된 저장소 샘플. GITHUB: RepoBite에 아직 없어 검색으로만 찾는 GitHub 저장소 샘플.
const OTHERS = new Set(['glanceapp/glance', 'henrygd/beszel', 'asciimoo/hister']);
const GITHUB = new Set(['bookorbit/bookorbit', 'neurosnap/zmx']);
const repos = new Map();
for (const issue of window.ISSUES) {
  const repo = repos.get(issue.repo) || {
    name: issue.repo, description: issue.d, topics: new Set(), all: [], external: GITHUB.has(issue.repo),
    get collected() { return !this.external || state.collected.has(this.name); },
    // RepoBite 목록에 보이는지: 수집됐거나 지금 수집 중인 저장소
    get listed() { return this.collected || state.collecting.has(this.name); },
    get subscribed() { return OTHERS.has(this.name) || state.subs.has(this.name); },
    // 화면에서 쓰는 이슈는 모두 이 getter를 거친다. 수집 전 저장소는 빈 목록이다.
    get issues() { return this.collected ? this.all : []; },
  };
  issue.c.forEach(t => repo.topics.add(t));
  repo.all.push(issue);
  repos.set(issue.repo, repo);
}

const state = { obStep: '', collected: new Set(), collecting: new Map(), searchOpen: false, open: new Set(), detail: '', dlv: 0, group: '', sort: 'recommended', search: '', onboarded: false, topics: new Set(), subs: new Set(), experience: 'new', level: 1, email: '', consent: true, mail: null, active: '', filter: 1, query: '', error: '' };
const view = document.querySelector('#view'), stack = document.querySelector('#stack');
const esc = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const short = name => name.split('/')[1];
const avatar = (name, size = 16, cls = '') => `<canvas class="${cls}" data-dither="seed" data-seed="${esc(name)}" width="${size}" height="${size}" aria-hidden="true"></canvas>`;
const owner = name => `<img class="owner" src="https://avatars.githubusercontent.com/${esc(name.split('/')[0])}?v=4&s=64" alt="" loading="lazy">`;
// 메인과 같은 순서로 저장소 이미지를 고른다: README 대표 이미지 > GitHub 소셜 미리보기 > 저장소 이름
const repoMedia = (name, cls = '') => {
  const social = `https://opengraph.githubassets.com/1/${name}`, image = window.REPO_IMAGES[name] || social;
  return `<span class="card-media ${cls}"><img class="card-art${image === social ? ' social' : ''}" src="${esc(image)}" data-social="${esc(social)}" alt="${esc(name)} 대표 이미지" loading="lazy"><span class="card-fallback" hidden>${esc(name)}</span></span>`;
};
// 가로 스크롤 대신 칩을 한 줄로 접고 '+N 더보기'로 펼친다
const moreChip = key => `<button class="chip more" data-more="${key}" aria-expanded="${state.open.has(key)}">${state.open.has(key) ? '접기' : ''}</button>`;
function fold(box) {
  const chips = [...box.querySelectorAll('.chip:not(.more)')], more = box.querySelector('.more');
  chips.forEach(c => { c.hidden = false; });
  more.hidden = false;
  if (state.open.has(box.dataset.fold)) { more.hidden = !chips.some(c => c.offsetTop !== chips[0].offsetTop); return; }
  more.hidden = true;
  // 첫 줄은 칩으로 채우고 더보기 칩은 다음 줄로 내려가도 된다
  const top = chips[0].offsetTop, overflows = () => chips.some(c => !c.hidden && c.offsetTop !== top);
  if (!overflows()) return;
  more.hidden = false;
  // 선택된 칩은 남기고 뒤에서부터 숨긴다
  for (let i = chips.length - 1, hidden = 0; i > 0 && overflows(); i--) {
    if (chips[i].getAttribute('aria-pressed') === 'true') continue;
    chips[i].hidden = true;
    more.textContent = `+${++hidden} 더보기`;
  }
}
// display: contents인 묶음은 offsetParent가 없으므로 첫 칩으로 화면 표시 여부를 본다
const foldAll = () => document.querySelectorAll('[data-fold]').forEach(box => box.querySelector('.chip')?.offsetParent && fold(box));
const issues = n => `${n} issue${n === 1 ? '' : 's'}`;
const icon = name => `<span data-lucide="${name}"></span>`;
const recentIssues = () => window.ISSUES.filter(i => repos.get(i.repo).collected);
const subIssues = () => [...state.subs].flatMap(name => repos.get(name).issues);
const route = () => location.hash.replace('#/', '') || 'explore';
const levelTags = list => [1, 2, 3].map(n => [n, list.filter(i => i.lv === n).length]).filter(([, c]) => c).map(([n, c]) => `<span class="tag">${LEVELS[n - 1]} ${c}</span>`).join('');
const issueRow = i => `<a class="issue-row" href="https://github.com/${esc(i.repo)}/issues/${i.n}" target="_blank" rel="noopener noreferrer"><span class="inv">Lv.${i.lv} ${LEVELS[i.lv - 1]}</span><span class="pix">#${i.n}</span><b>${esc(i.t)}</b></a>`;
const go = name => { location.hash = `#/${name}`; };

// 상세에서 여는 온보딩 다이얼로그는 저장소가 정해져 있으므로 난이도와 알림 두 단계만 쓴다
const DIALOG_STEPS = STEPS.filter(([key]) => key === 'level' || key === 'mail');
let flowSteps = STEPS;
// 첫 단계의 왼쪽 아래 링크: 이전 단계가 있으면 "이전", 없으면 닫기
const prevOrLater = step => {
  const index = flowSteps.findIndex(([key]) => key === step);
  return index ? `<button class="later" data-go="${flowSteps[index - 1][0]}">이전</button>` : '<button class="later" data-go="explore">나중에 할게요</button>';
};
function flow(step, body, foot) {
  const steps = flowSteps, index = steps.findIndex(([key]) => key === step);
  const back = index ? `<button data-go="${steps[index - 1][0]}" aria-label="이전">‹</button>` : '<span></span>';
  return `<div class="flow">
    <div class="flow-top">${back}<div class="dashes" aria-label="${steps.length}단계 중 ${index + 1}단계">${steps.map((_, i) => `<span class="${i <= index ? 'on' : ''}"></span>`).join('')}</div><button data-go="explore" aria-label="닫기">×</button></div>
    <div class="panel"><span class="eyebrow">STEP 0${index + 1} / 0${steps.length}</span>${body}</div>
    <div class="flow-foot">${foot}</div></div>`;
}

// 검색 결과 부분만 다시 그리는 조각들. 타이핑 중에 입력칸을 바꿔 끼우면 한글 조합이 끊기므로 입력칸은 건드리지 않는다.
const listedRepos = () => [...repos.values()].filter(r => r.listed);
const matches = (r, query) => (r.name + r.description).toLowerCase().includes(query.toLowerCase());
// RepoBite에 없는 GitHub 저장소는 두 글자 이상 검색했을 때만 결과로 보여 준다
const githubMatches = query => query.trim().length < 2 ? [] : [...repos.values()].filter(r => !r.listed && matches(r, query.trim()));
function exploreList() {
  const groupTopics = state.group.split(' ');
  const list = listedRepos().filter(r => (!state.group || [...r.topics].some(t => groupTopics.includes(t))) && matches(r, state.search));
  return state.sort === 'name' ? list.sort((a, b) => a.name.localeCompare(b.name)) : list;
}
// 수집 전 저장소(아직 RepoBite에 없음)는 이슈 대신 수집 상태를 보여 준다
const collectStatus = r => state.collecting.has(r.name)
  ? `<span class="tag">수집 중</span><span class="collect-bar"><span style="width:${state.collecting.get(r.name)}%"></span></span>`
  : '<span class="tag">구독하면 바로 수집</span>';
const exploreCards = list => list.map(r => `<article class="card win"><button class="card-hit" data-detail="${esc(r.name)}" aria-haspopup="dialog">
        <span class="win-bar"><span>${esc(short(r.name))}</span><span>${r.collected ? issues(r.issues.length) : state.collecting.has(r.name) ? 'collecting' : 'github'}</span></span>${repoMedia(r.name)}
        <span class="card-body"><span class="card-meta">${owner(r.name)}<span><b>${esc(r.name)}</b><small>${esc(r.description)}</small></span></span><span class="tags">${r.collected ? levelTags(r.issues) : collectStatus(r)}</span></span></button>
</article>`).join('') || '<p class="empty">일치하는 저장소가 없습니다.</p>';
// 구독된 레포와 POPULAR를 나눈 피드. 검색과 수집 상태 변경 때 이 부분만 다시 그린다.
function updateFeeds() {
  const list = exploreList(), subscribed = list.filter(r => r.subscribed), popular = list.filter(r => !r.subscribed), github = githubMatches(state.search);
  const section = document.querySelector('#subscribed-section');
  if (!section) return;
  section.hidden = !subscribed.length;
  document.querySelector('#subscribed-feed').innerHTML = exploreCards(subscribed);
  document.querySelector('#subscribed-count').textContent = subscribed.length;
  document.querySelector('#popular-feed').innerHTML = exploreCards(popular);
  document.querySelector('#popular-count').textContent = popular.length;
  document.querySelector('#github-section').hidden = !github.length;
  document.querySelector('#github-feed').innerHTML = exploreCards(github);
}
function repoRows() {
  const list = listedRepos().filter(r => (state.subs.has(r.name) || [...r.topics].some(t => state.topics.has(t))) && matches(r, state.query))
    .concat(githubMatches(state.query));
  return list.map(r => `<button class="repo" data-repo="${esc(r.name)}" aria-pressed="${state.subs.has(r.name)}">${repoMedia(r.name, 'thumb')}<span><b>${esc(r.name)}</b><small>${esc(r.description)}</small>${r.collected ? '' : `<small class="collect-hint">${state.collecting.has(r.name) ? '수집 중' : 'RepoBite에 아직 없음 · 구독하면 바로 수집'}</small>`}</span><span class="pix">${r.collected ? issues(r.issues.length) : 'new'}</span><span class="check">${icon('check')}</span></button>`).join('') || '<p class="empty">일치하는 저장소가 없습니다.</p>';
}

const screens = {
  explore() {
    const chips = [['전체', '']].concat(GROUPS).map(([label, value]) => `<button class="chip" data-group="${value}" aria-pressed="${state.group === value}">${label}${value ? '' : ` <span class="pix">${listedRepos().length}</span>`}</button>`).join('');
    // 오른쪽 패널이 숨는 좁은 화면에서는 돋보기 버튼으로 필터 바 위에 검색칸을 펼친다
    const inline = state.searchOpen ? `<div class="inline-search"><label class="search-box">${icon('search')}<input class="search" id="explore-search-m" type="search" placeholder="저장소 이름이나 설명으로 검색" aria-label="저장소 검색" value="${esc(state.search)}"></label><button class="ghost" data-search-close>닫기</button></div>` : '';
    return `<div class="explore"><button class="search-toggle" data-search-open aria-label="저장소 검색" aria-expanded="${state.searchOpen}">${icon('search')}</button>${inline}
      <div class="bar"><select class="sort" id="sort" aria-label="정렬"><option value="recommended">추천순</option><option value="name" ${state.sort === 'name' ? 'selected' : ''}>레포 이름순</option></select><div class="chips" data-fold="groups">${chips}${moreChip('groups')}</div></div>
      <div class="section-head"><span class="eyebrow">REPOSITORIES / ${listedRepos().length}</span><button class="ghost invert" data-go="${state.onboarded ? 'subs' : 'topics'}">${state.onboarded ? '내 구독 보기' : '레포바이트 이용하기'}</button></div>
      <section class="feed-section" id="github-section" hidden><div class="feed-title"><h2>GitHub에서 찾은 저장소</h2><p>RepoBite에 아직 없는 저장소입니다. 구독하면 바로 이슈를 수집합니다.</p></div><div class="masonry" id="github-feed"></div></section>
      <section class="feed-section" id="subscribed-section"><div class="feed-title"><h2>구독된 레포 <span class="pix" id="subscribed-count"></span></h2><p>다른 사용자가 구독한 저장소입니다.</p></div><div class="masonry" id="subscribed-feed"></div></section>
      <section class="feed-section"><div class="feed-title"><h2>POPULAR <span class="pix" id="popular-count"></span></h2></div><div class="masonry" id="popular-feed"></div></section></div>`;
  },
  topics() {
    const tiles = TOPICS.map(([key, name, glyph]) => {
      const count = listedRepos().filter(r => r.topics.has(key)).length;
      return `<button class="topic" data-topic="${key}" aria-pressed="${state.topics.has(key)}"><i>${icon(glyph)}</i>${name}<small>${count}</small></button>`;
    }).join('');
    return flow('topics', `<canvas class="art" data-dither="orb" width="84" height="60" aria-hidden="true"></canvas>
      <h1>어떤 분야의 이슈가<br>궁금하세요?</h1><p class="sub">고른 분야의 저장소를 다음 화면에서 보여 드립니다. 숫자는 분야별 저장소 수입니다.</p>
      <div class="topics">${tiles}</div>`,
      `<button class="later" data-go="explore">나중에 할게요</button><button class="next" data-go="repos" aria-label="저장소 선택으로" ${state.topics.size ? '' : 'disabled'}>${icon('arrow-right')}</button>`);
  },
  repos() {
    return flow('repos', `<h1>어떤 저장소를<br>구독할까요?</h1><p class="sub">${[...state.topics].map(t => TOPIC_NAME[t]).join(', ') || '고른 분야'}의 저장소입니다.</p>
      <input class="search" id="query" type="search" placeholder="저장소 이름으로 찾기" aria-label="저장소 검색" value="${esc(state.query)}">
      <div class="repos">${repoRows()}</div>`,
      `<button class="later" data-go="topics">분야 다시 고르기</button><button class="next" data-go="level" aria-label="난이도 선택으로" ${state.subs.size ? '' : 'disabled'}>${icon('arrow-right')}</button>`);
  },
  level() {
    const all = subIssues(), matched = all.filter(i => i.lv === state.level);
    const rows = [1, 2, 3].map(n => {
      const count = all.filter(i => i.lv === n).length;
      return `<button class="bench-row" data-level="${n}" aria-pressed="${state.level === n}" style="--at:${all.length ? (count / all.length) * 100 : 0}%"><span class="inv">Lv.${n} ${LEVELS[n - 1]}</span><span></span><span class="count">${count}</span><span class="track"></span></button>`;
    }).join('');
    const first = matched[0];
    const spec = first ? `<div class="spec" style="margin-top:28px;width:100%"><span class="cross tl"></span><span class="cross br"></span>
        <div class="full">${repoMedia(first.repo, 'spec-media')}</div>
        <div><span class="lab">Issue</span><span class="val big">#${first.n}</span></div>
        <div class="right"><span class="outline">Output</span><div class="val" style="margin-top:8px">Lv.${first.lv}</div></div>
        <div class="full"><span class="lab">Repository</span><span class="val">${esc(first.repo)}</span></div>
        <div class="full"><h3>${esc(first.t)}</h3></div>
        <div><span class="lab">Difficulty</span><span class="inv">${LEVELS[first.lv - 1]}</span></div>
        <div class="right"><span class="lab">Match</span><span class="val">${matched.length} / ${all.length}</span></div>
        <div class="full barcode" aria-hidden="true"></div></div>` : '<p class="empty">이 난이도의 이슈가 지금은 없습니다. 새 이슈가 판정되면 보내 드립니다.</p>';
    return flow('level', `<h1>오픈 소스 기여는<br>얼마나 해 보셨어요?</h1><p class="sub">경험에 맞춰 난이도를 추천합니다. 추천은 아래에서 직접 바꿀 수 있습니다.</p>
      <div class="pills" role="group" aria-label="개발 경험">${EXPERIENCES.map(([key, text]) => `<button class="pill" data-exp="${key}" aria-pressed="${state.experience === key}">${text}</button>`).join('')}</div>
      <div class="bench" role="group" aria-label="받을 난이도">${rows}</div>
      <div class="bench-foot" style="width:100%"><div class="circles" aria-label="구독 이슈 ${all.length}건 중 ${matched.length}건">${all.map(i => `<span class="${i.lv === state.level ? 'on' : ''}"></span>`).join('')}</div><span class="pix">${matched.length} / ${issues(all.length)}</span></div>
      ${spec}`,
      `${prevOrLater('level')}<button class="next" data-go="mail" aria-label="알림 설정으로">${icon('arrow-right')}</button>`);
  },
  mail() {
    return flow('mail', `<canvas class="art" data-dither="burst" width="84" height="60" aria-hidden="true"></canvas>
      <h1>새 이슈를 메일로<br>받아 볼까요?</h1><p class="sub">구독한 저장소 ${state.subs.size}곳에서 Lv.${state.level} ${LEVELS[state.level - 1]} 이슈가 생기면 보내 드립니다.</p>
      <div class="slots" aria-hidden="true"><span class="on">1</span><span class="on">2</span><span class="on">3</span></div>
      <div class="slots-cap">하루 최대 3개, 조건에 맞는 이슈가 없으면 보내지 않습니다</div>
      <label class="field-label">알림 이메일<input class="search" id="email" type="email" autocomplete="email" placeholder="you@example.com" value="${esc(state.email)}"></label>
      <div class="toggle-row"><span>선택한 조건의 이슈를 이메일로 받는 데 동의합니다.</span><button class="toggle" data-consent role="switch" aria-checked="${state.consent}" aria-label="이메일 수신 동의"></button></div>
      ${state.error ? `<p class="error" role="alert">${state.error}</p>` : ''}
      <div style="margin-top:28px;display:grid;justify-items:center;gap:4px"><button class="cta" data-finish="mail">알림받기</button><button class="text-btn" data-finish="skip">알림 없이 구독하기</button></div>`, '');
  },
  subs() {
    if (!state.subs.size) {
      return `<div class="page"><header class="page-head"><span class="cross tr"></span><div><span class="eyebrow">MY SUBSCRIPTIONS</span><h1>내 구독</h1></div></header>
        <p class="empty" style="text-align:left">아직 구독한 저장소가 없습니다.</p><button class="solid-btn" data-go="topics">저장소 고르기 ${icon('arrow-right')}</button></div>`;
    }
    if (!state.subs.has(state.active)) state.active = [...state.subs][0];
    const repo = repos.get(state.active), items = repo.issues.filter(i => i.lv === state.filter);
    const cells = items.map(i => `<article><div style="display:flex;justify-content:space-between;gap:8px;align-items:center"><span class="inv">Lv.${i.lv} ${LEVELS[i.lv - 1]}</span><span class="pix">#${i.n}</span></div>
      <h3 style="font-size:18px;line-height:1.35;margin:14px 0 12px;letter-spacing:-.01em">${esc(i.t)}</h3>
      <a href="https://github.com/${esc(i.repo)}/issues/${i.n}" target="_blank" rel="noopener noreferrer" style="color:var(--muted);font-size:13px">GitHub에서 열기 ↗</a></article>`).join('');
    return `<div class="page">
      <header class="page-head"><span class="cross tr"></span><div><span class="eyebrow">MY SUBSCRIPTIONS</span><h1>내 구독</h1></div>
        <div style="display:grid;justify-items:end;gap:12px"><span class="pix">${state.subs.size} REPOS / LV.${state.level} / MAIL ${state.mail ? 'ON' : 'OFF'}</span><button class="ghost" data-go="topics">처음부터 다시 설정</button></div></header>
      <nav class="mobile-subs" data-fold="subs" aria-label="구독 저장소">${[...state.subs].map(n => `<button class="chip" data-active="${esc(n)}" aria-pressed="${n === state.active}">${esc(short(n))}</button>`).join('')}${moreChip('subs')}</nav>
      <section class="repo-head">${avatar(repo.name)}<div><h2>${esc(repo.name)}</h2><p>${esc(repo.description)}</p></div><button class="ghost" data-unsub="${esc(repo.name)}">구독 해제</button></section>
      <div class="spec spec-3"><span class="cross tl"></span><span class="cross br"></span>
        <div><span class="lab">Issues</span><span class="val big">${repo.issues.length}</span></div>
        <div><span class="lab">Topics</span><div class="tags" style="margin-top:6px">${[...repo.topics].map(t => `<span class="tag">${esc(TOPIC_NAME[t])}</span>`).join('')}</div></div>
        <div class="right"><span class="lab">Match Lv.${state.filter}</span><div class="circles" style="margin-top:10px">${repo.issues.map(i => `<span class="${i.lv === state.filter ? 'on' : ''}"></span>`).join('')}</div></div>
        <div class="full barcode" aria-hidden="true"></div></div>
      <div class="chips" role="group" aria-label="난이도">${[1, 2, 3].map(n => `<button class="chip" data-filter="${n}" aria-pressed="${state.filter === n}">Lv.${n} ${LEVELS[n - 1]} <span class="pix">${repo.issues.filter(i => i.lv === n).length}</span></button>`).join('')}</div>
      <div class="action-grid">${cells || '<p class="empty" style="text-align:left">이 난이도의 이슈가 지금은 없습니다.</p>'}</div></div>`;
  },
};

function renderSide() {
  stack.classList.remove('stack');
  stack.innerHTML = `<label class="search-box">${icon('search')}<input class="search" id="explore-search" type="search" placeholder="저장소 이름이나 설명으로 검색" aria-label="저장소 검색" value="${esc(state.search)}"></label>
    <section class="win dots"><div class="win-bar"><span>RECENT</span><span>${issues(recentIssues().length)}</span></div><div class="win-body"><div class="issue-list">${recentIssues().slice(0, 6).map(i => `<button class="issue-row with-owner" data-detail="${esc(i.repo)}" aria-haspopup="dialog">${owner(i.repo)}<span class="inv">Lv.${i.lv} ${LEVELS[i.lv - 1]}</span><span class="pix">${esc(short(i.repo))}</span><b>${esc(i.t)}</b></button>`).join('')}</div></div></section>`;
}

// 저장소 상세 다이얼로그: TypeSafe 스펙 시트 오버레이 (2026-10-23 A·B·C 시안 중 C로 확정)
const detailBox = document.querySelector('#detail');
// 수집 전 저장소 안내. 구독하는 순간 바로 수집한다.
const collectNotice = repo => `<section class="win dots collect-notice"><div class="win-bar"><span>COLLECT</span><span>${state.collecting.has(repo.name) ? `${Math.round(state.collecting.get(repo.name))}%` : 'github'}</span></div><div class="win-body">
  ${state.collecting.has(repo.name)
    ? '<p>지금 이 저장소의 이슈를 수집하고 있습니다. 끝나면 알림으로 알려 드립니다.</p>'
    : '<p>RepoBite에 아직 없는 GitHub 저장소입니다. <b>구독하면 바로 이슈를 수집</b>하고, 수집이 끝나면 구독된 레포에 나타납니다.</p>'}</div></section>`;

function subscribe(name) {
  state.subs.add(name);
  const repo = repos.get(name);
  if (!repo.collected && !state.collecting.has(name)) collect(repo);
}

// 즉시 수집 흉내: 진행 토스트를 띄우고, 끝나면 완료 토스트로 바꾼 뒤 숨겨 둔 샘플 이슈를 보여 준다
const toasts = document.querySelector('#toasts');
function showToasts() {
  // popover는 열린 dialog보다 위 레이어에 놓이도록 다시 연다
  if (toasts.matches(':popover-open')) toasts.hidePopover();
  if (toasts.children.length) toasts.showPopover();
}
function collect(repo) {
  const toast = document.createElement('section');
  toast.className = 'win toast';
  toasts.append(toast);
  let percent = 0;
  const draw = () => {
    const step = percent < 45 ? '이슈를 가져오는 중' : percent < 90 ? '난이도를 판정하는 중' : '정리하는 중';
    toast.innerHTML = `<div class="win-bar"><span>COLLECT</span><span>${esc(short(repo.name))}</span></div><div class="win-body"><p><b>${esc(repo.name)}</b> 구독 즉시 수집 · ${step}</p><div class="progress"><span style="width:${percent}%">${Math.round(percent)}%</span></div></div>`;
  };
  state.collecting.set(repo.name, 0);
  draw();
  showToasts();
  refresh();
  const timer = setInterval(() => {
    percent = Math.min(100, percent + 2 + Math.random() * 3);
    state.collecting.set(repo.name, percent);
    draw();
    refreshProgress(repo.name, percent);
    if (percent < 100) return;
    clearInterval(timer);
    state.collecting.delete(repo.name);
    state.collected.add(repo.name);
    toast.remove();
    notify('DONE', short(repo.name), `<p><b>${esc(repo.name)}</b> 수집 완료 · ${issues(repo.issues.length)}</p><button class="ghost" data-detail="${esc(repo.name)}">보기</button>`);
    refresh();
  }, 150);
}
// 수집 상태가 바뀌면 다시 그린다. 입력 중이면 입력칸을 건드리지 않도록 목록만 갱신한다.
function refresh() {
  if (document.activeElement?.matches('input, textarea')) {
    updateFeeds();
    const list = document.querySelector('.repos');
    if (list) { list.innerHTML = repoRows(); window.lucide.createIcons(); }
    return;
  }
  render();
}
// 진행률은 매 틱마다 막대와 숫자만 바꾼다
function refreshProgress(name, percent) {
  document.querySelectorAll(`.card-hit[data-detail="${CSS.escape(name)}"] .collect-bar span`).forEach(bar => { bar.style.width = `${percent}%`; });
  if (state.detail === name) {
    const label = detailBox.querySelector('.collect-notice .win-bar span:last-child');
    if (label) label.textContent = `${Math.round(percent)}%`;
  }
}

function detailParts(repo) {
  const counts = [1, 2, 3].map(n => repo.issues.filter(i => i.lv === n).length);
  const list = repo.issues.filter(i => !state.dlv || i.lv === state.dlv);
  const subscribed = state.subs.has(repo.name);
  return {
    counts, list,
    topics: `<div class="tags">${[...repo.topics].map(t => `<span class="tag">${esc(TOPIC_NAME[t] || t)}</span>`).join('')}</div>`,
    cta: subscribed ? '<button class="ghost" data-go="subs">구독 중 · 내 구독 보기</button>' : `<button class="solid-btn" data-subscribe="${esc(repo.name)}">${repo.collected ? '이 저장소 구독하기' : '구독하고 바로 수집'} ${icon('arrow-right')}</button>`,
    github: `<a class="ghost" href="https://github.com/${esc(repo.name)}" target="_blank" rel="noopener noreferrer">GitHub ↗</a>`,
    chips: `<div class="chips" role="group" aria-label="난이도">${[[0, '전체', repo.issues.length], ...counts.map((c, i) => [i + 1, LEVELS[i], c])].map(([n, label, c]) => `<button class="chip" data-dlv="${n}" aria-pressed="${state.dlv === n}">${label} <span class="pix">${c}</span></button>`).join('')}</div>`,
    close: '<button class="detail-close" data-close aria-label="닫기">×</button>',
  };
}
function detailView(repo, p) {
    const cells = p.list.map(i => `<article><div style="display:flex;justify-content:space-between;gap:8px;align-items:center"><span class="inv">Lv.${i.lv} ${LEVELS[i.lv - 1]}</span><span class="pix">#${i.n}</span></div>
      <h3 style="font-size:17px;line-height:1.4;margin:12px 0 10px;letter-spacing:-.01em">${esc(i.t)}</h3><a href="https://github.com/${esc(i.repo)}/issues/${i.n}" target="_blank" rel="noopener noreferrer" style="color:var(--muted);font-size:13px">GitHub에서 열기 ↗</a></article>`).join('');
    return `<section class="overlay">${p.close}
      <div class="overlay-top"><div class="overlay-title"><span class="eyebrow">REPOSITORY</span><h2>${esc(short(repo.name))}</h2><span class="card-meta" style="margin-top:16px">${owner(repo.name)}<span><b class="detail-name">${esc(repo.name)}</b><small>${esc(repo.description)}</small></span></span>${p.topics}<div class="overlay-cta">${p.cta}${p.github}</div></div>
        <div class="spec"><span class="cross tl"></span><span class="cross br"></span><div class="full">${repoMedia(repo.name, 'spec-media')}</div>
          <div><span class="lab">Issues</span><span class="val big">${repo.collected ? repo.issues.length : '-'}</span></div>
          <div class="right"><span class="lab">Topics</span><span class="val big">${repo.topics.size}</span></div>
          ${p.counts.map((c, i) => `<div class="full" style="display:flex;justify-content:space-between"><span class="inv">Lv.${i + 1} ${LEVELS[i]}</span><span class="val">${repo.collected ? c : '-'}</span></div>`).join('')}
          <div class="full barcode" aria-hidden="true"></div></div></div>
      <div class="overlay-issues">${repo.collected ? `${p.chips}<div class="action-grid">${cells || '<p class="empty" style="text-align:left">이 난이도의 이슈가 지금은 없습니다.</p>'}</div>` : collectNotice(repo)}</div></section>`;
}
function renderDetail() {
  const repo = repos.get(state.detail);
  if (!repo) { if (detailBox.open) detailBox.close(); return; }
  detailBox.setAttribute('aria-label', `${repo.name} 상세`);
  detailBox.innerHTML = detailView(repo, detailParts(repo));
  if (!detailBox.open) detailBox.showModal();
  window.lucide.createIcons();
}
detailBox.addEventListener('close', () => { state.detail = ''; });
detailBox.addEventListener('click', event => { if (event.target === detailBox) closeDetail(); });

function renderStack(name) {
  if (name === 'explore') return renderSide();
  stack.classList.toggle('stack', name !== 'subs');
  if (name === 'subs') {
    stack.innerHTML = state.subs.size ? `<section class="win" style="--i:0"><div class="win-bar"><span>SUBSCRIBED</span><span>${state.subs.size}</span></div><div class="win-body"><div class="sub-list">${[...state.subs].map(n => `<button class="sub-row" data-active="${esc(n)}" aria-current="${n === state.active}">${avatar(n)}<span><b>${esc(short(n))}</b><small>${esc(n.split('/')[0])}</small></span><span class="pix">${repos.get(n).issues.length}</span></button>`).join('')}</div></div></section>
      <section class="win dots" style="--i:1"><div class="win-bar"><span>MAIL</span><span>${state.mail ? 'ON' : 'OFF'}</span></div><div class="win-body"><dl class="kv"><dt>받는 난이도</dt><dd>Lv.${state.level} ${LEVELS[state.level - 1]}</dd><dt>받는 주소</dt><dd>${esc(state.mail || '없음')}</dd><dt>발송</dt><dd>하루 최대 3개</dd></dl><button class="ghost" data-go="level" style="margin-top:16px">알림 설정 바꾸기</button></div></section>` : '';
    return;
  }
  const index = STEPS.findIndex(([key]) => key === name);
  const detail = {
    topics: ['관심 분야', [...state.topics].map(t => TOPIC_NAME[t])],
    repos: [`${state.subs.size}개 저장소 구독`, [...state.subs].map(short)],
    level: [`Lv.${state.level} ${LEVELS[state.level - 1]}`, [EXPERIENCES.find(([key]) => key === state.experience)[1]]],
    mail: [state.consent ? (state.email || '이메일 입력 전') : '알림 없이 구독', ['하루 최대 3개']],
  };
  stack.innerHTML = STEPS.slice(0, index + 1).map(([key, word], i) => {
    const [caption, tags] = detail[key];
    return `<section class="win ${i === index ? '' : 'dots'}" style="--i:${i}"><div class="win-bar"><span>${word}</span><span>0${i + 1}/04</span></div><div class="win-body">
      <span class="wordmark">${key === 'level' ? `LV.${state.level}` : word}</span><p class="caption">${esc(caption)}</p>
      <div class="tags">${tags.length ? tags.map(t => `<span class="tag">${esc(t)}</span>`).join('') : '<span class="pix">NONE</span>'}</div></div></section>`;
  }).join('');
}

function render() {
  let name = route();
  if (!screens[name]) name = 'explore';
  document.querySelectorAll('[data-nav]').forEach(a => {
    const current = a.dataset.nav === (name === 'explore' ? 'explore' : 'subs');
    a.toggleAttribute('aria-current', current);
    a.querySelector('canvas').dataset.color = current ? '--text' : '--dim';
  });
  if ((name === 'level' || name === 'mail') && !state.subs.size) return go(state.topics.size ? 'repos' : 'topics');
  if (name !== 'explore') state.detail = '';
  renderDetail();
  view.innerHTML = screens[name]();
  updateFeeds();
  renderStack(name);
  window.lucide.createIcons();
  window.paintDither();
  foldAll();
  renderOnboard();
}

// 상세에서 처음 구독할 때 여는 온보딩 다이얼로그. 전체 화면 온보딩과 같은 단계 화면을 쓰되 페이지는 탐색에 머문다.
const onboardBox = document.querySelector('#onboard');
function renderOnboard() {
  if (!state.obStep) { if (onboardBox.open) onboardBox.close(); return; }
  flowSteps = DIALOG_STEPS;
  onboardBox.innerHTML = screens[state.obStep]();
  flowSteps = STEPS;
  // 새로 연 다이얼로그가 수집 토스트를 덮지 않도록 토스트를 다시 위로 올린다
  if (!onboardBox.open) { onboardBox.showModal(); showToasts(); }
  window.lucide.createIcons();
  window.paintDither(onboardBox);
}
// close 이벤트는 비동기로 오므로, 닫은 직후 다시 그려도 열리지 않게 상태를 먼저 비운다
const closeOnboard = () => { state.obStep = ''; onboardBox.close(); };
const closeDetail = () => { state.detail = ''; detailBox.close(); };
onboardBox.addEventListener('close', () => { state.obStep = ''; });
onboardBox.addEventListener('click', event => { if (event.target === onboardBox) closeOnboard(); });
// 알림 토스트: 완료나 저장 결과를 잠시 보여 준다
function notify(bar, label, html) {
  const toast = document.createElement('section');
  toast.className = 'win toast';
  toast.innerHTML = `<div class="win-bar"><span>${bar}</span><span>${esc(label)}</span></div><div class="win-body toast-done">${html}</div>`;
  toasts.append(toast);
  showToasts();
  setTimeout(() => { toast.remove(); showToasts(); }, 5000);
  return toast;
}

function dialog(lines, done) {
  const box = document.querySelector('#dialog'), bar = document.querySelector('#dialog-bar');
  document.querySelector('#dialog-text').innerHTML = lines;
  box.hidden = false;
  let percent = 0;
  const timer = setInterval(() => {
    percent = Math.min(100, percent + 7 + Math.random() * 12);
    bar.style.width = `${percent}%`;
    bar.textContent = `${Math.round(percent)}%`;
    if (percent === 100) { clearInterval(timer); setTimeout(() => { box.hidden = true; done(); }, 250); }
  }, 90);
}

document.addEventListener('click', event => {
  const b = event.target.closest('button');
  if (!b || b.disabled) return;
  const d = b.dataset, inOnboard = !!b.closest('#onboard');
  if (d.go && inOnboard) {
    if (!DIALOG_STEPS.some(([key]) => key === d.go)) return closeOnboard();
    state.obStep = d.go;
    return renderOnboard();
  }
  if (d.go) return go(d.go);
  if ('searchOpen' in d) { state.searchOpen = true; if (route() !== 'explore') return go('explore'); }
  if ('searchClose' in d) { state.searchOpen = false; state.search = ''; }
  if ('group' in d) state.group = d.group;
  if (d.more) state.open.has(d.more) ? state.open.delete(d.more) : state.open.add(d.more);
  if (d.detail) { state.detail = d.detail; state.dlv = 0; if (route() !== 'explore') return go('explore'); }
  if ('close' in d) return closeDetail();
  if ('dlv' in d) state.dlv = Number(d.dlv);
  if (d.subscribe) {
    subscribe(d.subscribe);
    repos.get(d.subscribe).topics.forEach(t => state.topics.add(t));
    // 처음 구독이면 상세를 닫고 같은 자리에서 난이도·알림 두 단계 온보딩 다이얼로그를 연다
    if (!state.onboarded) { closeDetail(); state.obStep = 'level'; return render(); }
    state.active = d.subscribe;
  }
  if (d.topic) state.topics.has(d.topic) ? state.topics.delete(d.topic) : state.topics.add(d.topic);
  if (d.repo) state.subs.has(d.repo) ? state.subs.delete(d.repo) : subscribe(d.repo);
  if (d.exp) { state.experience = d.exp; state.level = EXPERIENCES.find(([key]) => key === d.exp)[2]; }
  if (d.level) state.level = Number(d.level);
  if ('consent' in d) state.consent = !state.consent;
  if (d.active) state.active = d.active;
  if (d.filter) state.filter = Number(d.filter);
  if (d.unsub) state.subs.delete(d.unsub);
  if (d.finish) {
    const email = document.querySelector('#email').value.trim();
    state.email = email;
    if (d.finish === 'mail' && !state.consent) { state.error = '이메일로 받으려면 수신 동의를 켜 주세요.'; return render(); }
    if (d.finish === 'mail' && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { state.error = '알림을 받을 이메일 주소를 확인해 주세요.'; return render(); }
    state.error = '';
    state.mail = d.finish === 'mail' ? email : null;
    state.onboarded = true;
    state.filter = state.level;
    state.active = [...state.subs].find(n => repos.get(n).issues.some(i => i.lv === state.level)) || '';
    if (inOnboard) {
      const mailOn = !!state.mail;
      closeOnboard();
      render();
      return dialog('Saving ...<br>Subscriptions, Mail', () => notify('DONE', 'SUBSCRIBED', `<p>구독을 시작했습니다.${mailOn ? ' 조건에 맞는 새 이슈를 메일로 보내 드립니다.' : ''}</p><button class="ghost" data-go="subs">내 구독</button>`));
    }
    render();
    return dialog('Saving ...<br>Subscriptions, Mail', () => go('subs'));
  }
  render();
  if ('searchOpen' in d) document.querySelector('#explore-search-m')?.focus();
});
document.addEventListener('change', event => { if (event.target.id === 'sort') { state.sort = event.target.value; render(); } });
document.addEventListener('input', event => {
  const id = event.target.id;
  if (id === 'email') state.email = event.target.value;
  // 검색은 결과 목록만 다시 그린다. 입력칸을 다시 만들면 한글 자모 조합이 끊겨 'ㅇㅏㄴ'처럼 흩어진다.
  if (id === 'query') {
    state.query = event.target.value;
    document.querySelector('.repos').innerHTML = repoRows();
    window.lucide.createIcons();
  }
  if (id === 'explore-search' || id === 'explore-search-m') {
    state.search = event.target.value;
    updateFeeds();
    document.querySelectorAll('#explore-search, #explore-search-m').forEach(input => { if (input !== event.target) input.value = state.search; });
  }
});
// 카드 이미지가 깨지면 소셜 미리보기, 그것도 실패하면 저장소 이름을 보여 준다 (error는 버블링되지 않아 캡처 단계에서 받는다)
document.addEventListener('error', event => {
  const img = event.target;
  if (!img.classList || !img.classList.contains('card-art')) return;
  if (!img.classList.contains('social')) { img.classList.add('social'); img.src = img.dataset.social; return; }
  img.hidden = true;
  img.nextElementSibling.hidden = false;
}, true);
window.addEventListener('hashchange', () => { render(); window.scrollTo(0, 0); });
document.fonts.ready.then(foldAll);
window.addEventListener('resize', () => { window.paintDither(document.querySelector('.desk')); foldAll(); });

render();
dialog('Loading ...<br>Repositories, Issues', () => {});
