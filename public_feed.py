"""로컬 웹과 공용 배치가 함께 사용하는 공개 이슈 변환."""

import radar
from repository_categories import catalog_metadata


def public_items(issues, rows, repositories=None):
    repositories = repositories or {}
    grades = {radar.issue_key(row): row for row in rows}
    items = []
    for issue in issues:
        row = grades.get(radar.issue_key(issue), {})
        if any(row.get(key) != issue.get(key) for key in ("title", "body")):
            row = {}
        metadata = repositories.get(issue["repo"].lower()) or catalog_metadata(issue["repo"])
        items.append({"repo": issue["repo"], "number": issue["number"],
                      "title": issue["title"], "url": issue["url"],
                      "created_at": issue["created_at"], "user": issue.get("user", ""),
                      "description": metadata["description"],
                      "repository_image": issue.get("repository_image", ""),
                      "categories": list(metadata["categories"]), "grade": row.get("grade"),
                      "error": row.get("error"), "model": row.get("model"),
                      "freshness": row.get("freshness"),
                      "criteria_version": row.get("criteria_version")})
    return items

