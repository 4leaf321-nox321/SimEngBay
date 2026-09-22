/**
 * 부서 홈 — **남은 일이 먼저 온다.**
 *
 * 관리 화면에 들어가야만 보이는 목록은 아무도 안 본다. 승인 대기가 며칠씩
 * 방치되고, 안 채워진 자료는 영영 안 채워진다.
 *
 * ## 도메인이 여기에 무엇을 더하나
 *
 * **화면을 고쳐서 더하지 않는다.** 서버의 레지스트리(`shared/extensions.py`)에
 * `register_maintenance` 로 등록하면 「남은 일」 에 저절로 뜬다 — 실패한 해석 작업,
 * 결과를 아직 안 뽑은 작업 같은 것이 그 자리다.
 */

import { Link, useParams } from "react-router-dom";

import { api } from "@/shared/api/client";
import type { MaintenanceItem } from "@/shared/api/types";
import { useAuth } from "@/shared/auth/AuthContext";
import { APP_NAME } from "@/shared/branding";
import { ErrorNotice } from "@/shared/components/ErrorNotice";
import { PageHeader } from "@/shared/components/PageHeader";
import { useResource } from "@/shared/hooks/useResource";

export default function WorkspaceHomePage() {
  const { slug } = useParams<{ slug?: string }>();
  const { user } = useAuth();
  const maintenance = useResource(
    () => api.get<MaintenanceItem[]>("/server/maintenance"),
    [],
  );

  const workspace = user?.memberships.find((one) => one.slug === slug);

  return (
    <div className="space-y-8">
      <PageHeader
        title={workspace?.name ?? APP_NAME}
        description={
          workspace?.path ??
          "소속된 부서가 없습니다. 관리자에게 배정을 요청하세요."
        }
      />

      <ErrorNotice error={maintenance.error} />

      <section className="space-y-3">
        <h2 className="text-base font-semibold">남은 일</h2>
        {/* **0 건인 항목은 서버가 안 내보낸다.** 다 0 인 목록을 매일 보면 사람은
            그 자리를 아예 안 읽게 되고, 그때 진짜 하나가 떠도 눈에 안 들어온다. */}
        {maintenance.data && maintenance.data.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            지금 처리할 일이 없습니다.
          </p>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {(maintenance.data ?? []).map((one) => (
              <li
                key={one.key}
                className={
                  one.severity === "warning"
                    ? "rounded-md border border-amber-500/40 bg-amber-500/5 p-4"
                    : "rounded-md border p-4"
                }
              >
                <p className="text-2xl font-semibold">{one.count}</p>
                <p className="text-sm">{one.label}</p>
                {one.link && (
                  <Link
                    to={one.link}
                    className="text-muted-foreground mt-2 block text-xs underline"
                  >
                    보러 가기
                  </Link>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* 빈 화면으로 두지 않는다 — 빈 화면은 「아직 안 만들었다」 와 「고장났다」 가
          구별되지 않는다. 무엇이 여기 올지까지 적는다. */}
      <section className="rounded-md border border-dashed p-6">
        <h2 className="text-sm font-medium">
          이 아래가 해석 작업의 자리입니다
        </h2>
        <p className="text-muted-foreground mt-1 text-sm">
          이 부서가 건 해석 작업의 최근 상태(모델링 중 · 솔버 대기 · 결과 추출
          완료)와 실패한 작업이 여기에 표시됩니다. 1단계(FE 모델링 자동화)에서
          채워집니다.
        </p>
      </section>
    </div>
  );
}
