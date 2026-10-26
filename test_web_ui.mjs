import test from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {issueMatches} from './subscription-client.mjs';
import {searchRepositories} from './repository-autocomplete.mjs';

test('공개 이슈는 현행 판정 중 선택 난이도와 일치하는 항목만 표시한다',()=>{
  const current={criteria_version:2,grade:{difficulty:2,exclude:false}};
  assert.equal(issueMatches(current,2),true);
  for(const row of [{...current,criteria_version:null},{...current,error:'failed'},{...current,grade:{difficulty:2,exclude:true}}]) assert.equal(issueMatches(row,2),false);
});
test('탐색 검색은 활성 공개 저장소만 반환한다',async()=>{
  const repo={full_name:'owner/repo',private:false,archived:false,has_issues:true};
  const rows=await searchRepositories(async()=>({ok:true,json:async()=>({items:[repo,{...repo,private:true},{...repo,archived:true},{...repo,disabled:true},{...repo,has_issues:false},{...repo,full_name:'<script>/invalid'}]})}),'repo');
  assert.deepEqual(rows,[repo]);
});
test('GitHub 검색 제한을 빈 성공 결과로 숨기지 않는다',async()=>{
  await assert.rejects(searchRepositories(async()=>({ok:false,status:429}),'repo'),/검색 한도/);
});

const app = readFileSync(new URL('./repobite-app.mjs', import.meta.url), 'utf8');
const html = readFileSync(new URL('./web.html', import.meta.url), 'utf8');
test('첫 화면은 서비스 목적과 원문 확인 안내를 표시한다', () => {
  assert.match(html, /<title>RepoBite \| 초보자가 바로 손댈 수 있는 오픈소스 이슈<\/title>/);
  assert.match(app, /<h1>처음 기여하기 좋은 오픈소스 이슈를 골라드립니다<\/h1>/);
  assert.match(app, /작업 전에 GitHub 원문과 현재 상태를 확인하세요/);
});
