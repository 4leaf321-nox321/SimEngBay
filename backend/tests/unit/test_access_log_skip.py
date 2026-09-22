"""접근 로그가 무엇을 안 남기는가.

폴링 경로를 안 빼면 표가 그 한 줄로 차서 **조회할 수 없는 크기**가 된다. 반대로 너무 넓게
빼면 남아야 할 기록이 말없이 사라지고, 그 사실은 감사 기록이 필요한 날에야 드러난다.
"""

from __future__ import annotations

from app.shared.access_log import is_skipped


def test_폴링_경로만_비껴간다() -> None:
    """**「/status 로 끝나면 전부」 가 아니다** — 나중에 생기는 다른 `/status` 까지 삼킨다."""
    assert is_skipped("/api/simulations/8a02556d-6334-4a35-928d-0259bcd88d41/status")
    assert is_skipped("/api/health")
    assert not is_skipped("/api/server/status")
    assert not is_skipped("/api/simulations")
