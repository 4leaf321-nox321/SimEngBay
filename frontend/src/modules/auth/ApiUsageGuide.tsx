/**
 * 발급한 토큰으로 API 를 부르는 법 — curl · Python.
 *
 * 토큰을 발급한 자리에서 바로 보여 준다. 사람은 토큰을 받아 들고 「이걸 어디에 넣지」 에서 막히고,
 * 그때 README 를 찾아가는 사람은 드물다. 발급 전에도 예시 형식은 보여 주되 토큰 자리는 자리표시자.
 *
 * 이 플랫폼의 기계 쪽 사용자는 **오케스트레이터**(CAD 형상 · 물성 · 경계조건을 보내고 결과를
 * 받아 가는 쪽)다. 그래서 AI 도구 연결이 아니라 HTTP 호출 예를 준다.
 */

import { useState } from "react";

import { Button } from "@/shared/components/ui/button";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/shared/components/ui/tabs";
import { PUBLIC_PATH } from "@/shared/base";
import { copyText } from "@/shared/lib/clipboard";

const TOKEN_PLACEHOLDER = "‹발급받은_토큰›";

/** 이 설치의 API 주소. 브라우저 밖(시험)에서는 상대 경로. */
export function apiBase(): string {
  if (typeof window === "undefined") return "/api";
  return `${window.location.origin}${PUBLIC_PATH}/api`;
}

export function usageSnippets(token: string | null, base = apiBase()) {
  const tok = token || TOKEN_PLACEHOLDER;
  const curl =
    `curl -H 'Authorization: Bearer ${tok}' \\\n` + `  ${base}/auth/me`;
  const python =
    `import requests\n\n` +
    `API = "${base}"\n` +
    `HEADERS = {"Authorization": "Bearer ${tok}"}\n\n` +
    `me = requests.get(f"{API}/auth/me", headers=HEADERS, timeout=30)\n` +
    `me.raise_for_status()\n` +
    `print(me.json())`;
  return { curl, python };
}

function Snippet({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState<"ok" | "fail" | null>(null);
  return (
    <div className="space-y-2">
      <pre className="bg-muted overflow-x-auto rounded px-2 py-2 font-mono text-[11px] whitespace-pre">
        {text}
      </pre>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() =>
            copyText(text)
              .then(() => setDone("ok"))
              .catch(() => setDone("fail"))
          }
        >
          {label} 복사
        </Button>
        {done === "ok" && (
          <span className="text-muted-foreground text-xs">복사됨</span>
        )}
        {done === "fail" && (
          <span className="text-destructive text-xs">
            복사 실패 — 직접 선택해 복사하세요
          </span>
        )}
      </div>
    </div>
  );
}

export function ApiUsageGuide({ token }: { token: string | null }) {
  const base = apiBase();
  const s = usageSnippets(token, base);
  return (
    <section className="space-y-3 rounded-md border p-4">
      <div>
        <h3 className="text-sm font-semibold">API 호출 예</h3>
        <p className="text-muted-foreground mt-1 text-xs">
          토큰은 <span className="font-mono">Authorization: Bearer</span> 헤더로
          보냅니다. 경로 목록은{" "}
          <a
            className="underline"
            href={`${base}/docs`}
            target="_blank"
            rel="noreferrer"
          >
            API 문서
          </a>
          에 있습니다. 주소: <span className="font-mono">{base}</span>
        </p>
      </div>
      {!token && (
        <div className="bg-muted/40 text-muted-foreground rounded-md border border-dashed px-3 py-2 text-xs">
          아직 토큰을 발급하지 않았습니다. 아래는 예시 형식이고 토큰 자리에{" "}
          <span className="font-mono">{TOKEN_PLACEHOLDER}</span> 이 들어
          있습니다. 위에서 발급하면 실제 토큰이 채워집니다.
        </div>
      )}
      <Tabs defaultValue="curl" className="w-full">
        <TabsList className="w-full flex-wrap justify-start">
          <TabsTrigger value="curl">curl</TabsTrigger>
          <TabsTrigger value="python">Python</TabsTrigger>
        </TabsList>
        <TabsContent value="curl" className="space-y-2">
          <Snippet text={s.curl} label="명령" />
        </TabsContent>
        <TabsContent value="python" className="space-y-2">
          <Snippet text={s.python} label="코드" />
        </TabsContent>
      </Tabs>
    </section>
  );
}
