"""Path → SQL table dispatcher.

storage primitive (`read_entity_file`/`write_entity_file`/`find_entity`/
`append_jsonl`/`today_path`/`iter_partitions_for_query`/`find_by_id` 등) 가
받는 path 를 분석해 해당 SQL 테이블 row 연산으로 라우팅한다. path 패턴은
shim 단계의 dispatch key 일 뿐 디스크에는 쓰지 않는다.

지원 path:
    .../cells/{cell_id}/{kind}.jsonl                       (entity:  projects|issues|labels|initiatives)
    .../cells/{cell_id}/{kind}/YYYY-MM-DD.jsonl            (date:    events|signals)
    .../cells/{cell_id}/{kind}                             (date dir)
    .../(data/)?actions|inbox/YYYY-MM-DD.jsonl             (global date: audit_actions|inbox_events)
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Any

from sqlalchemy import text

from ..db import get_engine

log = logging.getLogger("hub.sql")


# kind → (table, id_field, generated columns)
ENTITY_KINDS = {
    "projects": {"table": "projects", "id_field": "project_id"},
    "issues": {"table": "issues", "id_field": "issue_id"},
    "labels": {"table": "labels", "id_field": "label_id"},
    "initiatives": {"table": "initiatives", "id_field": "initiative_id"},
}

_ENTITY_PATH_RE = re.compile(r".*/cells/(?P<cell_id>[^/]+)/(?P<kind>projects|issues|labels|initiatives)\.jsonl$")


def parse_entity_path(path: Path | str) -> dict | None:
    """path가 entity jsonl 패턴이면 {cell_id, kind, table, id_field} 반환."""
    s = str(path)
    m = _ENTITY_PATH_RE.match(s)
    if not m:
        return None
    kind = m.group("kind")
    cfg = ENTITY_KINDS[kind]
    return {
        "cell_id": m.group("cell_id"),
        "kind": kind,
        "table": cfg["table"],
        "id_field": cfg["id_field"],
    }


# ---------------------------------------------------------------------------
# Date-partitioned tables — events / signals (Phase 2)
# ---------------------------------------------------------------------------

DATE_KINDS = {
    "events":  {"table": "events",  "id_field": "event_id"},
    "signals": {"table": "signals", "id_field": "signal_id"},
}

# 글로벌(셀 무관): /data/actions/, /data/inbox/.
GLOBAL_DATE_KINDS = {
    "actions": {"table": "audit_actions", "id_field": "action_id"},
    "inbox":   {"table": "inbox_events",  "id_field": "inbox_id"},
}

_DATE_FILE_RE = re.compile(
    r".*/cells/(?P<cell_id>[^/]+)/(?P<kind>events|signals)/(?P<date>\d{4}-\d{2}-\d{2})\.jsonl$"
)
_DATE_DIR_RE = re.compile(
    r".*/cells/(?P<cell_id>[^/]+)/(?P<kind>events|signals)/?$"
)
_GLOBAL_DATE_FILE_RE = re.compile(
    r".*/(?:data/)?(?P<kind>actions|inbox)/(?P<date>\d{4}-\d{2}-\d{2})\.jsonl$"
)
_GLOBAL_DATE_DIR_RE = re.compile(
    r".*/(?:data/)?(?P<kind>actions|inbox)/?$"
)


def parse_global_date_file_path(path: Path | str) -> dict | None:
    s = str(path)
    m = _GLOBAL_DATE_FILE_RE.match(s)
    if not m:
        return None
    kind = m.group("kind")
    cfg = GLOBAL_DATE_KINDS[kind]
    return {
        "cell_id": None,
        "kind": kind,
        "date": m.group("date"),
        "table": cfg["table"],
        "id_field": cfg["id_field"],
    }


def parse_global_date_dir_path(path: Path | str) -> dict | None:
    s = str(path).rstrip("/")
    m = _GLOBAL_DATE_DIR_RE.match(s)
    if not m:
        return None
    kind = m.group("kind")
    cfg = GLOBAL_DATE_KINDS[kind]
    return {
        "cell_id": None,
        "kind": kind,
        "table": cfg["table"],
        "id_field": cfg["id_field"],
    }


def parse_date_file_path(path: Path | str) -> dict | None:
    """`.../cells/{cell}/{kind}/YYYY-MM-DD.jsonl` 매칭."""
    s = str(path)
    m = _DATE_FILE_RE.match(s)
    if not m:
        return None
    kind = m.group("kind")
    cfg = DATE_KINDS[kind]
    return {
        "cell_id": m.group("cell_id"),
        "kind": kind,
        "date": m.group("date"),
        "table": cfg["table"],
        "id_field": cfg["id_field"],
    }


def parse_date_dir_path(path: Path | str) -> dict | None:
    """`.../cells/{cell}/{kind}` 디렉토리 매칭."""
    s = str(path).rstrip("/")
    m = _DATE_DIR_RE.match(s)
    if not m:
        return None
    kind = m.group("kind")
    cfg = DATE_KINDS[kind]
    return {
        "cell_id": m.group("cell_id"),
        "kind": kind,
        "table": cfg["table"],
        "id_field": cfg["id_field"],
    }


def date_dir_synthetic_path(directory: Path, date: str) -> Path:
    """date-partition path를 합성. 파일이 없어도 dispatcher가 인식."""
    return directory / f"{date}.jsonl"


def list_date_records_in_date(table: str, cell_id: str, date: str) -> list[dict]:
    """단일 날짜의 records (read_jsonl(path) 시맨틱)."""
    return list_date_records(table, cell_id, date_from=date, date_to=date)


def list_date_records(
    table: str,
    cell_id: str | None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """date 범위의 records를 ts asc로. 글로벌이면 cell_id=None 전달."""
    sql = f"SELECT {_select_cols(table)} FROM {table} WHERE 1=1"
    params: dict = {}
    if cell_id is not None:
        sql += " AND cell_id=:cid"
        params["cid"] = cell_id
    if date_from:
        sql += " AND ts_date >= :df"
        params["df"] = date_from
    if date_to:
        sql += " AND ts_date <= :dt"
        params["dt"] = date_to
    sql += " ORDER BY ts ASC"
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()
    out = [_row_to_dict(r) for r in rows]
    if cell_id is not None:
        _attach_cell_id(out, cell_id)
    return out


def insert_date_record(table: str, id_field: str, cell_id: str | None, record: dict) -> None:
    eid = record.get(id_field)
    if not eid:
        raise ValueError(f"{id_field} required")
    payload = json.dumps(record, ensure_ascii=False)
    has_seq = table in _SEQ_TABLES
    eng = get_engine()
    with eng.begin() as conn:
        if cell_id is None:
            # 글로벌: cell_id 컬럼은 generated이므로 INSERT 안 함
            conn.execute(
                text(
                    f"INSERT INTO {table} ({id_field}, data) VALUES (:eid, :data) "
                    f"ON DUPLICATE KEY UPDATE data=VALUES(data)"
                ),
                {"eid": eid, "data": payload},
            )
        elif has_seq:
            # seq 보유 테이블(signals): app 이 발급한 seq 를 컬럼에도 기록.
            # seq 는 엔티티 불변 — 중복 시 data 만 갱신, seq 보존.
            conn.execute(
                text(
                    f"INSERT INTO {table} (cell_id, {id_field}, data, seq) "
                    f"VALUES (:cid, :eid, :data, :seq) "
                    f"ON DUPLICATE KEY UPDATE data=VALUES(data)"
                ),
                {"cid": cell_id, "eid": eid, "data": payload, "seq": record.get("seq")},
            )
        else:
            conn.execute(
                text(
                    f"INSERT INTO {table} (cell_id, {id_field}, data) VALUES (:cid, :eid, :data) "
                    f"ON DUPLICATE KEY UPDATE data=VALUES(data)"
                ),
                {"cid": cell_id, "eid": eid, "data": payload},
            )


def replace_date_records_in_date(
    table: str, id_field: str, cell_id: str | None, date: str, records: list[dict]
) -> None:
    """write_jsonl(path) 시맨틱 — 해당 날짜 row만 교체. 글로벌이면 cell_id=None.

    seq 보유 테이블(signals)은 dict에 seq가 있으면 보존, 없으면 AUTO_INCREMENT 발급.
    """
    has_seq = table in _SEQ_TABLES
    eng = get_engine()
    with eng.begin() as conn:
        if cell_id is None:
            conn.execute(
                text(f"DELETE FROM {table} WHERE ts_date=:d"),
                {"d": date},
            )
            if records:
                if has_seq:
                    conn.execute(
                        text(f"INSERT INTO {table} ({id_field}, data, seq) VALUES (:eid, :data, :seq)"),
                        [
                            {"eid": r[id_field], "data": json.dumps(r, ensure_ascii=False), "seq": r.get("seq")}
                            for r in records
                            if r.get(id_field)
                        ],
                    )
                else:
                    conn.execute(
                        text(f"INSERT INTO {table} ({id_field}, data) VALUES (:eid, :data)"),
                        [
                            {"eid": r[id_field], "data": json.dumps(r, ensure_ascii=False)}
                            for r in records
                            if r.get(id_field)
                        ],
                    )
        else:
            conn.execute(
                text(f"DELETE FROM {table} WHERE cell_id=:cid AND ts_date=:d"),
                {"cid": cell_id, "d": date},
            )
            if records:
                if has_seq:
                    conn.execute(
                        text(f"INSERT INTO {table} (cell_id, {id_field}, data, seq) VALUES (:cid, :eid, :data, :seq)"),
                        [
                            {"cid": cell_id, "eid": r[id_field], "data": json.dumps(r, ensure_ascii=False), "seq": r.get("seq")}
                            for r in records
                            if r.get(id_field)
                        ],
                    )
                else:
                    conn.execute(
                        text(f"INSERT INTO {table} (cell_id, {id_field}, data) VALUES (:cid, :eid, :data)"),
                        [
                            {"cid": cell_id, "eid": r[id_field], "data": json.dumps(r, ensure_ascii=False)}
                            for r in records
                            if r.get(id_field)
                        ],
                    )


def list_distinct_dates(table: str, cell_id: str | None) -> list[str]:
    """all_partition_paths 시맨틱 — 데이터가 있는 날짜를 오름차순으로."""
    eng = get_engine()
    if cell_id is None:
        sql = f"SELECT DISTINCT ts_date FROM {table} WHERE ts_date IS NOT NULL ORDER BY ts_date"
        params = {}
    else:
        sql = f"SELECT DISTINCT ts_date FROM {table} WHERE cell_id=:cid AND ts_date IS NOT NULL ORDER BY ts_date"
        params = {"cid": cell_id}
    with eng.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()
    return [str(r[0]) for r in rows if r[0]]


def find_date_record_by_id(
    table: str, id_field: str, cell_id: str | None, id_value: str
) -> dict | None:
    eng = get_engine()
    if cell_id is None:
        sql = f"SELECT data FROM {table} WHERE {id_field}=:eid"
        params = {"eid": id_value}
    else:
        sql = f"SELECT data FROM {table} WHERE cell_id=:cid AND {id_field}=:eid"
        params = {"cid": cell_id, "eid": id_value}
    with eng.connect() as conn:
        row = conn.execute(text(sql), params).first()
    return _row_to_dict(row) if row else None


def get_date_for_record(
    table: str, id_field: str, cell_id: str | None, id_value: str
) -> str | None:
    """record가 속한 날짜를 반환 (find_by_id의 path 결과 호환용)."""
    eng = get_engine()
    if cell_id is None:
        sql = f"SELECT ts_date FROM {table} WHERE {id_field}=:eid"
        params = {"eid": id_value}
    else:
        sql = f"SELECT ts_date FROM {table} WHERE cell_id=:cid AND {id_field}=:eid"
        params = {"cid": cell_id, "eid": id_value}
    with eng.connect() as conn:
        row = conn.execute(text(sql), params).first()
    return str(row[0]) if row and row[0] else None


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------

_SEQ_TABLES = {"issues", "projects", "signals", "initiatives"}


def _select_cols(table: str) -> str:
    """seq 컬럼이 있는 테이블은 함께 SELECT 해 dict에 주입한다."""
    return "data, seq" if table in _SEQ_TABLES else "data"


def _attach_cell_id(records: list[dict], cell_id: str) -> list[dict]:
    """옛 record에 data.cell_id가 없을 수 있어 PK 컬럼으로 보정."""
    for d in records:
        d.setdefault("cell_id", cell_id)
    return records


def list_entities(table: str, cell_id: str) -> list[dict]:
    """삭제 안 된 모든 row의 data를 updated_at desc로 반환."""
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(
            f"SELECT {_select_cols(table)} FROM {table} WHERE cell_id=:cid AND deleted=0 "
            f"ORDER BY updated_at DESC"
        ), {"cid": cell_id}).fetchall()
    return _attach_cell_id([_row_to_dict(r) for r in rows], cell_id)


def list_entities_all(table: str, cell_id: str) -> list[dict]:
    """deleted 포함 모든 row. 마이그레이션·디버깅용."""
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(
            text(f"SELECT {_select_cols(table)} FROM {table} WHERE cell_id=:cid"),
            {"cid": cell_id},
        ).fetchall()
    return _attach_cell_id([_row_to_dict(r) for r in rows], cell_id)


def get_entity(table: str, id_field: str, cell_id: str, entity_id: str) -> dict | None:
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(
            text(f"SELECT {_select_cols(table)} FROM {table} WHERE cell_id=:cid AND {id_field}=:eid"),
            {"cid": cell_id, "eid": entity_id},
        ).first()
    if not row:
        return None
    d = _row_to_dict(row)
    d.setdefault("cell_id", cell_id)
    return d


def upsert_entity(table: str, id_field: str, cell_id: str, entity: dict) -> None:
    eid = entity.get(id_field)
    if not eid:
        raise ValueError(f"{id_field} required")
    payload = json.dumps(entity, ensure_ascii=False)
    has_seq = table in _SEQ_TABLES
    eng = get_engine()
    with eng.begin() as conn:
        if has_seq:
            # seq 는 app(entity_seq)이 발급한 (cell,type)별 정수 — 컬럼에도 기록해
            # 첫 insert 부터 일관. seq 는 엔티티 불변이라 중복 시 data 만 갱신.
            conn.execute(
                text(
                    f"INSERT INTO {table} (cell_id, {id_field}, data, seq) "
                    f"VALUES (:cid, :eid, :data, :seq) "
                    f"ON DUPLICATE KEY UPDATE data=VALUES(data)"
                ),
                {"cid": cell_id, "eid": eid, "data": payload, "seq": entity.get("seq")},
            )
        else:
            conn.execute(
                text(
                    f"INSERT INTO {table} (cell_id, {id_field}, data) VALUES (:cid, :eid, :data) "
                    f"ON DUPLICATE KEY UPDATE data=VALUES(data)"
                ),
                {"cid": cell_id, "eid": eid, "data": payload},
            )


class CASConflict(Exception):
    """optimistic CAS 가 max_retries 안에 수렴 못 함 (cross-pod 고경합 신호)."""


def _entity_rev(entity: dict | None) -> int:
    """entity 의 현재 rev(없으면 0). rev 는 data JSON 내 정수 — 스키마 마이그레이션 불필요."""
    if not entity:
        return 0
    try:
        return int(entity.get("rev") or 0)
    except (TypeError, ValueError):
        return 0


def cas_write_entity(table: str, id_field: str, cell_id: str, entity_id: str, entity: dict, expected_rev: int) -> bool:
    """rev-guarded single-row UPDATE. rowcount==1 성공 / 0 충돌(또는 행 소멸).

    블로킹 락 없이 cross-pod 동시 쓰기를 직렬화 — 두 pod 가 같은 행을 동시에 갱신하면
    한쪽만 expected_rev 매칭에 성공하고 다른 쪽은 0 row (충돌→호출자 재시도). 단일 행만
    건드려 충돌 표면이 셀 전체가 아닌 엔티티 단위 (replace_all_entities 의 셀 통째 재기록 대비).
    """
    payload = json.dumps(entity, ensure_ascii=False)
    eng = get_engine()
    with eng.begin() as conn:
        res = conn.execute(
            text(
                f"UPDATE {table} SET data=:data "
                f"WHERE cell_id=:cid AND {id_field}=:eid "
                f"AND COALESCE(CAST(JSON_EXTRACT(data, '$.rev') AS UNSIGNED), 0)=:exp"
            ),
            {"data": payload, "cid": cell_id, "eid": entity_id, "exp": expected_rev},
        )
        return res.rowcount == 1


def cas_update_entity(table, id_field, cell_id, entity_id, apply_fn, *, max_retries: int = 16):
    """단일 entity row 의 optimistic concurrency control update.

    apply_fn(fresh: dict | None) -> (result, mutated: dict | None):
      - (result, None): 쓰기 없이 result 반환 (not_found·검증 실패 등 — caller 가 판단).
      - (result, mutated): mutated 를 rev-guard 로 쓰고 성공 시 result 반환. rev 는 자동 증가.
    rev 충돌(다른 writer 가 먼저 씀) 시 fresh 를 재read 하고 apply_fn 을 재실행한다 —
    블로킹 락 없음(이벤트루프 stall·#277 부류 회피). 충돌 시 jitter backoff 로 thundering-herd
    완화. max_retries 초과 시 CASConflict (정상 운영의 같은-엔티티 동시쓰기는 드물어 도달
    안 함 — 도달은 비정상 고경합 신호).

    부수효과(emit_event/inbox/wake)는 apply_fn 안에서 하지 말 것 — 재시도 시 중복 발행된다.
    apply_fn 은 순수(read→검증→필드적용)해야 하고, 쓰기 성공 후 caller 가 한 번 emit 한다.
    """
    for attempt in range(max_retries):
        fresh = get_entity(table, id_field, cell_id, entity_id)
        expected = _entity_rev(fresh)
        result, mutated = apply_fn(fresh)
        if mutated is None:
            return result
        mutated["rev"] = expected + 1
        if cas_write_entity(table, id_field, cell_id, entity_id, mutated, expected):
            return result
        # 충돌 — 짧은 jitter 후 재read. 동기 sleep 이나 ms 단위라 루프 영향 미미하고,
        # 같은-엔티티 동시쓰기는 드물어 대개 0~1 회.
        time.sleep(random.uniform(0, min(0.02, 0.002 * (attempt + 1))))
    raise CASConflict(f"{table}:{cell_id}:{entity_id} rev 충돌 {max_retries}회 초과")


def replace_all_entities(table: str, id_field: str, cell_id: str, entities: list[dict]) -> None:
    """cell의 entities를 일괄 교체 (write_entity_file 시맨틱).

    트랜잭션 1개에서 cell의 row 모두 DELETE 후 bulk INSERT.
    seq 보유 테이블(issues/projects/signals)은 dict에 seq가 있으면 보존, 없으면 AUTO_INCREMENT 부여.
    """
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {table} WHERE cell_id=:cid"),
            {"cid": cell_id},
        )
        if not entities:
            return
        valid = [e for e in entities if e.get(id_field)]
        if not valid:
            return
        if table in _SEQ_TABLES:
            conn.execute(
                text(
                    f"INSERT INTO {table} (cell_id, {id_field}, data, seq) "
                    f"VALUES (:cid, :eid, :data, :seq)"
                ),
                [
                    {
                        "cid": cell_id,
                        "eid": e[id_field],
                        "data": json.dumps(e, ensure_ascii=False),
                        "seq": e.get("seq"),  # None이면 DB가 AUTO_INCREMENT 발급
                    }
                    for e in valid
                ],
            )
        else:
            conn.execute(
                text(f"INSERT INTO {table} (cell_id, {id_field}, data) VALUES (:cid, :eid, :data)"),
                [
                    {"cid": cell_id, "eid": e[id_field], "data": json.dumps(e, ensure_ascii=False)}
                    for e in valid
                ],
            )


def _row_to_dict(row: Any) -> dict:
    if not row:
        return {}
    raw = row[0]
    if isinstance(raw, dict):
        d = raw
    elif isinstance(raw, (str, bytes)):
        d = json.loads(raw)
    else:
        d = {}
    # seq 보유 테이블은 row[1]에 seq 컬럼이 함께 SELECT 되어 들어옴.
    if len(row) > 1 and row[1] is not None:
        d["seq"] = int(row[1])
    return d


# ---------------------------------------------------------------------------
# worker heartbeats — 공유 저장 (INFRA-ISSUE-284, 옛 in-memory _HEARTBEATS 대체)
# worker_id 당 단일 writer 라 CAS 불필요 (UPSERT). last_seen 은 ISO8601 UTC 문자열로
# lexicographic 비교 가능 (동일 포맷·타임존).
# ---------------------------------------------------------------------------

def upsert_heartbeat(worker_id: str, record: dict) -> None:
    payload = json.dumps(record, ensure_ascii=False)
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO worker_heartbeats (worker_id, data) VALUES (:w, :d) "
                "ON DUPLICATE KEY UPDATE data=VALUES(data)"
            ),
            {"w": worker_id, "d": payload},
        )


def get_heartbeat(worker_id: str) -> dict | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT data FROM worker_heartbeats WHERE worker_id=:w"), {"w": worker_id}
        ).first()
    return _row_to_dict(row) if row else None


def list_heartbeats(cutoff_iso: str) -> list[dict]:
    """last_seen >= cutoff_iso 인 살아있는 워커 레코드."""
    with get_engine().connect() as conn:
        rows = conn.execute(
            text("SELECT data FROM worker_heartbeats WHERE last_seen >= :c"), {"c": cutoff_iso}
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def prune_heartbeats(cutoff_iso: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text("DELETE FROM worker_heartbeats WHERE last_seen < :c"), {"c": cutoff_iso}
        )


def delete_heartbeat(worker_id: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text("DELETE FROM worker_heartbeats WHERE worker_id=:w"), {"w": worker_id}
        )
