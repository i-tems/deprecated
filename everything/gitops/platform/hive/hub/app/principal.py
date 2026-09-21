"""Caller Identity primitive.

모든 hub 호출은 인증된 Principal에 귀속된다. AuthMiddleware가 caller token을
디코드하거나 console JWT/legacy internal token에서 합성하여
request.state.principal에 채운다. 이후 미들웨어/핸들러는 이 단일 객체에서
호출자 신원을 읽는다.
"""

from __future__ import annotations

from dataclasses import dataclass


PRINCIPAL_TYPES = {"worker", "user", "system", "cli"}


@dataclass(frozen=True)
class Principal:
    type: str                       # worker | user | system | cli
    id: str                         # 예: "worker:w-019dfd6b"
    cell_id: str | None = None      # cell scope (worker/user). system은 None
    issue_id: str | None = None      # issue scope (worker)
    session_type: str | None = None # issue_progress | project_progress (worker, 단일 progress phase)
    actor_email: str | None = None  # 사람 사용자 이메일

    @classmethod
    def from_claims(cls, claims: dict) -> "Principal | None":
        ptype = claims.get("principal_type")
        pid = claims.get("principal_id")
        if ptype not in PRINCIPAL_TYPES or not pid:
            return None
        return cls(
            type=ptype,
            id=pid,
            cell_id=claims.get("cell_id"),
            issue_id=claims.get("issue_id"),
            session_type=claims.get("session_type"),
            actor_email=claims.get("actor_email"),
        )

    def to_claims(self) -> dict:
        out = {"principal_type": self.type, "principal_id": self.id}
        for k in ("cell_id", "issue_id", "session_type", "actor_email"):
            v = getattr(self, k)
            if v is not None:
                out[k] = v
        return out
