"""MySQL 연결 및 스키마 부트스트랩.

테이블 스키마는 KV-doc 스타일 — `data JSON` 에 record 전체 저장하고 자주 쓰는
필드만 generated column 으로 추출해 인덱스. 호출자(entity 모듈)는 dict 를
storage primitive (path 기반) 로 다루고, storage.sql 이 그 path 를 분석해
해당 테이블로 dispatch.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


log = logging.getLogger("hub.db")

_ENGINE: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _build_url() -> str:
    host = os.environ.get("DB_HOST", "hive-mysql.hive.svc.cluster.local")
    port = os.environ.get("DB_PORT", "3306")
    user = os.environ.get("DB_USER", "hive")
    password = os.environ.get("DB_PASSWORD", "")
    name = os.environ.get("DB_NAME", "hive")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}?charset=utf8mb4"


def get_engine() -> Engine:
    global _ENGINE, _SessionLocal
    if _ENGINE is None:
        url = _build_url()
        _ENGINE = create_engine(
            url,
            pool_pre_ping=True,
            pool_recycle=1800,
            pool_size=10,
            max_overflow=20,
            future=True,
        )
        _SessionLocal = sessionmaker(bind=_ENGINE, future=True, expire_on_commit=False)
    return _ENGINE


@contextmanager
def db_session():
    """단일 트랜잭션 컨텍스트. 예외 시 롤백."""
    if _SessionLocal is None:
        get_engine()
    s: Session = _SessionLocal()  # type: ignore
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Schema bootstrap — phase별로 누적 추가
# ---------------------------------------------------------------------------

_DELETED_GEN = """
    deleted TINYINT(1) AS (
        CASE
            WHEN JSON_EXTRACT(data, '$.deleted') IS NULL THEN 0
            WHEN JSON_EXTRACT(data, '$.deleted') = CAST('false' AS JSON) THEN 0
            ELSE 1
        END
    ) STORED
