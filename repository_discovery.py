"""GitHub Trending 또는 자체 관측과 누적 별 수로 저장소 후보를 제안한다.

--source와 양의 짝수 --limit를 명시한다. github-trending은 --period를,
own-history는 --tolerance-hours를 요구한다. 기존 수집 목록은 변경하지 않는다.
API 근거: https://docs.github.com/en/rest/search/search#search-repositories
https://docs.github.com/en/rest/repos/repos#get-a-repository
"""

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import radar

LOOKBACK = timedelta(days=7)
DEFAULT_QUERY = "stars:>=0 is:public archived:false"
REPO_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+")


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("관측 시각은 시간대를 포함한 문자열이어야 합니다")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("관측 시각 형식이 잘못되었습니다") from None
    if stamp.tzinfo is None:
        raise ValueError("관측 시각에 시간대가 필요합니다")
    return stamp.astimezone(timezone.utc)


def repo_name(value):
    if (not isinstance(value, str) or not REPO_PATTERN.fullmatch(value)
            or any(part in (".", "..") for part in value.split("/"))):
        raise ValueError("저장소 이름은 owner/repo 형식이어야 합니다")
    return value


def positive_even(value):
    if type(value) is not int:
        raise ValueError("총 제안 수는 양의 짝수여야 합니다")
    number = value
    if number <= 0 or number % 2:
        raise ValueError("총 제안 수는 양의 짝수여야 합니다")
    return number


def validate_observation(row):
    if not isinstance(row, dict):
        raise ValueError("관측은 객체여야 합니다")
    repo_name(row.get("repo"))
    if type(row.get("id")) is not int or row["id"] <= 0:
        raise ValueError("GitHub 저장소 ID가 필요합니다")
    if type(row.get("stars")) is not int or row["stars"] < 0:
        raise ValueError("별 수는 0 이상의 정수여야 합니다")
    timestamp(row.get("observed_at"))
    if row.get("source") != "https://api.github.com/repos/" + row["repo"]:
        raise ValueError("관측 원본 API 주소가 잘못되었습니다")
    return row


def read_history(path):
    path = Path(path)
    if not path.exists():
        return []
    content = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(content, dict) or content.get("version") != 1
            or not isinstance(content.get("observations"), list)):
        raise ValueError("별 관측 기록 형식이 잘못되었습니다")
    return [validate_observation(row) for row in content["observations"]]


def observation(info, observed_at):
    """공개·활성 저장소만 기록한다. 누락된 상태를 허용 상태로 추정하지 않는다."""
    if not isinstance(info, dict):
        raise ValueError("GitHub 저장소 응답이 객체가 아닙니다")
    for field in ("private", "archived", "disabled", "has_issues"):
        if type(info.get(field)) is not bool:
            raise ValueError("GitHub 저장소 상태가 누락되었습니다")
    for field in ("private", "archived", "disabled"):
        if info[field]:
            return None, field
    if not info["has_issues"]:
        return None, "issues_disabled"
    name = repo_name(info.get("full_name"))
    row = {"id": info.get("id"), "repo": name, "stars": info.get("stargazers_count"),
           "observed_at": observed_at, "source": "https://api.github.com/repos/" + name}
    return validate_observation(row), None


