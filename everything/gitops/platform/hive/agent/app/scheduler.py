"""Scheduling helpers for the execution loop.

단일 `progress` action 만 사용. cleanup status 는 별도 phase 가 아니지만 우선순위로 분리해
workspace 자원을 빨리 해제한다.
"""

from .models import Action


# dependency satisfaction·terminal 판정용. issue terminal(done/cancelled) 과
# container terminal(done/archive) 의 union — dep·waker 가드는 entity type 을 안 가리고
# "더 진전 안 함"만 보면 되므로 union 으로 충분. all-children-terminal 카운트처럼
# container-only 가 필요한 곳은 _CONTAINER_TERMINAL 을 따로 쓴다.
_SATISFIED_STATES = ("done", "cancelled", "archive")

# 컨테이너(Project/Initiative) terminal 전용. 자식이 컨테이너일 때(initiative 의 자식
# Project) "모두 종결" 카운트에 issue-only status(cancelled)가 끼어들지 않게 한다.
_CONTAINER_TERMINAL = ("done", "archive")

# initiative self-progress 우선순위 — issue(1)·project(2) 뒤. 전략 tier 는 가장 나중.
_INITIATIVE_PRIORITY = 3


def classify_initiative_actions(initiative: dict, projects: list[dict]) -> list[Action]:
    """active Initiative 의 self-progress action 발급 여부.

    Project 의 §A/§B 구분을 status 가 아니라 **자식 Project 존재 여부**로
    대신한다 (initiative 는 `active` 한정 워커, 자식 Project 도 동일 컨테이너 모델):

      - 활성 자식 Project ≥ 1 (¬done/archive) → idle, action 없음.
        자식 Project 워커가 일하고, 모두 종결되면 child→initiative cascade(hub)가
        깨워 다시 이 함수가 §B action 을 발급한다.
      - 활성 자식 0 (자식 미생성 §A, 또는 전부 done/archive §B) → self-progress.
        워커가 Phase 0 에서 자식 수로 §A(plan+생성) vs §B(완료 판단) 분기한다.

    pending user comment pickup·hold 제외는 work_finder 가 담당 (project 와 대칭).
    """
    active_children = [
        p for p in projects if p.get("status") not in _CONTAINER_TERMINAL
    ]
    if active_children:
        return []
    return [Action("progress", entity=initiative, priority=_INITIATIVE_PRIORITY)]


def project_has_external_waker(
    project: dict, issues: list[dict], status: str
) -> bool:
    """`active` 로 turn 을 끝낸 컨테이너(Project)가 데드락이 아니라 정상 idle 인지.

    통합 컨테이너 모델에서 Project 의 유일한 능동 status 는 ``active`` 이며, 이는
    Initiative 의 ``active`` 와 동일하게 (이번 turn 에 mutation 이 있었다면) **idle-ok**
    다 — 자식(issue) worker 의 완료 cascade·스케줄러 재pickup·사용자 댓글이 외부 깨움
    주체이므로 전이 없이 turn 을 끝내도 데드락이 아니다. cleanup/error/running 은
    컨테이너에 없다. waiting 은 사람 대기로 parked 된 비능동 status (self-action 미픽업).

    단 *mutation 없이* active 로 끝나면 데드락 — worker.py 가 pre/post mutation 키로
    판정해 그 경우만 waiting 으로 parked 한다 (이 함수가 아니라 worker.py 가 담당).
    그래야 §A.5 의 *정상* 결과 (project: active + 자식 생성 후 idle) 가 데드락으로
    오판돼 강제 전이되지 않는다 (ITEMS-PROJECT-1 회귀).
    """
    return status == "active"


def deps_satisfied(entity: dict, status_index: dict[str, str] | None) -> bool:
    """dependency 가 모두 terminal(issue done/cancelled · container done/archive)인지.
    lookup 못 한 dep 은 통과 (cross-cell 등)."""
    deps = entity.get("dependencies") or []
    if not deps or status_index is None:
        return True
    for dep in deps:
        s = status_index.get(dep)
        if s is not None and s not in _SATISFIED_STATES:
            return False
    return True


