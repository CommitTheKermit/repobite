"""운영자용 일별 반응·최근 익명 의견 보고. 환경변수로만 DB에 접속한다."""

import argparse
import re
import unicodedata

import metrics


def terminal_text(value):
    # ANSI CSI·OSC 이스케이프 시퀀스와 나머지 제어 문자를 제거한다.
    text = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]", "", str(value))
    return "".join(char for char in text if char == "\n" or not unicodedata.category(char).startswith("C"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=14, choices=range(1, 91), metavar="1-90")
    args = parser.parse_args(argv)
    try:
        rows = metrics.event_counts(args.days)
        feedback = metrics.recent_feedback(20)
    except (OSError, RuntimeError, ValueError, TypeError, KeyError):
        parser.exit(1, "반응 집계를 불러오지 못했습니다. DB 환경변수와 연결을 확인하세요.\n")
    print("| 날짜 (UTC) | visit | featured_click | issue_click | feedback |")
    print("| --- | ---: | ---: | ---: | ---: |")
    for row in rows:
        print("| " + " | ".join(str(row[key]) for key in ("date", *metrics.EVENTS, "feedback")) + " |")
    print("\n## 최근 의견 20건\n")
    for row in feedback:
        print(terminal_text(row["created_at"]) + "\n\n" + terminal_text(row["text"]) + "\n")


if __name__ == "__main__":
    main()
