import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))

_lock = asyncio.Lock()


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _file_path(collection: str) -> Path:
    return DATA_DIR / f"{collection}.json"


def _read_collection(collection: str) -> list[dict]:
    path = _file_path(collection)
    if not path.exists():
        return []
    with open(path, "r") as f:
        return json.load(f)


def _write_collection(collection: str, data: list[dict]):
    _ensure_dir()
    path = _file_path(collection)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _new_id() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    """JSON file-based storage replacing PostgreSQL."""

    # --- Users ---

    async def get_user_by_id(self, user_id: str) -> dict | None:
        async with _lock:
            for u in _read_collection("users"):
                if u["id"] == user_id:
                    return u
        return None

    async def get_user_by_google_sub(self, google_sub: str) -> dict | None:
        async with _lock:
            for u in _read_collection("users"):
                if u["google_sub"] == google_sub:
                    return u
        return None

    async def create_user(self, email: str, name: str, avatar_url: str | None, google_sub: str) -> dict:
        user = {
            "id": _new_id(),
            "email": email,
            "name": name,
            "avatar_url": avatar_url,
            "google_sub": google_sub,
            "created_at": _now_iso(),
        }
        async with _lock:
            users = _read_collection("users")
            users.append(user)
            _write_collection("users", users)
        return user

    async def update_user(self, user_id: str, **fields) -> dict | None:
        async with _lock:
            users = _read_collection("users")
            for u in users:
                if u["id"] == user_id:
                    u.update(fields)
                    _write_collection("users", users)
                    return u
        return None

    # --- Groups ---

    async def get_groups_for_user(self, user_id: str) -> list[dict]:
        async with _lock:
            members = _read_collection("group_members")
            groups = _read_collection("groups")
        group_ids = {m["group_id"] for m in members if m["user_id"] == user_id}
        result = []
        for g in groups:
            if g["id"] in group_ids:
                count = sum(1 for m in members if m["group_id"] == g["id"])
                result.append({**g, "member_count": count})
        result.sort(key=lambda x: x["created_at"], reverse=True)
        return result

    async def create_group(self, name: str, created_by: str, invite_code: str) -> dict:
        group = {
            "id": _new_id(),
            "name": name,
            "invite_code": invite_code,
            "created_by": created_by,
            "created_at": _now_iso(),
        }
        async with _lock:
            groups = _read_collection("groups")
            groups.append(group)
            _write_collection("groups", groups)
        return group

    async def get_group_by_id(self, group_id: str) -> dict | None:
        async with _lock:
            for g in _read_collection("groups"):
                if g["id"] == group_id:
                    return g
        return None

    async def get_group_by_invite_code(self, invite_code: str) -> dict | None:
        async with _lock:
            for g in _read_collection("groups"):
                if g["invite_code"] == invite_code:
                    return g
        return None

    async def update_group(self, group_id: str, **fields) -> dict | None:
        async with _lock:
            groups = _read_collection("groups")
            for g in groups:
                if g["id"] == group_id:
                    g.update(fields)
                    _write_collection("groups", groups)
                    return g
        return None

    async def delete_group(self, group_id: str):
        async with _lock:
            groups = _read_collection("groups")
            groups = [g for g in groups if g["id"] != group_id]
            _write_collection("groups", groups)
            # Cascade delete members
            members = _read_collection("group_members")
            members = [m for m in members if m["group_id"] != group_id]
            _write_collection("group_members", members)

    # --- Group Members ---

    async def get_group_members(self, group_id: str) -> list[dict]:
        async with _lock:
            members = _read_collection("group_members")
            users = _read_collection("users")
        users_map = {u["id"]: u for u in users}
        result = []
        for m in members:
            if m["group_id"] == group_id:
                user = users_map.get(m["user_id"], {})
                result.append({
                    **m,
                    "user_name": user.get("name", ""),
                    "user_email": user.get("email", ""),
                    "user_avatar_url": user.get("avatar_url"),
                })
        return result

    async def get_group_member(self, group_id: str, user_id: str) -> dict | None:
        async with _lock:
            for m in _read_collection("group_members"):
                if m["group_id"] == group_id and m["user_id"] == user_id:
                    return m
        return None

    async def add_group_member(self, group_id: str, user_id: str, role: str) -> dict:
        member = {
            "id": _new_id(),
            "group_id": group_id,
            "user_id": user_id,
            "role": role,
            "joined_at": _now_iso(),
        }
        async with _lock:
            members = _read_collection("group_members")
            members.append(member)
            _write_collection("group_members", members)
        return member

    async def remove_group_member(self, group_id: str, user_id: str):
        async with _lock:
            members = _read_collection("group_members")
            members = [m for m in members if not (m["group_id"] == group_id and m["user_id"] == user_id)]
            _write_collection("group_members", members)

    async def get_member_user_ids(self, group_id: str) -> list[str]:
        async with _lock:
            members = _read_collection("group_members")
        return [m["user_id"] for m in members if m["group_id"] == group_id]

    # --- Schedule Blocks ---

    @staticmethod
    def _ensure_date_field(block: dict) -> dict:
        """Migrate old start_time/end_time blocks to date-only format."""
        if "date" not in block and "start_time" in block:
            block["date"] = block["start_time"][:10]
        return block

    async def get_schedule_blocks(self, user_id: str, start_date: str, end_date: str) -> list[dict]:
        async with _lock:
            blocks = _read_collection("schedule_blocks")
        result = []
        for b in blocks:
            self._ensure_date_field(b)
            if b["user_id"] == user_id and b.get("date", "") >= start_date and b.get("date", "") <= end_date:
                result.append(b)
        result.sort(key=lambda x: x.get("date", ""))
        return result

    async def get_schedule_blocks_for_users(self, user_ids: list[str], start_date: str, end_date: str) -> list[dict]:
        user_set = set(user_ids)
        async with _lock:
            blocks = _read_collection("schedule_blocks")
        result = []
        for b in blocks:
            self._ensure_date_field(b)
            if b["user_id"] in user_set and b.get("date", "") >= start_date and b.get("date", "") <= end_date:
                result.append(b)
        return result

    async def get_schedule_block_by_date(self, user_id: str, date: str) -> dict | None:
        async with _lock:
            for b in _read_collection("schedule_blocks"):
                self._ensure_date_field(b)
                if b["user_id"] == user_id and b.get("date") == date:
                    return b
        return None

    async def create_schedule_block(self, user_id: str, title: str | None, date: str,
                                     pattern_id: str | None = None) -> dict:
        block = {
            "id": _new_id(),
            "user_id": user_id,
            "title": title,
            "date": date,
            "pattern_id": pattern_id,
            "created_at": _now_iso(),
        }
        async with _lock:
            blocks = _read_collection("schedule_blocks")
            blocks.append(block)
            _write_collection("schedule_blocks", blocks)
        return block

    async def get_schedule_block(self, block_id: str, user_id: str) -> dict | None:
        async with _lock:
            for b in _read_collection("schedule_blocks"):
                if b["id"] == block_id and b["user_id"] == user_id:
                    return b
        return None

    async def update_schedule_block(self, block_id: str, user_id: str, **fields) -> dict | None:
        if "date" in fields and hasattr(fields["date"], "isoformat"):
            fields["date"] = fields["date"].isoformat()
        async with _lock:
            blocks = _read_collection("schedule_blocks")
            for b in blocks:
                if b["id"] == block_id and b["user_id"] == user_id:
                    b.update(fields)
                    _write_collection("schedule_blocks", blocks)
                    return b
        return None

    async def delete_schedule_block(self, block_id: str, user_id: str) -> bool:
        async with _lock:
            blocks = _read_collection("schedule_blocks")
            new_blocks = [b for b in blocks if not (b["id"] == block_id and b["user_id"] == user_id)]
            if len(new_blocks) == len(blocks):
                return False
            _write_collection("schedule_blocks", new_blocks)
            return True

    async def delete_all_schedule_blocks(self, user_id: str) -> int:
        async with _lock:
            blocks = _read_collection("schedule_blocks")
            new_blocks = [b for b in blocks if not (b["user_id"] == user_id and not b.get("pattern_id"))]
            count = len(blocks) - len(new_blocks)
            _write_collection("schedule_blocks", new_blocks)
            return count

    async def delete_blocks_by_pattern(self, pattern_id: str, user_id: str):
        async with _lock:
            blocks = _read_collection("schedule_blocks")
            blocks = [b for b in blocks if not (b.get("pattern_id") == pattern_id and b["user_id"] == user_id)]
            _write_collection("schedule_blocks", blocks)

    # --- Shift Patterns ---

    async def get_shift_patterns(self, user_id: str) -> list[dict]:
        async with _lock:
            patterns = _read_collection("shift_patterns")
        result = [p for p in patterns if p["user_id"] == user_id]
        result.sort(key=lambda x: x["created_at"], reverse=True)
        return result

    async def create_shift_pattern(self, user_id: str, name: str, pattern_data: dict, start_date: str) -> dict:
        pattern = {
            "id": _new_id(),
            "user_id": user_id,
            "name": name,
            "pattern_data": pattern_data,
            "start_date": start_date,
            "created_at": _now_iso(),
        }
        async with _lock:
            patterns = _read_collection("shift_patterns")
            patterns.append(pattern)
            _write_collection("shift_patterns", patterns)
        return pattern

    async def get_shift_pattern(self, pattern_id: str, user_id: str) -> dict | None:
        async with _lock:
            for p in _read_collection("shift_patterns"):
                if p["id"] == pattern_id and p["user_id"] == user_id:
                    return p
        return None

    async def update_shift_pattern(self, pattern_id: str, user_id: str, **fields) -> dict | None:
        async with _lock:
            patterns = _read_collection("shift_patterns")
            for p in patterns:
                if p["id"] == pattern_id and p["user_id"] == user_id:
                    p.update(fields)
                    _write_collection("shift_patterns", patterns)
                    return p
        return None

    async def delete_shift_pattern(self, pattern_id: str, user_id: str) -> bool:
        async with _lock:
            patterns = _read_collection("shift_patterns")
            new_patterns = [p for p in patterns if not (p["id"] == pattern_id and p["user_id"] == user_id)]
            if len(new_patterns) == len(patterns):
                return False
            _write_collection("shift_patterns", new_patterns)
            # Set pattern_id to None on related schedule blocks
            blocks = _read_collection("schedule_blocks")
            for b in blocks:
                if b.get("pattern_id") == pattern_id:
                    b["pattern_id"] = None
            _write_collection("schedule_blocks", blocks)
            return True


storage = Storage()
