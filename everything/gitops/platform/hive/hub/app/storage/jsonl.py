"""path 기반 read/write/append primitives — SQL 백엔드 dispatch.

호출자는 옛 JSONL 인터페이스로 보이지만, path 가 `storage.sql` 의 dispatch
규칙에 매칭되면 INSERT/UPSERT/SELECT 로 라우팅된다 (prod 에선 모든 path 가
매칭). dispatch shim 은 다음 정리 단계에서 entity-typed API 로 재구조화 예정.

RMW(read-modify-write) 트랜잭션이 필요한 호출자는 `entity_lock` 으로 외부
직렬화한다.
"""

import contextlib
import contextvars
import fcntl
import hashlib
import json
import os
import tempfile
from pathlib import Path

# 락 파일은 /tmp(pod-local)에 보관. NFS 데이터 경로에 stub 빈 파일이 남지 않도록.
# hub은 단일 replica(Recreate 전략)이므로 cross-pod 락 불필요.
_LOCK_DIR = Path(os.environ.get("ENTITY_LOCK_DIR", "/tmp/hive-entity-locks"))

# 현재 실행 컨텍스트(같은 async task / 같은 호출 체인)가 이미 보유 중인 lock key 집합.
# 재진입 감지용 — contextvars 라 같은 task 의 await 체인·그 안의 sync 호출까지 전파되고
# 다른 task 끼리는 격리된다 (threadpool 은 schedule 시점 context 를 복사).
_held_lock_keys: contextvars.ContextVar = contextvars.ContextVar(
    "entity_lock_held", default=frozenset()
)


@contextlib.contextmanager
def entity_lock(path: Path):
    """RMW 트랜잭션을 호출자가 보호할 때 쓰는 외부 락 (OFD 단위 EX flock).

    SQL-라우팅 경로든 filesystem 경로든 동일하게 /tmp의 sentinel 파일에 flock.

    재진입(reentrant): 같은 실행 컨텍스트가 같은 path 를 이미 보유 중이면 새 flock 을
    잡지 않고 no-op 으로 통과한다. enclosing lock 이 이미 file 을 보호하므로 안전하고,
    같은-프로세스·다른-fd flock 의 self-deadlock 을 막는다 (INFRA-ISSUE-277:
    issue_update 가 lock 보유 중 emit_event→_touch_entity_activity 가 같은 file 재획득).

    [중요 불변식] 이 블록 안에서 절대 ``await``를 쓰지 말 것. flock은 동기 syscall이라
    이벤트 루프를 블록한다 — 다른 task 의 코루틴이 같은 lock 을 기다리는 동안 현재
    코루틴이 await로 yield하면 cross-task 데드락(재진입은 같은 컨텍스트만 막는다).
    async 함수에서 호출해도 critical section은 purely sync여야 한다.
    """
    key = hashlib.md5(str(path).encode()).hexdigest()
    held = _held_lock_keys.get()
    if key in held:
        # 같은 컨텍스트에서 이미 보유 — 재진입. 새 flock 금지(self-deadlock 방지).
        yield
        return
    _LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = _LOCK_DIR / key
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        token = _held_lock_keys.set(held | {key})
        try:
            yield
        finally:
            _held_lock_keys.reset(token)
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def read_jsonl(path: Path) -> list[dict]:
    from .sql import parse_date_file_path, parse_global_date_file_path, list_date_records_in_date
    info = parse_date_file_path(path) or parse_global_date_file_path(path)
    if info:
        return list_date_records_in_date(info["table"], info["cell_id"], info["date"])
    if not path.exists():
        return []
    text = path.read_text()
    entries = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def write_jsonl(path: Path, entries: list[dict]):
    """원자적 교체: 같은 디렉터리에 임시 파일로 쓴 뒤 rename. 호출자는 entity_lock으로 직렬화한다.

    cells/{cell}/{kind}/YYYY-MM-DD.jsonl 패턴은 SQL 백엔드 — 해당 날짜 row만 교체.
    """
    from .sql import parse_date_file_path, parse_global_date_file_path, replace_date_records_in_date
    info = parse_date_file_path(path) or parse_global_date_file_path(path)
    if info:
        replace_date_records_in_date(info["table"], info["id_field"], info["cell_id"], info["date"], entries)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def append_jsonl(path: Path, entry: dict):
    """O_APPEND atomic write. PIPE_BUF 미만 한 줄은 POSIX가 atomic 보장.

    SQL-매핑된 path는 INSERT(date) 또는 UPSERT(entity)로 라우팅.
    """
    from .sql import (
        parse_entity_path,
        parse_date_file_path,
        parse_global_date_file_path,
        upsert_entity,
        insert_date_record,
    )
    e_info = parse_entity_path(path)
    if e_info:
        upsert_entity(e_info["table"], e_info["id_field"], e_info["cell_id"], entry)
        return
    d_info = parse_date_file_path(path) or parse_global_date_file_path(path)
    if d_info:
        insert_date_record(d_info["table"], d_info["id_field"], d_info["cell_id"], entry)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
