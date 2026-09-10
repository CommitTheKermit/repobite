// 실행: node test_web_ui.mjs. 브라우저와 모델 호출 없이 화면의 오류 복구 검사.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const nodes = new Map();
function node() {
  return {value:'', dataset:{}, hidden:false, textContent:'', disabled:false,
    append(){}, replaceChildren(){}, addEventListener(){}, setAttribute(){}};
}
const document = {
  getElementById(id) { if (!nodes.has(id)) nodes.set(id,node()); return nodes.get(id); },
  createElement:node, querySelectorAll:()=>[],
};
const state = {repos:'a/b',max_repos:30,count:0,grade_count:0,deferred_count:0,
  grade_limit:100,repo_grade_limit:20,items:[],logs:[],summary:{failed:0,valid:0,cross:[]}};
const context = vm.createContext({document,setTimeout(){},
  fetch:async()=>({ok:true,json:async()=>state})});
const html = readFileSync(new URL('./web.html',import.meta.url),'utf8');
vm.runInContext(html.split('<script>')[1].split('</script>')[0],context);
await vm.runInContext('refresh()',context);
vm.runInContext('showError(new Error("Failed to fetch"), "poll")',context);
assert.equal(nodes.get('error').hidden,false);
assert.match(nodes.get('error').textContent,/로컬 서버에 연결하지 못했습니다/);
await vm.runInContext('refresh()',context);
assert.equal(nodes.get('error').hidden,true);
vm.runInContext('showError(new Error("실행 요청 실패"))',context);
await vm.runInContext('refresh()',context);
assert.equal(nodes.get('error').hidden,false); // 상태 조회 성공이 실행 요청 실패를 숨기지 않는다.
assert.equal(nodes.get('error').textContent,'실행 요청 실패');
console.log('통과: 연결 실패 안내·조회 복구 시 오류 해제·실행 요청 오류 유지');
