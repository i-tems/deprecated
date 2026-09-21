"""Entity read/write/find operations.

`cells/{cell}/{kind}.jsonl` path 패턴은 SQL 백엔드(`storage.sql`) 로 dispatch
되어 해당 테이블 row 연산을 수행한다. 매칭되지 않는 path 는 디스크 fallback
이지만 prod 에선 도달하지 않는다.
"""

from pathlib import Path

from .jsonl import read_jsonl, write_jsonl
from .sql import (
    parse_entity_path,
    list_entities,
    list_entities_all,
    get_entity,
    upsert_entity,
    replace_all_entities,
)


def read_entity_file(path: Path) -> list[dict]:
    info = parse_entity_path(path)
    if info:
        return list_entities(info["table"], info["cell_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return []
    return read_jsonl(path)


def write_entity_file(path: Path, entries: list[dict]):
    info = parse_entity_path(path)
    if info:
        replace_all_entities(info["table"], info["id_field"], info["cell_id"], entries)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(path, entries)


def find_entity(
    path: Path, id_field: str, id_value: str, *, include_deleted: bool = False,
) -> tuple[list[dict], dict | None]:
    info = parse_entity_path(path)
    if info and include_deleted:
        entries = list_entities_all(info["table"], info["cell_id"])
    else:
        entries = read_entity_file(path)
    for e in entries:
        if e.get(id_field) == id_value:
            return entries, e
    return entries, None


def get_entity_by_id(
    path: Path, id_field: str, id_value: str, *, include_deleted: bool = False,
) -> dict | None:
    """SQL 인덱스 lookup. find_entity 와 달리 entries 전체 list를 로드하지 않는다."""
    info = parse_entity_path(path)
    if info:
        e = get_entity(info["table"], id_field, info["cell_id"], id_value)
        if e and not include_deleted and e.get("deleted"):
            return None
        return e
    _, found = find_entity(path, id_field, id_value, include_deleted=include_deleted)
    return found
