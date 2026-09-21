"""Thread-safe session store for entity-scoped agent sessions."""

from .models import EntitySession


class SessionStore:
    def __init__(self, *, max_uses: int):
        self.max_uses = max_uses
        self._sessions: dict[str, EntitySession] = {}

    def get_or_create(self, entity_id: str) -> EntitySession:
        if entity_id not in self._sessions:
            self._sessions[entity_id] = EntitySession(entity_id=entity_id)
        session = self._sessions[entity_id]
        with session.lock:
            if session.use_count >= self.max_uses:
                session.session_id = None
                session.use_count = 0
                session.last_prompt_at = None
        return session

    def reset(self, entity_id: str) -> bool:
        session = self._sessions.get(entity_id)
        if not session:
            return False
        with session.lock:
            session.session_id = None
            session.use_count = 0
            session.last_prompt_at = None
        return True

    def active_session_ids(self) -> set[str]:
        active: set[str] = set()
        for session in self._sessions.values():
            with session.lock:
                if session.session_id:
                    active.add(session.session_id)
        return active
