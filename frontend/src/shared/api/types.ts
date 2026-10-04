/**
 * 공통 틀이 쓰는 API 타입 — **서버가 낸 스키마의 별칭이다.**
 *
 * ## 정본은 서버다
 *
 * 처음 설치에서는 이 파일이 손으로 적혀 있었다(생성기가 `node_modules` 안에 있어서 막 클론한
 * 사람은 아직 그것을 돌릴 수 없었다). 지금은 `npm run build` 앞의 `prebuild` 가 생성기를 부르므로
 * 그 이유가 없어졌다 — 손으로 적은 타입은 반드시 서버와 어긋나고, 어긋난 날 화면은 아무 말도 안
 * 하고 undefined 를 그린다. 그래서 전부 생성물(`schema.d.ts`)의 별칭으로 바꿨다:
 *
 *     cd backend  ; python scripts/export_openapi.py
 *     cd frontend ; npm run api:types
 *
 * 이름은 화면이 쓰던 그대로 둔다 — 가져다 쓰는 쪽을 한 줄도 안 바꾸고 정본만 갈아탄다.
 */

import type { components } from '@/shared/api/schema'

type Schemas = components['schemas']

export type WorkspaceMembership = Schemas['WorkspaceMembershipOut']
export type CurrentUser = Schemas['UserOut']
export type LoginResponse = Schemas['LoginResponse']
export type Workspace = Schemas['WorkspaceOut']
export type WorkspaceOption = Schemas['WorkspaceOption']
export type WorkspaceReference = Schemas['WorkspaceReferenceOut']
export type Member = Schemas['MemberOut']
export type Account = Schemas['AccountOut']
export type AccountSummary = Schemas['AccountSummaryOut']
export type TemporaryPassword = Schemas['TemporaryPasswordResponse']
export type Notice = Schemas['NoticeOut']
export type Notification = Schemas['NotificationOut']
export type AuditEntry = Schemas['AuditEntryOut']
export type AccessLog = Schemas['AccessLogOut']
export type Pat = Schemas['PatOut']
export type MaintenanceItem = Schemas['MaintenanceItemOut']
export type ServerStatus = Schemas['ServerStatusOut']
