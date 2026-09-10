"""추천 직전 GitHub 최신 상태 확인.

근거: https://docs.github.com/en/graphql/reference/issues
"""

from datetime import datetime, timezone
import json
import subprocess


BATCH_SIZE = 25


def is_candidate(row):
    grade = row.get("grade")
    return (isinstance(grade, dict) and not row.get("error")
            and grade.get("exclude") is False
            and grade.get("difficulty") == 1
            and grade.get("readiness") == "ready")


def _query(rows):
    variables = []
    fields = []
    options = []
    for index, row in enumerate(rows):
        owner, separator, name = row.get("repo", "").partition("/")
        number = row.get("number")
        if not separator or not owner or not name or "/" in name or type(number) is not int:
            raise ValueError("이슈 repo/number 형식이 잘못되었습니다")
        variables.extend((f"$owner{index}:String!", f"$name{index}:String!",
                          f"$number{index}:Int!"))
        fields.append(
            f"i{index}:repository(owner:$owner{index},name:$name{index}){{"
            f"issue(number:$number{index}){{state assignees(first:1){{totalCount}} "
            "closedByPullRequestsReferences(first:1,includeClosedPrs:false){totalCount}}}"
        )
        options.extend(("-F", f"owner{index}={owner}", "-F", f"name{index}={name}",
                        "-F", f"number{index}={number}"))
    return f"query({','.join(variables)}){{{''.join(fields)}}}", options


def _result(eligible, reason, checked_at):
    return {"eligible": eligible, "reason": reason, "checked_at": checked_at}


def _evaluate(issue, checked_at):
    if not isinstance(issue, dict):
        return _result(False, "이슈 조회 실패", checked_at)
    if issue.get("state") != "OPEN":
        return _result(False, "이슈 닫힘", checked_at)
    if (issue.get("assignees") or {}).get("totalCount", 0):
        return _result(False, "담당자 있음", checked_at)
    if (issue.get("closedByPullRequestsReferences") or {}).get("totalCount", 0):
        return _result(False, "연결된 열린 PR 있음", checked_at)
    return _result(True, "확인 완료", checked_at)


def apply_freshness(rows, run=subprocess.run, checked_at=None):
    """추천 후보 행에 freshness를 추가한다. 호출부는 출력 직전에 실행해야 한다."""
    checked_at = checked_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z")
    output = [dict(row) for row in rows]
    candidates = [(index, row) for index, row in enumerate(output) if is_candidate(row)]
    for start in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[start:start + BATCH_SIZE]
        try:
            query, options = _query([row for _, row in batch])
            response = run(["gh", "api", "graphql", "--hostname", "github.com",
                            "-f", f"query={query}", *options], capture_output=True,
                           text=True, timeout=180)
            if response.returncode:
                raise RuntimeError("gh api 실패")
            payload = json.loads(response.stdout)
            if payload.get("errors") or not isinstance(payload.get("data"), dict):
                raise ValueError("GraphQL 응답 오류")
            for alias, (index, _) in enumerate(batch):
                repository = payload["data"].get(f"i{alias}")
                issue = repository.get("issue") if isinstance(repository, dict) else None
                output[index]["freshness"] = _evaluate(issue, checked_at)
        except (OSError, subprocess.SubprocessError, ValueError, RuntimeError,
                TypeError, AttributeError, KeyError):
            for index, _ in batch:
                output[index]["freshness"] = _result(False, "최신 상태 확인 실패", checked_at)
    return output
