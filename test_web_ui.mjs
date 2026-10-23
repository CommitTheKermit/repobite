import test from 'node:test';
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
