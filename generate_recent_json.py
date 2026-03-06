#!/usr/bin/env python3
"""generate_recent_json.py

슬로우레터 빠른 검색 페이지의 즉시 렌더링용 recent.json 생성.

입력: data/raw/slowletter_web.csv
출력: data/context/recent.json

최신 30건의 데이터를 JSON으로 추출하여, 메인 페이지 진입 시
풀 CSV 로딩 전에 즉시 화면을 보여줄 수 있게 한다.
"""

import csv
import json
import os


def main():
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    in_path = os.path.join(repo_dir, "data", "raw", "slowletter_web.csv")
    out_dir = os.path.join(repo_dir, "data", "context")
    out_path = os.path.join(out_dir, "recent.json")

    os.makedirs(out_dir, exist_ok=True)

    with open(in_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # 날짜 역순 정렬 → 최신 30건
    rows.sort(key=lambda r: r.get("date", ""), reverse=True)
    recent = rows[:30]

    # 필요한 컬럼만 추출 (풀 CSV와 동일 스키마)
    output = []
    for r in recent:
        output.append({
            "id": r.get("id", ""),
            "date": r.get("date", ""),
            "title": r.get("title", ""),
            "content": r.get("content", ""),
            "persons": r.get("persons", ""),
            "orgs": r.get("orgs", ""),
        })

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False)

    size_kb = os.path.getsize(out_path) / 1024
    print(f"OK: {len(output)}건 → {out_path} ({size_kb:.1f}KB)")


if __name__ == "__main__":
    main()