def _todo_start_order(t: dict):
    """직렬화에서 다음에 시작할 todo 의 결정적 순서 — 높은 priority_score 먼저, 같으면 생성순(seq)."""
    return (-(t.get("priority_score") or 0), t.get("seq") or float("inf"))


def classify_goal_actions(
    project: dict,
    issues: list[dict],
    exclude_ids: set | None = None,
    *,
    status_index: dict[str, str] | None = None,
) -> list[Action]:
    """Return runnable actions derived from a project's children + project-self completion.

    자식 issue 의 progress action 은 parent project status 와 무관하게 발급된다 — `waiting`/
    `hold`/`todo`/`error` parent 밑에서도 자식 자신의 status·hold·dependency 만으로
    pickup 여부가 결정 (parent 상태는 child 자율 진행과 직교).

    마지막의 *project-self 완료 판단* progress 는 컨테이너가 `active` 일 때만 발급한다 —
    통합 컨테이너 모델에서 Project 의 유일한 능동 status 가 `active` 다. `backlog`(pre-launch)
    /`done`/`archive` 의 self-action 은 발급 안 됨 (work_finder 가 terminal reply 등 분기 담당).

    dependency 가 아직 satisfied 안 된 todo issue 는 actionable 에서 빠지고
    blocked 으로 잡혀 active project 의 self-completion 도 차단된다.

    같은 project 의 자식 실행은 **직렬** — running/cleanup 형제가 있으면 새 todo 를
    시작하지 않고, 시작할 때도 한 번에 1개만 (sibling clobber 원천 차단, 본문 주석).
    """
    exclude = exclude_ids or set()
    project_id = project["project_id"]

    cleanup_tasks = [t for t in issues if t["status"] == "cleanup" and t["issue_id"] not in exclude]
    active_tasks = [
        t for t in issues
        if t["status"] in ("running", "todo") and t["issue_id"] not in exclude
    ]
    actionable_tasks = [t for t in active_tasks if deps_satisfied(t, status_index)]
    dep_blocked = [t for t in active_tasks if not deps_satisfied(t, status_index)]
    blocked_tasks = [t for t in issues if t["status"] in ("waiting", "error")] + dep_blocked

    actions: list[Action] = []
    # cleanup 이 최우선 — workspace 자원을 빨리 해제하고 issue 를 종결.
    actions.extend(Action("progress", entity=t, priority=0) for t in cleanup_tasks)
    actions.extend(
        Action("progress", entity=t, priority=1)
        for t in actionable_tasks if t["status"] == "running"
    )

    # 형제 직렬화 — 같은 project 의 todo 자식은 실행 중(running/cleanup) 형제가 없을
    # 때만, 그리고 한 번에 1개만 시작한다. 병렬 형제가 같은 repo 파일을 동시에 고쳐
    # 서로 덮어쓰는 sibling clobber 를 디스패치 단계에서 원천 차단 (INFRA-ISSUE-296,
    # ITEMS-PROJECT-12 Phase 4~7 실사고) — 다음 자식은 앞 자식이 main 에 머지한 결과
    # 위에서 시작한다. 사람이 hold 로 잡고 실행 중인 자식(exclude)도 동일하게 막는다.
    # waiting/error 형제는 막지 않는다 — 미착수 suggestion·장기 사람 대기가 project
    # 전체를 세우는 것을 피한다 (미머지 PR 잔재와의 충돌은 git 머지 충돌로 가시화됨).
    in_flight = [t for t in issues if t["status"] in ("running", "cleanup")]
    actionable_todos = [t for t in actionable_tasks if t["status"] == "todo"]
    if not in_flight and actionable_todos:
        first = min(actionable_todos, key=_todo_start_order)
        actions.append(Action("progress", entity=first, priority=1))

    if actions:
        return actions

    # project-self 완료 판단은 active 일 때만 — 그 외는 work_finder 분기 담당.
    if project.get("status") != "active":
        return []

    if blocked_tasks:
        return []

    excluded_active = [
        t for t in issues
        if t["status"] in ("running", "cleanup", "todo") and t["issue_id"] in exclude
    ]
    if excluded_active:
        return []

    if project_id in exclude:
        return []

    # 자식 issue 모두 완료 → project 자체에 progress (완료 판단).
    return [Action("progress", entity=project, priority=2)]