def collect_observations(history, query, search_limit, gh=None, clock=None):
    """검색 후보와 이전 관측 저장소를 현재 API로 재확인한다. API 오류는 전파한다."""
    gh = gh or radar.gh_json
    clock = clock or (lambda: datetime.now(timezone.utc))
    if type(search_limit) is not int or not 1 <= search_limit <= 1000:
        raise ValueError("검색 상한은 1부터 1000까지입니다")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("검색 쿼리가 필요합니다")
    names, urls, found = {}, [], 0
    total_count = 0
    page = 1
    size = min(100, search_limit)
    while found < search_limit:
        endpoint = "search/repositories?" + urlencode(
            {"q": query, "sort": "stars", "order": "desc", "per_page": size, "page": page})
        response = gh(endpoint)
        if (not isinstance(response, dict) or response.get("incomplete_results") is not False
                or not isinstance(response.get("items"), list)
                or type(response.get("total_count")) is not int or response["total_count"] < 0
                or len(response["items"]) > size):
            raise ValueError("GitHub 검색 결과가 불완전하거나 형식이 잘못되었습니다")
        total_count = response["total_count"]
        urls.append("https://api.github.com/" + endpoint)
        selected = response["items"][:search_limit - found]
        for info in selected:
            if not isinstance(info, dict):
                raise ValueError("GitHub 검색 항목이 객체가 아닙니다")
            name = repo_name(info.get("full_name"))
            names[name.lower()] = name
        count = len(response["items"])
        found += len(selected)
        if count < size or found >= total_count:
            break
        page += 1
    # 이름이 바뀐 저장소는 동일한 GitHub ID로 비교한다. 재조회 오류를 0개 결과로 숨기지 않는다.
    latest = {}
    for row in history:
        validate_observation(row)
        if row["id"] not in latest or timestamp(row["observed_at"]) > timestamp(latest[row["id"]]["observed_at"]):
            latest[row["id"]] = row
    for row in latest.values():
        names.setdefault(row["repo"].lower(), row["repo"])
    observations, excluded, seen = [], Counter(), set()
    for name in names.values():
        info = gh("repos/" + name)
        row, reason = observation(info, clock().astimezone(timezone.utc).isoformat(timespec="seconds"))
        if reason:
            excluded[reason] += 1
        elif row["id"] not in seen:
            seen.add(row["id"])
            observations.append(row)
    source = {"query": query, "sort": "stars", "search_limit": search_limit,
              "search_total_count": total_count, "search_rows_read": found,
              "search_truncated": total_count > found, "search_urls": urls,
              "prior_repository_count": len(latest), "excluded": dict(excluded)}
    return observations, source


def select_proposals(current, history, limit, *, lookback, tolerance):
    """명시된 기간·오차에서 비교 가능한 동일 ID의 별 순증가를 계산한다."""
    if type(limit) is not int or positive_even(limit) != limit:
        raise ValueError("총 제안 수는 양의 짝수여야 합니다")
    if lookback <= timedelta(0) or not timedelta(0) <= tolerance < lookback:
        raise ValueError("관측 오차는 0 이상이며 비교 기간보다 짧아야 합니다")
    previous = {}
    for row in history:
        validate_observation(row)
        previous.setdefault(row["id"], []).append(row)
    by_id, compared, unavailable = {}, [], []
    for row in current:
        validate_observation(row)
        if row["id"] in by_id:
            raise ValueError("현재 관측에 중복 저장소 ID가 있습니다")
        by_id[row["id"]] = row
        end = timestamp(row["observed_at"])
        eligible = [old for old in previous.get(row["id"], [])
                    if abs((end - timestamp(old["observed_at"])) - lookback) <= tolerance]
        if not eligible:
            unavailable.append({"repo": row["repo"], "id": row["id"], "status": "unmeasured",
                                "reason": "no_comparable_observation"})
            continue
        baseline = min(eligible, key=lambda old: (
            abs((end - timestamp(old["observed_at"])) - lookback), old["observed_at"]))
        compared.append({**row, "net_star_delta": row["stars"] - baseline["stars"],
                         "baseline": baseline,
                         "period_seconds": int((end - timestamp(baseline["observed_at"])).total_seconds())})
    quota = limit // 2
    rising = sorted((row for row in compared if row["net_star_delta"] > 0),
                    key=lambda row: (-row["net_star_delta"], -row["stars"], row["repo"].lower()))
    trend = [{**row, "selection_basis": "own_history_net_star_delta"} for row in rising[:quota]]
    used = {row["id"] for row in trend}
    famous = [{**row, "selection_basis": "cumulative_stars"}
              for row in sorted(current, key=lambda row: (-row["stars"], row["repo"].lower()))
              if row["id"] not in used][:quota]
    return {"method": "own_history_net_star_delta", "requested_total": limit,
            "selection_order": ["trend", "famous"],
            "scope": "현재 검색 후보와 이전 관측 저장소 안에서의 순위이며 GitHub Trending이 아님",
            "quota": {"trend": quota, "famous": quota},
            "measurement": {"lookback_seconds": int(lookback.total_seconds()),
                            "tolerance_seconds": int(tolerance.total_seconds()),
                            "comparable_count": len(compared), "unmeasured_count": len(unavailable),
                            "unmeasured": unavailable},
            "trend": {"status": "unmeasured" if not compared else "complete" if len(trend) == quota else "insufficient",
                      "items": trend, "shortfall": quota - len(trend)},
            "famous": {"status": "complete" if len(famous) == quota else "insufficient",
                       "items": famous, "shortfall": quota - len(famous)}}


