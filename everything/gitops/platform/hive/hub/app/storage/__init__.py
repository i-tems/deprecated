"""Storage layer.

`read_jsonl`/`write_jsonl`/`append_jsonl` 및 `today_path` 등 path-기반 primitive 는
이름이 시사하는 것과 달리 모두 SQL(`storage.sql`) 로 dispatch 된다 — cells/{cell}/*
또는 글로벌 actions/inbox 경로 패턴 → 해당 테이블 row 연산. 이 shim 은 다음
정리 단계에서 entity-typed API 로 재구조화 예정이며, 그 전까지는 path 가
dispatch key 역할을 한다.

`{entity}_repo` 모듈(cells_repo 등) 은 같은 SQL 백엔드 위에 entity 타입별
직접 API 를 제공한다.
"""

from .jsonl import read_jsonl, write_jsonl, append_jsonl, entity_lock
from .date_store import (
    today_path, date_range_paths, find_by_id,
    all_partition_paths,
    iter_partitions_for_query,
)
from .entity_store import read_entity_file, write_entity_file, find_entity, get_entity_by_id
from . import cells_repo  # noqa: F401
