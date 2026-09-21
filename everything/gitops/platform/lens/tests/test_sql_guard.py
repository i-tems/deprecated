"""sql_guard 회귀 테스트 — read-only 단일 SELECT/WITH 만 통과, 쓰기/다중문 거부."""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from app.sql_guard import SqlGuardError, guard_sql  # noqa: E402


@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "select dt, sum(value) from polaris.metrics.metric_fact group by dt",
    "WITH t AS (SELECT 1 AS a) SELECT a FROM t",
    "SELECT updated_at, created_at FROM x",            # 식별자에 forbidden 부분문자열
    "SELECT dims['entity_id'] FROM x WHERE metric='lifecycle.created'",
    "  SELECT 1 ;  ",                                   # 끝 세미콜론 1개는 허용(정규화)
])
def test_allows_read_only(sql):
    assert guard_sql(sql)


@pytest.mark.parametrize("sql", [
    "",
    "   ",
    "INSERT INTO x VALUES (1)",
    "UPDATE x SET a=1",
    "DELETE FROM x",
    "DROP TABLE x",
    "CREATE TABLE x (a int)",
    "TRUNCATE TABLE x",
    "SELECT 1; DROP TABLE x",                            # 다중문
    "SELECT 1; SELECT 2",
    "MERGE INTO x ...",
    "REFRESH TABLE x",
])
def test_rejects_writes_and_multi(sql):
    with pytest.raises(SqlGuardError):
        guard_sql(sql)


def test_strips_comment_injected_write():
    # 주석 제거 후에도 본문이 SELECT 면 통과, 주석 속 키워드는 무시.
    assert guard_sql("SELECT 1 -- DROP TABLE x")
    # 주석으로 위장한 실제 다중문은 거부.
    with pytest.raises(SqlGuardError):
        guard_sql("SELECT 1 /* x */; DELETE FROM y")
