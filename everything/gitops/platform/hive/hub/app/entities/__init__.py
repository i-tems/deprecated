"""entities 공용 헬퍼 — issue / project 동일 패턴 처리."""

from datetime import datetime, timezone

from capability_framework import CapabilityResponse

from ..helpers import (
    emit_event, emit_inbox, entity_lock, find_entity,
    normalize_resources, read_entity_file, resolve_owner,
    transition_linked_signals,
)
from ..models import compute_priority_score
from ..storage.sql import cas_update_entity, parse_entity_path


def cas_entity(cp, entity_type: str, entity_id: str, mutate):
    """단일 entity 를 per-entity optimistic CAS 로 read-modify-write (INFRA-ISSUE-284).

    ``mutate(found: dict) -> CapabilityResponse | None``:
      - None: found(클로저가 in-place 수정) 를 rev-guard 로 쓰고 found 반환.
      - CapabilityResponse: abort (쓰기 안 함) — 검증 실패 등.
    반환: 성공 시 found(dict) / 행 없음 시 None / abort 시 그 CapabilityResponse.

    셀 전체 재기록(write_entity_file) 대체 — 충돌 표면이 엔티티 단위, cross-pod lost-update
    방지. get_entity 는 deleted row 도 반환하므로 delete/restore 경로도 그대로 동작한다.
    transition 중에는 호출부가 entity_lock 을 유지해 미변환 whole-cell writer 와 within-pod
    직렬화한다.
    """
    table = parse_entity_path(_entity_file(cp, entity_type))["table"]
    id_field = f"{entity_type}_id"

    def _apply(found):
        if found is None:
            return (None, None)
        abort = mutate(found)
        if abort is not None:
            return (abort, None)
        return (found, found)

    return cas_update_entity(table, id_field, cp.cell_id, entity_id, _apply)

# terminal 자식 상태 — entity_type 별로 분리 (status 모델이 fork 됨).
#   - issue: 8-status worker 모델 (done/cancelled/error).
#   - container(project/initiative): 4-status 모델 (done/archive).
_ISSUE_TERMINAL = {"done", "cancelled", "error"}
_CONTAINER_TERMINAL = {"done", "archive"}

# 종결 전이 가드 (project_issue_model.md §2). *.update 만 강제, *.force_update 우회.


def terminal_transition_denied(old: str, new: str) -> str | None:
    """ISSUE 전용 종결 전이 가드. cleanup 외 상태에서 done/cancelled 직접 전이 거부 사유. 허용이면 None.

    - 모든 종결(done·cancelled)은 cleanup 경유 → cleanup 에서만 가능.
    운영자·error 복구 우회: issue.force_update.
    """
    if new == old:
        return None
    if new in ("done", "cancelled") and old != "cleanup":
        return f"'{old}' → '{new}' 직접 전이 금지 — 종결은 cleanup 경유 (force_update 로 우회)."
    return None


def container_transition_denied(old: str, new: str, completion_gate: str) -> str | None:
    """CONTAINER(Project/Initiative) 종결 전이 가드. 거부 사유, 허용이면 None.

    5-status 모델 (backlog/active/waiting/done/archive) — cleanup 중간 상태 없음.
    - terminal 집합 = {done, archive}: terminal 에서 나가는 전이 금지 (재개하려면
      force_update). waiting 은 NON-terminal — 자유롭게 active/done/archive 로 나감.
    - completion=auto(기본)/skip: active→done 직접 허용 (cleanup 경유 불필요).
    - completion=require: active→done 직접 금지 (워커가 active→waiting 핸드오프,
      사람이 waiting→done 확정). waiting→done 은 항상 허용 (사람 확정 경로).
    - archive (terminal) 는 어느 비-terminal 상태(backlog/active/waiting)에서도 직접 허용.
    - 그 외(backlog↔active, active↔waiting, 역전이 등) 자유.
    가드 우회: project.force_update.
    """
    if new == old:
        return None
    if old in _CONTAINER_TERMINAL:
        return (
            f"'{old}' 는 terminal — '{new}' 로의 전이 금지 (재개·정정은 force_update 로 우회)."
        )
    # active→done 직접 전이만 completion=require 에서 차단 (워커 핸드오프 후 사람 확정).
    # waiting→done 은 require 라도 허용 — 그게 사람 확정 경로다.
    if new == "done" and old == "active" and completion_gate == "require":
        return (
            f"'{old}' → 'done' 직접 전이 금지 — gates.completion=require "
            "(워커가 active→waiting 핸드오프, 사람이 waiting→done 확정, force_update 로 우회)."
        )
    return None


