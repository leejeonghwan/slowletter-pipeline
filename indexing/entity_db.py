"""
SQLite 기반 엔티티 데이터베이스 구축
- 문서 테이블: 전체 문서 메타데이터 + 콘텐츠
- 엔티티 테이블: 엔티티-문서 관계 (시계열 쿼리용)
"""
from __future__ import annotations
import csv
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Optional


def create_db(csv_path: str, db_path: str) -> None:
    """CSV에서 SQLite DB를 구축합니다."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 테이블 생성
    cursor.executescript("""
        DROP TABLE IF EXISTS documents;
        DROP TABLE IF EXISTS entities;
        DROP TABLE IF EXISTS daily_summaries;

        CREATE TABLE documents (
            doc_id TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            content_for_service TEXT,
            persons TEXT,
            organizations TEXT,
            concepts TEXT,
            events TEXT,
            locations TEXT,
            total_entities INTEGER DEFAULT 0
        );

        CREATE TABLE entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_name TEXT NOT NULL,
            entity_type TEXT NOT NULL,  -- person, organization, concept, event, location
            doc_id TEXT NOT NULL,
            date TEXT NOT NULL,
            FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
        );

        -- 날짜별 요약 (시계열 브라우징용)
        CREATE TABLE daily_summaries (
            date TEXT PRIMARY KEY,
            doc_count INTEGER,
            titles TEXT,  -- JSON array
            top_persons TEXT,
            top_organizations TEXT,
            top_concepts TEXT
        );

        -- 인덱스
        CREATE INDEX idx_documents_date ON documents(date);
        CREATE INDEX idx_entities_name ON entities(entity_name);
        CREATE INDEX idx_entities_type_date ON entities(entity_type, date);
        CREATE INDEX idx_entities_name_date ON entities(entity_name, date);
        CREATE INDEX idx_entities_doc ON entities(doc_id);
    """)

    # CSV 읽기 및 삽입
    print(f"Reading CSV: {csv_path}")
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Total rows: {len(rows)}")

    # 문서 삽입
    doc_count = 0
    entity_count = 0
    for row in rows:
        doc_id = row.get("ID", "")
        date = row.get("date", "")[:10]  # YYYY-MM-DD
        title = row.get("title", "")
        content = row.get("cleaned_content_for_api", "")
        content_svc = row.get("cleaned_content_for_service", "")
        persons = row.get("solar_persons", "")
        orgs = row.get("solar_organizations", "")
        concepts = row.get("solar_concepts", "")
        events = row.get("solar_events", "")
        locations = row.get("solar_locations", "")
        total_ent = int(row.get("total_entities", 0) or 0)

        if not doc_id or not content:
            continue

        cursor.execute("""
            INSERT OR REPLACE INTO documents
            (doc_id, date, title, content, content_for_service,
             persons, organizations, concepts, events, locations, total_entities)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (doc_id, date, title, content, content_svc,
              persons, orgs, concepts, events, locations, total_ent))
        doc_count += 1

        # 엔티티 삽입
        entity_map = {
            "person": persons,
            "organization": orgs,
            "concept": concepts,
            "event": events,
            "location": locations,
        }
        for etype, evalue in entity_map.items():
            if evalue:
                for name in evalue.split(";"):
                    name = name.strip()
                    if name:
                        cursor.execute("""
                            INSERT INTO entities (entity_name, entity_type, doc_id, date)
                            VALUES (?, ?, ?, ?)
                        """, (name, etype, doc_id, date))
                        entity_count += 1

    # 날짜별 요약 생성 (Python으로 처리 - Mac SQLite 호환성)
    daily_data = defaultdict(lambda: {"titles": [], "persons": set(), "orgs": set(), "concepts": set()})
    for row in rows:
        d = row.get("date", "")[:10]
        if not d or not row.get("cleaned_content_for_api", ""):
            continue
        daily_data[d]["titles"].append(row.get("title", ""))
        for p in row.get("solar_persons", "").split(";"):
            p = p.strip()
            if p:
                daily_data[d]["persons"].add(p)
        for o in row.get("solar_organizations", "").split(";"):
            o = o.strip()
            if o:
                daily_data[d]["orgs"].add(o)
        for c in row.get("solar_concepts", "").split(";"):
            c = c.strip()
            if c:
                daily_data[d]["concepts"].add(c)

    for date_key, info in daily_data.items():
        cursor.execute("""
            INSERT OR REPLACE INTO daily_summaries
            (date, doc_count, titles, top_persons, top_organizations, top_concepts)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            date_key,
            len(info["titles"]),
            " | ".join(info["titles"]),
            "; ".join(info["persons"]),
            "; ".join(info["orgs"]),
            "; ".join(info["concepts"]),
        ))

    conn.commit()
    print(f"DB created: {doc_count} documents, {entity_count} entity links")

    # 통계 출력 (Mac SQLite 호환 - 서브쿼리 사용)
    cursor.execute("SELECT COUNT(*) FROM (SELECT DISTINCT entity_name FROM entities)")
    unique_entities = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM (SELECT DISTINCT date FROM documents)")
    unique_dates = cursor.fetchone()[0]
    print(f"Unique entities: {unique_entities}, Unique dates: {unique_dates}")

    conn.close()


class EntityDB:
    """엔티티 DB 쿼리 인터페이스"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    def get_entity_timeline(
        self,
        entity_name: str,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        granularity: str = "day",  # day, week, month
        limit: int = 50,
    ) -> list[dict]:
        """특정 엔티티의 시간순 보도 흐름을 반환합니다."""
        if granularity == "month":
            date_expr = "SUBSTR(r.doc_date, 1, 7)"
        elif granularity == "week":
            date_expr = "SUBSTR(r.doc_date, 1, 7) || '-W' || CAST((CAST(SUBSTR(r.doc_date, 9, 2) AS INTEGER) - 1) / 7 + 1 AS TEXT)"
        else:
            date_expr = "r.doc_date"

        # 서브쿼리로 DISTINCT 처리 후 집계 (Mac SQLite 호환)
        inner = """
            SELECT DISTINCT e.doc_id, e.date as doc_date, d.title
            FROM entities e
            JOIN documents d ON e.doc_id = d.doc_id
            WHERE e.entity_name LIKE ?
        """
        params = [f"%{entity_name}%"]

        if date_start:
            inner += " AND e.date >= ?"
            params.append(date_start)
        if date_end:
            inner += " AND e.date <= ?"
            params.append(date_end)

        query = f"""
            SELECT {date_expr} as period,
                   COUNT(*) as doc_count,
                   GROUP_CONCAT(r.title, ' | ') as titles
            FROM ({inner}) r
            GROUP BY {date_expr}
            ORDER BY period ASC
            LIMIT ?
        """
        params.append(limit)

        cursor = self.conn.execute(query, params)
        results = []
        for row in cursor:
            titles = row["titles"].split(" | ") if row["titles"] else []
            results.append({
                "period": row["period"],
                "doc_count": row["doc_count"],
                "titles": titles[:5],
            })
        return results

    def get_trend_data(
        self,
        keyword: str,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        granularity: str = "month",
    ) -> dict:
        """키워드 트렌드 데이터를 반환합니다."""
        if granularity == "month":
            date_group = "SUBSTR(d.date, 1, 7)"
        else:
            date_group = "d.date"

        # 키워드 포함 문서의 시계열 분포
        query = f"""
            SELECT {date_group} as period,
                   COUNT(*) as doc_count
            FROM documents d
            WHERE (d.content LIKE ? OR d.title LIKE ?
                   OR d.concepts LIKE ? OR d.events LIKE ?)
        """
        params = [f"%{keyword}%"] * 4

        if date_start:
            query += " AND d.date >= ?"
            params.append(date_start)
        if date_end:
            query += " AND d.date <= ?"
            params.append(date_end)

        query += f" GROUP BY {date_group} ORDER BY period ASC"

        cursor = self.conn.execute(query, params)
        timeline = [{"period": row["period"], "count": row["doc_count"]} for row in cursor]

        # 공출현 엔티티 (키워드와 함께 등장하는 엔티티)
        co_query = """
            SELECT e.entity_name, e.entity_type, COUNT(*) as co_count
            FROM entities e
            JOIN documents d ON e.doc_id = d.doc_id
            WHERE (d.content LIKE ? OR d.title LIKE ?
                   OR d.concepts LIKE ? OR d.events LIKE ?)
              AND e.entity_name NOT LIKE ?
        """
        co_params = [f"%{keyword}%"] * 4 + [f"%{keyword}%"]

        if date_start:
            co_query += " AND d.date >= ?"
            co_params.append(date_start)
        if date_end:
            co_query += " AND d.date <= ?"
            co_params.append(date_end)

        co_query += " GROUP BY e.entity_name, e.entity_type ORDER BY co_count DESC LIMIT 20"

        cursor = self.conn.execute(co_query, co_params)
        co_entities = [
            {"name": row["entity_name"], "type": row["entity_type"], "count": row["co_count"]}
            for row in cursor
        ]

        # 대표 문서 (기간별 1건씩)
        repr_query = """
            SELECT d.doc_id, d.date, d.title, SUBSTR(d.content, 1, 200) as snippet
            FROM documents d
            WHERE (d.content LIKE ? OR d.title LIKE ?
                   OR d.concepts LIKE ? OR d.events LIKE ?)
        """
        repr_params = [f"%{keyword}%"] * 4
        if date_start:
            repr_query += " AND d.date >= ?"
            repr_params.append(date_start)
        if date_end:
            repr_query += " AND d.date <= ?"
            repr_params.append(date_end)
        repr_query += " ORDER BY d.date DESC LIMIT 10"

        cursor = self.conn.execute(repr_query, repr_params)
        representative_docs = [dict(row) for row in cursor]

        return {
            "keyword": keyword,
            "timeline": timeline,
            "co_entities": co_entities,
            "representative_docs": representative_docs,
            "total_count": sum(t["count"] for t in timeline),
        }

    def search_by_entity(
        self,
        entity_name: str,
        entity_type: Optional[str] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """엔티티 이름으로 관련 문서를 검색합니다."""
        query = """
            SELECT DISTINCT d.doc_id, d.date, d.title, d.content,
                   d.persons, d.organizations, d.concepts
            FROM entities e
            JOIN documents d ON e.doc_id = d.doc_id
            WHERE e.entity_name LIKE ?
        """
        params = [f"%{entity_name}%"]

        if entity_type:
            query += " AND e.entity_type = ?"
            params.append(entity_type)
        if date_start:
            query += " AND e.date >= ?"
            params.append(date_start)
        if date_end:
            query += " AND e.date <= ?"
            params.append(date_end)

        query += " ORDER BY d.date DESC LIMIT ?"
        params.append(limit)

        cursor = self.conn.execute(query, params)
        return [dict(row) for row in cursor]

    def search_by_source(
        self,
        media_name: str,
        topic: Optional[str] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """언론사 이름으로 관련 문서를 검색합니다."""
        query = """
            SELECT d.doc_id, d.date, d.title, d.content,
                   d.persons, d.organizations, d.concepts
            FROM documents d
            WHERE d.organizations LIKE ?
        """
        params = [f"%{media_name}%"]

        if topic:
            query += " AND (d.content LIKE ? OR d.title LIKE ? OR d.concepts LIKE ?)"
            params.extend([f"%{topic}%"] * 3)
        if date_start:
            query += " AND d.date >= ?"
            params.append(date_start)
        if date_end:
            query += " AND d.date <= ?"
            params.append(date_end)

        query += " ORDER BY d.date DESC LIMIT ?"
        params.append(limit)

        cursor = self.conn.execute(query, params)
        return [dict(row) for row in cursor]

    def close(self):
        self.conn.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python entity_db.py <csv_path> <db_path>")
        sys.exit(1)
    create_db(sys.argv[1], sys.argv[2])
