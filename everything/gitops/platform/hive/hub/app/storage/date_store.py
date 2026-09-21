"""Date-partition path helpers and lookup — SQL 백엔드 dispatch.

cells/{cell}/{kind}/ 디렉토리(events/signals) 와 글로벌 actions/inbox 디렉토리는
SQL 테이블로 라우팅된다 — date "path" 는 SQL 쿼리의 합성 키.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from .jsonl import read_jsonl
from .sql import (
    parse_date_dir_path,
    parse_global_date_dir_path,
    list_distinct_dates,
    get_date_for_record,
    date_dir_synthetic_path,
)


def _resolve_date_dir(path: Path):
    """cell-scoped 또는 global date dir 정보를 반환. 둘 다 아니면 None."""
    return parse_date_dir_path(path) or parse_global_date_dir_path(path)

_PARTITION_GLOB = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].jsonl"


def today_path(directory: Path) -> Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    info = _resolve_date_dir(directory)
    if info:
        # SQL 백엔드: 디스크에 디렉토리 안 만들고 합성 path만 반환
        return date_dir_synthetic_path(directory, today)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{today}.jsonl"


def date_range_paths(directory: Path, date_from: str | None, date_to: str | None) -> list[Path]:
    info = _resolve_date_dir(directory)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    end = date_to or today
    start = date_from or end
    if info:
        # SQL: 데이터 있는 날짜 중 범위 내만 합성 path
        all_dates = list_distinct_dates(info["table"], info["cell_id"])
        return [date_dir_synthetic_path(directory, d) for d in all_dates if start <= d <= end]
    paths = []
    current = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    while current <= end_dt:
        p = directory / f"{current.strftime('%Y-%m-%d')}.jsonl"
        if p.exists():
            paths.append(p)
        current += timedelta(days=1)
    return paths


def all_partition_paths(directory: Path) -> list[Path]:
    """디렉토리 내 모든 YYYY-MM-DD.jsonl 파티션을 시간순으로 반환."""
    info = _resolve_date_dir(directory)
    if info:
        return [date_dir_synthetic_path(directory, d) for d in list_distinct_dates(info["table"], info["cell_id"])]
    if not directory.exists():
        return []
    return sorted(directory.glob(_PARTITION_GLOB))


def iter_partitions_for_query(
    directory: Path,
    date_from: str | None,
    date_to: str | None,
    *,
    entity_scoped: bool,
) -> list[Path]:
    """entity-scoped 조회면 전수 스캔, 아니면 date 윈도우. 날짜가 명시되면 항상 date 윈도우."""
    if entity_scoped and not date_from and not date_to:
        return all_partition_paths(directory)
    return date_range_paths(directory, date_from, date_to)


def find_by_id(directory: Path, id_field: str, id_value: str, max_days: int | None = None) -> tuple[Path | None, list[dict] | None, dict | None]:
    """ID로 레코드 조회. max_days=None이면 전수 스캔, 아니면 최근 max_days일만 스캔.

    SQL 백엔드는 max_days 무시하고 직접 SELECT.
    """
    info = _resolve_date_dir(directory)
    if info:
        date = get_date_for_record(info["table"], id_field, info["cell_id"], id_value)
        if not date:
            return None, None, None
        synthetic = date_dir_synthetic_path(directory, date)
        entries = read_jsonl(synthetic)
        for e in entries:
            if e.get(id_field) == id_value:
                return synthetic, entries, e
        return None, None, None
    if max_days is None:
        paths = list(reversed(all_partition_paths(directory)))
    else:
        today = datetime.now(timezone.utc)
        paths = []
        for i in range(max_days):
            date = today - timedelta(days=i)
            p = directory / f"{date.strftime('%Y-%m-%d')}.jsonl"
            if p.exists():
                paths.append(p)
    for path in paths:
        entries = read_jsonl(path)
        for e in entries:
            if e.get(id_field) == id_value:
                return path, entries, e
    return None, None, None
