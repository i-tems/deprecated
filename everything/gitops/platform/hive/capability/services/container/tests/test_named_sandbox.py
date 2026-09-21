import importlib.util
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path


class _Obj:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _App:
    def post(self, *args, **kwargs):
        return lambda fn: fn

    def websocket(self, *args, **kwargs):
        return lambda fn: fn

    def on_event(self, *args, **kwargs):
        return lambda fn: fn


def _install_stubs():
    k8s_client = types.ModuleType("kubernetes.client")
    for name in [
        "V1EnvVar", "V1EnvVarSource", "V1SecretKeySelector", "V1Volume",
        "V1EmptyDirVolumeSource", "V1PersistentVolumeClaimVolumeSource",
        "V1VolumeMount", "V1SecurityContext", "V1Capabilities",
        "V1Container", "V1ResourceRequirements", "V1ObjectMeta",
        "V1Pod", "V1PodSpec", "V1PodSecurityContext", "V1SeccompProfile",
    ]:
        setattr(k8s_client, name, _Obj)
    # CoreV1Api 는 인자 없이도(core_v1) ApiClient 인자와도(exec_v1) 생성된다.
    k8s_client.ApiClient = lambda *a, **k: _Obj()
    k8s_client.CoreV1Api = lambda *a, **k: _Obj()

    exceptions = types.ModuleType("kubernetes.client.exceptions")
    exceptions.ApiException = type("ApiException", (Exception,), {})

    k8s_config = types.ModuleType("kubernetes.config")
    k8s_config.load_incluster_config = lambda: None
    k8s_config.load_kube_config = lambda: None

    k8s_stream = types.ModuleType("kubernetes.stream")
    k8s_stream.stream = lambda *args, **kwargs: None

    kubernetes = types.ModuleType("kubernetes")
    kubernetes.client = k8s_client
    kubernetes.config = k8s_config

    framework = types.ModuleType("capability_framework")
    framework.CapabilityResponse = _Obj
    framework.create_app = lambda **kwargs: _App()

    fastapi = types.ModuleType("fastapi")
    fastapi.Request = object
    fastapi.WebSocket = object
    fastapi.WebSocketDisconnect = type("WebSocketDisconnect", (Exception,), {})

    sys.modules.update({
        "kubernetes": kubernetes,
        "kubernetes.client": k8s_client,
        "kubernetes.client.exceptions": exceptions,
        "kubernetes.config": k8s_config,
        "kubernetes.stream": k8s_stream,
        "capability_framework": framework,
        "fastapi": fastapi,
    })


