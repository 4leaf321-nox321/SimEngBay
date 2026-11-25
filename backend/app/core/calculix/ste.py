"""STE(Smart Twin Explorer, Slurm 클러스터)에서 ccx 를 푼다 — **ccx 한 번 = STE 잡 한 번.**

요청서 「CalculiX 솔브를 STE 에서 — SimEngBay 경유 · 건 사람 명의 제출」(2026-11-24)의 E-1 ·
E-3. 메시 · 덱 쓰기 · 결과 뽑기는 그대로 이 서버에서 하고, `solve()` 가 ccx 를 부르는 자리만
이것으로 갈린다(`solve.LocalCcx` ↔ `SteCcx`). 판정(`_judged`) · 메모리 재시도 · 모드 찾기 ·
질량 대조는 로컬과 **같은 코드**다 — 이 모듈은 결과 파일을 작업 폴더에 같은 이름으로
내려놓기만 한다.

## 명의 — 건 사람 것만 (E-3)

토큰은 작업을 건 사람(`requested_by`) 명의로만 받는다: SimEngBay 전용 비밀로 STE 의
`POST /api/auth/sso` 를 부른다(조직 표준 「ste 방식」, HWAXPortal `docs/sso-delegation`). 못
받으면 `ste_auth` 로 끝낸다 — 서비스 계정 · 남의 토큰으로 대신하지 않고, **로컬로 몰래 풀지도
않는다** (사람은 그것을 STE 결과로 읽는다). 업로드 · 제출 · 상태 · 결과 · 취소를 모두 그 한
토큰으로 하므로 「업로드 주인 = 제출자」(STE 가 강제한다, 다르면 404)가 저절로 맞는다. STE 잡
인자 · 업로드 파일에는 어떤 자격도 넣지 않는다.

## STE 계약 — 무엇을 확인했고 무엇이 짐작인가 (2026-11-24)

STE 서버 소스는 공개 저장소에 없다. HWAXPortal(`ste_credential.py`, `docs/ste-cae00` ·
`docs/ste-stepforge-1117`) · HWAXMcpGateway · SmartTwinCluster(`sso_delegate_api.py`)에서
맞췄다.

- 확인: `POST /api/auth/sso`(머리 넷 → 200 `{access_token, expires_in}`, 403 계정 정지),
  `POST /api/uploads` → `{id, ticket, expires_at}`, `PUT /api/uploads/{id}/{파일}`(주인 PAT 도
  받는다), 결과 `GET /api/jobs/{id}/result/file/{파일}`, 오류 본문 `{"detail": …}`.
- 짐작 — **`ENDPOINTS` · `_submit_form` · `_state` 세 곳만 고치면 된다**: 제출 `POST
  /api/jobs`(폼 `app` · `upload_id` · `params`), 상태 `GET /api/jobs/{id}`(`state` ·
  `exit_code` · `max_rss_mb` · `ccx_sha256`), 취소 `POST /api/jobs/{id}/cancel`.

## 토큰을 왜 기계 안에서 나눠 쓰나

STE 의 위임 창구는 **같은 (사람, client)의 직전 토큰을 지운다**(클라이언트당 활성 하나 —
게이트웨이가 백엔드마다 client 이름을 갈라 쓴 까닭, HWAXMcpGateway 7bcdf49). 워커 여럿이 한
사람의 DOE 점을 동시에 풀면서 저마다 받으면 서로의 토큰을 죽이고, 「401 이면 한 번 다시 받기」
가 또 서로를 죽인다. 그래서 받은 토큰을 메모리 파일시스템(`/dev/shm`)의 사람별 파일(0600)에
두고 파일 잠금으로 **한 번만** 받는다(`Tokens`). DB · 로그 · 작업 폴더에는 남기지 않는다.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import logging
import math
import os
import re
import stat
import string
import subprocess
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from app.core.calculix import tools
from app.core.stages import StageFailure

logger = logging.getLogger(__name__)

# --- 설정 — 환경 변수(앱이 `.env` 에서 읽어 실행기가 자식에 넘긴다) ---------------------

BASE_URL_ENV = "STE_BASE_URL"
SECRET_ENV = "STE_SSO_SECRET"
CLIENT_ENV = "STE_SSO_CLIENT"
APP_ENV = "STE_CALCULIX_APP"
POLL_ENV = "STE_POLL_SECONDS"
POLL_GRACE_ENV = "STE_POLL_GRACE_SECONDS"
MEM_MAX_ENV = "STE_MEM_GB_MAX"
TOKEN_DIR_ENV = "STE_TOKEN_DIR"

DEFAULT_APP = "calculix"
#: 상태를 묻는 간격(초) — 요청서 E-1 의 15초.
POLL_SECONDS = 15.0
#: 상태를 못 읽어도 이만큼은 기다린다 — STE 백엔드 재기동 · 포털 nginx 재적재 한 번에 몇
#: 시간짜리 해석을 버리지 않는다. 업로드 · 제출은 기다리지 않는다(아직 아무것도 안 걸었다).
POLL_GRACE_SECONDS = 300.0
#: 토큰 수명이 이만큼 남으면 미리 새로 받는다.
RENEW_MARGIN_SECONDS = 600.0
#: STE 가 수명을 안 적으면 — 포털 중계의 기본(12시간).
DEFAULT_TOKEN_SECONDS = 43200
#: SPOOLES 어림에 곱하는 여유(요청서 E-1). `solve.MEMORY_SHARE`(0.7)의 역수보다 작아야 직접
#: 솔버를 그대로 고른다 — 1/1.5 = 0.67 < 0.7.
MEMORY_MARGIN = 1.5
MEM_GB_MIN = 2
MEM_GB_MAX = 64
HTTP_TIMEOUT = httpx.Timeout(60.0, connect=10.0)

#: 짐작이 든 경로는 여기 한 곳(모듈 머리글).
ENDPOINTS = {
    "sso": "/api/auth/sso",
    "uploads": "/api/uploads",
    "upload_file": "/api/uploads/{upload}/{name}",
    "jobs": "/api/jobs",
    "job": "/api/jobs/{job}",
    "cancel": "/api/jobs/{job}/cancel",
    "result_file": "/api/jobs/{job}/result/file/{name}",
    # 대기열 요약 — `cluster_info` 가 쓰는 길(포털 게이트웨이 점검이 `GET /api/cluster` 를
    # 부른다). 응답 꼴은 요청서 S-3 이 바라는 것으로 읽는다(`_queue`) — 모르는 칸은 버린다.
    "cluster": "/api/cluster",
}

#: 결과로 받아 올 파일 — 로컬 ccx 가 작업 폴더에 남기는 것과 같은 이름(요청서 A-2).
RESULT_FILES = ("model.frd", "model.dat", "model.sta", "model.cvg", "ccx.out")
#: Slurm 로그는 이름을 바꿔 둔다 — 실패를 읽을 단서다.
SLURM_LOG = ("slurm.out", "ste-slurm.out")
#: 이 작업이 낸 STE 잡의 장부(한 줄에 하나, 토큰 없음) — 부모(워커)가 읽어 단계 기록 · 감사로
#: 옮긴다. 자식이 도중에 죽어도 낸 잡은 여기 남는다.
LEDGER_NAME = ".ste-jobs.jsonl"

#: Slurm 이 끝낸 상태들.
FINISHED = frozenset(
    {
        "COMPLETED",
        "FAILED",
        "OUT_OF_MEMORY",
        "TIMEOUT",
        "CANCELLED",
        "NODE_FAIL",
        "PREEMPTED",
        "BOOT_FAIL",
        "DEADLINE",
    }
)
RUNNING = frozenset({"RUNNING", "COMPLETING"})

#: 이름 머리에서 그대로 두는 글자 — 출력 가능한 ASCII 에서 `%` 만 뺀다(HWAXPortal
#: `ste_credential._NAME_SAFE` 와 같은 규칙 — 한글 이름이면 httpx 가 머리를 못 싣는다).
_NAME_SAFE = "".join(c for c in string.printable if c not in "%\t\n\r\x0b\x0c")
_SHA = re.compile(r"sha256\s*[:=]\s*([0-9a-f]{64})", re.IGNORECASE)


@dataclass(frozen=True)
class SteConfig:
    base_url: str
    secret: str
    client: str
    app: str = DEFAULT_APP
    poll_seconds: float = POLL_SECONDS
    poll_grace_seconds: float = POLL_GRACE_SECONDS
    mem_gb_max: int = MEM_GB_MAX
    token_dir: Path | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> SteConfig:
        """**비밀이 비면 STE 를 못 쓴다** — 그때 STE 로 걸린 작업은 `ste_auth` 로 끝난다."""
        env = os.environ if env is None else env
        base = env.get(BASE_URL_ENV, "").strip().rstrip("/")
        secret = env.get(SECRET_ENV, "").strip()
        client = env.get(CLIENT_ENV, "").strip()
        if not base or not secret or not client:
            raise StageFailure(
                "ste_auth",
                "이 서버에 STE 가 설정돼 있지 않습니다(STE_BASE_URL · STE_SSO_SECRET). "
                "STE 에서 풀도록 건 작업이라 로컬로 돌리지 않습니다 — 풀 곳을 「이 서버」 로 "
                "다시 거세요.",
            )
        given = env.get(TOKEN_DIR_ENV, "").strip()
        return cls(
            base_url=base,
            secret=secret,
            client=client,
            app=env.get(APP_ENV, "").strip() or DEFAULT_APP,
            poll_seconds=float(env.get(POLL_ENV, "") or POLL_SECONDS),
            poll_grace_seconds=float(env.get(POLL_GRACE_ENV, "") or POLL_GRACE_SECONDS),
            mem_gb_max=int(env.get(MEM_MAX_ENV, "") or MEM_GB_MAX),
            token_dir=Path(given) if given else default_token_dir(client),
        )


def default_token_dir(client: str) -> Path | None:
    """메모리 파일시스템이 있으면 그 아래 — 같은 기계의 워커(Apptainer 도 호스트의 `/dev/shm`
    을 본다)가 나눠 쓴다. 없으면 프로세스 안에서만."""
    shm = Path("/dev/shm")
    return shm / f"{client}-ste-{os.getuid()}" if shm.is_dir() else None


#: 시험이 가짜 STE 를 꽂는 자리(`httpx.MockTransport`). 운영은 비운다.
TRANSPORT: httpx.BaseTransport | None = None


def http_client() -> httpx.Client:
    return httpx.Client(timeout=HTTP_TIMEOUT, transport=TRANSPORT)


def _detail(response: httpx.Response) -> str:
    """STE 의 오류 한 줄(`{"detail": …}`) — 사람이 읽을 문장이면 그대로 보인다(요청서 P-2)."""
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()[:200]
    if isinstance(body, dict):
        for key in ("detail", "error", "message"):
            if body.get(key):
                return str(body[key])[:300]
    return str(body)[:200]


# --- 토큰 ---------------------------------------------------------------------------------


def mint(
    config: SteConfig, http: httpx.Client, email: str, name: str = ""
) -> tuple[str, float]:
    """그 사람 명의의 STE 토큰 하나(토큰, 만료 시각 epoch)."""
    headers = {
        "X-Heax-Gateway-Secret": config.secret,
        "X-Heax-User-Email": email,
        "X-Heax-User-Name": quote(name or "", safe=_NAME_SAFE),
        "X-Heax-Client": config.client,
    }
    try:
        response = http.post(config.base_url + ENDPOINTS["sso"], headers=headers)
    except httpx.HTTPError as failure:
        raise StageFailure(
            "ste_unavailable",
            f"STE 에 닿지 못해 {email} 명의의 토큰을 받지 "
            f"못했습니다({type(failure).__name__}).",
        ) from failure
    if response.status_code >= 500:
        raise StageFailure(
            "ste_unavailable",
            f"STE 가 토큰 발급에 {response.status_code} 로 답했습니다: {_detail(response)}",
        )
    if response.status_code != 200:
        raise StageFailure(
            "ste_auth",
            f"STE 가 {email} 명의의 토큰을 내주지 않았습니다(HTTP {response.status_code}): "
            f"{_detail(response)}",
        )
    try:
        body = response.json()
    except ValueError:
        body = {}
    token = str((body or {}).get("access_token") or "").strip()
    if not token:
        raise StageFailure("ste_auth", f"STE 가 {email} 명의의 토큰을 비워 보냈습니다.")
    seconds = int((body or {}).get("expires_in") or DEFAULT_TOKEN_SECONDS)
    return token, time.time() + seconds


class Tokens:
    """사람별 STE 토큰 — 프로세스 안 + **같은 기계의 워커끼리**(모듈 머리글 「토큰을 왜…」).

    `get` 은 살아 있는 것을 주고(없거나 곧 끝나면 받는다), `renew` 는 401 을 받은 뒤에 부른다 —
    나눠 둔 것이 그 죽은 토큰과 다르면 **다른 워커가 이미 새로 받은 것**이라 그대로 쓴다.
    """

    def __init__(
        self,
        config: SteConfig,
        http: httpx.Client,
        *,
        minter: Callable[[SteConfig, httpx.Client, str, str], tuple[str, float]] = mint,
    ) -> None:
        self.config = config
        self.http = http
        self.minter = minter
        self._memo: dict[str, tuple[str, float]] = {}
        self.directory = _usable_dir(config.token_dir)

    def get(self, email: str, name: str = "") -> str:
        memo = self._memo.get(email)
        if memo and _alive(memo):
            return memo[0]
        with self._shared(email) as shared:
            found = shared.read()
            if found and _alive(found):
                self._memo[email] = found
                return found[0]
            return self._mint(email, name, shared)

    def renew(self, email: str, stale: str, name: str = "") -> str:
        with self._shared(email) as shared:
            found = shared.read()
            if found and found[0] != stale and _alive(found):
                self._memo[email] = found
                return found[0]
            return self._mint(email, name, shared)

    def _mint(self, email: str, name: str, shared: _Shared) -> str:
        fresh = self.minter(self.config, self.http, email, name)
        self._memo[email] = fresh
        shared.write(fresh)
        logger.info("STE 토큰을 받았습니다(%s, client %s)", email, self.config.client)
        return fresh[0]

    @contextlib.contextmanager
    def _shared(self, email: str) -> Iterator[_Shared]:
        if self.directory is None:
            yield _Shared(None)
            return
        key = hashlib.sha256(f"{self.config.client}\n{email}".encode()).hexdigest()[:32]
        lock = os.open(self.directory / f"{key}.lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield _Shared(self.directory / f"{key}.json")
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            os.close(lock)


def _alive(entry: tuple[str, float]) -> bool:
    return entry[1] - time.time() > RENEW_MARGIN_SECONDS


def _usable_dir(directory: Path | None) -> Path | None:
    """나눠 쓸 폴더 — **내 것이고 남이 못 들여다볼 때만**(0700). 아니면 프로세스 안에서만
    둔다."""
    if directory is None:
        return None
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = directory.stat()
    except OSError as failure:
        logger.warning(
            "STE 토큰 폴더를 못 씁니다(%s): %s — 워커마다 따로 받습니다", directory, failure
        )
        return None
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        logger.warning(
            "STE 토큰 폴더 %s 가 내 것이 아니거나 남이 읽을 수 있습니다 — 쓰지 않습니다",
            directory,
        )
        return None
    return directory


@dataclass(frozen=True)
class _Shared:
    path: Path | None

    def read(self) -> tuple[str, float] | None:
        if self.path is None:
            return None
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            return str(saved["token"]), float(saved["expires_at"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def write(self, entry: tuple[str, float]) -> None:
        if self.path is None:
            return
        temporary = self.path.with_suffix(f".{os.getpid()}.tmp")
        handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump({"token": entry[0], "expires_at": entry[1]}, out)
        os.replace(temporary, self.path)


# --- 한 사람 명의의 호출 ------------------------------------------------------------------


class SteSession:
    """한 사람 명의로 STE 를 부른다 — **401 이면 한 번만** 다시 받아 같은 요청을 다시
    보낸다."""

    def __init__(
        self,
        config: SteConfig,
        email: str,
        *,
        name: str = "",
        http: httpx.Client,
        tokens: Tokens,
    ) -> None:
        self.config = config
        self.email = email
        self.name = name
        self.http = http
        self.tokens = tokens

    def call(self, method: str, path: str, *, what: str, **kwargs: Any) -> httpx.Response:
        """보낸다. 닿지 못함 · 5xx 는 `ste_unavailable`, 두 번째 401 은 `ste_auth` — 나머지
        응답은 부른 쪽이 가른다."""
        token = self.tokens.get(self.email, self.name)
        for attempt in (0, 1):
            try:
                response = self.http.request(
                    method,
                    self.config.base_url + path,
                    headers={"Authorization": f"Bearer {token}"},
                    **kwargs,
                )
            except httpx.HTTPError as failure:
                raise StageFailure(
                    "ste_unavailable",
                    f"STE 에 닿지 못했습니다({what}: {type(failure).__name__}).",
                ) from failure
            if response.status_code == 401 and attempt == 0:
                token = self.tokens.renew(self.email, token, self.name)
                continue
            break
        if response.status_code == 401:
            raise StageFailure(
                "ste_auth",
                f"STE 가 {self.email} 명의의 토큰을 받지 않습니다({what}, 다시 받아도 401): "
                f"{_detail(response)}",
            )
        if response.status_code >= 500:
            raise StageFailure(
                "ste_unavailable",
                f"STE 가 {what} 에 {response.status_code} 로 답했습니다: {_detail(response)}",
            )
        return response

    def accepted(self, response: httpx.Response, what: str) -> dict[str, Any]:
        """업로드 · 제출의 답 — 4xx 면 `ste_rejected`(STE 의 문장을 그대로)."""
        if response.status_code >= 400:
            raise StageFailure(
                "ste_rejected",
                f"STE 가 {what} 을 거절했습니다(HTTP {response.status_code}): "
                f"{_detail(response)}",
            )
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise StageFailure("ste_rejected", f"STE 의 {what} 답이 JSON 이 아닙니다.")
        return body


def _submit_form(app: str, upload: str, params: dict[str, Any]) -> dict[str, str]:
    """제출 본문 — 짐작(모듈 머리글). 폼 칸 셋, 인자는 JSON 글자로."""
    return {"app": app, "upload_id": upload, "params": json.dumps(params)}


def _state(status: dict[str, Any]) -> str:
    """STE 상태 → Slurm 낱말 하나. 일반 FAILED 에 Slurm 최종 상태가 따로 실려 오면 그것을
    본다(메모리 · 시간 초과는 재시도가 갈린다 — 요청서 A-3). `CANCELLED by 1000` 같은 꼴도
    받는다."""
    words = [
        str(status.get(key) or "").strip().upper().split(" ")[0]
        for key in ("state", "slurm_state")
    ]
    state, slurm = words
    if slurm in {"OUT_OF_MEMORY", "TIMEOUT", "CANCELLED"} and state in {"", "FAILED"}:
        return slurm
    reason = str(status.get("reason_code") or "").lower()
    if state == "FAILED" and reason in {"out_of_memory", "oom"}:
        return "OUT_OF_MEMORY"
    if state == "FAILED" and reason == "timeout":
        return "TIMEOUT"
    return state or slurm


# --- 고를 수 있나(요청서 E-2) -------------------------------------------------------

#: 화면이 기다리는 한도 — 고르는 창이 STE 를 오래 기다리면 안 된다.
PROBE_TIMEOUT = httpx.Timeout(8.0, connect=5.0)
#: 대기열 요약에서 읽는 칸(요청서 S-3) — STE 가 다른 이름을 쓰면 여기만 고친다.
QUEUE_KEYS = (
    "partition",
    "cpus_total",
    "cpus_allocated",
    "cpus_idle",
    "jobs_pending",
    "jobs_running",
)


@dataclass(frozen=True)
class Probe:
    """이 사람 명의로 STE 를 쓸 수 있나 — 못 쓰면 까닭(사람이 읽을 한 줄), 쓰면 대기열."""

    available: bool
    reason: str | None = None
    queue: dict[str, Any] | None = None


def probe(config: SteConfig, email: str, name: str = "") -> Probe:
    """**그 사람의 토큰을 받아** 대기열 요약을 묻는다. 토큰은 워커와 같은 자리에 나눠 둔 것을
    쓴다(`Tokens`) — 살아 있으면 새로 받지 않는다(새로 받으면 그 사람의 돌던 잡의 토큰이
    바뀐다 — 그래도 워커는 나눠 둔 것을 다시 읽어 잇는다). 요약 길이 없으면(404) 쓸 수는 있다고
    본다."""
    http = httpx.Client(timeout=PROBE_TIMEOUT, transport=TRANSPORT)
    try:
        session = SteSession(config, email, name=name, http=http, tokens=Tokens(config, http))
        response = session.call("GET", ENDPOINTS["cluster"], what="대기열 요약")
    except StageFailure as failure:
        return Probe(False, failure.message)
    finally:
        http.close()
    if response.status_code >= 400:
        return Probe(True)
    try:
        body = response.json()
    except ValueError:
        return Probe(True)
    return Probe(True, None, _queue(body))


def _queue(body: Any) -> dict[str, Any] | None:
    """`GET /api/cluster` → `{partition, cpus_total, cpus_allocated, cpus_idle, jobs_pending,
    jobs_running, mine: {running, pending}}` 중 있는 것만. 남은 코어는 없으면 셈한다."""
    if not isinstance(body, dict):
        return None
    summary = body.get("summary")
    source: dict[str, Any] = summary if isinstance(summary, dict) else body
    found: dict[str, Any] = {
        key: source[key]
        for key in QUEUE_KEYS
        if isinstance(source.get(key), int | float | str)
    }
    total, allocated = found.get("cpus_total"), found.get("cpus_allocated")
    if "cpus_idle" not in found and isinstance(total, int) and isinstance(allocated, int):
        found["cpus_idle"] = total - allocated
    mine = source.get("mine")
    if isinstance(mine, dict):
        found["mine"] = {
            key: mine[key] for key in ("running", "pending") if isinstance(mine.get(key), int)
        }
    return found or None


# --- ccx 한 번 ------------------------------------------------------------------------------


@dataclass
class SteCcx:
    """`solve()` 의 ccx 자리 — STE 판. **부를 때마다 업로드 · 잡이 새로 생긴다**(업로드는 한
    번만 쓴다). 재시도 · 모드 찾기로 다시 부르면 STE 대기열에 다시 선다 — 그 사실이 `jobs` 에
    남는다."""

    session: SteSession
    workdir: Path
    threads: int = 2
    mem_gb: int = MEM_GB_MIN
    jobs: list[dict[str, Any]] = field(default_factory=list)
    sleep: Callable[[float], None] = time.sleep
    where: str = "ste"

    @classmethod
    def start(cls, workdir: Path, *, email: str | None, name: str = "") -> SteCcx:
        config = SteConfig.from_env()
        if not email:
            raise StageFailure(
                "ste_auth",
                "작업을 건 사람이 없어 STE 를 쓸 수 없습니다 — STE 잡은 건 사람 명의로만 "
                "냅니다(옛 작업 · 시스템 작업은 「이 서버」 로 거세요).",
            )
        http = http_client()
        session = SteSession(config, email, name=name, http=http, tokens=Tokens(config, http))
        return cls(
            session=session,
            workdir=workdir,
            threads=_threads(os.environ.get(tools.THREADS_ENV, "")),
        )

    # --- solve() 가 부르는 셋 ---

    def available_mb(self, estimate_mb: float) -> float:
        """**잡에 청할 메모리가 곧 쓸 수 있는 메모리다** — SPOOLES 어림 x 여유, 위아래를
        묶는다. 어림이 상한을 넘으면 상한을 주고, `plan_solver` 가 반복 솔버를 고른다(고를 수
        있으면)."""
        wanted = math.ceil(max(estimate_mb, 1.0) * MEMORY_MARGIN / 1024)
        self.mem_gb = max(MEM_GB_MIN, min(self.session.config.mem_gb_max, wanted))
        return float(self.mem_gb * 1024)

    def run(
        self, deck: Path, *, timeout_seconds: int, env_extra: Mapping[str, str] | None
    ) -> subprocess.CompletedProcess[str]:
        session = self.session
        config = session.config
        equation = int((env_extra or {}).get("CCX_NPROC_EQUATION_SOLVER") or self.threads)
        params = {
            "deck": deck.stem,
            "threads": self.threads,
            "equation_solver_threads": equation,
            "mem_gb": self.mem_gb,
            "time_limit_min": max(1, math.ceil(timeout_seconds / 60)),
        }
        # **지난 결과를 먼저 지운다** — 이번 잡이 어떤 파일을 못 내면, 지난 잡의 것을 이번
        # 것으로 읽게 된다(모드 찾기 · 반복 솔버 재시도가 같은 폴더를 다시 푼다).
        for name in (*RESULT_FILES, SLURM_LOG[1]):
            (self.workdir / name).unlink(missing_ok=True)

        upload = session.accepted(
            session.call("POST", ENDPOINTS["uploads"], what="업로드 만들기"), "업로드 만들기"
        )
        upload_id = str(upload.get("id") or "")
        if not upload_id:
            raise StageFailure("ste_rejected", "STE 가 업로드 번호를 주지 않았습니다.")
        session.accepted(self._put(upload_id, deck), "덱 올리기")
        submitted = session.accepted(
            session.call(
                "POST",
                ENDPOINTS["jobs"],
                what="잡 내기",
                data=_submit_form(config.app, upload_id, params),
            ),
            "잡 내기",
        )
        job = str(submitted.get("id") or submitted.get("job_id") or "")
        if not job:
            raise StageFailure("ste_rejected", "STE 가 잡 번호를 주지 않았습니다.")
        record: dict[str, Any] = {
            "where": "ste",
            "ste_job_id": job,
            "upload_id": upload_id,
            "mem_gb": self.mem_gb,
            "threads": self.threads,
            "equation_solver_threads": equation,
        }
        self._ledger({"event": "submit", **record, "at": time.time()})
        logger.info(
            "STE 잡 %s 를 냈습니다(%s 명의, 메모리 %d GB · 스레드 %d)",
            job,
            session.email,
            self.mem_gb,
            self.threads,
        )

        status, queued, running = self._wait(job, timeout_seconds)
        state = _state(status)
        self._fetch(job)
        log_path = self.workdir / RESULT_FILES[-1]
        log = (
            log_path.read_text(encoding="utf-8", errors="replace")
            if log_path.is_file()
            else ""
        )
        found = _SHA.search(log.split("\n", 1)[0])
        record.update(
            ste_state=state,
            exit_code=status.get("exit_code"),
            reason_code=status.get("reason_code"),
            queued_s=round(queued, 1),
            run_s=round(running, 1),
            max_rss_mb=status.get("max_rss_mb"),
            ccx_sha256=status.get("ccx_sha256") or (found.group(1) if found else None),
        )
        self.jobs.append(record)
        self._ledger({"event": "end", **record, "at": time.time()})
        return self._outcome(record, log)

    def summary(self) -> dict[str, object]:
        if not self.jobs:
            return {}
        return {
            "solved_on": "ste",
            "ste_jobs": len(self.jobs),
            "ste_mem_gb": self.mem_gb,
            "ste_queued_seconds": round(sum(one.get("queued_s") or 0 for one in self.jobs), 1),
            "ste_run_seconds": round(sum(one.get("run_s") or 0 for one in self.jobs), 1),
        }

    def detail(self) -> str:
        if not self.jobs:
            return ""
        queued = sum(one.get("queued_s") or 0 for one in self.jobs)
        return f" · STE 잡 {len(self.jobs)}개(대기 {queued:.0f}초)"

    # --- 속 ---

    def _put(self, upload_id: str, deck: Path) -> httpx.Response:
        return self.session.call(
            "PUT",
            ENDPOINTS["upload_file"].format(upload=upload_id, name=deck.name),
            what="덱 올리기",
            content=deck.read_bytes(),
        )

    def _wait(self, job: str, timeout_seconds: int) -> tuple[dict[str, Any], float, float]:
        """끝날 때까지 묻는다 → (마지막 상태, 대기 초, 실행 초). 못 읽는 동안은 `poll_grace`
        까지 참는다. 시간을 넘기면 STE 에서 취소하고 `timeout`."""
        config = self.session.config
        submitted = time.monotonic()
        last_heard = submitted
        began: float | None = None
        while True:
            status: dict[str, Any] | None = None
            try:
                response = self.session.call(
                    "GET", ENDPOINTS["job"].format(job=job), what="잡 상태"
                )
            except StageFailure as failure:
                if failure.code != "ste_unavailable":
                    raise
                if time.monotonic() - last_heard > config.poll_grace_seconds:
                    raise StageFailure(
                        "ste_unavailable",
                        f"STE 잡 {job} 의 상태를 {config.poll_grace_seconds:.0f}초 넘게 못 "
                        f"읽었습니다 — {failure.message}",
                    ) from failure
                logger.warning("STE 잡 %s 상태를 못 읽었습니다 — 다시 묻습니다", job)
            else:
                if response.status_code >= 400:
                    raise StageFailure(
                        "ste_rejected",
                        f"STE 가 잡 {job} 의 상태를 주지 않습니다"
                        f"(HTTP {response.status_code}): {_detail(response)}",
                    )
                last_heard = time.monotonic()
                body = response.json()
                status = body if isinstance(body, dict) else {}
            now = time.monotonic()
            if status is not None:
                state = _state(status)
                if began is None and state in RUNNING:
                    began = now
                if state in FINISHED:
                    started = began if began is not None else now
                    return (status, *_durations(status, started - submitted, now - started))
            if now - submitted > timeout_seconds:
                self._cancel(job)
                raise StageFailure(
                    "timeout",
                    f"STE 잡 {job} 이 {timeout_seconds}초 안에 끝나지 않았습니다(대기열에 선 "
                    "시간 포함) — STE 에서 취소했습니다.",
                )
            self.sleep(config.poll_seconds)

    def _cancel(self, job: str) -> None:
        """되는 만큼만 — 취소가 실패해도 이쪽의 판정은 그대로다."""
        with contextlib.suppress(StageFailure):
            self.session.call("POST", ENDPOINTS["cancel"].format(job=job), what="잡 취소")

    def _fetch(self, job: str) -> None:
        """결과를 같은 이름으로. 없는 파일(404)은 건너뛴다 — 무엇이 빠졌는지는 판정이
        말한다."""
        for name in RESULT_FILES:
            self._download(job, name, self.workdir / name)
        with contextlib.suppress(StageFailure):
            self._download(job, SLURM_LOG[0], self.workdir / SLURM_LOG[1])

    def _download(self, job: str, name: str, target: Path) -> None:
        path = ENDPOINTS["result_file"].format(job=job, name=name)
        token = self.session.tokens.get(self.session.email, self.session.name)
        url = self.session.config.base_url + path
        for attempt in (0, 1):
            try:
                with self.session.http.stream(
                    "GET", url, headers={"Authorization": f"Bearer {token}"}
                ) as response:
                    if response.status_code == 401 and attempt == 0:
                        token = self.session.tokens.renew(
                            self.session.email, token, self.session.name
                        )
                        continue
                    if response.status_code == 404:
                        return
                    if response.status_code >= 400:
                        raise StageFailure(
                            "ste_unavailable"
                            if response.status_code >= 500
                            else "ste_rejected",
                            f"STE 잡 {job} 의 {name} 을 받지 못했습니다"
                            f"(HTTP {response.status_code}).",
                        )
                    partial = target.with_name(target.name + ".part")
                    with partial.open("wb") as out:
                        for chunk in response.iter_bytes():
                            out.write(chunk)
                    os.replace(partial, target)
                    return
            except httpx.HTTPError as failure:
                raise StageFailure(
                    "ste_unavailable",
                    f"STE 잡 {job} 의 {name} 을 받다 끊겼습니다({type(failure).__name__}).",
                ) from failure
        raise StageFailure(
            "ste_auth",
            f"STE 가 {self.session.email} 명의의 토큰을 받지 않습니다({name} 받기).",
        )

    def _outcome(self, record: dict[str, Any], log: str) -> subprocess.CompletedProcess[str]:
        """Slurm 의 끝 → 로컬과 같은 판정 재료. 메모리 · 시간 초과는 로컬의 그 실패 코드로
        올린다 (`solve()` 가 메모리면 반복 솔버로 한 번 더 푼다)."""
        from app.core.calculix.solve import ERROR_MARK  # 순환 import 를 피한다

        job, state = record["ste_job_id"], record["ste_state"]
        exit_code = record.get("exit_code")
        if state == "OUT_OF_MEMORY":
            used = record.get("max_rss_mb")
            raise StageFailure(
                "out_of_memory",
                f"CalculiX 가 STE 잡 메모리({self.mem_gb} GB)를 넘어 Slurm 이 끊었습니다"
                f"(잡 {job}"
                + (f", 최대 {used:,.0f} MB" if isinstance(used, int | float) else "")
                + ").",
            )
        if state == "TIMEOUT":
            raise StageFailure(
                "timeout", f"STE 잡 {job} 이 시간 한도를 넘어 Slurm 이 끊었습니다."
            )
        if state == "CANCELLED":
            raise StageFailure(
                "solver_failed",
                f"STE 에서 잡 {job} 이 취소됐습니다 — 이 서버가 멈춘 것이 아닙니다(STE 화면 · "
                "관리자가 멈췄을 수 있습니다).",
            )
        code = int(exit_code) if isinstance(exit_code, int | float) else 0
        if state == "COMPLETED" or (
            state == "FAILED" and (code != 0 or ERROR_MARK.search(log))
        ):
            # 판정은 `_judged` 가 로컬과 똑같이 — 같은 덱이면 같은 실패 문장이다.
            return subprocess.CompletedProcess(
                args=["ccx", "(STE)", job], returncode=code, stdout=log, stderr=""
            )
        reason = record.get("reason_code")
        raise StageFailure(
            "solver_failed",
            f"STE 잡 {job} 이 {state}"
            + (f"({reason})" if reason else "")
            + " 로 끝났습니다 — ccx 는 오류를 적지 않았습니다. "
            f"{SLURM_LOG[1]} 을 보거나 다시 걸어 보세요.",
        )

    def _ledger(self, entry: dict[str, Any]) -> None:
        with (self.workdir / LEDGER_NAME).open("a", encoding="utf-8") as out:
            out.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _threads(given: str) -> int:
    """`OMP_NUM_THREADS` → 잡의 스레드 수. `4,2`(OpenMP 겹 단계)면 바깥 수, 못 읽으면 2."""
    head = given.split(",")[0].strip()
    return int(head) if head.isdigit() and int(head) > 0 else 2


def _durations(status: dict[str, Any], queued: float, running: float) -> tuple[float, float]:
    """(대기 초, 실행 초) — **STE 가 시각을 적어 주면 그것**(폴링 간격 15초보다 정확하다),
    아니면 이쪽에서 본 것. 짧은 잡은 RUNNING 을 못 보고 끝나므로 본 것으로는 실행이 0 이
    된다."""

    def moment(*keys: str) -> float | None:
        for key in keys:
            value = status.get(key)
            if isinstance(value, int | float):
                return float(value)
            if isinstance(value, str) and value:
                with contextlib.suppress(ValueError):
                    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        return None

    begun = moment("started_at", "start_time")
    ended = moment("ended_at", "finished_at", "end_time")
    asked = moment("submitted_at", "created_at", "submit_time")
    if begun is not None and ended is not None and ended >= begun:
        running = ended - begun
        if asked is not None and begun >= asked:
            queued = begun - asked
    return queued, running


def ledger_size(workdir: Path) -> int:
    """장부의 지금 크기 — 부모가 단계 앞에서 재 두고, 뒤에 그 뒤만 읽는다(`read_ledger`)."""
    try:
        return (workdir / LEDGER_NAME).stat().st_size
    except OSError:
        return 0


def read_ledger(workdir: Path, offset: int = 0) -> list[dict[str, Any]]:
    """`offset` 뒤에 적힌 잡들 — 잡마다 한 행(낸 것 + 끝난 것을 합친다), 낸 차례대로."""
    try:
        with (workdir / LEDGER_NAME).open("rb") as handle:
            handle.seek(offset)
            raw = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    jobs: dict[str, dict[str, Any]] = {}
    for line in raw.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or not entry.get("ste_job_id"):
            continue
        entry.pop("event", None)
        entry.pop("at", None)
        jobs.setdefault(str(entry["ste_job_id"]), {}).update(entry)
    return list(jobs.values())
