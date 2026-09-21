"""Re-export bridge — ``from ..helpers import X`` 호환 유지."""

import os


def read_cell_token(cell_id: str) -> str | None:
    """hive-cell-tokens secret 에서 cell PAT 조회. 양쪽 watcher 공용."""
    from kubernetes import client as k8s, config as k8s_config
    import base64
    try:
        k8s_config.load_incluster_config()
    except Exception:
        k8s_config.load_kube_config()
    core = k8s.CoreV1Api()
    secret_name = os.environ.get("CELL_TOKENS_SECRET", "hive-cell-tokens")
    ns = os.environ.get("HUB_NAMESPACE", "hive")
    try:
        sec = core.read_namespaced_secret(name=secret_name, namespace=ns)
    except Exception:
        return None
    raw = (sec.data or {}).get(cell_id)
    return base64.b64decode(raw).decode() if raw else None


# Storage
from .storage import (
    read_jsonl, write_jsonl, append_jsonl, entity_lock,
    today_path, date_range_paths, find_by_id,
    all_partition_paths,
    iter_partitions_for_query,
    read_entity_file, find_entity, get_entity_by_id,
)

# URI normalization
from .uri import normalize_resource_uri, normalize_resources

# Events
from .events import emit_event, emit_inbox

# Signal linkage
from .signal_links import transition_linked_signals

# Owner resolution
from .owner import resolve_me_alias, resolve_owner

# Cursor pagination
from .cursor import decode_cursor, encode_cursor