def _entity_file(cp, entity_type: str):
    if entity_type == "issue":
        return cp.issue_file
    if entity_type == "initiative":
        return cp.initiative_file
    if entity_type == "label":
        return cp.label_file
    return cp.project_file


def _cascade_cancel_active_children(cp, project_id: str, principal, sid: str | None) -> None:
    """project 사람 강제 terminal 시 active 자식 issue 들을 cancelled 로 일괄 cancel.

    AI 가 project 을 terminal 로 전이할 때는 spec 지시 (자식 먼저 정리) 를 따라야 한다.
    사람 console JWT 가 project terminal 로 직접 잡았을 때만 cascade 가 동작 — 자식
    worker 들이 entity-level wake bus 로 즉시 terminal 감지.
    """
    now = datetime.now(timezone.utc).isoformat()

    def _cancel(found):
        if found.get("deleted") or found.get("status") in _ISSUE_TERMINAL:
            return  # 이미 terminal/deleted (cross-pod 재read 시 달라졌을 수 있음) — skip
        found["status"] = "cancelled"
        found["updated_at"] = now

    with entity_lock(cp.issue_file):
        entries = read_entity_file(cp.issue_file)
        targets: list[tuple[str, str, list]] = [
            (t["issue_id"], t["status"], t.get("source_signal_ids") or [])
            for t in entries
            if not t.get("deleted")
            and t.get("project_id") == project_id
            and t.get("status") not in _ISSUE_TERMINAL  # 자식은 issue — issue terminal 집합.
        ]
        for issue_id, _old, _src in targets:
            cas_entity(cp, "issue", issue_id, _cancel)
    for issue_id, old, src in targets:
        emit_event(
            "issue", issue_id, "status_change",
            {"from": old, "to": "cancelled"},
            event_dir=cp.event_dir, session_id=sid, principal=principal,
            cascade_to=[project_id, f"cell:{cp.cell_id}"],
        )
        # reverse 링크(자식 issue.source_signal_ids ∈ signal)도 reopen — 단일 취소 경로와
        # 동일. None 이면 forward 링크(signal.issue_id) 만 매칭돼 reverse-only signal 이
        # triage 큐로 돌아오지 못한다 (INFRA-ISSUE-322).
        transition_linked_signals(
            cp.signal_dir,
            entity_type="issue",
            entity_id=issue_id,
            source_signal_ids=src,
            entity_status="cancelled",
        )


def entity_set_session(
    *, cp, entity_type: str, entity_id: str,
    session_id: str | None, last_prompt_at: str | None,
) -> CapabilityResponse:
    """issue / project 의 활성 Claude session_id + last_prompt_at 영구화. worker 전용.

    last_prompt_at 은 다음 워커가 풀 컨텍스트 대신 델타만 주입하도록 cursor 역할 — claude
    가 --resume 으로 이미 conversation history 를 갖고 있으므로 sibling/signals/old events
    재주입은 토큰 낭비. session_id 가 None 이면 cursor 도 같이 clear.
    """
    id_field = f"{entity_type}_id"
    file = _entity_file(cp, entity_type)

    def _mutate(found):
        if session_id:
            found["session_id"] = session_id
        else:
            found.pop("session_id", None)
        if last_prompt_at:
            found["last_prompt_at"] = last_prompt_at
        elif session_id is None:
            found.pop("last_prompt_at", None)
        found["updated_at"] = datetime.now(timezone.utc).isoformat()

    with entity_lock(file):
        res = cas_entity(cp, entity_type, entity_id, _mutate)
    if res is None:
        return CapabilityResponse(status="error", error_code="not_found", message=f"{entity_type} {entity_id} not found")
    return CapabilityResponse(status="ok", data={
        id_field: entity_id,
        "session_id": session_id,
        "last_prompt_at": last_prompt_at,
    })


# field_change 이벤트로 활동피드에 남길 필드. update 적용 전 스냅샷(old_vals)을
# 떠 적용 후 값과 다르면 field_change 발행 — Linear 가 assignee/priority 등 모든
# 필드 변경을 activity 에 남기는 것과 동일한 감사성.
# 제외: priority_score(priority 파생값), labels/dependencies/hold(자체 변경 플래그로
# 별도 발행), status(status_change 로 별도), metadata(내부 누적 dict).
# capability/model 은 issue 전용 — project 에선 항상 미존재라 diff 가 무이벤트(무해).
_TRACKED_FIELDS = (
    "title", "description", "plan", "owner",
    "capability", "model",
    "priority", "resources", "gates",
    "source_signal_ids",
    "initiative_id",
)


