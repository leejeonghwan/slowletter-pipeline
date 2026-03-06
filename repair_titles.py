"""
제목 불일치 수리 스크립트
- archives.csv(원본)와 entities.csv의 제목을 비교
- 불일치하는 항목을 entities에서 삭제 → 다음 파이프라인 실행 시 자동 재추출
- 고아 ID(archives에 없는)도 제거
"""
import csv
import pandas as pd
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent / "data"
ARCHIVES_CSV = BASE_DIR / "slowletter_data_archives.csv"
ENTITIES_CSV = BASE_DIR / "raw" / "slowletter_solar_entities.csv"


def repair(dry_run: bool = True):
    print("=== 제목 불일치 수리 ===")
    print(f"Archives: {ARCHIVES_CSV}")
    print(f"Entities: {ENTITIES_CSV}")

    archives = pd.read_csv(ARCHIVES_CSV, dtype=str)
    entities = pd.read_csv(ENTITIES_CSV, dtype=str)

    print(f"Archives: {len(archives)}건, Entities: {len(entities)}건")

    # archives에서 ID → title 매핑
    archive_titles = {}
    for _, row in archives.iterrows():
        aid = str(row.get("ID", "")).strip()
        if aid:
            archive_titles[aid] = str(row.get("title", "")).strip()

    # 불일치 찾기
    mismatched_ids = []
    orphan_ids = []
    for _, row in entities.iterrows():
        eid = str(row.get("ID", "")).strip()
        entity_title = str(row.get("title", "")).strip()

        if eid not in archive_titles:
            orphan_ids.append(eid)
            continue

        if entity_title != archive_titles[eid]:
            mismatched_ids.append(eid)
            print(f"  불일치 {eid}: \"{entity_title[:40]}\" → \"{archive_titles[eid][:40]}\"")

    print(f"\n불일치: {len(mismatched_ids)}건")
    print(f"고아 ID: {len(orphan_ids)}건")

    if orphan_ids:
        for o in orphan_ids[:10]:
            print(f"  고아: {o}")
        if len(orphan_ids) > 10:
            print(f"  ... 외 {len(orphan_ids) - 10}건")

    remove_ids = set(mismatched_ids) | set(orphan_ids)
    if not remove_ids:
        print("\n수리할 항목 없음.")
        return

    if dry_run:
        print(f"\n[DRY RUN] 총 {len(remove_ids)}건 삭제 예정")
        print(f"수정하려면: python repair_titles.py --fix")
        return

    # 백업
    backup = ENTITIES_CSV.with_suffix(".csv.bak")
    entities.to_csv(backup, index=False, encoding="utf-8", quoting=csv.QUOTE_NONNUMERIC)
    print(f"\n백업: {backup}")

    # 불일치 + 고아 행 삭제
    before = len(entities)
    entities = entities[~entities["ID"].isin(remove_ids)].copy()
    after = len(entities)

    entities.to_csv(ENTITIES_CSV, index=False, encoding="utf-8", quoting=csv.QUOTE_NONNUMERIC)
    print(f"수정 완료: {before} → {after}건 ({before - after}건 삭제)")
    print(f"\n다음 파이프라인 실행 시 삭제된 항목의 엔티티가 자동 재추출됩니다.")


if __name__ == "__main__":
    fix = "--fix" in sys.argv
    repair(dry_run=not fix)
