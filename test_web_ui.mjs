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

const collectionSource = app.slice(app.indexOf('function collectionTime('), app.indexOf('function exploreList('));
const clock = Date.parse('2026-10-26T01:00:00Z');
const timeContext = vm.createContext({Intl, Date: class extends Date { static now() { return clock; } }});
vm.runInContext(collectionSource, timeContext);
const collectionTime = value => timeContext.collectionTime(value);
test('수집 시각은 한국 시간으로 표시하고 36시간 초과만 지연으로 알린다', () => {
  assert.equal(collectionTime('2026-10-26T00:00:00Z'), '10월 26일 09:00 수집');
  assert.match(collectionTime('2026-10-24T12:59:59Z'), /최근 수집이 지연되고 있습니다$/);
  assert.doesNotMatch(collectionTime('2026-10-24T13:00:00Z'), /지연/);
  for (const value of [null, undefined, '', 'invalid']) assert.equal(collectionTime(value), '수집 시각 미확인');
});

test('추천 이슈는 기존 조건과 검색·분야를 따르고 최신순과 빈 결과를 표시한다', () => {
  const item = (number, repo, created_at, extra = {}) => ({number, repo, created_at, title: `추천 ${number}`, grade: {difficulty: 1, exclude: false, readiness: 'ready', reason: '숨길 판정 이유'}, freshness: {eligible: true}, ...extra});
  const state = {items: [item(1, 'a/one', '2026-10-25'), item(2, 'b/two', '2026-10-26'), item(3, 'a/one', '2026-10-27', {freshness: {eligible: false}})], group: '', search: '', sort: 'recommended'};
  const list = [{name: 'a/one', description: 'alpha', topics: new Set(['dev-tools'])}, {name: 'b/two', description: 'beta', topics: new Set(['database'])}];
  const context = vm.createContext({state, listedRepos: () => [...list], matches: (r, q) => (r.name + r.description).includes(q), esc: v => String(v).replace(/</g, '&lt;'), collectionTime});
  const source = app.slice(app.indexOf('function exploreList('), app.indexOf('// 수집 전 저장소'));
  vm.runInContext(source, context);
  assert.deepEqual(Array.from(context.featuredIssues(), i => i.number), [2, 1]);
  assert.match(context.featuredMarkup(), /지금 손댈 만한 이슈 2건/);
  assert.doesNotMatch(context.featuredMarkup(), /숨길 판정 이유/);
  state.group = 'dev-tools';
  assert.deepEqual(Array.from(context.featuredIssues(), i => i.number), [1]);
  assert.match(context.featuredMarkup(), /이슈 1건/);
  state.group = ''; state.search = 'beta';
  assert.deepEqual(Array.from(context.featuredIssues(), i => i.number), [2]);
  state.search = 'missing';
  assert.match(context.featuredMarkup(), /이슈 0건/);
  assert.match(context.featuredMarkup(), /지금은 조건을 통과한 이슈가 없습니다/);
});

test('공유 미리보기는 정식 절대 주소와 1200x630 PNG를 사용한다', () => {
  for (const [property, content] of Object.entries({'og:type':'website', 'og:site_name':'RepoBite', 'og:url':'https://repobite.vercel.app/', 'og:title':'RepoBite | 초보자가 바로 손댈 수 있는 오픈소스 이슈', 'og:image':'https://repobite.vercel.app/og.png', 'og:image:width':'1200', 'og:image:height':'630'})) {
    assert(html.includes(`<meta property="${property}" content="${content}">`));
  }
  assert.match(html, /name="description" content="[^"]+"/);
  assert.match(html, /property="og:description" content="[^"]+"/);
  assert.match(html, /name="twitter:card" content="summary_large_image"/);
  const png = readFileSync(new URL('./og.png', import.meta.url));
  assert.equal(png.subarray(0,8).toString('hex'), '89504e470d0a1a0a');
  assert.equal(png.readUInt32BE(16), 1200); assert.equal(png.readUInt32BE(20), 630);
  assert(png.length <= 300 * 1024);
});

const measurementSource = app.slice(app.indexOf('function track('), app.indexOf('const go ='));
test('방문은 탭에서 한 번 전송하며 저장소와 네트워크 장애를 무시한다', async () => {
  const sent = [], values = new Map();
  const context = vm.createContext({fetch: (url, options) => {sent.push({url, options}); return Promise.reject(Error('offline'));}, sessionStorage: {getItem: k => values.get(k), setItem: (k,v) => values.set(k,v)}});
  vm.runInContext(measurementSource, context);
  context.trackVisit(); context.trackVisit();
  await Promise.resolve();
  assert.equal(sent.length, 1); assert.equal(sent[0].options.keepalive, true);
  assert.equal(sent[0].url, '/api/events');
  assert.equal(JSON.parse(sent[0].options.body).name, 'visit');
  context.sessionStorage = {getItem() {throw Error('denied');}};
  context.trackVisit(); await Promise.resolve();
  assert.equal(sent.length, 2);
  context.fetch = () => {throw Error('offline');};
  assert.doesNotThrow(() => context.track('issue_click'));
});
test('추천·상세 링크의 클릭과 페이지 로드에 집계가 연결된다', () => {
  assert.match(app, /data-track="featured_click"/);
  assert.match(app.slice(app.indexOf('function detailView(')), /data-track="issue_click"/);
  assert.match(app, /if \(link\) track\(link.dataset.track\)/);
  assert.match(app, /trackVisit\(\);\s*await initialize/);
});
test('의견은 중복 전송을 막고 실패 시 입력 유지, 성공 시 비우고 닫는다', async () => {
  const input = {value: '의견', readOnly: false}, button = {disabled: false}, status = {textContent: ''};
  const form = {querySelector: q => q === 'textarea' ? input : q === '[type="submit"]' ? button : status};
  let resolve, closed = 0, notified = 0, calls = 0;
  const context = vm.createContext({fetch: () => {calls++; return new Promise(r => {resolve = r;});}, feedbackBox: {close() {closed++;}}, notify() {notified++;}});
  vm.runInContext(measurementSource, context);
  const event = {preventDefault() {}, currentTarget: form};
  const pending = context.submitFeedback(event);
  assert.equal(button.disabled, true); assert.equal(input.readOnly, true);
  await context.submitFeedback(event); assert.equal(calls, 1);
  resolve({ok: false, json: async () => ({error: '잠시 후 다시 시도하세요.'})}); await pending;
  assert.equal(input.value, '의견'); assert.equal(status.textContent, '잠시 후 다시 시도하세요.');
  assert.equal(closed, 0); assert.equal(button.disabled, false); assert.equal(input.readOnly, false);
  context.fetch = async () => ({ok: true, json: async () => ({})});
  await context.submitFeedback(event);
  assert.equal(input.value, ''); assert.equal(closed, 1); assert.equal(notified, 1);
  input.value = '연결 실패'; context.fetch = async () => {throw Error('연결 실패 안내');};
  await context.submitFeedback(event);
  assert.equal(input.value, '연결 실패'); assert.equal(status.textContent, '연결 실패 안내');
});
