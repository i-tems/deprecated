"""읽기 전용 SQL 가드 (defense-in-depth).

query.sql 자체가 Kyuubi 단일 자격으로 read 만 보장하지만, 생성된 spec 의
SQL 이 앱을 통과하기 전 한 겹 더 막는다 (DDL/DML·다중문 거부). 토큰 단위
보수적 차단 — 거짓 거부(legit 쿼리에 forbidden 단어가 식별자로 등장)는
드물고, 거짓 통과보다 안전하다.
"""
import re

_COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)

# 쓰기·DDL·세션변경 계열. 식별자는 `[a-z_]+` 최대 매칭이라 updated_at/created_at
# 같은 컬럼명은 이 집합에 안 걸린다 (token='updated_at' ≠ 'update').
_FORBIDDEN = {
    "insert", "update", "delete", "merge", "upsert",
    "drop", "alter", "create", "truncate", "replace",
    "grant", "revoke", "call", "use", "set", "reset",
    "refresh", "analyze", "msck", "load", "optimize", "vacuum",
    "copy", "attach", "detach", "comment",
}


class SqlGuardError(Exception):
    pass


def guard_sql(sql: str) -> str:
    """read-only 단일 SELECT/WITH 만 허용. 통과 시 정규화된 SQL 반환."""
    if not sql or not sql.strip():
        raise SqlGuardError("empty sql")
    stripped = _COMMENT_RE.sub(" ", sql).strip().rstrip(";").strip()
    if ";" in stripped:
        raise SqlGuardError("multiple statements not allowed")
    low = stripped.lower()
    head = re.match(r"[a-z]+", low)
    if not head or head.group(0) not in ("select", "with"):
        raise SqlGuardError("only SELECT / WITH queries are allowed")
    bad = sorted(set(re.findall(r"[a-z_]+", low)) & _FORBIDDEN)
    if bad:
        raise SqlGuardError(f"forbidden keyword(s): {', '.join(bad)}")
    return stripped
