import test from 'node:test';
import assert from 'node:assert/strict';
import {SubscriptionClient, issueMatches} from './subscription-client.mjs';
const session=id=>({authenticated:true,user:{id},subscriptions:[],preferences:{}});
const ok=value=>({ok:true,json:async()=>value});
test('mutation is owner bound and requires readback',async()=>{
 const requests=[],responses=[ok(session('10')),ok({}),ok({...session('10'),subscriptions:['o/r']})];
 const client=new SubscriptionClient(async(url,options)=>{requests.push(options);return responses.shift();});
 await client.load();await client.save('subscriptions',{repo:'o/r'},s=>s.subscriptions.includes('o/r'));
 assert.equal(JSON.parse(requests[1].body).expected_user_id,'10');
 assert.equal(client.session.subscriptions[0],'o/r');
});
test('account switch does not adopt another account',async()=>{
 const responses=[ok(session('10')),ok({}),ok(session('20'))];const client=new SubscriptionClient(async()=>responses.shift());
 await client.load();await assert.rejects(client.save('personalization',{},()=>true),/계정이 바뀌/);
 assert.equal(client.session.user.id,'10');
});
test('failed write and failed readback are not success',async()=>{
 for(const response of [{ok:false,status:503,json:async()=>({error:'실패'})},ok({})]){
  const responses=[ok(session('10')),response,ok(session('10'))];const client=new SubscriptionClient(async()=>responses.shift());
  await client.load();await assert.rejects(client.save('onboarding',{},()=>false));
 }
});
test('only current nonexcluded matching grades display',()=>{
 const row={criteria_version:2,grade:{difficulty:2,exclude:false}};
 assert.equal(issueMatches(row,2),true);assert.equal(issueMatches(row,1),false);
 assert.equal(issueMatches({...row,criteria_version:1},2),false);
 assert.equal(issueMatches({...row,error:'failed'},2),false);
});

test('로그아웃 뒤 늦은 저장 응답은 이전 계정을 복원하지 않는다',async()=>{
 let finish; const client=new SubscriptionClient(async(url,opts)=>{
   if(opts.method==='POST') {await new Promise(resolve=>finish=resolve);return ok({});}
   return ok({...session('10'),subscriptions:['o/r']});
 });
 client.session=session('10');
 let committed=false;
 const saving=client.save('subscriptions',{repo:'o/r'},()=>true,'POST',()=>{committed=true});
 client.invalidate(); finish();
 await assert.rejects(saving,/계정 요청이 변경/);
 assert.equal(client.session,null);
 assert.equal(committed,false,'로그아웃 후 도착한 응답으로 수집 표시를 복원하지 않는다');
});

test('구독 접수 상태는 느린 계정 재조회보다 먼저 전달한다',async()=>{
 let resolveReadback, commit;
 const client=new SubscriptionClient(async(url,options)=>options.method==='POST'
   ? ok({repo:'o/r',collection:{repo:'o/r',stage:'queued',attempt:0}})
   : new Promise(resolve=>{resolveReadback=resolve}));
 client.session=session('10');
 const saving=client.save('subscriptions',{repo:'o/r'},s=>s.subscriptions.includes('o/r'),'POST',value=>{commit=value});
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(commit.collection.stage,'queued','재조회가 끝나기 전에 접수된 수집을 표시할 수 있다');
 resolveReadback(ok({...session('10'),subscriptions:['o/r']}));
 await saving;
});

test('저장 거절은 수집을 시작하지 않고 재조회 실패는 이미 접수한 수집을 취소하지 않는다',async()=>{
 for(const failWrite of [true,false]) {
   let committed=false;
   const client=new SubscriptionClient(async(url,options)=>options.method==='POST'&&!failWrite
     ? ok({collection:{stage:'queued'}})
     : {ok:false,status:503,json:async()=>({error:'연결 오류'})});
   client.session=session('10');
   await assert.rejects(client.save('subscriptions',{repo:'o/r'},()=>true,'POST',()=>{committed=true}),/연결 오류/);
   assert.equal(committed,!failWrite);
 }
});
