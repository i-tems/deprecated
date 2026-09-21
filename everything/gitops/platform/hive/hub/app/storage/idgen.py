"""Human-readable entity ID 발급.

모든 도메인 엔티티 id 는 `<CELL>-<TYPE>-<SEQ>` 형식 (예: `ITEMS-ISSUE-302`).
  - CELL  : cell_id 대문자화 (kebab 그대로 — "acme-corp" → "ACME-CORP")
  - TYPE  : 엔티티 타입 태그 (PROJECT|ISSUE|SIGNAL|LABEL|EVENT|ACTION|INBOX)
  - SEQ   : (cell_id, entity_type) 별 1부터 단조증가하는 정수

SEQ 는 `entity_seq` 카운터 테이블에서 원자적으로 발급한다 (MySQL
LAST_INSERT_ID 트릭 — INSERT ... ON DUPLICATE KEY UPDATE 한 문장으로
read-modify-write 없이 동시성 안전). 기존 UUID7 체계는 폐기됨.

seq 값은 issues/projects/signals 의 `seq` 컬럼에도 그대로 저장되어 UI 짧은 표시·
issue preview overlay(`issue-<seq>`) 식별자로 재사용된다 — preview path 는 항상
cell 로 스코프되므로 per-cell-per-type seq 로도 충돌하지 않는다.
"""

from __future__ import annotations

# entity_type → ID 태그. 새 엔티티 타입 추가 시 여기에 등록.
ENTITY_TYPE_TAG: dict[str, str] = {
    "project": "PROJECT",
    "issue": "ISSUE",
    "signal": "SIGNAL",
    "label": "LABEL",
    "event": "EVENT",
    "action": "ACTION",
    "inbox": "INBOX",
    "initiative": "INITIATIVE",
}


def _norm_cell(cell_id: str | None) -> str:
    """cell prefix 정규화. cell 무관 글로벌 엔티티는 GLOBAL."""
    cid = (cell_id or "").strip()
    return cid.upper() if cid else "GLOBAL"


def alloc_seq(cell_id: str | None, entity_type: str) -> int:
    """(cell_id, entity_type) 의 다음 seq 를 원자적으로 발급.

    카운터 행이 없으면 1, 있으면 +1. 단일 statement 라 동시 호출에도
    중복/유실 없음 (InnoDB row lock + LAST_INSERT_ID 세션 스코프).
    """
    scope = _norm_cell(cell_id)
    if entity_type not in ENTITY_TYPE_TAG:
        raise ValueError(f"unknown entity_type for id: {entity_type!r}")
    from sqlalchemy import text
    from ..db import get_engine

    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO entity_seq (cell_id, entity_type, next_seq) "
                "VALUES (:c, :t, LAST_INSERT_ID(1)) "
                "ON DUPLICATE KEY UPDATE next_seq = LAST_INSERT_ID(next_seq + 1)"
            ),
            {"c": scope, "t": entity_type},
        )
        seq = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
    return int(seq)


def make_entity_id(cell_id: str | None, entity_type: str, seq: int) -> str:
    """seq 가 이미 있을 때 canonical id 문자열 합성."""
    tag = ENTITY_TYPE_TAG[entity_type]
    return f"{_norm_cell(cell_id)}-{tag}-{seq}"


def new_entity_id(cell_id: str | None, entity_type: str) -> tuple[str, int]:
    """seq 발급 + canonical id 반환. -> (entity_id, seq)."""
    seq = alloc_seq(cell_id, entity_type)
    return make_entity_id(cell_id, entity_type, seq), seq
