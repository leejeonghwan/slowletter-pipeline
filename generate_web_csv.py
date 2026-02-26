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
import re
import json
import pandas as pd


def _normalize_date(value) -> str:
    if value is None:
        return ""
    s = str(value)
    return s[:10]  # "YYYY-MM-DD"만


def _load_entity_rules(repo_dir: str) -> dict:
    """entity_rules.json 로드 (없으면 빈 dict 반환)"""
    rules_path = os.path.join(repo_dir, "entity_rules.json")
    if not os.path.exists(rules_path):
        return {"person": {}, "org": {}}
    try:
        with open(rules_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[warn] entity_rules.json 로드 실패: {e}")
        return {"person": {}, "org": {}}


def _normalize_entities(value, entity_type: str, rules: dict) -> str:
    """엔티티 정규화: 세미콜론 구분 문자열을 규칙에 따라 변환"""
    if value is None or str(value).strip() == "":
        return ""
    
    entities = [e.strip() for e in str(value).split(";") if e.strip()]
    type_rules = rules.get(entity_type, {})
    
    # 정규화 적용
    normalized = []
    seen = set()
    for entity in entities:
        # 규칙에 매칭되면 변환
        canonical = type_rules.get(entity, entity)
        # 중복 제거 (대소문자 구분)
        if canonical not in seen:
            normalized.append(canonical)
            seen.add(canonical)
    
    return "; ".join(normalized)


def _normalize_content(value) -> str:
    if value is None:
        return ""
    s = str(value)

    # cleaned_content_for_service는 불렛/링크 포함 텍스트이며, 줄바꿈이 있을 수도/없을 수도 있습니다.
    # 웹 CSV는 <br> 기반으로 통일합니다.
    s = s.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not s:
        return ""

    # 1) 줄바꿈은 <br>로
    s = s.replace("\n", "<br> ")

    # 2) 줄 시작 불렛("<br>   •")은 먼저 정규화
    s = re.sub(r"<br>\s+•", "<br> •", s)

    # 3) 중간에 " ... • ..." 형태로 불렛이 붙어버린 케이스를 줄바꿈으로 교정
    #    단, 이미 줄 시작 불렛(<br> •)인 경우는 건드리지 않도록 보호 토큰 사용
    s = s.replace("<br> •", "%%BR_BULLET%%")
    s = s.replace(" • ", "<br> • ")
    s = s.replace("%%BR_BULLET%%", "<br> •")

    # 4) </a> 뒤에 공백이 사라지는 케이스 보정 ("</a>다음문장" → "</a> 다음문장")
    s = re.sub(r"</a>(?=[^\s<])", "</a> ", s)

    # 5) 연속 <br> 정리
    while "<br> <br>" in s:
        s = s.replace("<br> <br>", "<br> ")

    # 6) 정리 과정에서 다시 생길 수 있는 공백 재정규화
    s = re.sub(r"<br>\s+•", "<br> •", s)

    return s


def main():
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    in_path = os.path.join(repo_dir, "data", "raw", "slowletter_solar_entities.csv")
    out_path = os.path.join(repo_dir, "data", "raw", "slowletter_web.csv")

    if not os.path.exists(in_path):
        raise FileNotFoundError(f"입력 파일이 없습니다: {in_path}")

    # 엔티티 정규화 규칙 로드
    entity_rules = _load_entity_rules(repo_dir)
    print(f"Loaded entity rules: {len(entity_rules.get('person', {}))} person, {len(entity_rules.get('org', {}))} org")

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
        "persons": df["solar_persons"].apply(lambda x: _normalize_entities(x, "person", entity_rules)),
        "orgs": df["solar_organizations"].apply(lambda x: _normalize_entities(x, "org", entity_rules)),
    })

    out.to_csv(out_path, index=False)
    print(f"OK: wrote {len(out)} rows → {out_path}")


if __name__ == "__main__":
    main()