def apply_entity_fields_and_persist(
    *, req, request, cp, entity_type: str, validate_status, enforce_guard: bool = True,
) -> CapabilityResponse:
    """issue.update / project.update 공통 — 필드 적용 + 영속화 + 이벤트 발행 + signal/inbox/wake.

    [동시성] entity 별 optimistic CAS 로 쓴다 (INFRA-ISSUE-284): read→검증·필드적용→
    rev-guard 단일행 UPDATE, 충돌 시 재read+재적용. cross-pod lost-update 를 막아
    multi-replica 를 가능케 한다. 셀 전체 재기록(replace_all_entities) 폐기 — 충돌 표면이
    엔티티 단위. find/검증/필드적용은 ``_apply`` 클로저(재시도 가능)에 두고, 부수효과
    (emit_event/signal/inbox)는 쓰기 성공 후 1회만 (재시도 시 중복 방지).

    [불변식] entity_lock 보유 중 호출되므로 클로저는 순수 동기 — ``await`` 금지
    (INFRA-ISSUE-277). validate_status(old, new, req, found, enforce_guard) 는 entity 별
    전이 가드(issue=terminal / project=container) 를 주입한다.
    """
    id_field = f"{entity_type}_id"
    entity_id = getattr(req, id_field)
    table = "issues" if entity_type == "issue" else "projects"

    box: dict = {}

    def _apply(found):
        if not found:
            return (CapabilityResponse(status="error", error_code="not_found", message=f"{entity_type} {entity_id} not found"), None)
        if found.get("deleted"):
            return (
                CapabilityResponse(
                    status="error", error_code="entity_deleted",
                    message=f"cannot update deleted {entity_type} {entity_id}. restore it first.",
                ),
                None,
            )
        old_status = found["status"]
        if req.status and req.status != old_status:
            err = validate_status(old_status, req.status, req, found, enforce_guard)
            if err:
                return (err, None)
            found["status"] = req.status

        old_vals = {f: found.get(f) for f in _TRACKED_FIELDS}
        # field_change old→new 보존용 — 변경 적용 전 스냅샷 (labels/deps/hold 는
        # _TRACKED_FIELDS 밖 자체 플래그 발행이라 따로 뜬다). INFRA-ISSUE-304.
        old_labels = list(found.get("labels") or [])
        old_deps = list(found.get("dependencies") or [])
        old_hold = bool(found.get("hold"))

        if req.title is not None:
            found["title"] = req.title
        if req.description is not None:
            found["description"] = req.description
        if getattr(req, "plan", None) is not None:
            found["plan"] = req.plan
        if req.owner is not None:
            found["owner"] = req.owner or None
        if entity_type == "issue":
            # issue 전용 필드. IssueUpdateRequest 에만 존재.
            if getattr(req, "capability", None) is not None:
                found["capability"] = req.capability
            if getattr(req, "model", None) is not None:
                found["model"] = req.model
        if req.priority is not None:
            p = req.priority.model_dump()
            found["priority"] = p
            found["priority_score"] = compute_priority_score(p)
        elif req.clear_priority:
            found["priority"] = None
            found["priority_score"] = 0
        if req.resources is not None:
            found["resources"] = normalize_resources([r.model_dump() for r in req.resources])
        # apps: Project 전용 (meta App 이름). 지정 시 통째 교체. derived deployments 소스.
        if getattr(req, "apps", None) is not None:
            found["apps"] = req.apps
        if req.gates is not None:
            found["gates"] = req.gates.model_dump()
        if req.metadata is not None:
            existing = found.get("metadata") or {}
            existing.update(req.metadata)
            found["metadata"] = existing
        # hold: agent-loop 자동 픽업 차단 토글. None=유지. status 와 직교 — 개인 세션
        # 수동 작업 중 자동 워커 간섭을 막고, 해제 시 마지막 status 그대로 재개.
        hold_changed = False
        if getattr(req, "hold", None) is not None:
            new_hold = bool(req.hold)
            if new_hold != bool(found.get("hold")):
                hold_changed = True
            found["hold"] = new_hold
        if req.source_signal_ids is not None:
            found["source_signal_ids"] = req.source_signal_ids
        # initiative_id: Project 변경 시 같은 cell 의 initiative 존재 검증 (cross-cell 거부).
        # Issue 는 initiative_id 필드가 없어 getattr 이 None — 분기 안 탐.
        # None=유지. 명시적 unset 은 후속 (clear_initiative_id 플래그 필요해지면 추가).
        if getattr(req, "initiative_id", None) is not None:
            from .initiative import validate_initiative_ref
            initiative_err = validate_initiative_ref(cp, req.initiative_id)
            if initiative_err:
                return (initiative_err, None)
            found["initiative_id"] = req.initiative_id
        # labels: None 이면 변경 안 함, 리스트면 통째 교체. invalid label_id 는 거부.
        labels_changed = False
        if getattr(req, "labels", None) is not None:
            from .label import normalize_label_ids
            label_ids, label_err = normalize_label_ids(cp, req.labels)
            if label_err:
                return (label_err, None)
            new_labels = label_ids or []
            if set(new_labels) != set(found.get("labels") or []):
                labels_changed = True
            found["labels"] = new_labels
        # dependencies: append-only + 명시 제거. Linear blockedBy / removeBlockedBy 패턴.
        # create 시엔 호출 안 됨 (이 helper 는 update 경로 전용). 단독 dependencies 전달 시
        # 기존 list 에 새 id 만 추가하고, remove_dependencies 가 있으면 명시 제거. 동시 지정 시
        # 추가가 먼저, 제거가 뒤 (자기 자신을 add+remove 하면 결과적으로 없음).
        deps_before = list(found.get("dependencies") or [])
        add_deps = getattr(req, "dependencies", None)
        if add_deps:
            seen = set(deps_before)
            deps_before = deps_before + [d for d in add_deps if d not in seen]
        remove_deps = getattr(req, "remove_dependencies", None)
        if remove_deps:
            drop = set(remove_deps)
            deps_before = [d for d in deps_before if d not in drop]
        deps_changed = deps_before != (found.get("dependencies") or [])
        if deps_changed:
            found["dependencies"] = deps_before
        found["updated_at"] = datetime.now(timezone.utc).isoformat()
        box.update(
            old_status=old_status, old_vals=old_vals,
            old_labels=old_labels, old_deps=old_deps, old_hold=old_hold,
            labels_changed=labels_changed, deps_changed=deps_changed, hold_changed=hold_changed,
        )
        return (CapabilityResponse(status="ok", data=found), found)

    resp = cas_update_entity(table, id_field, cp.cell_id, entity_id, _apply)
    if resp.status == "error":
        return resp
    # ---- 쓰기 성공 후 부수효과 (1회) ----
    found = resp.data
    old_vals = box["old_vals"]
    old_status = box["old_status"]
    old_labels = box["old_labels"]
    old_deps = box["old_deps"]
    old_hold = box["old_hold"]
    labels_changed = box["labels_changed"]
    deps_changed = box["deps_changed"]
    hold_changed = box["hold_changed"]

    sid = getattr(request.state, "session_id", None)
    principal = getattr(request.state, "principal", None)
    new_status = found["status"]
    status_changed = new_status != old_status

    # cascade — status_change 시 깨워야 할 대상:
    #   - 자식 cascade (issue done/cancelled/error → 부모 project):
    #     parent project worker 가 자식 issue terminal 직후 cycle 재개.
    #   - 상위 cascade (project done/cancelled/error → 부모 initiative):
    #     parent initiative worker 가 자식 project terminal 직후 §B(완료 판단) 재개.
    #     initiative wake key = bare initiative_id (wake._wake_key), 자식 issue→project
    #     와 같은 메커니즘 한 tier 위.
    #   - cell cascade (모든 status_change): agent-loop 가 cell 단위 long-poll 중일
    #     때 새 actionable 등장 가능성 (todo / error 복귀 등) — cell:<cell_id> 키 깨움.
    # terminal 집합은 entity_type 별로 다름: issue={done,cancelled,error},
    # container(project)={done,archive}. 이 helper 는 issue/project 만 처리.
    terminal_set = _ISSUE_TERMINAL if entity_type == "issue" else _CONTAINER_TERMINAL
    cascade: list[str] = []
    if status_changed:
        if new_status in terminal_set:
            if entity_type == "issue" and found.get("project_id"):
                cascade.append(found["project_id"])
            if entity_type == "project" and found.get("initiative_id"):
                cascade.append(found["initiative_id"])
        cascade.append(f"cell:{cp.cell_id}")

    if status_changed and (req.comment or "").strip():
        comment_data: dict = {"text": req.comment.strip(), "subtype": req.comment_subtype}
        if req.comment_payload:
            comment_data["payload"] = req.comment_payload
        emit_event(entity_type, entity_id, "comment",
                   comment_data, event_dir=cp.event_dir, session_id=sid, principal=principal)
    if status_changed:
        emit_event(entity_type, entity_id, "status_change",
                   {"from": old_status, "to": new_status},
                   event_dir=cp.event_dir, session_id=sid, principal=principal,
                   cascade_to=cascade or None)
    # field_change 는 old→new 를 함께 담아 수정 이력을 자기완결로 보존한다 (INFRA-ISSUE-304).
    # 워커 per-turn 컨텍스트엔 안 실리고(work_finder _DELTA_EVENT_KINDS 제외) event.list 로
    # 필요할 때만 조회 — description/plan 덮어쓰기 전 코멘트 백업을 대체한다.
    for _f in _TRACKED_FIELDS:
        if old_vals[_f] != found.get(_f):
            emit_event(entity_type, entity_id, "field_change",
                       {"field": _f, "old": old_vals[_f], "new": found.get(_f)}, event_dir=cp.event_dir, session_id=sid, principal=principal)
    if labels_changed:
        emit_event(entity_type, entity_id, "field_change",
                   {"field": "labels", "old": old_labels, "new": found.get("labels") or []},
                   event_dir=cp.event_dir, session_id=sid, principal=principal)
    if deps_changed:
        emit_event(entity_type, entity_id, "field_change",
                   {"field": "dependencies", "old": old_deps, "new": found.get("dependencies") or []},
                   event_dir=cp.event_dir, session_id=sid, principal=principal)
    if hold_changed:
        emit_event(entity_type, entity_id, "field_change",
                   {"field": "hold", "old": old_hold, "new": bool(found.get("hold"))},
                   event_dir=cp.event_dir, session_id=sid, principal=principal)

    if status_changed and new_status in terminal_set:
        transition_linked_signals(
            cp.signal_dir,
            entity_type=entity_type,
            entity_id=entity_id,
            source_signal_ids=found.get("source_signal_ids") or [],
            entity_status=new_status,
        )
        # project 사람 강제 terminal — 자식 issue 들 active 가 남았을 수 있으므로 일괄
        # cancelled 로 정리. 자식 worker 가 wake bus 로 즉시 종료.
        if (
            entity_type == "project"
            and bool(principal) and principal.type == "user"
        ):
            _cascade_cancel_active_children(cp, entity_id, principal, sid)

    if status_changed and new_status == "done":
        inbox_owner = resolve_owner(found, entity_type, project_file=cp.project_file) or found.get("owner")
        emit_inbox(f"{entity_type}.done", entity_id, found["title"], cell_id=cp.cell_id, owner=inbox_owner)

    return CapabilityResponse(status="ok", data=found)


