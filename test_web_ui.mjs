// 실행: node test_web_ui.mjs. 사용자 탐색과 공용 레포 표시 계약 검사.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const html = readFileSync(new URL('./web.html', import.meta.url), 'utf8');
assert.match(html, /data-filter="ai-ml agents-automation"/);
assert.match(html, /id="search"/);
assert.match(html, /id="sort"/);
assert.match(html, /id="clear"/);
assert.match(html, /selected=selected===r\.repo\?'':r\.repo/);
assert.match(html, /document\.querySelectorAll\('\.card'\)/);
assert.doesNotMatch(html, /selected=selected===r\.repo\?'':r\.repo;cards\(\)/);
assert.match(html, /a\.href=x\.url/);
assert.match(html, /x\.user\?'@'\+x\.user:'작성자 미상'/);
assert.match(html, /x\.created_at\.slice\(5,10\)\.replace\('-','\.'\)/);
assert.match(html, /make\('span','',gradeLabel\(x\)\)/);
assert.doesNotMatch(html, /난이도 미정|'쉬움 '|ready:'바로 착수'/);
assert.match(html, /if\(x\.error\)return'판정 실패'/);
assert.match(html, /if\(!x\.grade\)return'미판정'/);
assert.match(html, /if\(x\.grade\.exclude\)return'제외'/);
assert.match(html, /make\('div','repo-head'\)/);
assert.match(html, /r\.description\+' · '\+repoStatus\(r\)/);
assert.match(html, /av\.onerror=\(\)=>av\.hidden=true/);
assert.match(html, /slot=make\('span','avatar-slot'\)/);
assert.match(html, /readJSON\('\/data\.json'\)/);
assert.match(html, /opengraph\.githubassets\.com\/1\//);
assert.match(html, /avatars\.githubusercontent\.com/);
assert.match(html, /r\.repository_image\|\|social/);
assert.match(html, /img\.className='social'/);
assert.match(html, /img\.naturalWidth\*p\.clientHeight>img\.naturalHeight\*p\.clientWidth/);
assert.match(html, /fallback\.hidden=true/);
assert.match(html, /img\.hidden=true;fallback\.hidden=false/);
assert.match(html, /const cardCache=new Map/);
assert.match(html, /let b=cardCache\.get\(r\.repo\)/);
assert.match(html, /cardCache\.set\(r\.repo,b\)/);
assert.match(html, /\.side\{position:sticky;top:0;width:360px;height:100vh;overflow-y:auto/);
assert.match(html, /\['e',0\],\['m',1\],\['h',2\]/);
assert.doesNotMatch(html, /\/api\/run/);
assert.doesNotMatch(html, /id="collect"/);
assert.doesNotMatch(html, /id="grade"/);
console.log('통과: 탐색·검색·정렬·레포 선택·원본 이슈 이동과 운영 기능 비노출');

const gradeFunctions = html.slice(html.indexOf('function gradeLabel('),html.indexOf('function renderCards('))
  + html.slice(html.indexOf('function verdict('),html.indexOf('function issues('));
runInNewContext(gradeFunctions + `
  const current = difficulty=>({criteria_version:2,grade:{difficulty,readiness:'ready',exclude:false}});
  assert.equal(gradeLabel(current(1)),'Lv.1');
  assert.equal(verdict(current(1)),'본문 충분');
  assert.equal(verdict(current(2)),'추가 정보 필요');
  assert.equal(verdict(current(3)),'판단 보류');
  const legacy={grade:{difficulty:2,readiness:'ready',exclude:false},model:'gpt-5.6-luna'};
  assert.equal(gradeLabel(legacy),'Lv.2');
  assert.equal(verdict(legacy),'기준 미확인');
  assert.equal(verdict({...legacy,criteria_version:1}),'기준 미확인');
  assert.equal(verdict({...legacy,criteria_version:'2'}),'기준 미확인');
  assert.equal(verdict({...legacy,grade:{...legacy.grade,exclude:true}}),'제외 · 기준 미확인');
  assert.equal(verdict({...current(1),grade:{...current(1).grade,exclude:true}}),'제외');
  assert.equal(verdict({error:'TransportError',criteria_version:2}),'판정 실패');
  assert.equal(verdict({criteria_version:2}),'미판정');
  assert.equal(gradeLabel({}),'등급 미정');
  const mixed=[current(1),current(2),current(3),legacy,{...legacy,criteria_version:1},{...legacy,criteria_version:'2'},{}];
  assert.equal(JSON.stringify(gradeCounts(mixed)),JSON.stringify([1,1,1]));
  assert.equal(unverifiedCount(mixed),3);
  assert.equal(JSON.stringify(gradeCounts([legacy])),JSON.stringify([0,0,0]));
`,{assert});
console.log('통과: v2 의미·대응 등급·과거 숫자 보존·기준 미확인·버전별 집계 분리');

// 실제 카드 통계에도 과거 항목의 숫자를 v2로 합산하지 않는다.
const cardFunctions=html.slice(html.indexOf('function gradeLabel('),html.indexOf('function verdict('));
const rendered=[];
runInNewContext(cardFunctions+`
  const legacy={grade:{difficulty:1,readiness:'ready'}};
  const items=[legacy,{criteria_version:2,grade:{difficulty:2,readiness:'needs_info'}}];
  renderCards([{repo:'owner/project',description:'example',issues:items}],feed);
`,{cardCache:new Map,selected:'',feed:{replaceChildren(){},append(node){rendered.push(node)}},
  document:{createTextNode:text=>({textContent:String(text)})},
  make:(tag,cls,text)=>({tag,className:cls,textContent:text,dataset:{},children:[],attributes:{},
    append(...children){this.children.push(...children)},
    setAttribute(key,value){this.attributes[key]=value}})});
const stats=rendered[0].children[0].children.find(node=>node.className==='stats');
assert.equal(stats.attributes['aria-label'],'현행 v2: 본문 충분 0, 추가 정보 필요 1, 판단 보류 0, 기준 미확인 1');
assert.equal(stats.title,stats.attributes['aria-label']);
assert.deepEqual(stats.children.filter(node=>!node.className).map(node=>node.textContent),['0','1','0',' · 기준 미확인 1']);
console.log('통과: 실제 카드의 v2 통계·접근성 설명·과거 건수 표시');

const functions = html.slice(html.indexOf('function allRepos()'), html.indexOf('function cards()'));
runInNewContext(functions + `
  let list=allRepos();
  assert.equal(list.length,3);
  assert.equal(list.filter(r=>r.community).length,2);
  assert.equal(repoStatus(list.find(r=>r.repo==='new/pending')),'수집 대기');
  assert.equal(repoStatus(list.find(r=>r.repo==='new/empty')),'수집 완료 · 조건에 맞는 이슈 없음');
  assert.equal(repos().length,3);
  submitted.push({repo:'A/B',description:'duplicate'});
  assert.equal(allRepos().length,3);
  assert.equal(allRepos().find(r=>r.repo==='a/b').issues.length,1);
  query='pending';assert.equal(repos().length,1);
  query='';sort='recent';assert.equal(repos()[0].repo,'a/b');
`, {assert, state:{items:[{repo:'a/b',description:'base',categories:[],created_at:'2026-09-16'}]},
    submitted:[{repo:'new/pending',description:''},{repo:'new/empty',description:''}],
    collected:new Set(['new/empty']),tags:[],query:'',sort:'recommended',good:()=>false});
runInNewContext(functions + `
  assert.equal(allRepos().length,1);
  assert.equal(allRepos()[0].repo,'found/repo');
  assert.equal(repoStatus(allRepos()[0]),'수집 완료 · 조건에 맞는 이슈 없음');
`, {assert,state:{items:[],discovered_repos:['found/repo']},submitted:[],collected:new Set(['found/repo']),query:'',tags:[],sort:'recommended'});
console.log('통과: 공용/기본 구분·대기/빈 결과 구분·대소문자 중복 병합·검색·정렬');

// 검색은 저장하지 않고 선택한 정식 이름만 기존 등록 입력란에 전달한다.
const nodes=new Map;
function element(){return {value:'',textContent:'',children:[],attributes:{},
  append(...children){this.children.push(...children)},
  replaceChildren(...children){this.children=children},
  setAttribute(key,value){this.attributes[key]=value},
  querySelectorAll(){return this.children.map(li=>li.children[0])},focus(){this.focused=true}}}
const $=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)};
let response,requestURL;
const searchCode=html.slice(html.indexOf('let repoSearchController;'),html.indexOf("$('search-repos').onclick"));
const search=runInNewContext(searchCode+';({searchRepositories,clearRepoSearch})',{
  $,AbortController,setTimeout,clearTimeout,fetch:async url=>{requestURL=url;return response},
  make:(tag,cls,text)=>Object.assign(element(),{tag,textContent:text})});