def _load_container_main():
    _install_stubs()
    path = Path(__file__).resolve().parents[1] / "main.py"
    spec = importlib.util.spec_from_file_location("container_main_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class NamedSandboxContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_container_main()

    def test_name_validation_matches_kubernetes_label_subset(self):
        self.assertRegex("dev.1", self.mod._SANDBOX_NAME_RE)
        self.assertRegex("work_box-2", self.mod._SANDBOX_NAME_RE)
        self.assertNotRegex("-bad", self.mod._SANDBOX_NAME_RE)
        self.assertNotRegex("bad-", self.mod._SANDBOX_NAME_RE)

    def test_named_workspace_is_owner_and_cell_scoped_and_path_safe(self):
        root = self.mod._named_workspace_root("infra", "User+X@Example.com", "dev")
        self.assertTrue(root.startswith("/shared/terminals/user-x-example.com-"))
        self.assertTrue(root.endswith("/infra/dev"))
        # 같은 owner·이름이라도 cell 이 다르면 clone 경로가 분리된다 (repo 충돌 방지).
        self.assertNotEqual(
            root, self.mod._named_workspace_root("items", "User+X@Example.com", "dev"),
        )

    def test_named_pod_uses_persistent_project_and_home_paths(self):
        pod = self.mod._build_pod(
            "sandbox-test", "infra", "image",
            cpus=1, memory_mb=1024,
            owner_email="user@example.com", session_id=None,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
            repo_url="https://github.com/i-tems/cell-infra.git",
            sandbox_name="dev",
        )
        labels = pod.metadata.labels
        annos = pod.metadata.annotations
        self.assertEqual(labels[self.mod.LABEL_SANDBOX_NAME], "dev")
        self.assertIn("/shared/terminals/user-example.com-", annos[self.mod.ANNO_WORKDIR])
        self.assertTrue(annos[self.mod.ANNO_WORKDIR].endswith("/infra/dev/cell"))
        # HOME 은 per-name 격리하지 않고 공유 /shared 유지 — claude 인증·specs 보존.
        self.assertEqual(annos[self.mod.ANNO_HOME_DIR], "/shared")
        self.assertTrue(annos[self.mod.ANNO_WORKSPACE_ROOT].endswith("/infra/dev"))

    def test_anonymous_pod_keeps_legacy_workdir(self):
        pod = self.mod._build_pod(
            "sandbox-test", "infra", "image",
            cpus=1, memory_mb=1024,
            owner_email="user@example.com", session_id=None,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
            repo_url="https://github.com/i-tems/cell-infra.git",
        )
        self.assertNotIn(self.mod.LABEL_SANDBOX_NAME, pod.metadata.labels)
        self.assertEqual(pod.metadata.annotations[self.mod.ANNO_WORKDIR], "/work/cell")
        self.assertEqual(pod.metadata.annotations[self.mod.ANNO_HOME_DIR], "/shared")

    def test_claude_project_dir_matches_claude_slug(self):
        # claude 의 cwd→project 슬러그: 영숫자·하이픈 외 모든 문자를 '-' 로(대소문자 보존).
        # 실측(claude v2.1.177): /tmp/Ab_cd.ef-GH/ij → -tmp-Ab-cd-ef-GH-ij.
        f = self.mod._claude_project_dir
        self.assertEqual(
            f("/shared", "/tmp/Ab_cd.ef-GH/ij"),
            "/shared/.claude/projects/-tmp-Ab-cd-ef-GH-ij",
        )
        # owner segment 의 '.' 도 '-' 로 (과거 sed 's#/#-#g' 가 놓치던 부분).
        self.assertEqual(
            f("/shared", "/shared/terminals/dahuin000-gmail.com-abc/pen/attending/cell"),
            "/shared/.claude/projects/-shared-terminals-dahuin000-gmail-com-abc-pen-attending-cell",
        )

    def test_named_session_without_repo_uses_stable_cell_workdir_not_shared(self):
        # 회귀: repo_url 미해석 시에도 cwd 는 공유 /shared 가 아니라 고정 {ws}/cell.
        # repo 유무로 /cell 접미사가 붙었다 떼면 cwd 가 접속마다 흔들려 재개가 깨진다.
        pod = self.mod._build_pod(
            "sandbox-test", "pen", "image",
            cpus=1, memory_mb=1024,
            owner_email="user@example.com", session_id=None,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
            repo_url=None,
            sandbox_name="attending",
        )
        workdir = pod.metadata.annotations[self.mod.ANNO_WORKDIR]
        ws_root = pod.metadata.annotations[self.mod.ANNO_WORKSPACE_ROOT]
        self.assertNotEqual(workdir, "/shared")
        self.assertEqual(workdir, f"{ws_root}/cell")  # repo 없어도 /cell 고정
        self.assertTrue(workdir.endswith("/pen/attending/cell"))

    def test_workdir_stable_regardless_of_repo_url(self):
        # cwd 는 repo_url 유무와 무관히 동일해야 한다 (재개가 같은 project 를 찾도록).
        def wd(repo):
            return self.mod._build_pod(
                "sandbox-test", "pen", "image", cpus=1, memory_mb=1024,
                owner_email="user@example.com", session_id=None,
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                expires_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
                repo_url=repo, sandbox_name="attending",
            ).metadata.annotations[self.mod.ANNO_WORKDIR]
        self.assertEqual(wd(None), wd("https://github.com/i-tems/cell-pen.git"))

    def test_skill_session_without_repo_uses_unique_workdir_not_shared(self):
        pod = self.mod._build_pod(
            "sandbox-test", "pen", "image",
            cpus=1, memory_mb=1024,
            owner_email="user@example.com", session_id=None,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
            repo_url=None,
            entity_type="initiative", entity_id="PEN-INITIATIVE-1",
        )
        workdir = pod.metadata.annotations[self.mod.ANNO_WORKDIR]
        self.assertNotEqual(workdir, "/shared")
        self.assertTrue(workdir.startswith("/work/sessions/pen/"))
        self.assertTrue(workdir.endswith("/initiative/PEN-INITIATIVE-1/cell"))

    def test_skill_sessions_are_per_user(self):
        # 회귀: entity·directing cwd 에 owner 가 없으면 같은 cell 권한자끼리 한
        # 세션을 공유해(--continue 가 남의 대화를 resume) 사용자 격리가 깨진다.
        f = self.mod._skill_workspace_root
        a = f("pen", "u1@example.com", "initiative", "PEN-INITIATIVE-1")
        b = f("pen", "u2@example.com", "initiative", "PEN-INITIATIVE-1")
        self.assertIsNotNone(a)
        self.assertNotEqual(a, b)
        self.assertTrue(a.endswith("/initiative/PEN-INITIATIVE-1"))
        self.assertNotEqual(
            f("infra", "u1@example.com", self.mod.DIRECTING_KIND, None),
            f("infra", "u2@example.com", self.mod.DIRECTING_KIND, None),
        )
        self.assertNotEqual(
            f("infra", "u1@example.com", self.mod.ATTENDING_KIND, None),
            f("infra", "u2@example.com", self.mod.ATTENDING_KIND, None),
        )


if __name__ == "__main__":
    unittest.main()