"""

_UPDATED_GEN = "updated_at VARCHAR(64) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.updated_at'))) STORED"


_SCHEMA_STATEMENTS: list[str] = [
    # cells: 셀 레지스트리.
    f"""
    CREATE TABLE IF NOT EXISTS cells (
        cell_id VARCHAR(64) NOT NULL PRIMARY KEY,
        data JSON NOT NULL,
        status VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.status'))) STORED,
        {_DELETED_GEN},
        {_UPDATED_GEN},
        INDEX idx_status (status, deleted),
        INDEX idx_updated (updated_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,

    # projects: cell-scoped. project_id 는 `<CELL>-PROJECT-<seq>` canonical id.
    # seq 는 entity_seq 에서 발급된 (cell, project) 별 정수 — app 이 채워 넣는다
    # (AUTO_INCREMENT 아님). UI 짧은 표시용으로 (cell_id, seq) 인덱스.
    f"""
    CREATE TABLE IF NOT EXISTS projects (
        cell_id VARCHAR(64) NOT NULL,
        project_id VARCHAR(64) NOT NULL,
        seq BIGINT NULL,
        data JSON NOT NULL,
        status VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.status'))) STORED,
        owner VARCHAR(255) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.owner'))) STORED,
        {_DELETED_GEN},
        {_UPDATED_GEN},
        PRIMARY KEY (cell_id, project_id),
        INDEX idx_cell_seq (cell_id, seq),
        INDEX idx_cell_status (cell_id, status, deleted),
        INDEX idx_cell_updated (cell_id, updated_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,

    # labels: cell-scoped. (cell_id, label_id) PK. name 은 cell 내 unique (app 레벨 enforce — 삭제·복원 시 reuse 허용).
    f"""
    CREATE TABLE IF NOT EXISTS labels (
        cell_id VARCHAR(64) NOT NULL,
        label_id VARCHAR(64) NOT NULL,
        data JSON NOT NULL,
        name VARCHAR(128) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.name'))) STORED,
        {_DELETED_GEN},
        {_UPDATED_GEN},
        PRIMARY KEY (cell_id, label_id),
        INDEX idx_cell_name (cell_id, name, deleted),
        INDEX idx_cell_updated (cell_id, updated_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,

    # issues: cell-scoped. issue_id 는 `<CELL>-ISSUE-<seq>` canonical id.
    # seq 는 entity_seq 발급분 — issue preview overlay(`issue-<seq>`) 식별자로도 재사용.
    f"""
    CREATE TABLE IF NOT EXISTS issues (
        cell_id VARCHAR(64) NOT NULL,
        issue_id VARCHAR(64) NOT NULL,
        seq BIGINT NULL,
        data JSON NOT NULL,
        project_id VARCHAR(64) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.project_id'))) STORED,
        status VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.status'))) STORED,
        owner VARCHAR(255) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.owner'))) STORED,
        {_DELETED_GEN},
        {_UPDATED_GEN},
        PRIMARY KEY (cell_id, issue_id),
        INDEX idx_cell_seq (cell_id, seq),
        INDEX idx_cell_project (cell_id, project_id),
        INDEX idx_cell_status (cell_id, status, deleted),
        INDEX idx_cell_updated (cell_id, updated_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,

    # initiatives: cell-scoped. initiative_id 는 `<CELL>-INITIATIVE-<seq>` canonical id.
    # Strategic outcome anchor — Project 들이 advance 하는 상위 단위. Project 과 통일된
    # 단일 4-status container 축 (backlog/active/done/archive), sub-initiative ≤5 depth,
    # multi-parent projects, manual curation. worker entity 가 아님 — set_session·
    # force_update·add_pr 없음. spec: ~/hive/specs/model/initiative_model.md
    f"""
    CREATE TABLE IF NOT EXISTS initiatives (
        cell_id VARCHAR(64) NOT NULL,
        initiative_id VARCHAR(64) NOT NULL,
        seq BIGINT NULL,
        data JSON NOT NULL,
        status VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.status'))) STORED,
        name VARCHAR(255) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.name'))) STORED,
        parent_initiative_id VARCHAR(64) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.parent_initiative_id'))) STORED,
        {_DELETED_GEN},
        {_UPDATED_GEN},
        PRIMARY KEY (cell_id, initiative_id),
        INDEX idx_cell_seq (cell_id, seq),
        INDEX idx_cell_status (cell_id, status, deleted),
        INDEX idx_cell_name (cell_id, name, deleted),
        INDEX idx_cell_parent (cell_id, parent_initiative_id),
        INDEX idx_cell_updated (cell_id, updated_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,

    # (initiative_updates 테이블은 제거됨 — health 축 폐지, Project/Issue 와 동형.
    #  기존 테이블은 _drop_initiative_updates() 가 일회성으로 DROP. INFRA-ISSUE-207.)

    # events: date-partitioned. ts/ts_date를 data.ts에서 추출.
    """
    CREATE TABLE IF NOT EXISTS events (
        cell_id VARCHAR(64) NOT NULL,
        event_id VARCHAR(64) NOT NULL,
        data JSON NOT NULL,
        ts VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.ts'))) STORED,
        ts_date VARCHAR(10) AS (SUBSTRING(JSON_UNQUOTE(JSON_EXTRACT(data, '$.ts')), 1, 10)) STORED,
        type VARCHAR(64) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.type'))) STORED,
        entity_type VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.entity_type'))) STORED,
        entity_id VARCHAR(64) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.entity_id'))) STORED,
        principal_id VARCHAR(128) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.principal_id'))) STORED,
        principal_type VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.principal_type'))) STORED,
        session_id VARCHAR(128) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.session_id'))) STORED,
        trace_id VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.trace_id'))) STORED,
        span_id VARCHAR(16) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.span_id'))) STORED,
        parent_span_id VARCHAR(16) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.parent_span_id'))) STORED,
        PRIMARY KEY (cell_id, event_id),
        INDEX idx_cell_entity (cell_id, entity_type, entity_id, ts),
        INDEX idx_cell_date (cell_id, ts_date),
        INDEX idx_principal (principal_id, ts),
        INDEX idx_session (session_id),
        INDEX idx_trace (trace_id, ts)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,

    # signals: date-partitioned. ts는 ts_emitted에서 추출.
    """
    CREATE TABLE IF NOT EXISTS signals (
        cell_id VARCHAR(64) NOT NULL,
        signal_id VARCHAR(64) NOT NULL,
        seq BIGINT NULL,
        data JSON NOT NULL,
        ts VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.ts_emitted'))) STORED,
        ts_date VARCHAR(10) AS (SUBSTRING(JSON_UNQUOTE(JSON_EXTRACT(data, '$.ts_emitted')), 1, 10)) STORED,
        type VARCHAR(64) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.type'))) STORED,
        status VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.status'))) STORED,
        severity VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.severity'))) STORED,
        PRIMARY KEY (cell_id, signal_id),
        INDEX idx_cell_seq (cell_id, seq),
        INDEX idx_cell_status (cell_id, status, ts_date),
        INDEX idx_cell_type (cell_id, type, status),
        INDEX idx_cell_date (cell_id, ts_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,

    # audit_actions: 글로벌. 다른 테이블과 동일한 record.cell_id 키 사용.
    """
    CREATE TABLE IF NOT EXISTS audit_actions (
        action_id VARCHAR(64) NOT NULL PRIMARY KEY,
        data JSON NOT NULL,
        cell_id VARCHAR(64) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.cell_id'))) STORED,
        ts VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.ts'))) STORED,
        ts_date VARCHAR(10) AS (SUBSTRING(JSON_UNQUOTE(JSON_EXTRACT(data, '$.ts')), 1, 10)) STORED,
        capability_id VARCHAR(128) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.capability_id'))) STORED,
        issue_id VARCHAR(64) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.issue_id'))) STORED,
        status VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.status'))) STORED,
        principal_id VARCHAR(128) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.principal_id'))) STORED,
        principal_type VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.principal_type'))) STORED,
        session_id VARCHAR(128) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.session_id'))) STORED,
        session_type VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.session_type'))) STORED,
        trace_id VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.trace_id'))) STORED,
        span_id VARCHAR(16) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.span_id'))) STORED,
        parent_span_id VARCHAR(16) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.parent_span_id'))) STORED,
        INDEX idx_date (ts_date),
        INDEX idx_cap (capability_id, ts_date),
        INDEX idx_cell (cell_id, ts_date),
        INDEX idx_task (issue_id),
        INDEX idx_principal (principal_id, ts_date),
        INDEX idx_session (session_id),
        INDEX idx_session_type (session_type, ts_date),
        INDEX idx_trace (trace_id, ts)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,

    # inbox_events: 글로벌. cell_id는 record.cell_id에서 추출.
    """
    CREATE TABLE IF NOT EXISTS inbox_events (
        inbox_id VARCHAR(64) NOT NULL PRIMARY KEY,
        data JSON NOT NULL,
        cell_id VARCHAR(64) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.cell_id'))) STORED,
        ts VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.created_at'))) STORED,
        ts_date VARCHAR(10) AS (SUBSTRING(JSON_UNQUOTE(JSON_EXTRACT(data, '$.created_at')), 1, 10)) STORED,
        type VARCHAR(64) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.type'))) STORED,
        status VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.status'))) STORED,
        ref_id VARCHAR(64) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.ref'))) STORED,
        owner VARCHAR(255) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.owner'))) STORED,
        INDEX idx_date (ts_date),
        INDEX idx_status (status, ts_date),
        INDEX idx_cell (cell_id, ts_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,

    # auth_login_log: 로그인 시도 이력. 글로벌.
    """
    CREATE TABLE IF NOT EXISTS auth_login_log (
        login_id VARCHAR(64) NOT NULL PRIMARY KEY,
        data JSON NOT NULL,
        ts VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.ts'))) STORED,
        ts_date VARCHAR(10) AS (SUBSTRING(JSON_UNQUOTE(JSON_EXTRACT(data, '$.ts')), 1, 10)) STORED,
        email VARCHAR(255) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.email'))) STORED,
        success TINYINT(1) AS (
            CASE
                WHEN JSON_EXTRACT(data, '$.success') = CAST('true' AS JSON) THEN 1
                ELSE 0
            END
        ) STORED,
        INDEX idx_email (email, ts),
        INDEX idx_date (ts_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,

    # (wake_versions 테이블 제거: wake_bus 가 in-process pubsub 으로 회귀해
    #  cross-process DB 신호 불필요. 기존 배포의 빈 테이블은 무해 — 필요 시
    #  수동 DROP. hub 다중 replica 확장 시 외부 bus(Kafka)로 대체 예정.)

    # entity_seq: (cell_id, entity_type) 별 단조 카운터. canonical id
    # `<CELL>-<TYPE>-<SEQ>` 의 SEQ 발급원. idgen.alloc_seq 가 INSERT ...
    # ON DUPLICATE KEY UPDATE 한 문장으로 원자 증가. 이 테이블 존재 여부가
    # 신 ID 체계 적용 sentinel — init_schema 가 최초 1회 wipe 판단에 사용.
    """
    CREATE TABLE IF NOT EXISTS entity_seq (
        cell_id VARCHAR(64) NOT NULL,
        entity_type VARCHAR(32) NOT NULL,
        next_seq BIGINT NOT NULL DEFAULT 0,
        PRIMARY KEY (cell_id, entity_type)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,

    # worker heartbeat 공유 저장 (INFRA-ISSUE-284): 옛 in-memory _HEARTBEATS dict 대체.
    # multi-replica/롤아웃 overlap 에서 어느 pod 가 받아도 일관된 워커 목록. worker_id PK
    # (워커당 단일 writer 라 CAS 불필요 — UPSERT). last_seen TTL prune.
    """
    CREATE TABLE IF NOT EXISTS worker_heartbeats (
        worker_id VARCHAR(128) NOT NULL PRIMARY KEY,
        data JSON NOT NULL,
        cell_id VARCHAR(64) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.cell_id'))) STORED,
        issue_id VARCHAR(64) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.issue_id'))) STORED,
        last_seen VARCHAR(64) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.last_seen'))) STORED,
        INDEX idx_last_seen (last_seen),
        INDEX idx_cell_seen (cell_id, last_seen)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
]


# 기존 테이블에 새 generated column / index를 idempotent로 추가하는 패치 정의.
# (MySQL Oracle 8.x는 ADD COLUMN IF NOT EXISTS 미지원이라 INFORMATION_SCHEMA 조회로 idempotency 직접 구현.)
_TABLE_PATCHES: dict[str, dict[str, list]] = {
    "audit_actions": {
        "columns": [
            ("principal_id", "VARCHAR(128) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.principal_id'))) STORED"),
            ("principal_type", "VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.principal_type'))) STORED"),
            ("session_id", "VARCHAR(128) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.session_id'))) STORED"),
            ("session_type", "VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.session_type'))) STORED"),
            ("trace_id", "VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.trace_id'))) STORED"),
            ("span_id", "VARCHAR(16) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.span_id'))) STORED"),
            ("parent_span_id", "VARCHAR(16) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.parent_span_id'))) STORED"),
        ],
        "indexes": [
            ("idx_principal", "principal_id, ts_date"),
            ("idx_session", "session_id"),
            ("idx_session_type", "session_type, ts_date"),
            ("idx_trace", "trace_id, ts"),
        ],
        "drop_columns": ["actor"],
    },
    # issues/projects/signals 의 seq 는 더 이상 AUTO_INCREMENT 가 아니다 — entity_seq
    # 에서 발급해 app 이 채운다. 신 ID 체계 전환 시 해당 테이블은 wipe+recreate
    # 되므로 seq 컬럼 패치 불필요 (CREATE 문이 plain `seq BIGINT NULL` 로 생성).
    "events": {
        "columns": [
            ("principal_id", "VARCHAR(128) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.principal_id'))) STORED"),
            ("principal_type", "VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.principal_type'))) STORED"),
            ("session_id", "VARCHAR(128) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.session_id'))) STORED"),
            ("trace_id", "VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.trace_id'))) STORED"),
            ("span_id", "VARCHAR(16) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.span_id'))) STORED"),
            ("parent_span_id", "VARCHAR(16) AS (JSON_UNQUOTE(JSON_EXTRACT(data, '$.parent_span_id'))) STORED"),
        ],
        "indexes": [
            ("idx_principal", "principal_id, ts"),
            ("idx_session", "session_id"),
            ("idx_trace", "trace_id, ts"),
        ],
        "drop_columns": ["actor"],
    },
}


def _patch_table(conn, table: str, patch: dict) -> None:
    cols = {row[0] for row in conn.execute(text(
        f"SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        f"WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '{table}'"
    ))}
    for col, defn in patch.get("columns", []):
        if col not in cols:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {defn}"))
            log.info(f"[db] {table}: ADD COLUMN {col}")
    for col in patch.get("drop_columns", []):
        if col in cols:
            conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {col}"))
            log.info(f"[db] {table}: DROP COLUMN {col}")
    idx = {row[0] for row in conn.execute(text(
        f"SELECT INDEX_NAME FROM INFORMATION_SCHEMA.STATISTICS "
        f"WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '{table}'"
    ))}
    for name, expr in patch.get("indexes", []):
        if name not in idx:
            conn.execute(text(f"ALTER TABLE {table} ADD INDEX {name} ({expr})"))
            log.info(f"[db] {table}: ADD INDEX {name}")


# 신 ID 체계 전환 시 1회 비우고 새 스키마로 재생성할 엔티티 테이블.
# cells/auth_login_log 는 보존 (셀 레지스트리·인증로그). 더 이상 생성하지 않는
# 레거시 wake_versions 가 배포에 남아 있어도 _WIPE_TABLES 밖이라 그대로 둔다.
_WIPE_TABLES = (
    "projects", "issues", "labels", "events", "signals",
    "audit_actions", "inbox_events",
)


def _should_wipe_for_id_scheme(
    *, entity_seq_exists: bool, populated_tables: list[str], force: bool
) -> bool:
    """신 ID 체계 wipe 여부 판단 (DB 비의존 순수 함수 — 단위 테스트 대상).

    - entity_seq 존재 → 이미 신 체계, wipe 안 함 (멱등).
    - 부재 + populated 엔티티 테이블 존재 + force 아님 → entity_seq 만 비정상
      유실된 상태로 보고 wipe 차단 (live 데이터 보존). INFRA-ISSUE-321.
    - 부재 + (모두 비어있음 or force) → wipe. 신규 설치는 무해(no-op DROP),
      force 는 의도된 ID 체계 재전환.
    """
    if entity_seq_exists:
        return False
    if populated_tables and not force:
        return False
    return True


def _populated_wipe_tables(conn) -> list[str]:
    """_WIPE_TABLES 중 실재하면서 행이 1개 이상인 테이블 (선언 순서대로).

    존재하지 않는 테이블은 건너뛴다 — INFORMATION_SCHEMA 로 실재를 먼저 확인해
    없는 테이블에 COUNT(*) 를 던지지 않는다.
    """
    populated: list[str] = []
    for tbl in _WIPE_TABLES:
        exists = conn.execute(text(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
        ), {"t": tbl}).scalar()
        if not exists:
            continue
        if conn.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar():
            populated.append(tbl)
    return populated


def _maybe_wipe_for_id_scheme(conn) -> None:
    """`entity_seq` 부재 = 신 `<CELL>-<TYPE>-<SEQ>` ID 체계 최초 적용.

    이때 한정해 기존 UUID 엔티티 테이블을 DROP — 직후 _SCHEMA_STATEMENTS 의
    CREATE 가 새 스키마(plain seq, AUTO_INCREMENT 없음)로 재생성한다.
    entity_seq 생성이 sentinel 이라 이후 배포에선 이 분기를 타지 않아 멱등.
    빈 DB(신규 설치)에서도 DROP IF EXISTS 라 무해.

    가드(INFRA-ISSUE-321): entity_seq 만 유실되고 엔티티 테이블은 살아있는
    비정상 상태(부분 복원·수동 ops·실패한 마이그레이션)에선 sentinel 만 보고
    DROP 하면 live 데이터가 비가역 소실된다. populated 테이블이 하나라도 있으면
    명시적 override(ALLOW_ID_SCHEME_WIPE=1) 없이는 wipe 하지 않는다.
    """
    seq_exists = bool(conn.execute(text(
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'entity_seq'"
    )).scalar())
    force = os.environ.get("ALLOW_ID_SCHEME_WIPE", "").strip().lower() in ("1", "true", "yes")
    # entity_seq 가 이미 있으면(평시) populated 조회를 건너뛴다 — 빠른 경로 유지.
    populated = [] if seq_exists else _populated_wipe_tables(conn)
    if not _should_wipe_for_id_scheme(
        entity_seq_exists=seq_exists, populated_tables=populated, force=force
    ):
        if populated:
            log.error(
                "[db] entity_seq 부재이나 엔티티 테이블에 데이터 존재 — wipe 중단(데이터 보존). "
                "의도된 ID 체계 재전환이면 ALLOW_ID_SCHEME_WIPE=1 로 재기동. populated: %s",
                ", ".join(populated),
            )
        return
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    for tbl in _WIPE_TABLES:
        conn.execute(text(f"DROP TABLE IF EXISTS {tbl}"))
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    log.warning(
        "[db] 신 ID 체계 최초 적용 — 기존 엔티티 테이블 wipe: %s",
        ", ".join(_WIPE_TABLES),
    )


def _migrate_goal_task_to_project_issue(conn) -> None:
    """기존 goals/tasks 테이블 데이터를 신 projects/issues 로 이관 + ID 재합성.

    멱등 — 구 테이블 부재 시 no-op. 한 번 실행하면 RENAME TABLE 로 _legacy
    suffix 가 붙어 다음 부트스트랩에선 분기 안 탐. 롤백 대비 DROP 안 하고 보존.
    """
    has_old_goals = conn.execute(text(
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'goals'"
    )).scalar()
    has_old_tasks = conn.execute(text(
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tasks'"
    )).scalar()
    if not has_old_goals and not has_old_tasks:
        return

    log.warning("[db] Goal/Task → Project/Issue migration 시작")
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    moved_projects = 0
    moved_issues = 0

    if has_old_goals:
        rows = conn.execute(text(
            "SELECT cell_id, goal_id, seq, data FROM goals"
        )).fetchall()
        for cell_id, old_id, seq, data_raw in rows:
            new_id = old_id.replace('-GOAL-', '-PROJECT-')
            data = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
            if isinstance(data, dict):
                if 'goal_id' in data:
                    data['project_id'] = data.pop('goal_id')
                if isinstance(data.get('id'), str):
                    data['id'] = data['id'].replace('-GOAL-', '-PROJECT-')
            new_data = json.dumps(data).replace('-GOAL-', '-PROJECT-')
            conn.execute(text(
                "INSERT IGNORE INTO projects (cell_id, project_id, seq, data) "
                "VALUES (:c, :i, :s, :d)"
            ), {"c": cell_id, "i": new_id, "s": seq, "d": new_data})
            moved_projects += 1
        conn.execute(text("RENAME TABLE goals TO goals_legacy"))

    if has_old_tasks:
        rows = conn.execute(text(
            "SELECT cell_id, task_id, seq, data FROM tasks"
        )).fetchall()
        for cell_id, old_id, seq, data_raw in rows:
            new_id = old_id.replace('-TASK-', '-ISSUE-')
            data = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
            if isinstance(data, dict):
                if 'task_id' in data:
                    data['issue_id'] = data.pop('task_id')
                if 'goal_id' in data:
                    data['project_id'] = data.pop('goal_id')
                if isinstance(data.get('id'), str):
                    data['id'] = data['id'].replace('-TASK-', '-ISSUE-')
            new_data = (json.dumps(data)
                        .replace('-TASK-', '-ISSUE-')
                        .replace('-GOAL-', '-PROJECT-'))
            conn.execute(text(
                "INSERT IGNORE INTO issues (cell_id, issue_id, seq, data) "
                "VALUES (:c, :i, :s, :d)"
            ), {"c": cell_id, "i": new_id, "s": seq, "d": new_data})
            moved_issues += 1
        conn.execute(text("RENAME TABLE tasks TO tasks_legacy"))

    conn.execute(text(
        "INSERT IGNORE INTO entity_seq (cell_id, entity_type, next_seq) "
        "SELECT cell_id, 'project', next_seq FROM entity_seq WHERE entity_type='goal'"
    ))
    conn.execute(text("DELETE FROM entity_seq WHERE entity_type='goal'"))
    conn.execute(text(
        "INSERT IGNORE INTO entity_seq (cell_id, entity_type, next_seq) "
        "SELECT cell_id, 'issue', next_seq FROM entity_seq WHERE entity_type='task'"
    ))
    conn.execute(text("DELETE FROM entity_seq WHERE entity_type='task'"))

    conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    log.warning(
        "[db] migration 완료 — goals→projects (%d rows), tasks→issues (%d rows). "
        "구 테이블 보존: goals_legacy / tasks_legacy",
        moved_projects, moved_issues,
    )


def _drop_initiative_updates(conn) -> None:
    """initiative_updates 테이블·seq 제거 (health 축 폐지, INFRA-ISSUE-207).

    멱등 — 테이블/seq 부재 시 no-op (DROP TABLE IF EXISTS / DELETE WHERE).
    health 평가는 더 이상 별도 엔티티가 아니라 Initiative 타임라인(event.add)
    narrative 로 남으므로 이력 row 는 폐기한다 (사용자 확정: drop).
    """
    exists = conn.execute(text(
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'initiative_updates'"
    )).scalar()
    has_seq = conn.execute(text(
        "SELECT COUNT(*) FROM entity_seq WHERE entity_type = 'initiative_update'"
    )).scalar()
    if not exists and not has_seq:
        return
    conn.execute(text("DROP TABLE IF EXISTS initiative_updates"))
    conn.execute(text("DELETE FROM entity_seq WHERE entity_type = 'initiative_update'"))
    log.warning("[db] initiative_updates 테이블·seq 제거 (health 축 폐지, INFRA-ISSUE-207)")


def init_schema(*, retries: int = 12, backoff: float = 2.5) -> None:
    """모든 phase의 테이블을 IF NOT EXISTS로 보장. hub startup에서 호출.

    MySQL이 hub보다 늦게 ready될 수 있어 짧은 재시도로 감싼다 (총 ~30초).
    실패 시 예외를 다시 던져서 pod 재시작을 유도.
    """
    import time
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            eng = get_engine()
            with eng.begin() as conn:
                _maybe_wipe_for_id_scheme(conn)
                for stmt in _SCHEMA_STATEMENTS:
                    conn.execute(text(stmt))
                _migrate_goal_task_to_project_issue(conn)
                _drop_initiative_updates(conn)
                for table, patch in _TABLE_PATCHES.items():
                    _patch_table(conn, table, patch)
            log.info("[db] schema bootstrap 완료")
            return
        except Exception as exc:
            last_exc = exc
            if attempt + 1 < retries:
                log.warning(f"[db] schema init 재시도 {attempt + 1}/{retries}: {exc}")
                time.sleep(backoff)
    raise RuntimeError(f"schema init failed after {retries} retries") from last_exc


def health_check() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        log.warning(f"[db] health check 실패: {exc}")
        return False
