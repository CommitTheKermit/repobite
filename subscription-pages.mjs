import {SubscriptionClient, issueMatches} from './subscription-client.mjs';
const client = new SubscriptionClient(window.fetch.bind(window));
const main = document.querySelector('#main'), status = document.querySelector('#status');
const screen = document.body.dataset.screen;
const routes = ['repositories', 'difficulty', 'notifications'];
const topicNames = {'ai-ml':'AI · 머신러닝','agents-automation':'에이전트 · 자동화','search-knowledge':'검색 · 지식','dev-tools':'개발 도구','web-framework':'웹 프레임워크','ui-design-system':'UI · 디자인 시스템','backend-api':'백엔드 · API','security-identity':'보안 · 인증','database':'데이터베이스','ide-terminal':'에디터 · 터미널','desktop-app':'데스크톱 앱','observability':'모니터링','infra-cloud':'인프라 · 클라우드','productivity':'생산성','media-creative':'미디어','mobile':'모바일'};
const labels = ['본문 충분', '추가 정보 필요', '판단 보류'];
let rows = [], catalog = [], activeRepo = '', level = 1, experience = 'new', topics = [], busy = false;
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const badge = n => `<span class="level level-${n}">Lv.${n} ${labels[n-1]}</span>`;
const go = step => { location.href = `/onboarding-${step}.html`; };
const button = (text, attr, solid = true) => `<button class="button ${solid?'solid':''}" ${attr}>${text}</button>`;
function message(text) { status.textContent = text; }
function issueCard(item) {
  const url = `https://github.com/${encodeURI(item.repo)}/issues/${Number(item.number)}`;
  return `<article class="issue"><div class="issue-meta">${badge(item.grade.difficulty)}<span>${escape(item.repo)} #${Number(item.number)}</span></div><h3><a href="${escape(url)}" target="_blank" rel="noopener noreferrer">${escape(item.title)}</a></h3><p>${escape(item.grade.reason)}</p></article>`;
}
function preview() {
  const selected = new Set(client.session.subscriptions.map(r=>r.toLowerCase()));
  const items = rows.filter(r=> selected.has(r.repo.toLowerCase()) && issueMatches(r, level));
  return `<div class="preview"><div class="preview-title">구독한 저장소의 Lv.${level} 이슈</div>${items.slice(0,2).map(issueCard).join('') || '<p class="empty">현재 조건에 맞는 이슈가 없습니다.</p>'}</div>`;
}
function flowShell(title, body) {
  main.className='flow';
  const step = routes.indexOf(screen);
  main.innerHTML=`<div class="flow-head"><span>${step+1} / 3</span><a href="/subscriptions.html">닫기</a></div><div class="flow-progress">${routes.map((_,i)=>`<span class="${i<=step?'done':''}"></span>`).join('')}</div><h1>${title}</h1>${body}`;
}
function renderRepositories() {
  flowShell('어떤 저장소를 구독할까요?', `<p>관심 분야로 찾아보고 저장소를 선택하세요. 선택 즉시 계정에 저장됩니다.</p><div class="chips">${[...new Set(rows.flatMap(r=>r.categories || []))].map(t=>`<button class="chip" data-topic="${escape(t)}" aria-pressed="${topics.includes(t)}">${escape(topicNames[t] || t)}</button>`).join('')}</div><label class="field-heading" for="repo-search">저장소 검색</label><input id="repo-search" class="repo-search" placeholder="저장소 이름" type="search"><div class="repo-picks" id="repo-picks"></div><div class="flow-actions"><a href="/subscriptions.html">내 구독</a>${button('난이도 선택','data-next-repos')}</div>`);
  renderPicks();
  document.querySelector('#repo-search').addEventListener('input', renderPicks);
}
function renderPicks() {
  const query = document.querySelector('#repo-search').value.toLowerCase();
  const subscriptions = new Set(client.session.subscriptions.map(r=>r.toLowerCase()));
  const visible = catalog.filter(r=>r.repo.toLowerCase().includes(query) && (!topics.length || subscriptions.has(r.repo.toLowerCase()) || r.categories.some(t=>topics.includes(t))));
  document.querySelector('#repo-picks').innerHTML=visible.map(r=>`<button class="repo-pick" data-pick="${escape(r.repo)}" aria-pressed="${subscriptions.has(r.repo.toLowerCase())}"><span class="repo-icon">${escape(r.repo.split('/')[0][0])}</span><span><b>${escape(r.repo)}</b><small>${escape(r.description || '공개 GitHub 저장소')}</small></span><span class="tick">${subscriptions.has(r.repo.toLowerCase())?'✓':'+'}</span></button>`).join('') || '<p class="empty">일치하는 저장소가 없습니다. 탐색에서 저장소를 추가할 수 있습니다.</p>';
  document.querySelector('[data-next-repos]').disabled=!subscriptions.size;
}
function renderDifficulty() {
  flowShell('어떤 난이도의 이슈를 받을까요?', `<p>기존 Lv.1/2/3 기준으로 선택합니다. 경험에 따른 추천은 직접 바꿀 수 있습니다.</p><label class="field-heading" for="experience">개발 경험</label><select id="experience" class="experience">${[['new','오픈 소스 기여가 처음입니다'],['project','프로젝트 개발 경험이 있습니다'],['experienced','오픈 소스 기여 경험이 있습니다']].map(([v,t])=>`<option value="${v}" ${experience===v?'selected':''}>${t}</option>`).join('')}</select><div class="level-options">${[1,2,3].map(n=>`<button class="level-option" data-level="${n}" aria-pressed="${level===n}"><b>${badge(n)}</b><p>${['본문의 정보로 작업을 시작할 수 있습니다.','작업 전에 추가 정보를 확인해야 합니다.','현재 정보로는 작업 판단이 어렵습니다.'][n-1]}</p></button>`).join('')}</div>${preview()}<div class="flow-actions"><a href="/onboarding-repositories.html">이전</a>${button('알림 설정','data-next-level')}</div>`);
  document.querySelector('#experience').addEventListener('change',e=>{experience=e.target.value;level={new:1,project:2,experienced:3}[experience];renderDifficulty();});
}
function renderNotifications() {
  const prefs=client.session.preferences;
  flowShell('이슈 알림을 받을까요?', `<p>구독한 저장소에서 선택한 난이도의 이슈를 이메일로 받습니다.</p><div class="flow-summary">${client.session.subscriptions.map(r=>`<span class="tag">${escape(r)}</span>`).join('')}${badge(level)}</div>${preview()}<form id="notifications"><label class="email-label">알림 이메일<input id="email" type="email" autocomplete="email" value="${escape(prefs.email)}" required></label><label class="consent"><input id="consent" type="checkbox" ${prefs.delivery_enabled?'checked':''} required><span>선택한 조건의 이슈를 이메일로 받는 데 동의합니다.</span></label><p class="note">현재 운영자가 확인 후 수동 발송하며 하루 최대 3개를 보냅니다. 조건에 맞는 이슈가 없으면 보내지 않습니다.</p><div class="flow-actions"><a href="/onboarding-difficulty.html">이전</a>${button('알림받기','type="submit"')}</div>${button('알림 없이 구독하기','type="button" data-skip',false)}</form>`);
  document.querySelector('#notifications').addEventListener('submit', e=>{e.preventDefault();run(()=>finish(true));});
}
function renderMine() {
  main.className='';
  const s=client.session, prefs=s.preferences;
  if(!s.subscriptions.includes(activeRepo))activeRepo=s.subscriptions[0] || '';
  const items=rows.filter(r=>r.repo.toLowerCase()===activeRepo.toLowerCase() && issueMatches(r,level));
  main.innerHTML=`<div class="page-heading"><div><h1>내 구독</h1><p>${s.subscriptions.length}개 저장소</p></div><a class="button" href="/">저장소 탐색</a></div><div class="settings-strip"><span>${badge(prefs.difficulty || 1)} / 이메일 알림 ${prefs.delivery_enabled?'켜짐':'꺼짐'}</span><a href="/onboarding-difficulty.html">알림 설정</a></div>${!prefs.onboarding_completed?'<p class="note"><a href="/onboarding-repositories.html">저장소와 알림 설정을 이어서 완료하기 →</a></p>':''}${!s.subscriptions.length?'<div class="empty">아직 구독한 저장소가 없습니다.<br><a class="button" href="/onboarding-repositories.html">저장소 선택</a></div>':`<div class="workbench"><aside class="repositories">${s.subscriptions.map(repo=>`<button class="repo-row ${repo===activeRepo?'selected':''}" data-repo="${escape(repo)}"><span class="repo-icon">${escape(repo.split('/')[0][0])}</span><span><b>${escape(repo.split('/')[1])}</b><small>${escape(repo.split('/')[0])}</small></span></button>`).join('')}</aside><section class="issues-pane"><div class="repo-heading"><h2>${escape(activeRepo)}</h2>${button('구독 해제',`data-remove="${escape(activeRepo)}"`,false)}</div><div class="levels">${[1,2,3].map(n=>`<button class="${level===n?'active':''}" data-filter="${n}">${badge(n)}</button>`).join('')}</div>${items.map(issueCard).join('')||'<p class="empty">현재 이 난이도의 이슈가 없습니다.</p>'}</section></div>`}`;
}
async function finish(enabled) {
  const email=enabled?document.querySelector('#email').value:client.session.preferences.email;
  await client.save('onboarding',{email,delivery_enabled:enabled},s=>s.preferences.onboarding_completed && s.preferences.delivery_enabled===enabled && s.preferences.email.toLowerCase()===email.trim().toLowerCase());
  location.href='/subscriptions.html';
}
async function run(action) {
  if(busy)return;
  busy=true;message('저장하고 있습니다.');
  main.inert=true;main.setAttribute('aria-busy','true');
  try {await action();message('저장했습니다.');}
  catch(error){message(error.message);if(error.status===401||error.status===409){main.innerHTML='<h1>계정을 다시 확인해 주세요</h1><p><a class="button" href="/api/account?action=start">GitHub 로그인</a> <a href="/subscriptions.html">새로고침</a></p>';}}
  finally{busy=false;main.inert=false;main.setAttribute('aria-busy','false');}
}
main.addEventListener('click',e=>{
  const b=e.target.closest('button');if(!b||busy)return;
  if(b.dataset.topic){topics=topics.includes(b.dataset.topic)?topics.filter(t=>t!==b.dataset.topic):[...topics,b.dataset.topic];renderRepositories();}
  if(b.dataset.repo){activeRepo=b.dataset.repo;renderMine();}
  if(b.dataset.filter){level=Number(b.dataset.filter);renderMine();}
  if(b.dataset.level){level=Number(b.dataset.level);renderDifficulty();}
  if(b.dataset.pick||b.dataset.remove)run(async()=>{
    const repo=b.dataset.pick||b.dataset.remove, remove=client.session.subscriptions.some(r=>r.toLowerCase()===repo.toLowerCase());
    await client.save('subscriptions',{repo},s=>s.subscriptions.some(r=>r.toLowerCase()===repo.toLowerCase())!==remove,remove?'DELETE':'POST');
    if(screen==='mine')renderMine();else renderPicks();
  });
  if(b.hasAttribute('data-next-repos'))run(async()=>{
    await client.save('personalization',{difficulty:level,experience,topics},s=>s.preferences.difficulty===level);
    go('difficulty');
  });
  if(b.hasAttribute('data-next-level'))run(async()=>{
    await client.save('personalization',{difficulty:level,experience,topics},s=>s.preferences.difficulty===level && s.preferences.experience===experience);
    go('notifications');
  });
  if(b.hasAttribute('data-skip'))run(()=>finish(false));
});
async function start() {
  try {
    const session=await client.load();
    if(!session.authenticated){main.innerHTML='<h1>내 구독</h1><p>GitHub 계정으로 로그인해 구독을 관리하세요.</p><a class="button solid" href="/api/account?action=start">GitHub 로그인</a>';return;}
    document.querySelector('#identity').textContent=session.user.login;
    document.querySelector('#logout').hidden=false;
    level=session.preferences.difficulty||1;experience=session.preferences.experience||'new';topics=session.preferences.topics||[];
    if(screen!=='mine'&&screen!=='repositories'&&!session.subscriptions.length){go('repositories');return;}
    if(screen==='notifications'&&!session.preferences.difficulty){go('difficulty');return;}
    try{
      const response=await fetch('/api/repos',{cache:'no-store'});if(!response.ok)throw new Error();
      const feed=await response.json();rows=feed.snapshot?.items||[];
      const repos=new Map();
      for(const r of rows)if(typeof r.repo==='string')repos.set(r.repo.toLowerCase(),{repo:r.repo,description:r.description,categories:r.categories||[]});
      for(const r of feed.repos||[])if(typeof r.repo==='string'&&!repos.has(r.repo.toLowerCase()))repos.set(r.repo.toLowerCase(),{repo:r.repo,description:r.description,categories:[]});
      for(const repo of session.subscriptions)if(!repos.has(repo.toLowerCase()))repos.set(repo.toLowerCase(),{repo,categories:[]});
      catalog=[...repos.values()];
      if(!feed.snapshot)message('공용 이슈를 준비하고 있습니다. 구독 설정은 저장할 수 있습니다.');
    }catch{message('공용 목록을 불러오지 못했습니다. 새로고침해 다시 시도하세요.');catalog=session.subscriptions.map(repo=>({repo,categories:[]}));}
    ({mine:renderMine,repositories:renderRepositories,difficulty:renderDifficulty,notifications:renderNotifications})[screen]();
  }catch(error){message(error.message);main.innerHTML='<h1>계정을 불러오지 못했습니다</h1><a class="button" href="">다시 시도</a>';}
  finally{main.setAttribute('aria-busy','false');}
}
document.querySelector('#logout').addEventListener('click',()=>run(async()=>{await client.request('logout','POST');location.href='/';}));
start();