def entity_add_pr(*, cp, entity_type: str, entity_id: str, pr: dict) -> CapabilityResponse:
    """issue / project 에 worker 가 만든 PR 정보 누적. url 기준 dedup 후 최신 정보로 갱신. worker 전용.

    `merge_state` 는 더 이상 저장하지 않는다 — PR 의 실제 상태는 GitHub 이 정본이며,
    UI 가 렌더링 시점에 `pr.status` capability 로 derive-on-read 한다. 워커가 보내도
    무시한다 (하위 호환).
    """
    id_field = f"{entity_type}_id"
    file = _entity_file(cp, entity_type)
    sanitized = {k: v for k, v in (pr or {}).items() if k != "merge_state"}
    captured: dict = {}

    def _mutate(found):
        prs = list(found.get("pr_urls") or [])
        url = sanitized.get("url")
        if url:
            prs = [p for p in prs if p.get("url") != url]
        prs.append(sanitized)
        found["pr_urls"] = prs
        found["updated_at"] = datetime.now(timezone.utc).isoformat()
        captured["prs"] = prs

    with entity_lock(file):
        res = cas_entity(cp, entity_type, entity_id, _mutate)
    if res is None:
        return CapabilityResponse(status="error", error_code="not_found", message=f"{entity_type} {entity_id} not found")
    return CapabilityResponse(status="ok", data={id_field: entity_id, "pr_urls": captured["prs"]})