def run(*, limit, tolerance_hours, history_path, output_path, query=DEFAULT_QUERY,
        search_limit=100, gh=None, clock=None):
    limit = positive_even(limit)
    tolerance = timedelta(hours=tolerance_hours)
    if not timedelta(0) <= tolerance < LOOKBACK:
        raise ValueError("--tolerance-hours는 0 이상 168 미만이어야 합니다")
    history_path, output_path = Path(history_path), Path(output_path)
    if history_path.resolve() == output_path.resolve():
        raise ValueError("별 관측 기록과 후보 출력은 다른 파일이어야 합니다")
    protected = {radar.ROOT / "repos.txt", radar.ROOT / "data.json", radar.ROOT / "categories.json"}
    if any(path.resolve() in protected for path in (history_path, output_path)):
        raise ValueError("기존 수집 목록과 공개 데이터는 덮어쓸 수 없습니다")
    history = read_history(history_path)
    current, source = collect_observations(history, query, search_limit, gh=gh, clock=clock)
    result = select_proposals(current, history, limit, lookback=LOOKBACK, tolerance=tolerance)
    result["generated_at"] = (clock or (lambda: datetime.now(timezone.utc)))().astimezone(timezone.utc).isoformat(timespec="seconds")
    result["source"] = source
    # 모든 API 조회와 계산이 성공한 뒤에만 교체한다. 각 파일은 임시 파일로 원자 저장한다.
    with radar.atomic_output(history_path) as stream:
        json.dump({"version": 1, "observations": history + current}, stream, ensure_ascii=False)
        stream.write("\n")
    with radar.atomic_output(output_path) as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return result



PERIOD_LABELS = {"daily": "today", "weekly": "this week", "monthly": "this month"}


class TrendingParser(HTMLParser):
    """Trending 결과 article의 저장소 제목과 선택한 기간의 별 수만 읽는다."""

    def __init__(self, period):
        super().__init__(convert_charrefs=True)
        self.period = period
        self.rows = []
        self.article = None
        self.heading = False
        self.h1 = False
        self.h1_text = []
        self.closed_html = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "article":
            if self.article is not None or "Box-row" not in attributes.get("class", "").split():
                raise ValueError("Trending 결과 구조가 변경되었습니다")
            self.article = {"links": [], "heading": [], "text": []}
        if tag == "h1":
            self.h1 = True
        if self.article is not None:
            if tag == "h2":
                self.heading = True
            if tag == "a" and self.heading:
                href = attributes.get("href", "")
                if not href.startswith("/"):
                    raise ValueError("Trending 저장소 링크가 변경되었습니다")
                self.article["links"].append(repo_name(href[1:]))

    def handle_data(self, content):
        if self.h1:
            self.h1_text.append(content)
        if self.article is not None:
            self.article["text"].append(content)
            if self.heading:
                self.article["heading"].append(content)

    def handle_endtag(self, tag):
        if tag == "h1":
            self.h1 = False
        if tag == "h2":
            self.heading = False
        if tag == "html":
            self.closed_html = True
        if tag == "article":
            if self.article is None or len(self.article["links"]) != 1:
                raise ValueError("Trending 결과 저장소 제목을 확인할 수 없습니다")
            name = self.article["links"][0]
            if "".join("".join(self.article["heading"]).split()) != name:
                raise ValueError("Trending 제목과 저장소 주소가 다릅니다")
            text = " ".join(" ".join(self.article["text"]).split())
            matches = re.findall(r"(?<![0-9,])([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?![0-9,]) stars? " + PERIOD_LABELS[self.period] + r"\b", text)
            if len(matches) != 1:
                raise ValueError("Trending 기간별 별 수를 확인할 수 없습니다")
            if any(row["repo"].lower() == name.lower() for row in self.rows):
                raise ValueError("Trending 결과가 중복되었습니다")
            self.rows.append({"repo": name, "rank": len(self.rows) + 1,
                              "period_stars": int(matches[0].replace(",", ""))})
            self.article = None


def parse_trending(html, period):
    if period not in PERIOD_LABELS:
        raise ValueError("Trending 기간은 daily, weekly, monthly 중 하나여야 합니다")
    parser = TrendingParser(period)
    parser.feed(html)
    parser.close()
    if (not parser.closed_html or parser.article is not None or not parser.rows
            or " ".join("".join(parser.h1_text).split()) != "Trending"):
        raise ValueError("Trending HTML이 불완전하거나 구조가 변경되었습니다")
    return parser.rows


