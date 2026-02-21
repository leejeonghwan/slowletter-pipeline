#!/usr/bin/env python3
"""generate_web_csv.py

웹(Finder/GitHub Pages)에서 바로 읽을 수 있는 CSV를 생성합니다.

입력:
  data/raw/slowletter_solar_entities.csv
출력:
  data/raw/slowletter_web.csv

컬럼 스키마(출력):
  - id: ID (예: 2023_04_10_01)
  - date: YYYY-MM-DD
  - title: 섹션 제목(h3)
  - content: cleaned_content_for_service (줄바꿈 → <br>)
  - persons: solar_persons (세미콜론 구분 문자열)
  - orgs: solar_organizations (세미콜론 구분 문자열)

주의:
- 이 스크립트는 엔티티 재추출을 하지 않습니다.
- HTML 링크(<a href=...>)는 그대로 유지합니다.
"""

from __future__ import annotations

import os
import pandas as pd


def _normalize_date(value) -> str:
    if value is None:
        return ""
    s = str(value)
    return s[:10]  # "YYYY-MM-DD"만


def _normalize_content(value) -> str:
    if value is None:
        return ""
    s = str(value)
    # cleaned_content_for_service는 기본적으로 줄바꿈 기반("• ...\n")
    # 웹 CSV는 <br> 기반으로 맞춰둔다.
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.strip()
    if not s:
        return ""
    return "<br> ".join([line.strip() for line in s.split("\n") if line.strip()])


def main():
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    in_path = os.path.join(repo_dir, "data", "raw", "slowletter_solar_entities.csv")
    out_path = os.path.join(repo_dir, "data", "raw", "slowletter_web.csv")

    if not os.path.exists(in_path):
        raise FileNotFoundError(f"입력 파일이 없습니다: {in_path}")

    df = pd.read_csv(in_path)

    required = ["ID", "date", "title", "cleaned_content_for_service", "solar_persons", "solar_organizations"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"입력 CSV에 필요한 컬럼이 없습니다: {missing}")

    out = pd.DataFrame({
        "id": df["ID"].astype(str),
        "date": df["date"].map(_normalize_date),
        "title": df["title"].astype(str),
        "content": df["cleaned_content_for_service"].map(_normalize_content),
        "persons": df["solar_persons"],
        "orgs": df["solar_organizations"],
    })

    out.to_csv(out_path, index=False)
    print(f"OK: wrote {len(out)} rows → {out_path}")


if __name__ == "__main__":
    main()