const found={full_name:'owner/project',description:'<script>text only</script>',private:false,archived:false,has_issues:true};
response={ok:true,json:async()=>({items:[found,{...found,private:true},{...found,archived:true},{...found,has_issues:false}]})};
$('repo-query').value='project';
await search.searchRepositories();
assert.equal(new URL(requestURL).searchParams.get('q'),'project in:name is:public archived:false');
assert.equal($('repo-results').children.length,1);
assert.equal($('repo-input').value,'');
const choice=$('repo-results').children[0].children[0];
assert.equal(choice.children[1].textContent,found.description);
choice.onclick();assert.equal($('repo-input').value,'owner/project');
assert.equal(choice.attributes['aria-pressed'],true);
response={ok:false,status:403};await search.searchRepositories();
assert.match($('repo-search-status').textContent,/요청 한도/);
assert.equal($('search-repos').disabled,false);
response={ok:true,json:async()=>({items:[]})};await search.searchRepositories();
assert.match($('repo-search-status').textContent,/담을 수 있는 레포가 없습니다/);
let release,started;
const jsonStarted=new Promise(resolve=>started=resolve);
response={ok:true,json:()=>new Promise(resolve=>{release=resolve;started()})};
const pending=search.searchRepositories();await jsonStarted;
search.clearRepoSearch();release({items:[found]});await pending;
assert.equal($('repo-results').children.length,0);
assert.equal($('repo-search-status').textContent,'');
assert.match(readFileSync(new URL('./web.py',import.meta.url),'utf8'),/connect-src 'self' https:\/\/api\.github\.com/);
console.log('통과: 이름 검색·등록 가능 결과·선택 시 입력·요청 제한·빈 결과·늦은 응답 무시');
