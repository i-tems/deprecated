"""issues 테이블 리포지토리.

issue_id ↔ seq 매핑 헬퍼. seq는 issues.seq auto_increment 컬럼으로, 외부 식별자
(미리보기 도메인·overlay 폴더·Application 이름)에 사용된다. issue_id (UUID) 는
긴 식별자라 URL/리소스 이름에 부적합.

cells_repo 패턴 그대로 — capability handler 가 직접 import.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import text

from ..db import get_engine

log = logging.getLogger("hub.issues_repo")


def get_seq_by_issue_id(cell_id: str, issue_id: str) -> int | None:
    """issue_id 로 seq 조회. 없거나 삭제된 issue 면 None.

    deleted=1 도 제외 — 정리된 issue 는 미리보기 식별자로 쓰면 안 됨.
    """
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(
            text(
                "SELECT seq FROM issues "
                "WHERE cell_id=:cid AND issue_id=:tid AND (deleted=0 OR deleted IS NULL)"
            ),
            {"cid": cell_id, "tid": issue_id},
        ).first()
    if not row:
        return None
    return int(row[0])


def get_by_seq(seq: int) -> tuple[str, dict] | None:
    """seq 로 (cell_id, issue) 조회. ApplicationSet path → seq → issue 역방향용.

    deleted 포함 — cleanup 후에도 이전 상태 추적 가능해야 함. 호출자가 status 확인.
    """
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(
            text("SELECT cell_id, data FROM issues WHERE seq=:seq"),
            {"seq": int(seq)},
        ).first()
    if not row:
        return None
    cell_id = row[0]
    data = row[1]
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    if isinstance(data, str):
        data = json.loads(data)
    return cell_id, data


def get_issue_id_by_seq(seq: int) -> str | None:
    """seq → issue_id shortcut. ApplicationSet template 등에서 brief lookup 용."""
    pair = get_by_seq(seq)
    if not pair:
        return None
    _cell_id, issue = pair
    return issue.get("issue_id")


def list_active_seqs(cell_id: str | None = None) -> list[tuple[str, int, str]]:
    """issue preview watcher 가 polling 대상으로 봐야 할 issue 목록.

    status 포함:
      - running: 워커가 작업 중. push 가 일어나기 직전·직후.
      - waiting: 워커가 작업 끝내고 사람 머지 대기. 미리보기 환경은 이 시점에
                  사람이 가장 많이 보게 됨. PR 머지 후 사람이 done 으로 전이하면
                  cleanup hook 이 자동 정리.
    제외: done, cancelled, error (cleanup hook 이 처리). draft, todo
    (워커 진입 전이라 cell repo 변경 없음).

    cleanup 누락 감지·ApplicationSet 외부 generator 디버깅용.
    cell_id 지정 시 그 셀로 한정.
    """
    eng = get_engine()
    sql = (
        "SELECT cell_id, seq, issue_id FROM issues "
        "WHERE deleted=0 AND status IN ('running','waiting')"
    )
    params: dict = {}
    if cell_id is not None:
        sql += " AND cell_id=:cid"
        params["cid"] = cell_id
    sql += " ORDER BY seq ASC"
    with eng.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()
    return [(r[0], int(r[1]), r[2]) for r in rows]
