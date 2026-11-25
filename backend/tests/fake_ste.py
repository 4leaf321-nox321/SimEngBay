"""가짜 STE — SimEngBay 가 부르는 STE REST 를 흉내 낸다(요청서 2026-11-24 E-1 · E-3 시험용).

    python -m tests.fake_ste --port 8097 --secret dev-ste-secret     # 개발 서버를 여기에 붙일
    때

그다음 개발 `.env` 에 `STE_BASE_URL=http://127.0.0.1:8097` · `STE_SSO_SECRET=dev-ste-secret`
을 적으면 `solve_on: ste` 작업이 이 가짜로 간다. 잡은 **이 기계의 ccx 로 진짜
푼다**(`ccx_runner`).

**진짜 STE 와 같게 하는 것**(HWAXPortal `ste_credential.py` · SmartTwinCluster
`sso_delegate_api.py` · `docs/ste-stepforge-1117` 에서 맞춘 규칙 — `app/core/calculix/ste.py`
머리글):

- `POST /api/auth/sso`: **받는 곳(client)마다 다른 비밀**(요청서 S-1), 머리 넷, 처음 보는
  이메일은 계정을 만든다(JIT), **같은 (사람, client)의 직전 토큰은 죽인다**, 거절 목록의
  사람은 403 + 한 줄.
- 업로드: 주인 = 제출자(다르면 404), 한 번만(제출 뒤 409), 평평한 이름 · 점으로 시작 금지 ·
  예약 이름.
- 잡: `PENDING → RUNNING → 끝`. 주인만 본다(남의 잡은 404). 끝은 Slurm 낱말
  (`COMPLETED` · `FAILED` · `OUT_OF_MEMORY` · `TIMEOUT` · `CANCELLED`), `*ERROR` 면
  FAILED(요청서 A-4).
- 인자는 A-2 표의 다섯 개만 받는다(환경 변수를 자유롭게 받는 인자는 없다 — S-2).

경로 중 **짐작인 것**(제출 · 상태 · 취소)은 `ste.py` 의 `ENDPOINTS` 와 같은 꼴이다 — 진짜 STE
의 답을 받으면 둘을 함께 고친다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote

import httpx

from app.branding import DEFAULT_APP_SLUG

#: 이 설치가 STE 에 내미는 이름(`X-Heax-Client`) — 설정이 비면 `app_slug` 다.
CLIENT = DEFAULT_APP_SLUG
RESERVED = {"slurm.out", "status", "job.sh"}
PARAMS = {"deck", "threads", "equation_solver_threads", "mem_gb", "time_limit_min"}
FINISHED = {"COMPLETED", "FAILED", "OUT_OF_MEMORY", "TIMEOUT", "CANCELLED"}
ERROR_MARK = re.compile(r"\*ERROR|not converged|too many iterations", re.IGNORECASE)


@dataclass
class Outcome:
    """잡 하나의 끝 — 러너가 돌려준다. 결과 파일은 러너가 잡 폴더에 쓴다."""

    state: str = "COMPLETED"
    exit_code: int | None = 0
    reason_code: str | None = None
    max_rss_mb: float | None = None


#: (잡 폴더 — 올린 덱이 들어 있다, 인자) → 끝.
Runner = Callable[[Path, dict[str, Any]], Outcome]


def ccx_runner(folder: Path, params: dict[str, Any]) -> Outcome:
    """**진짜 ccx 로 푼다** — STE 앱 `calculix` 의 약속(요청서 A-2) 그대로: 작업 폴더에서 `ccx
    <deck>`, `OMP_NUM_THREADS` = threads, `CCX_NPROC_EQUATION_SOLVER` =
    equation_solver_threads, 표준 출력 · 오류는 `ccx.out`."""
    from app.core.calculix import tools

    binary = tools.ccx_bin()
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(folder),
        "OMP_NUM_THREADS": str(params.get("threads", 2)),
        "CCX_NPROC_EQUATION_SOLVER": str(
            params.get("equation_solver_threads", params.get("threads", 2))
        ),
    }
    if os.environ.get(tools.LD_ENV):
        env["LD_LIBRARY_PATH"] = os.environ[tools.LD_ENV]
    try:
        done = subprocess.run(
            [str(binary), str(params.get("deck", "model"))],
            cwd=folder,
            env=env,
            capture_output=True,
            text=True,
            timeout=60 * int(params.get("time_limit_min", 60)),
        )
    except subprocess.TimeoutExpired:
        return Outcome("TIMEOUT", None, "timeout")
    log = (done.stdout or "") + (done.stderr or "")
    (folder / "ccx.out").write_text(log, encoding="utf-8")
    if done.returncode == -9:
        return Outcome("OUT_OF_MEMORY", None, "out_of_memory")
    if done.returncode != 0:
        return Outcome("FAILED", done.returncode, "exit_code")
    if ERROR_MARK.search(log):
        reason = "ccx_error" if "*ERROR" in log.upper() else "not_converged"
        return Outcome("FAILED", 0, reason)
    return Outcome("COMPLETED", 0)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class Job:
    id: str
    owner: str
    app: str
    params: dict[str, Any]
    folder: Path
    state: str = "PENDING"
    exit_code: int | None = None
    reason_code: str | None = None
    max_rss_mb: float | None = None
    submitted_at: float = field(default_factory=time.time)
    started_at: float | None = None
    ended_at: float | None = None

    def view(self, sha: str | None) -> dict[str, Any]:
        return {
            "id": self.id,
            "app": self.app,
            "state": self.state,
            "exit_code": self.exit_code,
            "reason_code": self.reason_code,
            "max_rss_mb": self.max_rss_mb,
            "ccx_sha256": sha,
            "submitted_by": self.owner,
            "submitted_at": self.submitted_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
        }


class FakeSte:
    """`handle(httpx.Request) → httpx.Response` — `httpx.MockTransport` 에 꽂거나 `serve` 로
    띄운다.

    `lazy=True`(시험 기본)면 상태를 물을 때마다 한 걸음씩 간다(PENDING → RUNNING → 러너를 돌려
    끝) — 스레드 없이 순서가 정해진다. `lazy=False` 면 제출하자마자 뒤에서 돈다(`serve` 용)."""

    def __init__(
        self,
        *,
        secrets_by_client: dict[str, str] | None = None,
        runner: Runner | None = None,
        lazy: bool = True,
        ccx_sha256: str | None = None,
        token_seconds: int = 43200,
    ) -> None:
        self.secrets = secrets_by_client or {CLIENT: "ste-secret"}
        self.runner = runner or ccx_runner
        self.lazy = lazy
        self.ccx_sha256 = ccx_sha256
        self.token_seconds = token_seconds
        self.root = Path(tempfile.mkdtemp(prefix="fake-ste-"))
        self.lock = threading.RLock()
        self.tokens: dict[str, tuple[str, str]] = {}
        self.active: dict[tuple[str, str], str] = {}
        self.accounts: set[str] = set()
        self.denied: dict[str, str] = {}
        self.uploads: dict[str, dict[str, Any]] = {}
        self.jobs: dict[str, Job] = {}
        #: 기록 — 시험이 본다.
        self.mints: list[tuple[str, str]] = []
        self.requests: list[tuple[str, str, str | None]] = []
        self.submitted_params: list[dict[str, Any]] = []
        #: 길 이름(`sso` · `submit` · `status` …) → 다음에 낼 상태 코드들 — 5xx 를 흉내 낸다.
        self.faults: dict[str, list[int]] = {}
        #: 대기열 요약(`GET /api/cluster`) — 11-24 `cluster_info` 의 숫자. `None` 이면 없는 길.
        self.cluster: dict[str, Any] | None = {
            "partition": "alpha",
            "cpus_total": 2944,
            "cpus_allocated": 2722,
            "jobs_pending": 3,
        }
        self.seq = 0

    # --- 바깥에서 부르는 것 ---

    def revoke(self, email: str, client: str = CLIENT) -> None:
        """그 사람의 토큰을 죽인다 — 포털 · 다른 기계가 같은 client 로 새로 받은 것과 같다."""
        with self.lock:
            token = self.active.pop((email, client), None)
            if token:
                self.tokens.pop(token, None)

    def fault(self, route: str, *codes: int) -> None:
        """다음 `route` 요청 몇 번을 이 코드로 답한다(`sso` · `new_upload` · `put` · `submit` ·
        `status` · `cancel` · `file`)."""
        self.faults.setdefault(route, []).extend(codes)

    # --- 길 ---

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = unquote(request.url.path)
        at = path.find("/api/")
        path = path[at:] if at >= 0 else path
        method = request.method
        routes: list[tuple[str, str, Callable[..., httpx.Response]]] = [
            ("POST", r"/api/auth/sso", self._sso),
            ("POST", r"/api/uploads", self._new_upload),
            ("PUT", r"/api/uploads/(?P<upload>[^/]+)/(?P<name>.+)", self._put),
            ("GET", r"/api/uploads/(?P<upload>[^/]+)", self._upload_view),
            ("POST", r"/api/jobs", self._submit),
            ("GET", r"/api/jobs/(?P<job>[^/]+)", self._status),
            ("POST", r"/api/jobs/(?P<job>[^/]+)/cancel", self._cancel),
            ("GET", r"/api/jobs/(?P<job>[^/]+)/result/file/(?P<name>.+)", self._file),
            ("GET", r"/api/cluster", self._cluster),
        ]
        for want, pattern, route in routes:
            matched = re.fullmatch(pattern, path)
            if want == method and matched:
                queued = self.faults.get(route.__name__.lstrip("_"))
                if queued:
                    return _json({"detail": "가짜 STE 고장"}, queued.pop(0))
                with self.lock:
                    return route(request, **matched.groupdict())
        return _json({"detail": f"없는 길: {method} {path}"}, 404)

    def _owner(self, request: httpx.Request) -> str | None:
        head = request.headers.get("authorization", "")
        token = head.removeprefix("Bearer ").strip()
        found = self.tokens.get(token)
        owner = found[0] if found else None
        self.requests.append((request.method, request.url.path, owner))
        return owner

    def _sso(self, request: httpx.Request) -> httpx.Response:
        client = request.headers.get("x-heax-client", "").strip().lower()
        if client not in self.secrets:
            return _json({"detail": f"알 수 없는 클라이언트: {client!r}"}, 400)
        if request.headers.get("x-heax-gateway-secret", "") != self.secrets[client]:
            return _json({"detail": "시크릿이 맞지 않는다"}, 401)
        email = request.headers.get("x-heax-user-email", "").strip().lower()
        if email.count("@") != 1:
            return _json({"detail": f"위임할 수 없는 이메일: {email!r}"}, 400)
        if email in self.denied:
            return _json({"detail": self.denied[email]}, 403)
        self.accounts.add(email)
        previous = self.active.pop((email, client), None)
        if previous:
            self.tokens.pop(previous, None)
        token = "kst_" + secrets.token_hex(12)
        self.tokens[token] = (email, client)
        self.active[(email, client)] = token
        self.mints.append((email, client))
        return _json(
            {
                "access_token": token,
                "token_type": "bearer",
                "expires_in": self.token_seconds,
                "username": email.split("@")[0],
                "client": client,
            }
        )

    def _new_upload(self, request: httpx.Request) -> httpx.Response:
        owner = self._owner(request)
        if owner is None:
            return _json({"detail": "인증이 필요하다"}, 401)
        self.seq += 1
        upload = f"u{self.seq:04d}"
        self.uploads[upload] = {"owner": owner, "files": {}, "used": False}
        return _json(
            {"id": upload, "ticket": secrets.token_hex(8), "expires_at": time.time() + 86400}
        )

    def _put(self, request: httpx.Request, upload: str, name: str) -> httpx.Response:
        owner = self._owner(request)
        if owner is None:
            return _json({"detail": "인증이 필요하다"}, 401)
        found = self.uploads.get(upload)
        if found is None or found["owner"] != owner:
            return _json({"detail": "업로드를 찾지 못했다"}, 404)
        if found["used"]:
            return _json({"detail": "이미 제출에 쓴 업로드다"}, 409)
        if "/" in name or name.startswith(".") or name in RESERVED:
            return _json({"detail": f"쓸 수 없는 파일 이름: {name!r}"}, 400)
        found["files"][name] = request.read()
        return _json({"name": name, "bytes": len(found["files"][name])})

    def _upload_view(self, request: httpx.Request, upload: str) -> httpx.Response:
        owner = self._owner(request)
        found = self.uploads.get(upload)
        if owner is None:
            return _json({"detail": "인증이 필요하다"}, 401)
        if found is None or found["owner"] != owner:
            return _json({"detail": "업로드를 찾지 못했다"}, 404)
        files = {name: hashlib.sha256(raw).hexdigest() for name, raw in found["files"].items()}
        return _json({"id": upload, "files": files, "used": found["used"]})

    def _submit(self, request: httpx.Request) -> httpx.Response:
        owner = self._owner(request)
        if owner is None:
            return _json({"detail": "인증이 필요하다"}, 401)
        raw = request.read().decode("utf-8")
        kind = request.headers.get("content-type", "")
        form = (
            json.loads(raw)
            if "json" in kind
            else {key: values[0] for key, values in parse_qs(raw).items()}
        )
        if form.get("app") != "calculix":
            return _json({"detail": f"모르는 앱: {form.get('app')!r}"}, 404)
        upload = self.uploads.get(str(form.get("upload_id")))
        if upload is None or upload["owner"] != owner:
            # 업로드 주인과 제출자가 다르면 404 — 남의 업로드가 있는지조차 말하지 않는다.
            return _json({"detail": "업로드를 찾지 못했다"}, 404)
        if upload["used"]:
            return _json({"detail": "이미 제출에 쓴 업로드다"}, 409)
        params = form.get("params") or "{}"
        params = json.loads(params) if isinstance(params, str) else params
        unknown = set(params) - PARAMS
        if unknown:
            return _json({"detail": f"모르는 인자: {sorted(unknown)}"}, 400)
        upload["used"] = True
        self.seq += 1
        job = f"j{self.seq:04d}"
        folder = self.root / job
        folder.mkdir()
        for name, data in upload["files"].items():
            (folder / name).write_bytes(data)
        self.jobs[job] = Job(job, owner, "calculix", dict(params), folder)
        self.submitted_params.append(dict(params))
        if not self.lazy:
            threading.Thread(target=self._run, args=(self.jobs[job],), daemon=True).start()
        return _json({"id": job, "state": "PENDING"})

    def _job(self, request: httpx.Request, job: str) -> Job | httpx.Response:
        owner = self._owner(request)
        if owner is None:
            return _json({"detail": "인증이 필요하다"}, 401)
        found = self.jobs.get(job)
        if found is None or found.owner != owner:
            return _json({"detail": "잡을 찾지 못했다"}, 404)
        return found

    def _status(self, request: httpx.Request, job: str) -> httpx.Response:
        found = self._job(request, job)
        if isinstance(found, httpx.Response):
            return found
        if self.lazy and found.state == "PENDING":
            found.state = "RUNNING"
            found.started_at = time.time()
        elif self.lazy and found.state == "RUNNING":
            self._finish(found)
        return _json(found.view(self._sha()))

    def _cancel(self, request: httpx.Request, job: str) -> httpx.Response:
        found = self._job(request, job)
        if isinstance(found, httpx.Response):
            return found
        if found.state not in FINISHED:
            found.state = "CANCELLED"
            found.ended_at = time.time()
        return _json(found.view(self._sha()))

    def _file(self, request: httpx.Request, job: str, name: str) -> httpx.Response:
        found = self._job(request, job)
        if isinstance(found, httpx.Response):
            return found
        target = found.folder / name
        if "/" in name or not target.is_file():
            return _json({"detail": "파일이 없다"}, 404)
        return httpx.Response(200, content=target.read_bytes())

    def _cluster(self, request: httpx.Request) -> httpx.Response:
        """대기열 요약 — 요청서 S-3 이 바라는 꼴. `cluster` 가 `None` 이면 이 길이 없는 STE."""
        owner = self._owner(request)
        if owner is None:
            return _json({"detail": "인증이 필요하다"}, 401)
        if self.cluster is None:
            return _json({"detail": "없는 길"}, 404)
        mine = [one for one in self.jobs.values() if one.owner == owner]
        return _json(
            {
                **self.cluster,
                "mine": {
                    "running": sum(one.state == "RUNNING" for one in mine),
                    "pending": sum(one.state == "PENDING" for one in mine),
                },
            }
        )

    # --- 잡 ---

    def _run(self, job: Job) -> None:
        time.sleep(0.05)
        with self.lock:
            if job.state != "PENDING":
                return
            job.state = "RUNNING"
            job.started_at = time.time()
        self._finish(job)

    def _finish(self, job: Job) -> None:
        outcome = self.runner(job.folder, job.params)
        (job.folder / "slurm.out").write_text(
            f"job {job.id} {outcome.state}\n", encoding="utf-8"
        )
        with self.lock:
            if job.state == "CANCELLED":
                return
            job.state = outcome.state
            job.exit_code = outcome.exit_code
            job.reason_code = outcome.reason_code
            job.max_rss_mb = outcome.max_rss_mb
            job.ended_at = time.time()

    def _sha(self) -> str | None:
        if self.ccx_sha256 is not None:
            return self.ccx_sha256
        if self.runner is ccx_runner:
            from app.core.calculix import tools

            self.ccx_sha256 = _sha256(tools.ccx_bin())
        return self.ccx_sha256


def _json(body: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body)


def serve(
    fake: FakeSte, host: str = "127.0.0.1", port: int = 0
) -> tuple[ThreadingHTTPServer, str]:
    """진짜 HTTP 로 띄운다(다른 프로세스 — 단계 실행기 · 개발 서버가 부를 때). (서버, 주소)."""

    class Handler(BaseHTTPRequestHandler):
        def _any(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            request = httpx.Request(
                self.command,
                f"http://{host}{self.path}",
                headers=dict(self.headers.items()),
                content=body,
            )
            response = fake.handle(request)
            payload = response.content
            self.send_response(response.status_code)
            self.send_header(
                "Content-Type",
                response.headers.get("content-type", "application/octet-stream"),
            )
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = do_PUT = do_DELETE = _any

        def log_message(self, *_: Any) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=server.serve_forever, name="fake-ste", daemon=True).start()
    return server, f"http://{host}:{server.server_port}"


def main() -> None:
    parser = argparse.ArgumentParser(description="가짜 STE(진짜 ccx 로 푼다)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8097)
    parser.add_argument("--secret", default="dev-ste-secret")
    parser.add_argument("--client", default=CLIENT)
    args = parser.parse_args()
    fake = FakeSte(secrets_by_client={args.client: args.secret}, lazy=False)
    server, url = serve(fake, args.host, args.port)
    print(f"가짜 STE {url} (client {args.client}) — 잡 폴더 {fake.root}", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
