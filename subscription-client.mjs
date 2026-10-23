/** 모든 쓰기는 읽은 계정에 귀속하고 서버 재조회로 완료를 확인한다. */
export class SubscriptionClient {
  constructor(fetcher) { this.fetch = fetcher; this.session = null; this.revision = 0; }
  async request(action, method = 'GET', body) {
    const response = await this.fetch('/api/account?action=' + action, {
      method, credentials: 'same-origin', cache: 'no-store',
      ...(body ? {headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : {})
    });
    const value = await response.json();
    if (!response.ok) { const error = new Error(value.error || '저장하지 못했습니다. 다시 시도하세요.'); error.status = response.status; throw error; }
    return value;
  }
  invalidate() { this.revision++; this.session = null; }
  async load() {
    const revision = this.revision;
    const value = await this.request('session');
    if (value.authenticated !== false && (!value.user?.id || !Array.isArray(value.subscriptions) || !value.preferences)) throw new Error('계정 응답을 확인하지 못했습니다.');
    if (revision !== this.revision) throw new Error('계정 요청이 변경됐습니다.');
    this.session = value;
    return value;
  }
  async save(action, body, verify, method = 'POST') {
    const revision = this.revision;
    const owner = this.session?.user?.id;
    if (!owner) throw new Error('GitHub 로그인이 필요합니다.');
    await this.request(action, method, {...body, expected_user_id: owner});
    const fresh = await this.request('session');
    if (revision !== this.revision) throw new Error('계정 요청이 변경됐습니다.');
    if (!fresh.authenticated || fresh.user?.id !== owner) { const error = new Error('계정이 바뀌었습니다. 새로고침 후 다시 시도하세요.'); error.status = 409; throw error; }
    if (!verify(fresh)) throw new Error('저장 결과를 확인하지 못했습니다. 입력을 유지하고 다시 시도하세요.');
    this.session = fresh;
    return fresh;
  }
}
export const issueMatches = (item, level) => item.criteria_version === 2 && !item.error && item.grade?.exclude === false && item.grade?.difficulty === level;
