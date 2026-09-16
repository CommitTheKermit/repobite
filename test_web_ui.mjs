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
assert.match(html, /x\.grade\?\.difficulty\?'난이도 '\+x\.grade\.difficulty:'난이도 미정'/);
assert.match(html, /ready:'바로 착수',needs_info:'확인 필요',undecided:'판단 보류'/);
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
console.log('통과: 공용/기본 구분·대기/빈 결과 구분·대소문자 중복 병합·검색·정렬');