def fetch_trending(period, *, clock=None, open_url=None):
    if period not in PERIOD_LABELS:
        raise ValueError("Trending 기간을 명시하세요")
    url = "https://github.com/trending?" + urlencode({"since": period})
    request = Request(url, headers={"User-Agent": "RepoBite/1.0", "Accept": "text/html"})
    with (open_url or urlopen)(request, timeout=30) as response:
        if response.status != 200 or response.url != url:
            raise ValueError("Trending 응답 상태 또는 주소가 다릅니다")
        if response.headers.get_content_type() != "text/html":
            raise ValueError("Trending 응답이 HTML이 아닙니다")
        raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError("Trending 응답 크기가 제한을 넘었습니다")
        length = response.headers.get("Content-Length")
        if length is not None and int(length) != len(raw):
            raise ValueError("Trending 응답이 일부만 도착했습니다")
    rows = parse_trending(raw.decode("utf-8"), period)
    observed = (clock or (lambda: datetime.now(timezone.utc)))().astimezone(timezone.utc).isoformat(timespec="seconds")
    return rows, {"url": url, "period": period, "fetched_at": observed,
                  "rows": len(rows), "sha256": sha256(raw).hexdigest(), "bytes": len(raw)}


def famous_search(threshold, gh):
    """별 수 하한 이상의 검색 결과 전체를 완전성 검사 후 반환한다."""
    query = f"stars:>={threshold} is:public archived:false fork:true"
    records, urls, seen, total = [], [], set(), None
    for page in range(1, 11):
        endpoint = "search/repositories?" + urlencode(
            {"q": query, "sort": "stars", "order": "desc", "per_page": 100, "page": page})
        response = gh(endpoint)
        if (not isinstance(response, dict) or response.get("incomplete_results") is not False
                or type(response.get("total_count")) is not int or response["total_count"] < 0
                or not isinstance(response.get("items"), list) or len(response["items"]) > 100):
            raise ValueError("유명 저장소 검색이 불완전합니다")
        count = response["total_count"]
        if count > 1000:
            raise ValueError("유명 저장소 별 수 구간을 1000건 이하로 좁혀야 합니다")
        if total is not None and count != total:
            raise ValueError("유명 저장소 검색 건수가 페이지 사이에 변경되었습니다")
        total = count
        urls.append("https://api.github.com/" + endpoint)
        for row in response["items"]:
            if (not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] <= 0
                    or type(row.get("stargazers_count")) is not int or row["stargazers_count"] < threshold):
                raise ValueError("유명 저장소 검색 근거가 잘못되었습니다")
            repo_name(row.get("full_name"))
            if row["id"] in seen or (records and row["stargazers_count"] > records[-1]["stargazers_count"]):
                raise ValueError("유명 저장소 검색 중복 또는 정렬 변경을 감지했습니다")
            seen.add(row["id"])
            records.append(row)
        if len(records) == total:
            return records, {"query": query, "threshold": threshold, "total_count": total,
                             "returned_count": len(records), "incomplete_results": False, "urls": urls}
        if len(records) > total or len(response["items"]) < 100:
            raise ValueError("유명 저장소 검색의 일부 결과가 누락되었습니다")
    raise ValueError("유명 저장소 검색을 완전히 읽지 못했습니다")


