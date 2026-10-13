"""가짜 Standard Platform 코어 창구 — **연동 지침서 §4.2 의 약속대로** 답한다.

진짜 SP 없이 받는 쪽 규칙을 하나씩 시험하려고 둔다. 지키는 약속:

- `GET /api/core` 카탈로그(타입 · 칸 · 관계 · 건수 · 정의 판).
- `GET /api/core/{type}` · `/relations` — `since` 를 주면 그 뒤에 바뀐 것(무덤 포함), 안 주면
  살아 있는 것 전부. `limit` 만큼 자르고 `next`(커서)를 준다. **`next` 가 있으면 `as_of` 는
  null.**
- 무덤: `deleted` · `merged_into` · `hidden` · `renamed_from` · `previous_keys`.
- 404 두 가지 — `APP-CORE-0001`(공개 안 된 타입) · `APP-CORE-0002`(커서를 못 읽음).
- 선의 `reset` — 한 번 「처음부터 다시」 를 말한다.
- 토큰이 틀리면 401(SP 의 오류 봉투).
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.modules.ontology import sync

TOKEN = "standardplatform_pat_test"
BASE = "https://sp.example.com/api"


def _error(status: int, code: str, message: str) -> httpx.Response:
    return httpx.Response(
        status, json={"error": {"code": code, "message": message, "request_id": "req-1"}}
    )


class FakeCore:
    def __init__(self) -> None:
        self.revision = "1-aaaa"
        self.clock = 0
        self.types: dict[str, dict[str, Any]] = {}
        self.rows: dict[str, dict[str, dict[str, Any]]] = {}
        self.edges: dict[str, dict[tuple[str, str, str, str], dict[str, Any]]] = {}
        self.calls: list[tuple[str, dict[str, str]]] = []
        #: 경로 → 다음 몇 번의 답을 갈아 끼운다(5xx · 404 를 흉내 낼 때).
        self.overrides: dict[str, list[httpx.Response]] = {}
        #: 다음 선 요청에 「처음부터 다시」 를 한 번 말할 타입.
        self.reset_relations: set[str] = set()

    # --- SP 쪽에서 무엇이 바뀌었나 -------------------------------------------------------

    def stamp(self) -> str:
        self.clock += 1
        return f"2026-10-13T00:{self.clock // 60:02d}:{self.clock % 60:02d}.000000Z"

    def now(self) -> str:
        return f"2026-10-13T00:{self.clock // 60:02d}:{self.clock % 60:02d}.000000Z"

    def add_type(
        self,
        slug: str,
        label: str,
        properties: list[dict[str, Any]] | None = None,
        relations: list[str] | None = None,
    ) -> None:
        self.types[slug] = {
            "slug": slug,
            "label": label,
            "properties": properties or [],
            "relations": relations or [],
            "relation_kinds": [],
        }
        self.rows.setdefault(slug, {})
        self.edges.setdefault(slug, {})

    def put(self, slug: str, key: str, label: str, **fields: Any) -> None:
        row = {
            "key": key,
            "label": label,
            "status": fields.pop("status", "active"),
            "updated_at": self.stamp(),
            "deleted": False,
            "properties": fields.pop("properties", {}),
            **fields,
        }
        self.rows[slug][key] = row

    def rename(self, slug: str, old: str, new: str) -> None:
        row = self.rows[slug].pop(old)
        previous = [*row.get("previous_keys", []), old]
        self.put(
            slug,
            new,
            row["label"],
            properties=row["properties"],
            renamed_from=old,
            previous_keys=previous,
        )

    def delete(self, slug: str, key: str, merged_into: str | None = None) -> None:
        row = self.rows[slug][key]
        row.update(deleted=True, status="deprecated", updated_at=self.stamp(), properties={})
        if merged_into:
            row["merged_into"] = merged_into

    def hide(self, slug: str, key: str) -> None:
        self.rows[slug][key] = {
            "key": key,
            "deleted": True,
            "hidden": True,
            "updated_at": self.stamp(),
        }

    def link(self, slug: str, src: str, relation: str, dst: str, dst_type: str) -> None:
        self.edges[slug][(src, relation, dst, dst_type)] = {
            "src": src,
            "relation": relation,
            "dst": dst,
            "dst_type": dst_type,
            "evidence_note": "",
            "properties": {},
            "updated_at": self.stamp(),
            "deleted": False,
        }

    def unlink(self, slug: str, src: str, relation: str, dst: str, dst_type: str) -> None:
        edge = self.edges[slug][(src, relation, dst, dst_type)]
        edge.update(deleted=True, updated_at=self.stamp())

    def forget_edge(self, slug: str, src: str, relation: str, dst: str, dst_type: str) -> None:
        """끊긴 기록까지 사라진 선 — 오래 안 받아 간 쪽은 이것을 「끊김」 으로 못 듣는다."""
        del self.edges[slug][(src, relation, dst, dst_type)]

    # --- 창구 -----------------------------------------------------------------------------

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.rstrip("/")
        params = dict(request.url.params)
        self.calls.append((path, params))
        queued = self.overrides.get(path)
        if queued:
            return queued.pop(0)
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return _error(401, "APP-AUTH-0001", "토큰이 유효하지 않습니다.")
        parts = path.split("/")[3:]  # ['', 'api', 'core', ...]
        if not parts:
            return httpx.Response(200, json=self._catalog())
        slug = parts[0]
        relations = len(parts) > 1 and parts[1] == "relations"
        if slug not in self.types:
            return _error(404, "APP-CORE-0001", f"코어로 공개되지 않은 타입입니다: {slug}")
        cursor = params.get("cursor")
        offset = 0
        if cursor:
            if not cursor.startswith("c:"):
                return _error(404, "APP-CORE-0002", "커서를 읽을 수 없습니다.")
            offset = int(cursor[2:])
        since = params.get("since")
        limit = int(params.get("limit") or 500)
        if relations and since and slug in self.reset_relations:
            self.reset_relations.discard(slug)
            return httpx.Response(
                200,
                json={
                    "type_slug": slug,
                    "reset": True,
                    "reset_reason": "끊긴 선의 기록이 그보다 짧습니다",
                    "as_of": None,
                    "next": None,
                    "items": [],
                },
            )
        pool = list((self.edges if relations else self.rows)[slug].values())
        if since:
            pool = [one for one in pool if one["updated_at"] > since]
        else:
            pool = [one for one in pool if not one.get("deleted")]
        pool.sort(key=lambda one: (one["updated_at"], json.dumps(one, sort_keys=True)))
        page = pool[offset : offset + limit]
        more = offset + limit < len(pool)
        return httpx.Response(
            200,
            json={
                "type_slug": slug,
                "since": since,
                "as_of": None if more else self.now(),
                "next": f"c:{offset + limit}" if more else None,
                "items": page,
            },
        )

    def _catalog(self) -> dict[str, Any]:
        return {
            "system": "standardplatform",
            "revision": self.revision,
            "as_of": self.now(),
            "types": [
                {
                    **entry,
                    "count": sum(
                        1 for one in self.rows[slug].values() if not one.get("deleted")
                    ),
                    "endpoint": f"{BASE}/core/{slug}",
                }
                for slug, entry in self.types.items()
            ],
        }

    def client(self, token: str = TOKEN) -> sync.CoreClient:
        return sync.CoreClient(
            BASE, token, transport=httpx.MockTransport(self.handler), sleep=lambda _: None
        )


def materials_and_vendors() -> FakeCore:
    """재료 셋 · 공급사 둘 · 「공급」 선 — 시험이 함께 쓰는 처음 상태."""
    core = FakeCore()
    core.add_type(
        "vendor",
        "공급사",
        properties=[{"key": "country", "label": "나라", "data_type": "string"}],
    )
    core.add_type(
        "material",
        "재료",
        properties=[
            {"key": "density", "label": "밀도", "data_type": "number", "unit": "kg/m3"},
            {
                "key": "supplier",
                "label": "공급사",
                "data_type": "object_ref",
                "ref_type_slug": "vendor",
                "multi": False,
            },
        ],
        relations=["supplied_by"],
    )
    core.put("vendor", "ACME-001", "ACME 정밀", properties={"country": "KR"})
    core.put("vendor", "HAN-002", "한강금속", properties={"country": "KR"})
    core.put(
        "material",
        "SS400",
        "일반구조용강",
        properties={"density": 7850, "supplier": "ACME-001"},
    )
    core.put("material", "AL6061", "알루미늄 6061", properties={"density": 2700})
    core.put("material", "SUS304", "스테인리스 304", properties={"density": 7930})
    core.link("material", "SS400", "supplied_by", "ACME-001", "vendor")
    core.link("material", "AL6061", "supplied_by", "HAN-002", "vendor")
    return core
