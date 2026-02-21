"""
cleaned_content_for_service에 HTML 구조(불렛, 링크, 줄바꿈) 보존하기.

사용법:
  python update_service_content.py

- slowletter_data_archives.csv 의 h3_content (HTML 보존)를
  slowletter_solar_entities.csv 의 cleaned_content_for_service에 반영.
- cleaned_content_for_api는 그대로 (평문 유지).
- 엔티티 재추출 불필요.
"""

import pandas as pd
import re
import os

# --- 경로 설정 (환경에 맞게 수정) ---
ARCHIVE_CSV = os.path.expanduser("~/slowletter-pipeline/data/slowletter_data_archives.csv")
ENTITIES_CSV = os.path.expanduser("~/Downloads/work/data/raw/slowletter_solar_entities.csv")
OUTPUT_CSV = ENTITIES_CSV  # 덮어쓰기 (백업 자동 생성)


def clean_html_for_service(h3_content: str) -> str:
    """
    h3_content에서 <li>, <a href>, 줄바꿈만 보존.
    bold, color, span 등은 제거하고 텍스트만 남김.
    """
    if not h3_content or pd.isna(h3_content):
        return ""

    text = str(h3_content)

    # <a href="...">텍스트</a> 보존
    # 나머지 태그 중 <li>, </li>만 보존

    # 1) <li>...</li> 각각을 "• 내용\n" 형태로 변환
    #    li 안의 a 태그는 보존
    def process_li(match):
        inner = match.group(1)
        # a 태그 보존, 나머지 태그 제거
        inner = re.sub(r'<(?!/?a\b)[^>]+>', '', inner)
        inner = inner.strip()
        return f"• {inner}\n"

    text = re.sub(r'<li>(.*?)</li>', process_li, text, flags=re.DOTALL)

    # 2) 남은 태그 중 a 태그 외 모두 제거
    text = re.sub(r'<(?!/?a\b)[^>]+>', '', text)

    # 3) 연속 공백 정리
    text = re.sub(r'[ \t]+', ' ', text)

    # 4) 연속 줄바꿈 정리
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def main():
    print(f"📂 아카이브 CSV: {ARCHIVE_CSV}")
    print(f"📂 엔티티 CSV: {ENTITIES_CSV}")

    # 파일 존재 확인
    if not os.path.exists(ARCHIVE_CSV):
        print(f"❌ 아카이브 파일이 없습니다: {ARCHIVE_CSV}")
        return
    if not os.path.exists(ENTITIES_CSV):
        print(f"❌ 엔티티 파일이 없습니다: {ENTITIES_CSV}")
        return

    # 로드
    print("📖 아카이브 CSV 로딩...")
    archive_df = pd.read_csv(ARCHIVE_CSV, encoding="utf-8-sig")
    print(f"   → {len(archive_df)}건")

    print("📖 엔티티 CSV 로딩...")
    entities_df = pd.read_csv(ENTITIES_CSV)
    print(f"   → {len(entities_df)}건")

    # ID 기준 h3_content 매핑
    if "ID" not in archive_df.columns or "h3_content" not in archive_df.columns:
        print("❌ 아카이브에 ID 또는 h3_content 컬럼이 없습니다.")
        return

    h3_map = dict(zip(archive_df["ID"], archive_df["h3_content"]))
    print(f"🔗 ID 매핑: {len(h3_map)}건")

    # 매칭 확인
    matched = entities_df["ID"].isin(h3_map).sum()
    print(f"✅ 매칭: {matched}/{len(entities_df)}건")

    # cleaned_content_for_service 업데이트
    print("🔄 cleaned_content_for_service 업데이트 중...")
    entities_df["cleaned_content_for_service"] = entities_df["ID"].map(
        lambda x: clean_html_for_service(h3_map.get(x, ""))
    )

    # 빈 값 처리: 매핑 안 된 건 원래 값 유지
    original = pd.read_csv(ENTITIES_CSV)
    mask = entities_df["cleaned_content_for_service"] == ""
    entities_df.loc[mask, "cleaned_content_for_service"] = original.loc[mask, "cleaned_content_for_service"]

    # 백업 생성
    backup_path = ENTITIES_CSV + ".bak"
    os.rename(ENTITIES_CSV, backup_path)
    print(f"💾 백업: {backup_path}")

    # 저장
    entities_df.to_csv(OUTPUT_CSV, index=False)
    print(f"💾 저장: {OUTPUT_CSV}")

    # 샘플 확인
    print("\n--- 샘플 (최신 3건) ---")
    sample = entities_df.head(3)
    for _, row in sample.iterrows():
        print(f"\n[{row['ID']}] {row['title']}")
        content = row['cleaned_content_for_service']
        print(content[:300] if len(str(content)) > 300 else content)
        print("---")

    print("\n✅ 완료!")


if __name__ == "__main__":
    main()