def run_github_trending(*, limit, period, output_path, gh=None, clock=None, open_url=None):
    """Trending 순서 우선, 중복을 뺀 유명 저장소 순서로 정확히 절반씩 제안한다."""
    limit = positive_even(limit)
    gh = gh or radar.gh_json
    clock = clock or (lambda: datetime.now(timezone.utc))
    output_path = Path(output_path)
    if output_path.resolve() in {radar.ROOT / "repos.txt", radar.ROOT / "data.json", radar.ROOT / "categories.json"}:
        raise ValueError("기존 수집 목록과 공개 데이터는 덮어쓸 수 없습니다")
    quota = limit // 2
    ranked, trending_source = fetch_trending(period, clock=clock, open_url=open_url)
    cache, excluded = {}, Counter()

    def current(name):
        key = name.lower()
        if key not in cache:
            row, reason = observation(gh("repos/" + name), clock().astimezone(timezone.utc).isoformat(timespec="seconds"))
            cache[key] = row, reason
        return cache[key]

    trend, used = [], set()
    for record in ranked:
        row, reason = current(record["repo"])
        if reason:
            excluded[reason] += 1
            continue
        if row["id"] in used:
            raise ValueError("Trending 순위의 저장소 ID가 중복되었습니다")
        used.add(row["id"])
        trend.append({**row, "selection_basis": "github_trending", "rank": record["rank"],
                      "period_stars": record["period_stars"], "ranking_source": trending_source["url"],
                      "ranking_observed_at": trending_source["fetched_at"], "period": period})
        if len(trend) == quota:
            break
    if len(trend) != quota:
        raise ValueError(f"적격 Trending 저장소가 부족합니다 ({len(trend)}/{quota}개, 제외 {dict(excluded)}). 이전 후보 출력을 보존합니다")
    threshold, searches = 100000, []
    while True:
        candidates, evidence = famous_search(threshold, gh)
        searches.append(evidence)
        # 검색 하한 이상의 전체 후보를 개별 API로 검증한다. 조회 실패는 부분 성공으로 숨기지 않는다.
        with ThreadPoolExecutor(max_workers=8) as pool:
            checked = list(pool.map(lambda candidate: current(candidate["full_name"]), candidates))
        eligible = {}
        for candidate, (row, reason) in zip(candidates, checked):
            if row is not None and row["id"] != candidate["id"]:
                raise ValueError("유명 저장소 검색과 현재 저장소 ID가 다릅니다")
            if reason:
                excluded[reason] += 1
            elif row["id"] not in used:
                eligible[row["id"]] = row
        selected = sorted(eligible.values(), key=lambda row: (-row["stars"], row["repo"].lower()))[:quota]
        # 검색 하한보다 높은 최종 경계를 확보한 경우만 하한 아래의 검색을 생략한다.
        if len(selected) == quota and selected[-1]["stars"] >= threshold:
            famous = [{**row, "selection_basis": "cumulative_stars", "rank": rank,
                       "ranking_source": evidence["urls"], "search_threshold": threshold}
                      for rank, row in enumerate(selected, 1)]
            break
        if threshold == 0:
            raise ValueError("적격 유명 저장소가 부족합니다. 이전 후보 출력을 보존합니다")
        threshold //= 2
    result = {"version": 1, "method": "github_trending_and_cumulative_stars", "requested_total": limit,
              "generated_at": clock().astimezone(timezone.utc).isoformat(timespec="seconds"),
              "selection_order": ["trend", "famous"], "quota": {"trend": quota, "famous": quota},
              "trend": {"status": "complete", "items": trend, "shortfall": 0},
              "famous": {"status": "complete", "items": famous, "shortfall": 0},
              "repos": [row["repo"] for row in trend + famous],
              "source": {"trending": trending_source, "famous_searches": searches,
                         "excluded": dict(excluded),
                         "rank_scope": "공개·미보관·활성·이슈 허용 저장소, Trending 우선 중복 제외",
                         "consistency": "검색 인덱스 전체 결과와 개별 API 관측을 사용하며 원자적 글로벌 스냅샷은 아님"}}
    with radar.atomic_output(output_path) as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return result

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, required=True, help="총 제안 수, 양의 짝수")
    parser.add_argument("--source", choices=("github-trending", "own-history"), required=True)
    parser.add_argument("--period", choices=tuple(PERIOD_LABELS), help="GitHub Trending 조회 기간, github-trending에서 필수")
    parser.add_argument("--tolerance-hours", type=float, help="7일 전 관측과 허용할 시간 오차, 0 이상 168 미만")
    parser.add_argument("--query", default=DEFAULT_QUERY, help="관측할 공개 저장소 검색 쿼리")
    parser.add_argument("--search-limit", type=int, default=100, help="검색 후보 상한, 1부터 1000")
    parser.add_argument("--history", type=Path, default=Path(".repository-stars.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("repository-discovery.jsonl"))
    args = parser.parse_args(argv)
    if args.source == "github-trending" and args.period is None:
        parser.error("github-trending에는 --period가 필요합니다")
    if args.source == "own-history" and args.tolerance_hours is None:
        parser.error("own-history에는 --tolerance-hours가 필요합니다")
    try:
        if args.source == "github-trending":
            result = run_github_trending(limit=args.limit, period=args.period, output_path=args.output)
        else:
            result = run(limit=args.limit, tolerance_hours=args.tolerance_hours,
                         history_path=args.history, output_path=args.output,
                         query=args.query, search_limit=args.search_limit)
    except (OSError, ValueError, TypeError, RuntimeError, KeyError, OverflowError, subprocess.TimeoutExpired):
        print("저장소 발굴 실패: 원천 응답·후보 부족·입력·GitHub 상태를 확인하세요. 이전 후보 출력을 보존합니다.", file=sys.stderr)
        return 1
    print(f"저장소 후보: 트렌드 {len(result['trend']['items'])}개 "
          f"(부족 {result['trend']['shortfall']}개), 유명 {len(result['famous']['items'])}개 "
          f"(부족 {result['famous']['shortfall']}개)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
