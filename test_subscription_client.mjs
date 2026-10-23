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
