CompCore 의 환산 코드로 만든 물성 값 — 손으로 짓지 않았다.

만든 법 (2026-09-28, CompCore `bcb34fa`):

    cd ~/projects/CompCore/backend
    .venv/bin/python -c "
    import json, sys; sys.path.insert(0, '.')
    from app.core import conditions
    payload = …                      # 등록 재료: DOE 픽스처의 materials[0].payload
                                     # 문헌 물성: MatNexus 의 values[] 모양
    keys = {'탄성계수': 'mechanical.youngs_modulus'}
    print(json.dumps(conditions.converted_material(payload, '<계>', keys)))"

무엇이 다른가

  등록재료-mm_n_tonne.json   MatNexus 등록 재료 · mm · N · t 계 (MPa · tonne/mm3)
  등록재료-si.json           같은 재료 · SI 계 (Pa · kg/m3)
  등록재료-열쇠없음.json     물성 사전을 못 가져온 경우 — 열쇠가 안 붙고
                             `missing_structural` 이 실린다. **받는 쪽은 실패해야 한다**
  문헌물성-mm_n_tonne.json   문헌 카탈로그 (payload 의 `values[]` 모양) — 밀도 · 푸아송비가
                             목록에서 끌어올려져 등록 재료와 **같은 모양**이 된다 · 등급(tier)

옛 모양(2026-09-24 폴더)은 `tests/fixtures/doe/재료훑기-7c1d3a44` 안에 그대로 있다 —
평평한 `youngs_modulus` 칸이다. 그 경로도 함께 지킨다.
