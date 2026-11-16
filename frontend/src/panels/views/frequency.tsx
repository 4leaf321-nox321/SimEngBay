/**
 * 「주파수 요구 판정」 화면 — `study_frequency` 의 결과 아래에 뜬다. 웹의 「주파수 요구」 탭과 같은
 * 부품이다. 요구를 고쳐 미리 볼 수 있지만 저장하지 않는다(패널은 읽기만 한다).
 */

import { StudyFrequency } from '@/modules/simulations/StudyFrequency'
import { field, mountPanel, text } from '@/panels/mount'

mountPanel({
  tool: 'study_frequency',
  title: '주파수 요구 판정',
  pick: ({ args, result }) => text(args.study_id) ?? text(field(result, 'study_id')),
  render: (studyId) => <StudyFrequency studyId={studyId} readOnly={false} previewOnly />,
})
