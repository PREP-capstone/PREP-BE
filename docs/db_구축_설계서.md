# 룰베이스 DB 구축 설계서

> 버전: V4.5 | 2026-08-15
> V4.5 변경: **원문 재대조(2026-08-14) + 운영 DB 백필 반영, 문서 드리프트 2건 정정.** ① §8.2 침습 하드체크 키워드 목록을 **12개 → 13개**로 갱신 — 웰니스판단기준 0091-03 고위해도 예시 원문("피부를 침투하여 혈액을 채취하는 제품")에 있는 "채취"가 누락돼 있던 것을 발견해 추가. 같은 대조 과정에서 부정표현 제거 정규식이 "비침습/무침습"만 걸러내 "비이식형"·"비삽입형"(원문에 실제 등장)을 걸러내지 못하는 버그도 발견해 침습·이식·삽입 공통으로 확장 ② §8.2의 "correction_rules 두 생성 경로 간 동사 목록 불일치"(V4.4에서 신규 미결정 항목으로 등재) 항목을 **해소 처리** — `extract_c.py` 프롬프트에서 예방·보정을 위험 동사 힌트에서 제거해 경로①(verb_substitution)과 동기화 완료 ③ §8.2에 **D-12 후속 발견 기록 추가** — D-12 재연결 로직은 그 이후에 발생하는 Stage A 재발행부터만 적용되므로, 로직 도입 이전에 쌓인 이력 데이터(active correction_rules 104건 중 70건이 이미 deprecated된 gate_keywords 행을 참조 중이었음)는 소급 반영되지 않았음을 배포용 데이터 추출 중 발견. keyword 텍스트 기준 1:1 매칭으로 운영 DB에서 현재 active 키워드에 재연결하는 일회성 백필을 실행해 해소.
> V4.4 변경: **실제 구현(담당 E, 2026-08-13~14 실전 문서 투입) 대조 후 문서-코드 불일치 8건 정정.** ① §3.3에 **§3.3.3 verb_substitution 신설** — correction_rules 동사 사전 테이블, 원 계획("gate_keywords PROHIBITED_ACTION 재사용")이 실제 데이터 품질 문제로 폐기되고 별도 확정 목록(12행)으로 교체됨 ② §3.3에 **명사 재분류 규칙 추가** — gate_matrix.data_type(2종 enum)은 명사 원천이 될 수 없어, gate_keywords DISEASE 14건을 질병명/생체지표로 수기 재분류하는 방식으로 대체 ③ §1.2·§2.2·§4.1·§4.2 Stage C 서술을 **"LLM 추출" 단일 경로 → 코드 조합 생성/LLM 추출 두 경로 병행**으로 정정 — extract_c.py가 여전히 그래프에 연결돼 있어 기존 경로가 폐기된 게 아니라 신규 경로가 추가된 것임을 명확히 함. 두 경로 간 미해결 불일치(LLM 프롬프트가 "예방"·"보정"을 여전히 위험 동사로 나열)를 §8.2에 신규 미결정 항목으로 등재 ④ §3.4 서두 "본 두 테이블" → "본 세 테이블"(verb_substitution 포함) ⑤ §1.5.1에 **장(章) 접두어 제거 규칙 + 부칙 예외** 추가 — 청킹 내부 계층("제1장.제2조")을 LLM이 그대로 인용해 RAG join이 깨지는 사례 발견(약사법, 2026-08-14) ⑥ §1.5 문서 표에서 별표7(MFDS-R-2026-02) 행을 시행규칙 본문과 분리, **활용 Stage를 "RAG 전용"으로 정정**(2026-08-13 룰추출 대상에서 제외 — 별표7 항목 서술이 Stage C의 risky_text 패턴에 맞지 않아 3청크 시범 추출 0건) ⑦ §3.1·§4.5·§4.6의 "기존 버전은 deprecated" 서술을 **누적 발행(B안)** 방식으로 정정 — 실제로는 해당 Stage의 기존 active를 승계한 뒤 그 승계 대상만 deprecated 처리하며, 이 차이가 실제로 "문서 1건 투입마다 다른 Stage 룰까지 통째로 비활성화되는 버그"의 원인이었음 ⑧ §3.2에 gate_keywords **type 분류 판별 기준** 표 추가, §4.4에 **검증 완화 규칙 2건**(advertising_score=0 시 인용 면제, 공백 정규화 비교) 추가, §8.2 침습 하드체크 항목에 **키워드 12개 목록·CONDITIONAL 안전장치·부정표현 처리** 상세 추가. 이번 정정은 별도 세션(재확인 에이전트)의 코드-문서 대조 보고를 이 세션이 코드로 재검증한 뒤 반영함 — 재검증 과정에서 위 ③의 두 경로 병행 사실이 추가로 드러남(원 보고는 "LLM 추출이 코드 생성으로 완전히 대체됐다"고 서술했으나 부정확했음).
> V4.3 변경: MFDS-G-2026-05 **국가법령정보센터 조문본(34쪽, 고시 제2026-6호) 확보 및 처리 방침 확정** — ① **LLM 파이프라인 미투입** 유지(39개 조문 중 GATE 판정에 쓸 조항이 제8조 하나뿐이고, 나머지는 의료기기 판정 **이후**의 허가 절차) ② **RAG에는 적재**(`usage_scope=RAG`) — `avoidance_certification` 문구가 제8조를 인용하므로 조문 원문 표시에 필요 ③ 사용 파일을 **국가법령정보센터본으로 확정**, 기존 행정예고본(91쪽) 폐기 — 조문 단위 청킹이 가능하고 `section_id`가 §1.5.1 규칙에 바로 부합 ④ **제33조(정보제공의 범위)** 신규 확인 — AI 적용 디지털의료기기SW의 정보제공 의무 4항목, §1.5.2에 기록 ⑤ §8.2에 RAG 적재 요청 항목 추가.
> V4.2 변경: **MFDS-G-2026-05 원문 확인 후 기재 정정** — §1.5 표의 "제8조 = 임상·진료×비교추이분석 CONDITIONAL 4대 요건"이라는 설명이 **원문과 불일치함을 확인**. 제8조는 「허가 등의 제외대상 범위」로, 의료인 지원 도구가 허가 제외대상이 되기 위한 4대 요건을 정의하며 data_type(임상·진료)과 직접 관계가 없다. §1.5.2를 신설해 4대 요건 원문 요약·1차 구축 미투입 사유·action_templates 활용 방향을 기록. 아울러 §8.2의 침습적 하드체크 대상 목록을 **"각질층 관통 여부" 기준으로 확정**(CGM·채혈형=침습 / 패치는 관통 여부로 분기).
> V4.1 변경: Stage B/C 구현 완료 보고 반영 — ① **§3.2 acquire_method 설명 오류 정정**: 하드 오버라이드 결과를 `FAIL_CONFIRMED`로 적었으나 이는 `gate_keywords.verdict` 값이며 `gate_matrix.verdict`는 PASS/CONDITIONAL/FAIL 3종 닫힌 enum이므로 **`FAIL`로 정정**(구현은 정상적으로 FAIL로 되어 있음) ② §3.2에 `legal_basis_doc`/`legal_basis_article` 컬럼 본문 반영(그동안 §8.2·§16에만 "추가 필요"로 기재돼 있었음) ③ §1.5에 **document_id 이중 체계 경고 및 매핑표 추가** — 본 문서 내부 코드(MFDS-G-2020-01)와 RAG stable string ID(kr-mfds-wellness-...)가 다르며 `legal_basis_doc`은 후자를 참조 ④ §1.5 약사법 시행일 확보(2026.6.21.).
> V4.0 변경: **3축 점수의 계산 위치 분리 확정** — 원칙: *표현에서 결정되는 값은 룰에 저장하고, 사용자 입력에서 결정되는 값은 런타임에 계산한다.* ① `correction_rules.privacy_score` **컬럼 삭제** — 개인정보민감도는 risky_text가 아니라 사용자가 선택한 수집 항목에서 결정되므로 룰에 저장 불가(같은 위험표현이라도 수집 데이터에 따라 달라져야 함). §3.3.2를 런타임 계산 규칙으로 재작성 ② regulatory_score·advertising_score는 표현 자체의 속성이므로 오프라인 산출·저장 유지 ③ **최종 위험등급 산출(3축 최고값)도 런타임으로 이관** — 3축을 모아야 계산 가능하므로 ④ §3.3.1 signal_config·§3.9 data_sensitivity를 런타임 소비 대상으로 표시, `item_label`이 Step2 UI 문자열과 글자 단위로 일치해야 한다는 제약 명시 ⑤ §4.2 Stage C 파생 계산 스키마에서 privacy_score 제외.
> V3.9 변경: **RAG 담당과 조문 표기 규칙 합의 완료** — §1.5.1 신설: 룰베이스 `legal_basis_article`과 RAG `evidence_chunks.section_id`가 사용할 **공통 표기 규칙** 명문화. 원문 목차 표기를 기본으로 하되 정규화 규칙(로마숫자 ASCII 통일 `Ⅲ`→`III` / 마침표 구분자 / 공백 제거 / `별표7.제8호` 형식) 적용. 원문 표기는 `section_title`에 보존. **별표7은 항목 번호 단위(제1호~제18호) chunk 분할**로 합의. §8.2의 관련 미결정 4건(별표7 확보·제24조·section_id 규칙·chunk 분할) 상태 갱신.
> V3.8 변경: RAG 담당 「RAG DB 데이터 수집 최종 보고서」 회신 반영 — ① §1.5에 **보건복지부 비의료 건강관리 서비스 가이드라인(MOHW-G-2026-01)** 추가(웰니스·의료 경계 판단의 핵심 근거인데 그동안 참조 목록에서 누락), LAW-MED-01에 **의료법 제27조(무면허 의료행위)** 활용 근거 추가 ② §8.2에 RAG 연계 미결정 4건 추가 — 🔴 별표7 본문·의료기기법 제24조 미확보(선결 과제), evidence_* 스키마 확장 반영 대기, section_id 정규화 규칙 합의, 별표7 chunk 분할 단위.
> V3.7 변경: **의료기기 판단 가이드를 RAG에도 적재하도록 §1.4 매핑 변경(안 B 채택)** — 기존 "룰베이스 전용" → "룰베이스 + RAG, `usage_scope=BOTH`". 리포트 SECTION 1·부록의 GATE 판정 근거 원문 표시를 위해 필요. 함께 §1.4 표의 미정 항목들을 판정엔진_개발설계서 §15의 신규 테이블(public_data_catalog / api_catalog / standard_scales / mvp_strategy_templates / app_store_ranking)로 확정 연결. evidence_documents/chunks 스키마 확장 자체는 RAG 담당 보고서 기준 팀 합의 후 §3.7에 반영 예정.
> 📎 **연계 문서 신설 (2026-07-26)**: 판정 엔진 실행 흐름·리포트 조립 규칙은 `판정엔진_개발설계서.md` V1.0이 소유한다. 본 문서 §6.5~6.8(모듈 실행 순서·종합 신호등·LLM 호출 구조·트렌드 임계값)은 성격상 판정엔진 영역이나, 참조 편의를 위해 양쪽에 동일 내용을 둔다. **값 변경 시 본 문서를 먼저 수정하고 판정엔진 설계서를 동기화**한다.
> V3.6 추가 변경 (2차): privacy_score에서 **동의 언급 여부 축을 제거**하고 `sensitivity_level` 단일 축으로 확정(6행 → 4행). 아이디어 입력 폼에 동의 항목이 없어 자유 텍스트 추출에 의존해야 하고, 선언만으로 점수가 낮아져 변별력이 없으며, 동의 취득이 실제 규제 부담을 줄이지도 않기 때문. 동의 요건은 `action_templates`의 `sensitivity_level=3` 트리거 액션으로 이관(§3.3.2, §3.9). Stage C `extract_c.py`의 `consent_mentioned` 추출도 제거 대상.
> V3.6 변경: **판정 기준값 B그룹 확정** — ① §3.3.2 신설: privacy_score 산출 입력을 `gate_matrix.data_type`(2종) → `data_sensitivity.sensitivity_level`(3단계)로 **전면 개정**. 구 규칙은 심박수와 복용약물이 동일하게 3점을 받아 변별력이 없었고, 최고값 방식과 결합해 대부분의 아이디어가 "높음"으로 수렴하는 문제가 있었음 ② §3.3.1 임계값 재조정: `0=낮음/1~2=중간/3=높음` → **`0~1=낮음/2=중간/3=높음`**. 개정된 privacy_score에서 라이프스타일도 최소 1점이라 기존 임계값으로는 종합 신호등 초록(§6.6)이 도달 불가능했음 ③ §3.9 신설: 신규 테이블 등급 기준 일괄 확정(sensitivity_level 1~3, public_data_catalog.difficulty 1~3, api_catalog.integration_difficulty 1~3, action_templates.priority 100단위 5대역, 앱스토어 순위→수요 등급) ④ §5 RAG 검색 결과 개수 확정(조문 전량 / 사례 top-3) ⑥ §6.4 경쟁 카드 LIMIT 3 명시 ⑦ §6.8 신설: 검색 트렌드 임계값 산출 방식(20개 업종 캘리브레이션 + 앵커 키워드·R²·계절성·저검색량 보완) ⑧ §8.2 갱신.
> V3.5 변경: **판정 로직 A그룹 9개 항목 확정** — ① D축 2종 확정에 따른 데이터확보 난이도 임계값 재조정(1~3/4~10/12~30, 최대 100→30) 및 D×S "곱" 명시(§3.4) ② 경쟁 포화도를 가중합 → **개수 기반**으로 환원, 시장현실성 신호등 매핑 추가, 유사도 가중치 폐기·tier_score 플래그화(§3.5) ③ 규제위험도 "합산 vs 최고값" 충돌을 **최고값 채택**으로 정리, signal_config 임계값 축별 0/1~2/3 확정(§3.3, §3.3.1) ④ 약사법(LAW-PHARM-01) 추가, 약무행위는 축 신설 없이 regulatory_score 흡수(§1.5) ⑤ §6.5 모듈 실행 순서 신설 — §01~04 **병렬** 확정, GATE FAIL 시에도 §01은 실행하는 분기 명시 ⑥ §6.6 종합 신호등 산출 신설(결정3, "수익 높음"→"BM추천 존재"로 대체) ⑦ §6.7 LLM 호출 구조 신설 — "3회 고정" 제약 폐기, 5개 호출 2단계(병렬3+순차2) ⑧ §6.4 완화 전략 채택 확정 및 포화도와 공유 ⑨ §8.2 해소 2건·신규 3건 갱신. (리포트 저장 정책은 추후 결정으로 보류)
> V3.4 변경: 옛 룰베이스 DB 구축방안(초기 초안) 대조 결과 누락돼있던 2개 필드를 gate_matrix(§3.2)에 복원 — ① acquire_method(획득방법: 수동입력/기기연동/OS연동, 침습적 하드체크 오버라이드 전용, 매트릭스 축 확장 아님) ② avoidance_redesign/avoidance_certification(회피 방향 2가지 안내, verdict=FAIL row 전용). §4.2 Stage B JSON 스키마 예시도 함께 갱신. 두 필드 모두 V2.7(2026-07-12, data_type 2분류 축소) 과정에서 스키마 정리 중 유실된 것으로 확인됨.
> V3.3 변경: category_1(질병축)에서 **유전자 삭제, 8종→7종**(수면/정신건강/운동/식단/만성질환/여성건강/미용) — 팀 확인 결과 실제 시장에 사례가 거의 없어 taxonomy에서 완전히 제외(2차 확장 시 재검토 가능성은 열어둠). §3.5, §3.6, §6.3 관련 문구 갱신. 경쟁사 수기 수집 역할분담(5인, 질병축별 담당, 총 90개 목표)도 이 7종 기준으로 확정.
> V3.2 변경: §6.4 신설 — BM 모듈이 bm_mapping VIEW를 조회하는 로직(기본 쿼리, 4단계 완화(fallback) 전략, Python 코드 예시)을 문서화. §1.1의 "DB 구축 범위" 원칙에 대한 명시적 예외로 표시. §8.2에 완화 전략 팀 확정 필요 항목 추가.
> V3.1 변경: competitors.category(5종, AI분류모델 기준 가정)를 팀 확정 마켓 분류 체계인 **category_1(질병축 8종: 수면/정신건강/운동/식단/만성질환/여성건강/유전자/미용) + category_2(기능축 4종: 정보제공/데이터기록관리/매칭연결/개입치료)** 2축으로 교체. data_type(라이프스타일/생체지표, GATE 연동)과 §3.5 유사도 공식은 영향 없이 그대로 유지 — category_1/2는 시장 분류 전용, data_type은 규제 분류 전용으로 역할 분리. bm_mapping VIEW(§3.6)의 GROUP BY 키를 category → category_1, category_2로 갱신. category_1에 "만성질환" 포함이 data_type 2분류(임상·진료 제외) 결정과 상충하지 않음을 명시(시장 카테고리 vs 규제 데이터유형은 별개 축).
> V3.0 변경: bm_mapping을 **저장 테이블에서 VIEW로 전환** — frequency_score/precedent_level/contributing_competitor_ids는 모두 competitors에서 실시간 계산 가능한 값이라 별도 저장·배치 재집계가 불필요하다는 판단에 따름. §6.4(자동 집계 파이프라인) 섹션 삭제, §3.6을 SQL VIEW 정의로 재작성하며 precedent_level의 "0건-수동판단" 케이스를 국내/해외 빈도 분리로 100% 자동화. evidence_id는 VIEW로 표현 불가능한 수동 큐레이션 정보라 MVP 범위에서 제외(추후 별도 소형 테이블로 확장 가능). §0/§1.2/§1.3/§1.4/§2.2/§6.1/§7/§8.1 관련 표·문구 갱신.
> V2.9 변경: §8.2의 "bm_mapping.bm_pattern 서브셋 확정" 항목에 대해 Business Model Navigator 공식 출처(businessmodelnavigator.com/explore, 원저: Gassmann·Frankenberger·Csik) 기준 웰니스향 12개 후보 서브셋을 초안으로 확정 — Freemium, Subscription, Add-on, Lock-in, Two-sided Market, Pay Per Use, Sensor As A Service, Leverage Customer Data, Digitization, Self-service, Performance-based Contracting, Razor And Blade (§3.5, §3.6). ⚠️ 팀 최종 승인 전까지는 초안 상태.
> V2.8 변경: §3.5 competitors에 data_type/target/service_type/bm_pattern/note/updated_at 컬럼 신설. §3.6 bm_mapping을 LLM 추출(Stage D) 대상에서 제외하고 competitors 집계 기반 자동 파생 테이블로 전면 재설계 — frequency_score/precedent_level 산출식과 contributing_competitor_ids 신설, evidence_id는 선택적 보강용으로 축소. §4.2 Stage D 항목 정리, §6.4 신설(bm_mapping 자동 집계 파이프라인), §0/§2.2/§7 표 갱신, §8.2에 tier_score·유사도가중치·BM Navigator 서브셋·경쟁사 갱신주기 담당자·data_type(진료·병력) 범위 재확인 항목 추가 (근거: 프랩_기획서.pdf §6.4·§12, 프랩_디자인_프로토타입.pdf Step2)
> V2.7 변경: Stage B data_type을 4분류(라이프스타일/생체지표/민감정보/임상·진료)→2분류(라이프스타일/생체지표)로 축소 확정(1차 구축 범위). 민감정보는 생체지표에 포함되는 개념으로 처리, 임상·진료는 2차 구축으로 이연. gate_matrix.data_type enum, 12칸→6칸 시드데이터(§3.2), privacy_score 파생규칙(§3.3), competitors 유사도 기준(§3.5, data_type 인접관계 미결정 항목 사실상 해소), §1.5 참조문서 설명, §4.2 JSON스키마, §8.2 미결정항목을 함께 갱신 (룰_추출_기준_최종확정본.md v1.1 반영)
> V2.6 변경: §4 LLM 추출 파이프라인의 구현 프레임워크로 LangGraph 채택 확정, 상세 설계는 별도 문서 langgraph_파이프라인_설계서.md로 분리
> V2.4 변경: §4.2 Stage A weight·FAIL_CONFIRMED·CONTEXT_CHECK 표의 조문 인용을 지침서-0091-02 → 0091-03 확정 조문(Ⅲ.2.가·나/Ⅳ.2.가/Ⅲ.2.다/Ⅲ.가+Ⅳ.1/Ⅲ.나+Ⅳ.2.나)으로 전면 재작성 (룰_추출_기준_현황_및_보완분석.md V1.5 반영)
> V2.5 변경: data_type_focus ↔ gate_matrix.data_type 이중체계 문제 해결 확정 — data_type_focus는 포맷 참고용 태그로만 사용, 위험도 판단은 gate_matrix.data_type 단일 기준으로 통일 (§3.2); risk_metadata 참조방식에서 data_type_focus 제거 (§3.2.1); competitors.core_tags 데이터유형을 gate_matrix.data_type 4종으로 통일, data_type 인접관계는 미확정 상태로 별도 등록 (§3.5, §8.2)
> 기반 문서: db_구축_계획서_V0.3.md, rulebase_db_구축안.md, 필요데이터소스 정리.md, 프랩_개발설계서.pdf
> 변경 사항: Stage A weight 척도·FAIL_CONFIRMED 기준 법적 근거 추가 (§4.2); 참조 규제문서 목록 신설 (§1.5)
> V2.2 변경: 참조 규제문서 목록 전면 갱신 — 지침서-0091-02→03 버전 반영, 신규 문서 9종 추가 (§1.5); gate_keywords.data_type_focus ↔ gate_matrix.data_type 이중체계 관계 명시 및 미결정 항목 등록 (§3.2, §8.2); correction_rules에 derived_from_keyword_id 추가 및 axis_score 산출방식 파생/독립추출로 분리 (§3.3, §4.2); function_type 닫힌 enum으로 확정 (§3.2); 자동검증 규칙 추가 (§4.4); evidence_documents.tag_advertising 설명 정정 (§3.7). 근거: 룰_추출_기준_현황_및_보완분석.md V1.4
> V2.3 변경: gate_matrix.verdict를 PASS/FAIL 2종 → **PASS/CONDITIONAL/FAIL 3종**으로 확장, "제외대상" 특수 케이스는 신규 `exemption_note` 필드로 분리 처리 (§3.2, §4.2); 우선순위 로직을 FAIL>CONDITIONAL>PASS 3단계로 갱신; data_type×function_type 12칸 확정 매핑을 시드데이터로 §3.2에 직접 삽입 (룰_추출_기준_현황_및_보완분석.md Stage B 확정본 그대로 반영)

---

## 0. Stage별 추출 스키마 요약 (한눈에 보기)

> 상세 정의는 §4.2 참조. 아래 표는 각 Stage가 어떤 테이블을 채우고 어떤 핵심 필드를 추출하는지 빠르게 확인하기 위한 요약이다.

| Stage | 대상 테이블 | 핵심 추출 필드 | 판단 기준 축 |
|---|---|---|---|
| **A** | gate_keywords | type, keyword, keyword_category, data_type_focus, verdict, weight | 사용목적(의료용/비의료용), 데이터 유형 |
| **B** | gate_matrix | data_type, function_type, verdict, risk_code, priority | 데이터 유형(What) × 기능 목적(Why) |
| **C** | correction_rules | risky_text, safe_text, regulatory_score, advertising_score | 규제 / 광고 2축 저장 (개인정보 축은 런타임 계산 — §3.3.2) |

> ~~Stage D~~ **(2026-07-20 제외)**: bm_mapping은 더 이상 어떤 Stage에도 속하지 않는다. competitors 기반 VIEW로 실시간 계산되며 별도 추출·적재 단계가 없다 (§3.6 참조).

**위해도 기준**: DB 컬럼 내 저장하지 않으며 `risk_metadata`(§3.2.1)로 분리 관리 → Gate Engine 판정 시 런타임 로드.

---

## 1. 개요

### 1.1 목적

PREP(웰니스 창업 진단 플랫폼) 개발설계서의 판정 엔진·DB 설계를 기준으로, **룰베이스 DB·RAG·사전구축 DB를 구축하는 자동화 파이프라인**을 설계한다. 본 문서는 개발설계서의 §8(판정 엔진), §9(RAG), §10(DB) 영역 중 "DB에 무엇을, 어떤 절차로 채워 넣는가"에 집중한다.

### 1.2 범위

| 구축 대상 | PREP 테이블 | 구축 방식 |
|---|---|---|
| GATE 1차 키워드 | gate_keywords | LLM 추출 (룰베이스) |
| GATE 2차 조합 | gate_matrix | LLM 추출 (룰베이스) |
| 위험표현·교정 | correction_rules | **코드 조합 생성 + LLM 추출 (병행, 2026-08-13~)** — 동사×명사 조합은 코드가 생성(§3.3.3, §4.2), 문서 청크 기반 추출은 `extract_c.py`가 계속 담당. advertising_score는 후자에서만 산출 |
| 데이터 난이도 가중치(D) | data_difficulty | 고정 기준표 직접 입력 |
| 수집방법 가중치(S) | collection_difficulty | 고정 기준표 직접 입력 |
| 경쟁사 DB | competitors | 사전구축 (수동조사+크롤링) |
| BM 매핑 | bm_mapping | VIEW (competitors 기반 실시간 계산, 저장 안 함) |
| 근거 문서/RAG | evidence_documents, evidence_chunks (+ChromaDB) | RAG 인덱싱 (항상호출, 근거전용) |
| 지원사업 | funding_programs | 사전구축 (API+수동) |
| 룰 버전 | rule_versions | 파이프라인 산출물 (버전관리) |

### 1.3 핵심 원칙 (PREP 설계 원칙 그대로 채택)

```
법령·가이드·자료 PDF → LLM 추출 파이프라인 → JSON 룰 초안 → 관리자 검수(ADMIN01) → DB 적재(rule_versions 발행)
```

- 최종 판정은 룰베이스(gate_keywords/gate_matrix/correction_rules/data_difficulty/collection_difficulty/competitors/bm_mapping(VIEW))가 담당
- RAG(evidence_documents/evidence_chunks)는 판정에 영향 없이 근거만 제공, **항상 호출**
- LLM은 분류 보조·설명문장·대체표현·제안서 초안 생성에만 사용
- 사용자 입력·분석결과는 본 DB에 저장하지 않음 (TTL 캐시, PREP §10.3 참조) → 본 설계서는 **기준 데이터(룰·근거) 구축만** 다룸

### 1.4 데이터 소스 ↔ 구축 위치 매핑

| 데이터 소스 | 활용 섹션 | 구축 방식 | 구축 위치 (PREP 테이블 기준) |
|---|---|---|---|
| 법령·규제 문서 | §01 규제 | 룰베이스 + RAG | gate_keywords (LLM 추출) + evidence_documents/evidence_chunks(+ChromaDB) |
| 의료기기 판단 가이드 | §01 규제(GATE) | **룰베이스 + RAG** (2026-07-26 변경) | gate_keywords, gate_matrix (LLM 추출) + evidence_documents/evidence_chunks(+ChromaDB), `usage_scope=BOTH` |
| 위험 표현 사전 | §01 규제 | 룰베이스 | correction_rules |
| 규제 위반 사례 | §01 규제 | RAG | evidence_documents/evidence_chunks(+ChromaDB) |
| 공개 통계 카탈로그 | §02 시장 + §03 데이터 | 사전구축 DB | ★ public_data_catalog (판정엔진_개발설계서 §15.4) |
| 앱 시장·검색 트렌드 | §02 시장 | 배치 수집 + 런타임 API | ★ app_store_ranking + 트렌드 계산 모듈(비저장, §6.8) |
| 경쟁 서비스 DB | §02 시장 | 사전구축 | competitors |
| 카테고리별 유료화 패턴 | §02 시장 + §04 수익 | VIEW (competitors 기반, 비저장) | bm_mapping |
| 공개 API 가능성 매핑 | §03 데이터 | 사전구축 | ★ api_catalog (판정엔진_개발설계서 §15.5) |
| 표준 척도 라이브러리 | §03 데이터 | 사전구축 | ★ standard_scales (판정엔진_개발설계서 §15.6) |
| 데이터 유형×난이도 룰 | §03 데이터 | 고정 기준표 | data_difficulty, collection_difficulty |
| MVP 전략 템플릿 | §03 데이터 | 전문가 수기 작성 + RAG 참고 | ★ mvp_strategy_templates (판정엔진_개발설계서 §15.7) |
| BM 사례·논문 RAG | §04 수익 | RAG | evidence_documents/evidence_chunks(+ChromaDB) |
| 국내외 경쟁 앱 가격정책 | §02 시장 + §04 수익 | 사전수집 | competitors / funding_programs |
| EAP·기업복지 시장정보 | §04 수익 | RAG | evidence_documents/evidence_chunks(+ChromaDB) |
| 스타트업 IR·인터뷰 | §02 + §04 | RAG | evidence_documents/evidence_chunks(+ChromaDB) |

> ✅ **결정 완료 (2026-07-26) — 의료기기 판단 가이드를 RAG에도 적재 (안 B 채택)**: 기존에는 판단가이드(지침서-0091-03, 모바일 의료용 앱 안전관리 지침, LLM 디지털의료기기 가이드라인)를 **룰베이스 추출 전용**으로 규정했으나, RAG에도 함께 적재하도록 변경한다. `usage_scope=BOTH`로 관리.
>
> **변경 사유**: 결과 리포트의 **SECTION 1「서비스 분류」의 "GATE 판정 결과 및 근거"**와 **부록「의료기기 판정 시」의 "의료기기 판정 근거 제공"**은 gate_matrix가 지정한 지침서 조문(예: `0091-03 Ⅳ.3`)의 **원문**을 표시해야 한다. 판단가이드가 evidence_chunks에 적재돼 있지 않으면 이 원문을 조회할 수 없어, "의료기기로 판정되었습니다"만 표시하고 판정 이유를 보여주지 못한다.
>
> **단점 대응**: "RAG 검색 결과에서 법령보다 가이드가 과도하게 노출될 수 있다"는 우려는 판정엔진 설계로 이미 완화된다 — ① 조문 근거는 **ID 기반 조회**라 룰이 지정한 chunk만 가져오므로 검색 경쟁이 없고, ② 유사 사례 벡터 검색은 **top-3**으로 제한된다 (§5, 판정엔진_개발설계서 §10).
>
> ⚠️ 이 결정에 따라 `evidence_documents`에 `usage_scope`(RAG / RULE_BASE / BOTH) 컬럼이 필요하다. 스키마 전체 확장안은 RAG 담당의 「RAG DB 데이터 수집 최종 보고서」기준으로 팀 합의 후 §3.7에 반영한다.

> 미정 항목 4종(공개 통계 카탈로그, 앱 시장·검색 트렌드, 공개 API 가능성 매핑, 표준 척도 라이브러리)은 §8.2 미결정 항목과 연계하여 별도 테이블 신설 여부를 결정 필요.

### 1.5 참조 규제 문서 (판단 기준 근거)

룰베이스 DB 추출 기준의 법적 근거가 되는 공식 문서 목록.

> ⚠️ **(2026-08-09) document_id 체계가 두 갈래다 — 매핑 필요**: 아래 표의 "문서 ID"(`MFDS-G-2020-01` 형식)는 **본 설계서 내부 참조용 코드**이고, RAG `evidence_documents.document_id`는 stable string ID(`kr-mfds-wellness-0091-03-20260212` 형식)를 사용한다. 룰 테이블의 `legal_basis_doc`은 **RAG 쪽 ID를 참조**해야 하므로, 아래 표에 RAG document_id 매핑 열을 추가할 것. (Stage B 시드 구현 시 RAG id로 채움)

| 본 문서 ID | RAG document_id (예시) |
|---|---|
| MFDS-G-2020-01 | `kr-mfds-wellness-0091-03-20260212` |
| LAW-PHARM-01 | `kr-pharmaceutical-affairs-act-20260621` |
| (나머지는 RAG 담당 확정 후 채울 것) | |

> ⚠️ **버전 갱신 (2026-07-05)**: MFDS-G-2020-01이 가리키던 「의료기기와 개인용 건강관리(웰니스) 제품 판단기준」은 지침서-0091-02(2020.11.27.)에서 **지침서-0091-03(2026.2.)으로 개정·대체됨**. document_id는 유지하되 `evidence_documents.version`을 "0091-03", `effective_date`를 "2026-02"로 갱신 (§4.6 법령 개정 대응 절차 그대로 적용).
>
> ⚠️ **미검증 항목**: MFDS-G-2025-02(안내서-1425-01, 2025.5.)는 이번 보완 작업에서 원문을 확보·대조하지 않음. 소프트웨어 안전성 등급 A/B/C, 사용목적 분류 A~H 근거가 아직 실물로 검증되지 않은 상태 — 원문 확보 후 재확인 필요.

| 문서 ID | 문서명 | 발행처/문서번호 | 발행일 | 활용 Stage | 주요 사용 기준 |
|---|---|---|---|---|---|
| MFDS-G-2020-01 | 의료기기와 개인용 건강관리(웰니스) 제품 판단기준 (공무원 지침서) | 식약처, 지침서-0091-03 | 2026.2. (구 0091-02, 2020.11.27.) | Stage A, B | 고위해도 5요소 → FAIL_CONFIRMED; weight 척도 1~5; data_type 경계(생체지표/라이프스타일); PASS/FAIL 매핑테이블 근거 |
| MFDS-G-2025-02 | 디지털의료기기소프트웨어 허가·심사 가이드라인 (민원인 안내서) | 식약처, 안내서-1425-01 | 2025.5. | Stage A, B | 소프트웨어 안전성 등급 A/B/C; 사용목적 분류 A~H (⚠️미검증) |
| MFDS-G-2026-03 | 모바일 의료용 앱 안전관리 지침 (민원인 안내서) | 식약처 의료기기안전국 | 2020.2.21. | Stage B | function_type 3분류(단순기록/비교·추이분석/수치예측·진단) 학술적 출처; data_type 경계 사례 |
| MFDS-G-2026-04 | 거대언어모델(LLM) 기반 디지털의료기기 허가·심사 가이드라인 (민원인 안내서) | 식약처, 안내서-1511-01 | 2026.6.30. | Stage B | data_type×function_type 매핑테이블 사례(라이프스타일 축 — 민감정보·임상·진료 관련 사례는 2차 구축 참고용으로 보류) |
| MOHW-G-2026-01 | 비의료 건강관리 서비스 가이드라인 | 보건복지부 | (확인 필요) | Stage A, B, C | **2026-07-26 추가** — 웰니스와 의료행위의 경계 판단, Before→After 표현 교정 근거. "치료"→"관리·개선" 등 허용 표현 범위의 직접 근거이나 그동안 참조 목록에서 누락돼 있었음. ⚠️ 원문·서지정보 미확보, RAG 수집 목록에도 없어 추가 수집 요청 완료 |
| LAW-PIPA-01 | 개인정보 보호법 | 법률 제20897호 | 2025.4.1. 일부개정(시행 2025.10.2.) | Stage B, C | 제23조(민감정보의 처리 제한) — 생체지표가 그 자체로 민감정보에 해당함을 뒷받침하는 근거, privacy_score 파생근거 (2026-07-12: 민감정보 별도 분류 제외 이후) |
| LAW-PIPA-02 | 개인정보 보호법 시행령 | 대통령령 제35343호 | 2025.2.25. 일부개정(시행 2025.3.13.) | Stage B, C | 제18조(민감정보의 범위) — "건강에 관한 정보"에 정신건강 포괄 (⚠️원문 미확보, 웹검색으로만 확인) |
| MFDS-R-2026-01 | 디지털의료제품법 시행규칙 | 총리령 제2088호 | 2026.1.24. 시행 | 2차 구축 참고용 | 제11조제6호 가·나·다목 — data_type(임상·진료) 제외대상 근거 (2026-07-12: 임상·진료 2차 구축 이연으로 1차 구축 미사용) |
| MFDS-G-2026-05 | 디지털의료제품 허가·인증·신고·심사 및 평가 등에 관한 규정 | 식약처고시 **제2026-6호** | **2026.1.25. 일부개정·시행** | **RAG 전용** (`usage_scope=RAG`) / action_templates 소재 | **제8조(허가 등의 제외대상 범위)** — 의료인 지원 도구가 허가 제외대상이 되기 위한 4대 요건. **제33조(정보제공의 범위)** — AI 적용 디지털의료기기SW의 정보제공 의무. 상세는 §1.5.2. **LLM 파이프라인 투입 안 함** |
| LAW-MDA-01 | 의료기기법 | 법률 제21263호 | 2026.7.1. 시행 | Stage A, C | 제2조(정의) — 의료기기 4목적; 제24조(기재 및 광고의 금지) — advertising_score 주 근거 |
| MFDS-R-2026-02 | 의료기기법 시행규칙 (본문) | 총리령 제2127호 | 2026.7.1. 시행 | Stage C | 제45조(의료기기광고의 범위 등) — advertising_score 산출의 법적 근거. RAG 문서 `kr-medical-device-act-rule-20260701` |
| MFDS-R-2026-02-별표7 | 의료기기법 시행규칙 별표7 | 총리령 제2127호 | 2026.7.1. 시행 | **RAG 전용** (`usage_scope=RAG`, 2026-08-13 정정) | 별표7(금지되는 광고의 범위, 18개 항목) — advertising_score 0~3 척도의 **근거 조문**이지만, 척도 자체는 이미 `extract_c.py` 프롬프트에 하드코딩돼 있다. Stage C 룰추출(risky_text 생성) 대상에서는 **제외** — 별표7 각 항목은 "이런 광고는 금지"라는 유형 서술이라 correction_rules가 찾는 risky_text(동사×명사 결합) 패턴에 맞지 않아 3청크 시범 추출 시 0건이었다. 항목 원문 표시는 RAG evidence_chunks 조회로 처리(§1.5.1 항목 단위 chunk 분할). RAG 문서 `kr-medical-device-act-rule-annex7-20260701` |
| LAW-MED-01 | 의료법 | 법률 제21524호 | 2026.4.7. | Stage A, C | 제27조(무면허 의료행위 금지) — "진단·치료" 표현의 regulatory_score 근거(2026-07-26 추가); 제56·57조(의료광고 금지·심의) — advertising_score 보조근거(의료기관·의료인 직접 광고 시 한정) |
| LAW-PHARM-01 | 약사법 | **법률 제21109호** (2026-08-14 확보·확인) | **2026.6.21. 시행** | Stage A, C | 무면허 약무행위(처방·조제·복약지도) 근거 — 2026-07-26 추가, 2026-08-14 파일 확보(발췌본, 제2·23·24·44조만 포함— 전문 아님). 약무행위를 correction_rules의 4번째 축으로 신설하지 않고 `regulatory_score`에 흡수하기로 확정했으므로(§3.3), gate_keywords에 약무 키워드를 `type=PROHIBITED_ACTION`으로 시딩해 자동 반영한다. 제23조=조제, 제24조④=복약지도, 제44조=투약(판매·수여 포섭, 잠정 — "투약"은 법률 용어가 아니라 원문에 문언 자체가 없음, 전문 확보 시 재확인 필요) |

**핵심 조항 요약**

| 기준 항목 | 출처 문서 | 조항 위치 | 내용 요약 |
|---|---|---|---|
| 고위해도 5가지 판단요소 | MFDS-G-2020-01(0091-03) | Ⅲ.2.가·나 (구 §II.2.다.2)) | ①생체적합성 문제 ②침습적 ③오작동 시 상해·질병 발생 ④위급상황 탐지 ⑤기기 기능·특성 통제·변경 → 해당 시 의료기기 |
| 의료기기 정의 4가지 목적 | LAW-MDA-01 제2조제1항 | 본문 | 질병 진단·치료·경감·처치·예방 / 상해·장애 보정 / 구조·기능 검사·대체·변형 / 임신 조절 |
| 만성질환 자가관리 예외 | MFDS-G-2020-01(0091-03) | Ⅳ.2.나 + Ⅲ.나(의사결정흐름도) (구 §II.1.나.2)) | 치료법·피드백 제공 없이 생활습관 유도만 하는 경우 웰니스로 허용 → CONTEXT_CHECK 전환 근거 |
| 소프트웨어 안전성 등급 | MFDS-G-2025-02 | §3 안전성 등급 분류 | A=피해없음 / B=경상 가능 / C=심각한 부상·사망 가능 → weight 5/3/1 매핑 참고 (⚠️미검증) |
| 주된 사용목적 분류 | MFDS-G-2025-02 | §2 사용목적 분류표 | 검사(A)·진단(B)·치료(C) → keyword_category=DIAGNOSIS/TREATMENT 근거; 정보제공·관리(F) → 웰니스 가능성 높음 (⚠️미검증) |
| data_type 2분류 정의·경계 (1차 구축) | MFDS-G-2026-03, MFDS-G-2020-01(0091-03) | 모바일앱지침 Ⅲ.2~3, 0091-03 Ⅳ.1~3 | 라이프스타일/생체지표 각각의 정의·경계 (§3.2 참조). 민감정보는 생체지표에 포함, 임상·진료는 2차 구축 이연(2026-07-12) |
| function_type 3분류 근거 | MFDS-G-2026-03 | Ⅲ.2(의료기기 해당 5유형)/Ⅲ.3(비해당 6유형) | 단순기록/비교·추이분석/수치예측·진단 — 닫힌 3분류 확정 |
| data_type×function_type 매핑 | MFDS-G-2020-01(0091-03), MFDS-G-2026-04 | 각 문서 해당 조항 | 6개 조합 PASS/FAIL/CONDITIONAL 전부 확정 (§3.2 gate_matrix 참조). MFDS-R-2026-01/MFDS-G-2026-05는 임상·진료 2차 구축 시 재사용 예정 |
| 민감정보=생체지표 근거 | LAW-PIPA-01, LAW-PIPA-02 | 제23조, 시행령 제18조 | 생체지표(건강에 관한 정보)는 제23조 본문상 민감정보에 해당 — 별도 data_type 없이 생체지표 판정에 흡수(2026-07-12) |
| 3축(regulatory/privacy/advertising) 분리 근거 | LAW-MDA-01, LAW-PIPA-01 | 제2조·제24조, 제23조 | regulatory·privacy는 Stage A/B 파생, advertising만 독립 근거 (§3.3 참조) |
| advertising_score 척도 | MFDS-R-2026-02-별표7 (RAG 전용, 룰추출 미대상) | 제45조제1항 관련 | 18개 금지유형 → 0~3점 매핑, `extract_c.py` 프롬프트에 하드코딩 (§3.3 참조) |

#### 1.5.1 조문 표기 규칙 (2026-07-28 확정) — 룰베이스 ↔ RAG 공통

룰 테이블의 `legal_basis_article`과 RAG `evidence_chunks.section_id`는 **동일한 표기 규칙**을 사용한다. 두 값이 join 키로 쓰이므로 표기가 어긋나면 조회가 조용히 실패한다.

**기본 원칙**: 각 문서의 **원문 목차 표기를 그대로** 사용하되, 아래 정규화 규칙을 적용한다.

| 문서 | 표기 예시 |
|---|---|
| 웰니스판단기준 0091-03 | `III.2.가`, `III.나`, `IV.1.가`, `IV.2.나`, `IV.3` |
| 모바일 의료용 앱 안전관리 지침 | `III.2.2`, `III.2.5`, `III.3.3`, `III.3.5`, `부록2.Q1`, `부록2.Q11` |
| 의료기기법 | `제2조`, `제24조` |
| 개인정보보호법 / 시행령 | `제23조` / `제18조` |
| 의료기기법 시행규칙 | `제45조`, `별표7.제1호` ~ `별표7.제18호` |

**정규화 규칙**

| 항목 | 규칙 | 이유 |
|---|---|---|
| 로마숫자 | **ASCII 대문자로 통일** (`Ⅲ` → `III`) | `Ⅲ`(U+2162)과 `III`(영문 I 3개)는 서로 다른 문자열이라 그대로 두면 join 실패. PDF 추출 결과가 문서마다 갈릴 수 있음 |
| 구분자 | 마침표 `.` 통일, 끝에 마침표 없음 | |
| 공백 | 제거 (`부록2 Q11` → `부록2.Q11`) | |
| 조문 | `제23조` 형태 유지 | |
| 별표 | `별표7.제8호` 형태 | 항목 번호 단위 chunk와 1:1 대응 |
| 장(章) 접두어 | 법령(statute) 조문에서 **제거** (`제1장.제2조` → `제2조`) (2026-08-14 추가) | 청킹이 조문 위치 추적용으로 만드는 내부 계층 라벨("제1장.제2조")을 LLM이 그대로 인용해 그 형태로 발행되는 사례 발생(약사법 Stage C 실전 추출, 2026-08-14). §1.5 표기 예시(`의료기기법 \| 제2조, 제24조`)가 이미 장 없는 형태이므로 이 규칙은 원래도 암묵적으로 전제돼 있었으나 명문화가 안 돼 있었다 |
| 부칙 | 장이 아니므로 위 제거 대상 **아님** — `부칙.제1조` 형태 유지 | 부칙은 본문과 조문 번호가 겹치는 별도 인용 체계라 접두어를 지우면 어느 조문인지 구분이 안 된다 |

> **2단 정규화 구조**: 청킹 단계(내부용, 장 정보 보존)와 최종 인용값(장 제거) 정규화 규칙이
> 다르다. 코드 구현은 `_normalize_symbols()`(로마숫자·구분자만, 장 보존 — 청킹이 내부 계층
> 라벨을 만들 때 사용)와 `normalize_article()`(장 접두어까지 제거 — LLM 출력을 최종
> `legal_basis_article`로 정리할 때 사용) 2단으로 분리돼 있다.

> **원문 표기 보존**: 정규화 전 원본 표기(`Ⅲ. 2. 가.`)는 `evidence_chunks.section_title`에 보존한다. `section_id`는 기계용 키, `section_title`은 사람용 라벨로 역할을 나눈다.

#### 1.5.2 MFDS-G-2026-05 제8조 — 허가 제외대상 4대 요건 (2026-08-09 원문 확인)

> ⚠️ **기존 기재 정정**: §1.5 표에 "임상·진료×비교추이분석 CONDITIONAL 4대 요건"으로 적혀 있었으나, 원문 확인 결과 **해당 표현은 존재하지 않는다.** 제8조는 「허가 등의 제외대상 범위」이며 시행규칙 제11조제6호다목의 *"임상적·학술적으로 검증된 보건의료정보를 수집, 처리 및 분석하는 방법"*이 무엇인지를 정의하는 조항이다. data_type(임상·진료)과는 직접 관계가 없다.

**4대 요건 (모두 만족해야 제외대상)**

| # | 요건 |
|---|---|
| 1 | 의료영상·생체신호·체외진단검사 결과 등 **의료인의 판단이 필요한 정보를 분석하지 않을 것** |
| 2 | 이미 확정되었거나 잘 알려진 보건의료정보(동료검토 완료 임상자료, 임상진료지침, 교과서, EMR 기록 등)를 수집·처리·분석할 것 |
| 3 | 의료인을 **지원하거나 권장사항을 제공할 목적**일 것 — 단 ①구체적 진단·치료 결과를 제공하지 않고 ②의료인의 판단을 대체하지 않으며 ③질병·상태의 치료계획이나 위험확률을 제공하지 않을 것 |
| 4 | 의료인이 결과를 **독립적으로 검토**할 수 있도록 사용목적·대상환자·입출력 정보·작용원리·성능·한계점 등을 제공하고, 임상적 판단을 보장하지 않을 것 |

**제33조(정보제공의 범위) — AI 적용 SW의 정보제공 의무** (2026-08-09 추가 확인)

시행규칙 제33조제2항제5호에 따라 **인공지능 기술이 적용된 디지털의료기기소프트웨어**가 제공해야 하는 정보.

| # | 항목 |
|---|---|
| 1 | 인공지능 모델의 훈련방법 및 학습데이터 정보 |
| 2 | 예측되는 성능의 범위 및 한계 |
| 3 | 제3자 클라우드 서비스로 개발·구현된 경우 그 종류 및 구성 형태 |
| 4 | 변경관리 계획 범위 내 변경 시 변경내용 및 결과 |

> GATE 판정에는 쓰이지 않으나, PREP 사용자 중 AI 기능을 넣는 경우가 많으므로 **"정식 인증 트랙을 택하면 이런 의무가 따라붙는다"**는 안내 재료로 유용하다.

**LLM 파이프라인에 투입하지 않는 이유**

- 전체 39개 조문 중 GATE 판정에 쓸 수 있는 것은 **제8조 하나뿐**이다. 나머지는 명칭·제품코드·모양 및 구조·제조공정·시험규격·첨부서류·심사절차 등 **이미 의료기기로 판정된 뒤의 허가 절차**를 다룬다. GATE는 그 앞단(의료기기 해당 여부)을 판정하므로 축이 다르다.
- 제8조 자체가 **B2B(의료인 대상) 임상의사결정지원 도구**를 전제한다. PREP 사용자는 B2C 웰니스 창업자라 적용 상황이 드물다.

**RAG에는 적재한다** (`usage_scope=RAG`, 2026-08-09 결정)

`avoidance_certification` 문구가 제8조를 인용하므로, 리포트에 **조문 원문을 표시하려면 `evidence_chunks`에 적재돼 있어야 한다.** 없으면 조문 번호만 적고 내용은 못 띄운다.

**⚠️ 사용할 파일 버전**

동일 문서의 두 가지 파일이 존재한다. **국가법령정보센터 조문본을 사용할 것.**

| | 행정예고본 (폐기) | **국가법령정보센터본 (채택)** |
|---|---|---|
| 쪽수 | 91쪽 | **34쪽** |
| 구성 | 제정이유·주요내용 + 전문 | 제1~39조 조문만 |
| 청킹 | 조문이 페이지에 흩어져 분할 어려움 | **조문 단위로 깔끔히 분할**, `section_id`가 `제8조` 형태로 §1.5.1 규칙에 바로 부합 |

**활용 방향 — `action_templates` 소재**

GATE FAIL 시 회피 경로 안내(`avoidance_certification`)의 재료로 활용한다. "의료인 지원 도구로 포지셔닝을 전환하면 제외대상이 될 수 있다"는 경로를 제시할 수 있다. 상세 문구는 담당 A와 협의(§8.2 D-2).

---

> **별표7은 항목 번호 단위(제1호~제18호)로 chunk를 분할한다** — `advertising_score` 척도가 18개 항목 번호에 매여 있고(3점: 1·2·4·8·9·15·17·18호 / 2점: 3·5·6·7·10·11·14호 / 1점: 12·13·16호) 점수별로 항목이 흩어져 있어, 항목 하나하나가 독립적인 판정 단위다. 통짜 chunk면 판정 근거를 항목 단위로 인용할 수 없어 리포트 SECTION 2-1의 "참고 법령 inline 표시"를 충족하지 못한다. 부가 이득으로 벡터 검색 품질 향상(항목별 의미가 살아있는 임베딩)과 척도 조정 용이성(chunk 유지, 매핑만 수정)이 있다.

---

## 2. 전체 아키텍처

### 2.1 데이터 흐름 (PREP §9.2 RAG 파이프라인 기준 통합)

```
┌───────────────────────────────────────────────────────────┐
│              원천 자료: 법령/가이드 PDF, 사전조사자료, 경쟁사정보 │
└───────────────────────────────────────────────────────────┘
     │                    │                       │
     ▼                    ▼                       ▼
[A] LLM 추출 파이프라인   [B] 사전구축 DB 수집     [C] RAG 인덱싱
  (룰베이스 5종)           (competitors,           법령/가이드 PDF
     │                     funding_programs)        → 텍스트추출
     ▼                    │                       → 조문/제목/기준 정리
관리자 검수(ADMIN01)        │                       → 메타데이터 부여
     │                    │                       → Embedding(OpenAI)
     ▼                    ▼                       ▼
┌───────────────────────────────────────────────────────────┐
│  rule_versions (버전관리) + PostgreSQL 룰 테이블군            │
│  evidence_documents/evidence_chunks (메타) + ChromaDB(벡터)   │
└───────────────────────────────────────────────────────────┘
     │
     ▼
┌───────────────────────────────────────────────────────────┐
│  판정 엔진 (Domain 계층)                                       │
│  GATE(게이트) → [Regulatory ∥ Data Feasibility ∥ Market ∥ BM] │
│  ※ 위 나열은 논리 순서이며 §01~04는 병렬 실행 (§6.5 참조)      │
│  각 모듈: PostgreSQL 룰 조회(판정) + RAG 하이브리드검색(근거)    │
└───────────────────────────────────────────────────────────┘
```

### 2.2 구축 방식별 분류 (PREP 모듈 매핑)

| 구축 방식 | 대상 테이블 | PREP 모듈 | 파이프라인 |
|---|---|---|---|
| LLM 추출 (룰베이스) | gate_keywords, gate_matrix | Gate Engine, Regulatory | §4 LLM 추출 파이프라인 |
| 코드 조합 생성 + LLM 추출 (병행) | correction_rules | Regulatory | §3.3.3(동사 사전) + §4 LLM 추출 파이프라인 |
| 고정 기준표 입력 | data_difficulty, collection_difficulty, **verb_substitution** | Data Feasibility, Regulatory | 직접 입력 (결정5 D×S표, §3.3.3) |
| 사전구축 DB | competitors, funding_programs | Market, Funding | §6.3 수집 파이프라인 |
| VIEW (파생, 비저장) | bm_mapping | BM | §3.6 참조 (competitors 기반 실시간 계산, 별도 파이프라인 없음) |
| RAG | evidence_documents, evidence_chunks (+Chroma) | AI·RAG 계층 | §5 RAG 파이프라인 |

---

## 3. DB 스키마 설계 (PREP §10.2 ERD 기준)

> 아래 스키마는 PREP 개발설계서 §10.1 ERD·§10.2 주요 테이블의 필드를 기준으로 하며, 본 설계서에서는 **각 테이블을 채우는 룰의 추출 스키마**를 추가로 정의한다.

### 3.1 rule_versions — 룰 버전 관리 (공통)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| rule_version_id | UUID, PK | |
| version | VARCHAR | 예: v0.3, v0.4 |
| status | VARCHAR | draft / active / deprecated |
| created_by | UUID | 관리자(admin) ID |
| activated_at | TIMESTAMP | |
| created_at | TIMESTAMP | |

→ gate_keywords, gate_matrix, correction_rules 등 모든 룰 테이블은 `rule_version_id`를 FK로 가짐. §4.6 법령 개정 대응 시 신규 rule_version 발행.

> **발행 정책 — 누적 발행(B안, 2026-08-13 확정)**: 새 버전은 **이번 draft만 담지 않는다.**
> 해당 Stage의 기존 active 행 전체를 새 버전으로 **복사 승계한 뒤** 이번 draft를 추가하고,
> 승계 대상이 된 기존 active 버전만 deprecated 처리한다.
>
> 이렇게 바뀐 이유는 실제 버그다 — 초기 구현은 "이번 draft만 담은 새 버전을 만들고 기존
> active를 deprecated로 내린다" 방식이었는데, 이러면 **문서를 한 건씩 순차 투입할 때마다
> 직전 문서에서 얻은 룰이 통째로 비활성화됐다.** 여러 법령 문서를 순서대로 넣는 것이
> 정상 운영 방식인 이 파이프라인 구조상 치명적이었다.
>
> 불변식은 유지된다.
> - **Stage당 active 버전은 항상 유일**하다 (조회 쪽 `status='active'` 필터는 그대로 유효)
> - **Stage 간 lineage는 독립**이다 — deprecate 대상을 "해당 Stage의 데이터를 가진 active
>   버전"으로 join 스코프를 좁혀서 판단한다. 이 스코프 제한이 없으면 Stage A만 발행해도
>   Stage B의 active 버전까지 deprecated로 끌려가는 과거 버그가 재발한다.
>
> ⚠️ **미해결 항목**: Stage A 행을 승계 복사하면 `keyword_id`(PK)가 새로 발급된다.
> 이미 적재된 `correction_rules.derived_from_keyword_id`는 승계 이전(deprecated)
> 키워드 행을 계속 가리키게 되어 FK는 유효하지만 참조가 낡는다. 재연결 정책 미정
> (미결정_항목_정리.md D-12).

### 3.2 GATE 테이블 (결정1: 키워드스캐닝 + 조합매트릭스, PREP §8.1~8.2)

**`gate_keywords`** — 1차 키워드 스캔

| 컬럼 | 타입 | 설명 |
|---|---|---|
| keyword_id | UUID, PK | |
| rule_version_id | UUID, FK | |
| type | VARCHAR | DISEASE / PROHIBITED_ACTION / DOCTOR_REPLACEMENT |
| keyword | VARCHAR | 예: "당뇨", "진단", "전문의 없이" |
| keyword_category | VARCHAR | 진단단계(DIAGNOSIS) / 치료단계(TREATMENT) / 데이터유형(DATA_TYPE) / 기타(OTHER) |
| data_type_focus | VARCHAR | 영상(IMAGING) / 텍스트(TEXT) / 수치(NUMERIC) / 해당없음(NONE) |
| verdict | VARCHAR | FAIL_CANDIDATE / CONTEXT_CHECK / FAIL_CONFIRMED |
| weight | INTEGER | 문맥 평가용 가중치 |
| created_at | TIMESTAMP | |

> **`type` 분류 판별 기준 (2026-08-14 추가)** — 실전 문서 투입 중 LLM이 `type`을 거의 전부
> `PROHIBITED_ACTION`으로 몰아 발급하는 편향이 관측됐다(원인: 이 표에 판별 기준이 없어
> extract_a.py 프롬프트가 참조할 근거가 없었음). 판별은 **품사** 기준이다.
>
> | type | 판별 기준 | 예시 |
> |---|---|---|
> | DISEASE | 질병명·생체지표 등 **명사**가 그대로 키워드인 경우 | "당뇨", "부정맥", "혈당", "혈압", "심전도" |
> | PROHIBITED_ACTION | 면허 없이 하면 안 되는 **행위**를 가리키는 경우 | "진단", "처방", "조제", "치료법 제공" |
> | DOCTOR_REPLACEMENT | 의사의 진단·처방을 **대체한다**고 명시한 경우 | "전문의 없이", "의사 상담 없이 처방" |
>
> 조문에서 뽑히는 키워드는 대부분 질병명·생체지표(DISEASE)이거나 판단 대상 데이터이며,
> 행위를 가리킬 때만 PROHIBITED_ACTION을 고른다. extract_a.py 프롬프트에 이 표와 "PROHIBITED_ACTION만
> 반복해서 쓰지 말 것" 경고를 반영해 편향을 교정했다(2026-08-14).

- `keyword_category`: 키워드가 어느 의료행위 단계에 해당하는지 구분 (진단단계: "혈당측정", "체온감지" 등 / 치료단계: "약물추천", "처치안내" 등 / 데이터유형: 특정 데이터 자체가 키워드인 경우)
- `data_type_focus`: 해당 키워드가 주로 어떤 입력 포맷과 관련 있는지 표시하는 참고용 태그 (UI 표시·라우팅 용도). **위험도 판단에는 사용하지 않음** — 위험도는 weight(본 테이블) 및 gate_matrix.data_type(Stage B)로만 산출 (2026-07-05 결정, 아래 체계표 참조)
- type별 기본 처리 (PREP §8.1): DISEASE → 의료목적 맥락 확인, PROHIBITED_ACTION → FAIL 후보 생성, DOCTOR_REPLACEMENT → FAIL 후보 생성
- 탐지만으로 즉시 FAIL 확정하지 않고, FAIL_CONFIRMED 룰만 즉시 FAIL 반환 (관리자 검수 시 지정)

**데이터 유형 (포맷 태그, 키워드 분류 참고용 — 위험도 산출에는 미사용)**

| 데이터 유형 | 예시 키워드 | 비고 |
|---|---|---|
| 영상(IMAGING) | 피부사진, 안저영상, X-ray 분석 | UI 표시·라우팅 참고용 |
| 수치(NUMERIC) | 혈당, 혈압, 체온, 산소포화도 | UI 표시·라우팅 참고용 |
| 텍스트(TEXT) | 증상 입력, 문진, 의료상담 | UI 표시·라우팅 참고용 |
| 라이프스타일(LIFESTYLE) | 수면, 식단, 운동 기록 | UI 표시·라우팅 참고용 |

> ⚠️ 위해도 등급 자체는 DB 내부 컬럼이 아닌 별도 `risk_metadata`(§3.2.1)로 관리한다.

> ✅ **결정 완료 (2026-07-05) — data_type_focus ↔ gate_matrix.data_type 이중체계 정리**
>
> B안 채택: `data_type_focus`는 **"키워드가 어떤 입력 포맷인지"를 나타내는 참고용 태그로만 사용**하고, 규제 위험도 판단은 전적으로 `gate_matrix.data_type`(라이프스타일/생체지표/민감정보/임상·진료, 법적 근거는 룰_추출_기준_현황_및_보완분석.md Stage B에서 확정)만 사용한다. `data_type_focus`는 위험도 계산·gate_matrix 조회 어디에도 입력으로 쓰이지 않으며, UI 표시나 키워드 라우팅 등 부가 용도로만 남긴다.
>
> 근거: 두 필드는 애초에 서로 다른 층위(포맷 vs 법적범주)를 다루고, IMAGING·TEXT는 맥락에 따라 생체지표/민감정보/임상·진료 어디로도 갈 수 있어 1:1 매핑이 불가능함. 위험도 판단 근거를 하나(gate_matrix.data_type)로 통일하는 것이 "LLM이 판단하지 않고 미리 정의된 테이블에서 조회한다"는 프로젝트 전체 원칙과 일관됨.
>
> 후속 조치: §3.2.1 risk_metadata 참조방식, §3.5 competitors 유사도 기준에 동일 원칙 반영 완료.

#### 3.2.1 risk_metadata — 위해도 기준 메타데이터 (DB 외부 분리)

위해도 판단 기준은 법령·가이드 개정 시 자주 변경되므로 DB 컬럼이 아닌 **별도 설정 파일(JSON/YAML) 또는 관리자 설정 테이블**로 분리 관리한다.

| 항목 | 내용 |
|---|---|
| 관리 위치 | `risk_metadata.json` (버전 관리 대상) 또는 `risk_config` 테이블 |
| 구성 요소 | 고위해도 5종 목록, 데이터 유형별 기본 위험등급, 위험도 판단 우선순위 |
| 업데이트 시점 | 의료기기 판단 가이드 개정 시 (DB 전체 재구축 없이 메타데이터만 갱신) |
| 참조 방식 | Gate Engine 판정 시 런타임 로드, gate_keywords.type·weight와 조합하여 위험도 산출 (2026-07-05: data_type_focus는 위험도 계산에서 제외 — §3.2 결정 완료 항목 참조. 데이터 유형에 따른 위험도는 gate_matrix.data_type 조회로만 판단) |

**`gate_matrix`** — 2차 조합 판정

| 컬럼 | 타입 | 설명 |
|---|---|---|
| matrix_id | UUID, PK | |
| rule_version_id | UUID, FK | |
| data_type | VARCHAR | 라이프스타일/생체지표 (What, 닫힌 2종 enum — 2026-07-12: 민감정보/임상·진료 제외 확정, 1차 구축 범위. 민감정보는 생체지표에 포함되는 개념으로 처리, 임상·진료는 2차 구축에서 재도입 예정) |
| function_type | VARCHAR | 단순기록/비교·추이분석/수치예측·진단 (Why, 닫힌 3종 enum — 모바일앱지침 Ⅲ.2~3 근거로 확정, "등" 제거) |
| verdict | VARCHAR | **PASS / CONDITIONAL / FAIL** (2026-07-05 갱신: 기존 PASS/FAIL 2종 → 3종으로 확장. 근거: 룰_추출_기준_현황_및_보완분석.md Stage B 매핑테이블 확정 결과 CONDITIONAL 포함. data_type 2분류 축소 이후 6칸 중 2칸이 CONDITIONAL) |
| exemption_note | VARCHAR, nullable | "제외대상"류 특수 PASS 케이스의 법적 근거 요약(예: "시행규칙 제11조6호가·나목 제외대상") — 별도 enum 값 대신 이 필드로 구분. verdict=PASS인데 exemption_note가 있으면 "조건부 제외" 성격임을 표시 |
| legal_basis_doc | VARCHAR, nullable | **(2026-08-09 추가)** evidence_documents.document_id 참조 — `correction_rules`(§3.3)와 동일 패턴. 리포트 SECTION 1·부록의 GATE 판정 근거 표시에 사용 |
| legal_basis_article | VARCHAR, nullable | **(2026-08-09 추가)** 조문 표기 — **§1.5.1 정규화 규칙 적용** (예: `III.가`, `IV.3`). RAG `evidence_chunks.section_id`와 join 키 |
| acquire_method | VARCHAR, nullable | **(2026-07-26 복원)** 수동입력/기기연동/OS연동/기관연동 — data_type×function_type 6칸 매트릭스의 축을 늘리는 용도가 아니라, "침습적 하드체크" 오버라이드 전용 필드. data_type=생체지표 + acquire_method=기기연동 + Stage A에서 고위해도 2번(침습적) 키워드가 함께 감지된 조합은 function_type·표 조회 결과와 무관하게 **`verdict='FAIL'`로 하드 오버라이드**(구 룰베이스 구축방안 pseudocode의 `if acquireMethod=="기기연동" and 침습적: return FAIL` 로직 복원). 해당 없는 일반 조합은 이 필드 비워둠 |
| avoidance_redesign | VARCHAR, nullable | **(2026-07-26 복원)** verdict=FAIL일 때만 채움 — 회피 방향 옵션1 "기능 재정의": 어떤 표현·기능을 빼면 PASS/CONDITIONAL로 전환 가능한지 안내 (예: "피드백 제거 → '수치 저장·기록'으로만 기능 축소") |
| avoidance_certification | VARCHAR, nullable | **(2026-07-26 복원)** verdict=FAIL일 때만 채움 — 회피 방향 옵션2 "의료기기 인증 트랙": 정식 인증을 받고자 할 경우의 안내(문의처·절차 등) |
| risk_code | VARCHAR | 후속 §01 연계용 코드 |
| priority | INTEGER | 복수 조합 시 우선순위 |
| created_at | TIMESTAMP | |

→ 복수 데이터×목적 조합이 입력되면 **FAIL > CONDITIONAL > PASS** 우선순위(가장 위험한 판정 채택) 적용하여 최종 판정 채택 (PREP §8.2 원칙 확장 — 기존 FAIL 고정 우선 원칙에 CONDITIONAL 계층 추가)

> **(2026-07-26 추가) acquire_method·avoidance_* 복원 배경**: 옛 룰베이스 DB 구축방안(2026-07 이전 초안)에 있던 획득방법(acquire_method) 축과 회피 방향 2가지 안내(fail_options)가 V2.7 이후 data_type 2분류 축소 과정에서 스키마에서 누락되어 있었음을 재확인(2026-07-26). 리포트 파이프라인 다이어그램의 "회피 방향 2가지 안내" 출력 박스가 이 필드에 대응됨 — 지금까지는 대응하는 DB 필드가 없어 실제로 채울 방법이 없었음. acquire_method는 전체 매트릭스를 3축(data_type×acquire_method×function_type)으로 확장하지 않고 침습적 하드체크 전용으로 좁게 복원 — 축을 그대로 확장하면 옛 문서 기준 최소 18칸(2×3×3)으로 늘어나는데, 실제로 verdict를 가르는 변수는 대부분 function_type이었고 acquire_method가 verdict를 바꾸는 사례는 "침습적 기기연동" 케이스뿐이었음(구 룰베이스 구축방안 GATE metrix 표 참조 — 혈압 기기연동 PASS/FAIL을 가른 건 function_type이었지, acquire_method가 아니었음).

**data_type × function_type 확정 매핑 (시드 데이터, 룰_추출_기준_최종확정본.md v1.2 기준 — 2026-07-20 갱신, verdict 변경 없음. function_type 판별 상세 기준(디시전 트리·예시 문구·경계 케이스 처리)은 최종확정본.md §Stage B 참조)**

| data_type | function_type | verdict | exemption_note / 근거 |
|---|---|---|---|
| 생체지표 | 단순기록 | PASS | 웰니스판단기준(0091-03) Ⅳ.1.가 — 수치화 없이 그래프·추이만 표시 |
| 생체지표 | 비교·추이분석 | CONDITIONAL | 0091-03 Ⅲ.가 4대 요건(비침습·비이식/비의료목적/기허가 의료기기 대체 아님/임상적 조치 유도 안 함) 충족 시 PASS |
| 생체지표 | 수치예측·진단 | FAIL | 0091-03 Ⅳ.3 — 혈당 수치값 표시+위험수치 알람 기능=의료기기 |
| 라이프스타일 | 단순기록 | PASS | 0091-03 Ⅳ.1 — 체지방·수면 자가측정 |
| 라이프스타일 | 비교·추이분석 | PASS | 0091-03 Ⅲ.다 — 식사소비량 모니터+과식경고, 저위해도 명시 |
| 라이프스타일 | 수치예측·진단 | CONDITIONAL | LLM가이드라인 표3-1 — 예측 결과가 진단·위험도 산출로 이어지는지에 따라 결정 |

> 이 6건은 관리자 검수 없이 즉시 rule_versions=active로 적재 가능한 확정 시드데이터로 취급한다 (법령·고시 원문 근거 100% 확보 완료). 기존 민감정보·임상·진료 관련 6건은 2026-07-12 data_type 2분류 결정에 따라 제외됨 — 임상·진료는 2차 구축 시 재검토.

### 3.3 correction_rules — 위험표현·교정 (결정2, PREP §8.3)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| rule_id | UUID, PK | |
| rule_version_id | UUID, FK | |
| risky_text | VARCHAR | 위험 표현 (동사×명사 결합, 예: "당뇨 진단") |
| safe_text | VARCHAR | 대체 표현 |
| regulatory_score | INTEGER | 의료행위표현 축 점수 — **오프라인 파생**: gate_keywords.weight 조회로 산출 (LLM 미판단). risky_text 자체의 속성이므로 룰에 저장 |
| ~~privacy_score~~ | ~~INTEGER~~ | **2026-07-28 컬럼 삭제** — 개인정보민감도는 룰의 속성이 아니라 **사용자가 무엇을 수집하는가**에 따라 결정되므로 런타임에 계산한다. §3.3.2 참조 |
| advertising_score | INTEGER | 광고표현위험 축 점수 — **오프라인 독립 추출**: LLM이 별표7(의료기기법 시행규칙 제45조) 신호어 매칭으로 직접 산출. risky_text 자체의 속성이므로 룰에 저장 |
| derived_from_keyword_id | UUID, FK, nullable | gate_keywords 참조 — regulatory_score 산출 근거 키워드 추적용 (검수 시 "왜 이 점수인지" 확인) |
| legal_basis_doc | VARCHAR | evidence_documents.document_id 참조 |
| legal_basis_article | VARCHAR | |
| created_at | TIMESTAMP | |

> **변경 이유 (교수 피드백 반영)**: 기존 `category` 단일 컬럼은 성격이 다른 3개 항목(규제·개인정보·광고)을 하나로 묶어 판단 근거가 불명확했음. 축별 독립 점수 컬럼으로 분리하여 각 영역의 위험도를 개별 추적 가능하게 함.

> **axis_score 산출방식**: regulatory_score는 Stage A(gate_keywords)에서 이미 확정한 법적 근거를 재사용하는 **파생값**이므로 LLM이 새로 판단하지 않고 조회·계산만 함(§4.1 파이프라인 [5]~[6] 사이에 산출 단계 추가, §4.2 참조). advertising_score만 Stage A·B가 다루지 않는 새 영역(의료기기법 제24조·시행규칙 제45조·별표7)이라 LLM이 독립적으로 추출함.
>
> **risky_text/safe_text 생성 경로 (2026-08-13~ 정정)**: 원 계획은 "동사×명사 매트릭스로 위험 태그 생성"(아래 문단)이었고 이는 그대로 유지되나, 실제 구현은 **코드 조합 생성**(§3.3.3, LLM 호출 없음)과 **LLM 추출**(`extract_c.py`, 문서 청크 기반, advertising_score 산출 겸용) **두 경로가 병행**된다. 하나가 다른 하나를 대체한 게 아니다 — regulatory_score만 필요한 경우(동사×명사 조합)는 코드가 채우고, 문서에 실제 위험 표현이 등장하는 경우(광고 문구 등 advertising_score가 필요한 경우)는 LLM이 채운다. 상세는 §3.3.3, §4.2 Stage C.
>
> - regulatory_score 산출: gate_keywords.weight=5 또는 verdict=FAIL_CONFIRMED 매칭 시 3점 / weight 3~4 매칭 시 2점 / weight 1~2 매칭 시 1점 / 매칭 없음 0점
> - advertising_score 산출: 별표7 18개 항목 중 1·2·4·8·9·15·17·18호 해당 시 3점 / 3·5·6·7·10·11·14호 해당 시 2점 / 12·13·16호 해당 시 1점 / 해당없음 0점
> - privacy_score: **본 테이블에서 산출하지 않음** — 런타임 계산으로 이관(§3.3.2)

**오프라인 판정 흐름 (본 파이프라인 범위)**: 동사×명사 매트릭스(risky_text) 매칭으로 위험 태그 생성 → `regulatory_score`(gate_keywords 조회) / `advertising_score`(LLM 독립추출) 2축을 산출해 룰에 저장.

> **최종 위험등급 산출은 런타임(판정엔진)에서 수행한다.** 3축 중 privacy_score가 사용자 입력에서 결정되므로 오프라인에서는 등급을 확정할 수 없다. 상세 흐름은 §3.3.2 및 판정엔진_개발설계서 §6 참조.

> ✅ **결정 완료 (2026-07-26) — "합산" vs "최고값" 충돌 정리**: db_구축_계획서의 결정2는 "매트릭스 1차 판정 → **점수 합산**으로 레벨 산출"로 기술돼 있었으나, 본 절의 "3축 중 **최고 등급** 채택" 규칙과 충돌했다. **최고값 방식을 채택**하고, 합산점수(0~9)는 판정에 쓰지 않고 리포트 §2-1 판단근거 4줄에 참고 수치로만 노출한다.
>
> 합산을 쓰지 않는 이유: 광고 축만 3점인 경우 합산이 3점에 그쳐 "중간"으로 분류되는데, 별표7 3점 항목(1·2·4·8·9·15·17·18호 = 허위·과대광고)은 그 자체로 즉시 시정 대상이라 과소평가 위험이 크다. 어느 한 축이라도 최고 위험이면 최종 등급도 높음이어야 한다.

#### 3.3.2 privacy_score 산출 규칙 — 🔵 **런타임 계산** (2026-07-28 확정)

> 🔵 **본 절은 오프라인 파이프라인이 아니라 판정엔진(런타임)에서 수행하는 계산이다.** 값이 룰이 아니라 **사용자 입력**에서 결정되므로 correction_rules에 저장하지 않는다.

**입력**: 사용자가 아이디어 입력 Step2에서 선택한 **수집 데이터 항목** → §3.9 `data_sensitivity.sensitivity_level` 조회

| sensitivity_level | privacy_score | 등급(§3.3.1) |
|---|---|---|
| 3 | 3 | 높음 |
| 2 | 2 | 중간 |
| 1 | 1 | 낮음 |
| 미포함 | 0 | 낮음 |

> 복수 항목 선택 시 **최댓값** 채택 (§3.4 D×S와 동일 원칙)

> ✅ **결정 완료 (2026-07-28) — 3축의 계산 위치 분리**
>
> 3축을 모두 correction_rules에 저장하려던 기존 구조는 `privacy_score`에서 모순을 일으켰다. 아래 두 서비스를 보면 명확하다.
>
> | | 서비스 A | 서비스 B |
> |---|---|---|
> | 설명 | "**수면 데이터**를 분석해 불면증을 진단합니다" | "**복용약물**을 분석해 불면증을 진단합니다" |
> | 매칭 risky_text | "불면증 진단" (동일) | "불면증 진단" (동일) |
> | regulatory_score | 3 | 3 — 같아야 맞음 |
> | advertising_score | 0 | 0 — 같아야 맞음 |
> | privacy_score | 수면 = level 1 → **1** | 복용약물 = level 3 → **3** |
>
> 같은 위험표현인데 privacy_score만 달라져야 하는데, 룰에 저장하면 값을 하나만 가질 수 있어 구조적으로 불가능하다.
>
> **원칙**: **표현에서 결정되는 값은 룰에 저장하고, 사용자 입력에서 결정되는 값은 런타임에 계산한다.**
>
> | 축 | 결정 요인 | 계산 위치 |
> |---|---|---|
> | regulatory_score | risky_text(표현) | 오프라인 — 룰에 저장 |
> | advertising_score | risky_text(표현) | 오프라인 — 룰에 저장 |
> | **privacy_score** | **사용자가 선택한 수집 항목** | **런타임 — 저장 안 함** |
>
> 리포트 명세도 이를 뒷받침한다 — SECTION 2-1 판단근거 ②가 "**수집** 데이터 민감도 평가"로, 사용자가 선택하는 값을 평가한다고 명시하고 있다.
>
> **연쇄 결정**: 3축을 모아야 하는 **최종 위험등급 산출(축별 등급 → 최고값)도 런타임**에서 수행한다. 룰 하나하나에 등급을 매기는 것은 의미가 없다(등급은 "이 아이디어가 얼마나 위험한가"이지 "이 룰이 얼마나 위험한가"가 아니다).

**런타임 계산 흐름 (판정엔진 §01)**

```
1. 사용자 서비스 설명 ← correction_rules.risky_text 매칭
        ↓ 매칭된 룰 N개
2. regulatory_score  = 매칭 룰들의 최댓값   (룰에서 조회)
   advertising_score = 매칭 룰들의 최댓값   (룰에서 조회)
        ↓
3. 사용자 Step2 수집 항목 → data_sensitivity 조회
   privacy_score = sensitivity_level 최댓값  (런타임 계산)
        ↓
4. 3축 → signal_config 임계값 → 축별 등급
5. 최고 등급 채택 → 최종 규제위험도
```

> ⚠️ **`data_sensitivity.item_label` 표기 정합이 전제 조건**: 런타임에 **사용자가 고른 값으로 직접 조회**하므로, `item_label`은 아이디어 입력 Step2 UI 옵션 문자열과 **글자 단위로 일치**해야 한다. "심박수" vs "심박 수" 같은 차이도 조회 실패를 일으키며, 실패 시 해당 항목의 민감도가 조용히 누락된다. 테이블 작성 전 디자인 담당으로부터 확정된 옵션 목록을 받아 그대로 사용할 것.

> ✅ **결정 완료 (2026-07-26 2차) — 동의 언급 여부를 점수 산출에서 제외**: 개정 초안은 `sensitivity_level × 동의 언급 여부` 2축이었으나, 아래 사유로 **동의 축을 점수에서 제거**하고 `action_templates`의 다음 액션 안내로 이관한다.
>
> 1. **검증 불가능한 입력이다** — 아이디어 입력 폼(3단계)에는 동의 관련 항목이 없어 서비스 설명 자유 텍스트에서 LLM이 추출하는 방식뿐이다. 그런데 실제 아이디어 설명에 동의 절차를 기술하는 경우는 드물어 대부분 `false`로 수렴하고, 결과적으로 동의 축이 작동하지 않는다.
> 2. **선언만으로 점수가 내려간다** — "동의를 받겠습니다" 한 줄로 3점이 2점이 된다. 아이디어 단계라 그 절차가 실재할 수 없고, 체크박스로 바꿔도 전원이 체크하므로 변별력이 생기지 않는다.
> 3. **동의를 받아도 규제 부담은 줄지 않는다** — 민감정보는 동의 취득 후에도 처리·보관·파기 규제가 그대로 적용되며, 오히려 제23조 별도 동의라는 의무가 추가된다. 점수를 낮춰주는 것이 실질을 반영한다고 보기 어렵다.
> 4. **프로젝트 원칙과의 정합** — 아이디어 단계에서 검증 불가능한 값을 점수화하지 않는다는 원칙(§6.4 `insufficient_data` 처리, 결과 리포트 명세의 "정밀 수치보다 정성적 평가")과 일관된다.
>
> **대체 처리**: 동의 요건은 리포트 §2-1의 "구체적 다음 액션"으로 안내한다. `action_templates`에 `sensitivity_level=3` 트리거 액션을 두고, 개인정보보호법 제23조의 **별도 동의**가 필요하며 일반 이용약관 동의로는 요건을 충족하지 못한다는 점을 명시한다.

> ✅ **개정 사유 (2026-07-26) — 구 규칙의 변별력 상실 문제**: 기존 규칙은 판단 입력이 `gate_matrix.data_type`(라이프스타일/생체지표 2종) 하나뿐이었다. 2026-07-12에 민감정보를 생체지표로 흡수한 결과, **심박수와 복용약물·과거병력이 동일하게 3점**을 받게 되어 실제 위험도가 전혀 다른 서비스를 구분할 수 없었다.
>
> 더 큰 문제는 최종 등급이 3축 최고값이라는 점이다. 웰니스 서비스 대부분이 생체지표를 하나 이상 다루므로 **거의 모든 아이디어가 규제위험도 "높음"으로 수렴**해, 신호등이 정보를 담지 못하는 상태가 된다.
>
> `data_sensitivity`(§3.9) 테이블을 신설하는 목적 자체가 이 구분이므로, privacy_score의 입력을 data_type → sensitivity_level로 교체한다. 교체하지 않으면 data_sensitivity는 어디에서도 읽히지 않는 테이블이 된다.

> **sensitivity_level 정의 (조사자 기준)**: 심박수 등도 개인정보보호법 제23조의 "건강에 관한 정보"로서 민감정보에 해당할 여지가 있으므로, level 구분은 "민감정보인가 아닌가"의 이분법이 아니라 **재식별·피해 위험의 정도** 차이로 정의한다.
> - **level 3** — 그 자체로 질병·치료·생식 이력이 드러나는 정보 (복용약물, 과거병력, 심리상담기록, 유전자정보, 생리주기)
> - **level 2** — 신체 측정값이나 단독으로는 질병을 특정하기 어려운 정보 (심박수, 혈압, 혈당, 체중, 체성분)
> - **level 1** — 라이프스타일 (걸음수, 수면시간, 식단사진, 활동량, 기분기록)

> ⚠️ **data_type과의 관계**: `gate_matrix.data_type`(2종)은 **GATE 규제 판정 전용**으로 그대로 유지된다. privacy_score만 sensitivity_level을 참조하도록 바뀐 것이며, 두 축은 목적이 다른 별개 필드다(§3.5 category_1/2 ↔ data_type 관계와 동일한 구조).

#### 3.3.1 signal_config — 점수 임계값 설정 (PREP §8.3)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| config_id | UUID, PK | |
| rule_version_id | UUID, FK | |
| axis | VARCHAR | 의료행위표현/개인정보민감도/광고표현위험 |
| threshold_low | INTEGER | **축별** 점수 ≤ N → 낮음 |
| threshold_mid | INTEGER | **축별** 점수 ≤ M → 중간, 초과 시 높음 |

> 적용한 rule_version은 리포트에 표시 (PREP §8.3)

> 🔵 **적용 위치**: signal_config는 **런타임(판정엔진)에서 조회**한다. 축별 등급 산출과 최고값 채택이 모두 런타임에서 이루어지기 때문이다(§3.3.2). 테이블·시드는 오프라인에서 구축하되 소비는 판정엔진이 한다.

**임계값 확정 (2026-07-26 최종)** — 3축 모두 동일 적용

| 축별 점수 | 등급 |
|---|---|
| **0~1** | **낮음** |
| 2 | 중간 |
| 3 | 높음 |

> 즉 `threshold_low=1`, `threshold_mid=2`. 각 축이 0~3점 척도(§3.3의 3축 산출 규칙)이므로 임계값도 그 척도 안에서 정의된다. 기존 설명이 "합산점수" 기준이었던 것은 결정2의 합산 방식을 전제한 것으로, 2026-07-26 최고값 방식 확정에 따라 **축별 점수 기준으로 정정**했다.

> ✅ **재조정 (2026-07-26 2차) — 초록 신호등 도달 불가 문제 해소**: 1차 확정값은 `0=낮음 / 1~2=중간 / 3=높음`이었으나, §3.3.2 privacy_score 개정 결과 **라이프스타일만 수집해도 최소 1점**이 나온다. 종합 신호등(§6.6)의 초록 조건이 "규제위험도 '낮음'"이므로, 1점부터 중간으로 분류하면 **데이터를 전혀 수집하지 않는 서비스만 초록을 받을 수 있어 사실상 초록이 도달 불가능**해진다.
>
> 웰니스 서비스가 데이터를 하나도 수집하지 않는 경우는 없으므로, 걸음수·수면시간 등 라이프스타일만 다루는 서비스는 규제 위험이 실제로 낮다고 보아 **1점까지 '낮음'에 포함**한다. 검토한 대안 중 임계값 한 줄만 조정하면 되는 이 방식을 채택했다(대안: privacy_score 라이프스타일을 0점화 → 개인정보를 수집하는데 0점은 부적절 / 초록 조건을 "낮음 또는 중간"으로 완화 → 초록이 과다 발생).
>
> 부수 효과: `regulatory_score` 1점(경계선·웰니스 키워드 포함)과 `advertising_score` 1점(별표7 12·13·16호)도 낮음으로 분류된다. 세 축 모두 1점은 "경미한 주의 수준"에 해당하므로 일관성 있는 처리다.

#### 3.3.3 verb_substitution — correction_rules 조합 생성용 동사 사전 (2026-08-13 신설)

data_difficulty·collection_difficulty와 같은 **고정 기준표**다 — LLM 추출 대상이 아니라 직접
INSERT하고, rule_version에 묶지 않는다.

**신설 배경**: 원 계획(§3.3, 결정2)은 "동사 목록: gate_keywords의 PROHIBITED_ACTION 키워드
재사용"이었다. 실제 적재된 PROHIBITED_ACTION 값에는 "모니터링"·"의료용으로 표시"처럼
동사가 아닌 것이 섞여 있어 그대로 재사용할 수 없었다 — gate_keywords는 게이트 판정용
어휘고 correction_rules 동사 목록은 표현 조합용 어휘라 목적 자체가 다르다. 대신 문서가
이미 열거해둔 확정 동사 목록(룰_추출_기준_최종확정본.md §Stage C)을 이 테이블에 못박았다.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| verb | VARCHAR, PK | 위험 동사 (예: "진단", "처방") |
| verb_category | VARCHAR | DIAGNOSIS / TREATMENT / PHARM |
| safe_verb | VARCHAR | 대체(안전) 표현. 원문의 실제 PASS 예시 문구에서 가져온다 |
| noun_classes | VARCHAR | 조합 가능한 명사 계열, 파이프(`\|`) 구분자로 다중 표기 (`질병명`, `생체지표`) |
| standalone | BOOLEAN | 명사 없이 동사 단독으로 risky_text가 되는가 (약무 3종만 true) |
| legal_basis_doc | VARCHAR | evidence_documents.document_id 참조 |
| legal_basis_article | VARCHAR, nullable | §1.5.1 표기 규칙 적용. 근거 문서 미확보 시 빈 문자열 |

**확정 12행** (문서 원안 11개 중 2개 제외 + 약무 3개 추가)

| verb_category | 동사 | noun_classes | 비고 |
|---|---|---|---|
| DIAGNOSIS (4) | 진단, 검사, 판별 | 질병명 | |
| 〃 | 측정 | **생체지표 전용** | 아래 "측정" 참조 |
| TREATMENT (5) | 치료, 처방, 개선, 완화, 처치 | 질병명 | **예방·보정 제외**(아래 참조) |
| PHARM (3) | 조제, 투약, 복약지도 | — (standalone) | 약사법 근거 |

- **예방·보정 제외**: 원 목록(11개: 진단·검사·판별·측정·치료·처방·예방·개선·완화·처치·보정)에
  있었으나, 웰니스판단기준 0091-03 원문 대조 결과 두 단어가 **PASS 예시로 직접 쓰이고 있어**
  위험 동사로 둘 수 없다. "예방": IV.2.가 "만성질환을 **예방**하거나 관리에 도움을 주기 위한
  앱". "보정": IV.1.나 "낙상 위험도 측정을 통해 **보행교정**이 가능하도록 도와주는 제품".
  목적어가 이미 질병명 자체라 noun_classes 제한으로는 걸러낼 수 없어 목록에서 뺐다.
- **"측정"의 noun_classes를 생체지표 전용으로 제한**: 0091-03 IV.3(개인용건강관리제품과
  의료기기 판단사례)이 "혈압을 측정하여 수치화하지 않고 그래프로 표시"는 PASS, "혈당값을
  측정하여…위험수치 알람"은 FAIL로 가른다. 즉 측정 자체가 아니라 **수치 표시·알람 여부**가
  관건이라 텍스트 매칭으로 잡을 층위가 아니다. safe_text에 "(수치·알람 기능 없이)" 조건을
  덧붙이는 방식으로 처리하고 룰 구조는 바꾸지 않는다.
- **약무 3종(조제·투약·복약지도) 추가**: 원 목록 확정(2026-07-20) 이후인 2026-08-12 C안
  결정(weight=4 + FAIL_CONFIRMED)에서 나온 값이라 원 목록에 없었다. `standalone=true` —
  명사와 조합하지 않고 동사 단독으로 risky_text가 된다.

**명사 목록 (verb_substitution과 별도, gate_keywords·correction_terms.py 조합)**

원 계획(§3.3, 결정2)은 "명사 목록: gate_keywords의 DISEASE 키워드 + gate_matrix의
data_type(생체지표) 항목 재사용"이었다. 후자가 실행 불가능하다 — `gate_matrix.data_type`은
라이프스타일/생체지표 **2종 enum**(GATE 판정 축)일 뿐 "혈당"·"심전도" 같은 세부 명사가
담겨 있지 않다. 대신 `gate_keywords`의 DISEASE 키워드(현재 14건)를 수기로 재분류한다.

- 질병명(7): 고지혈증, 고혈압, 당뇨, 당뇨병, 비만, 심장질환, 저혈압
- 생체지표(7, gate_keywords에서): 혈당, 혈압, 체온, 체지방, 수면, 스트레스, 정신적 안정
- 생체지표 보충(BIOMARKER_EXTRA, 5): 심박수, 체중, 체성분, 심전도, 산소포화도 —
  gate_keywords에 아직 없지만 §3.2 생체지표 정의 예시·판정_기준값_확정표.md §8
  sensitivity_level=2 목록에서 가져왔다

이 재분류는 자동이 아니라 **수기 매핑**(`app/pipeline/correction_terms.py`)이다. "고혈압"과
"혈압"처럼 접두어만 다른 케이스를 규칙으로 가르기 어렵고, 목록에 없는 새 DISEASE 키워드가
나오면 자동 포함하지 않고 경고만 낸다 — 문서가 늘어날 때마다 이 매핑을 갱신해야 한다는
신호다. "혈압"이 질병명(고혈압·저혈압)과 생체지표 양쪽에 걸치는 건 의도적으로 그대로
둔다 — 문법적으로 성립하지 않는 조합("혈압 진단")은 매칭 자체가 안 되므로 문제되지 않는다.

### 3.4 data_difficulty / collection_difficulty — D×S 점수표 (결정5, PREP §8.4)

**`data_difficulty`**

| 컬럼 | 타입 | 설명 |
|---|---|---|
| data_type | VARCHAR, PK | 라이프스타일/생체지표 (2026-07-12: Stage B data_type 2분류 축소에 맞춰 통일. 민감정보는 생체지표에 포함, 임상·진료는 2차 구축 이연) |
| weight | INTEGER | D 점수: 라이프스타일=1 / 생체지표=3 (5/10은 임상·진료 2차 구축 시 재사용 예정) |

**`collection_difficulty`**

| 컬럼 | 타입 | 설명 |
|---|---|---|
| method | VARCHAR, PK | 수동입력/OS연동/기기연동/기관연동 |
| weight | INTEGER | S 점수: 1/2/4/10 |

산출: `개별점수 = data_difficulty.weight × collection_difficulty.weight`(**곱**, 2026-07-26 확정), 복수 데이터 선택 시 **최댓값** 채택 → 등급 **1~3 쉬움 / 4~10 보통 / 12~30 어려움** (출력방향: 쉬움→즉시활용+MVP제안, 보통→단계별로드맵, 어려움→우회데이터+기관협력 강조)

> **(2026-07-26 확정) 임계값 재조정 — D축 2종 확정에 따른 필수 조정**: 기존 임계값(1~4 / 5~15 / 16~100)은 D축이 4종(1/3/5/10)이던 시절 기준이었다. D축을 2종(1/3)으로 확정하면서 실제로 나올 수 있는 값이 아래 8개로 줄어, 옛 임계값을 그대로 두면 🔴 어려움이 단 1개 조합(생체지표×기관연동=30)에서만 발생해 3단계 판정이 사실상 2단계로 붕괴한다.
>
> | | 수동입력(1) | OS연동(2) | 기기연동(4) | 기관연동(10) |
> |---|---|---|---|---|
> | 라이프스타일(1) | 1 🟢 | 2 🟢 | 4 🟡 | 10 🟡 |
> | 생체지표(3) | 3 🟢 | 6 🟡 | 12 🔴 | 30 🔴 |
>
> 재조정 결과 쉬움 3 / 보통 3 / 어려움 2로 분포가 균형을 이룬다. 최댓값도 100 → **30**으로 변경(D 최대 3 × S 최대 10).
>
> **연쇄 변경 — 리포트 2-2 🔴 분기 근거 교체**: 결과 리포트 명세 §2-2는 신호등 빨강의 사유를 "임상·진료 데이터 등 직접 수집 불가"로 서술하고 있으나, 임상·진료가 1차 구축에서 제외되면서 이 예시는 더 이상 성립하지 않는다. 🔴 조건을 **"생체지표를 기기연동·기관연동으로 확보해야 하는 경우"**로 다시 정의할 것.
>
> **민감정보 과소평가 이슈 (허용)**: 생리주기·복용약물·과거병력 등은 옛 D축에서 5점이었으나 생체지표(3)에 흡수되면서 난이도 점수가 낮아진다. 실제로는 개인정보보호법 제23조 별도 동의가 필요해 확보가 더 어렵지만, 이 부담은 §3.3 `privacy_score`가 독립적으로 평가하므로 난이도 축에서 재차 반영하지 않는다(이중 계산 방지).

> 본 두 테이블은 LLM 추출 대상이 아니며 고정 기준표를 직접 INSERT (계획서 결정5와 동일).
> `verb_substitution`(§3.3.3)도 같은 패턴이나 correction_rules 조합 생성용이라 §3.3.3에 별도
> 문서화했다 — 세 테이블 모두 "고정 기준표 직접 INSERT" 원칙은 동일하다.

### 3.5 competitors — 경쟁사 DB + 경쟁 포화도 (PREP §8.5, **공식 변경**)

**`competitors`**

| 컬럼 | 타입 | 설명 |
|---|---|---|
| competitor_id | UUID, PK | |
| name | VARCHAR | 삼성헬스, 눔, Calm 등 |
| category_1 | VARCHAR | 질병축(7종) — 수면/정신건강/운동/식단/만성질환/여성건강/미용 (2026-07-20: 유전자는 시장 사례 부족으로 제외) |
| category_2 | VARCHAR | 기능축(4종) — 정보제공/데이터기록관리/매칭연결/개입치료 |
| country | VARCHAR | |
| tier | VARCHAR | 플랫폼 / 카테고리리더 / 일반경쟁자 |
| data_type | VARCHAR | 라이프스타일/생체지표 (gate_matrix.data_type과 통일) |
| target | VARCHAR | 아이디어 입력 Step2 타겟 옵션과 동일 값 |
| service_type | VARCHAR | 아이디어 입력 Step1·Step3 서비스형태 옵션과 동일 값 |
| core_tags | JSON | 핵심 기능 태그 |
| sub_tags | JSON | 부가 기능 태그 |
| bm_pattern | JSON(배열) | Business Model Navigator 패턴 서브셋, 복수 겸영 허용(예: 구독형+코칭애드온) — §3.6 bm_mapping 집계의 원천 데이터 |
| note | VARCHAR | 자유 메모 |
| created_at | TIMESTAMP | 최초 등록일 |
| updated_at | TIMESTAMP | 최근 갱신일 (데이터 노후화 리스크 대응, 프랩_기획서.pdf §12) |

> (2026-07-20 추가) data_type/target/service_type/bm_pattern/note/updated_at 컬럼 신설 — bm_mapping을 본 테이블 기반 파생 VIEW로 전환하기 위함(§3.6). bm_pattern taxonomy는 Business Model Navigator(가스만 외, 55패턴) 채택 (근거: 프랩_기획서.pdf §6.4)
>
> **(2026-07-20 갱신) category → category_1 + category_2**: 기존 category(5종, AI 분류모델과 동일하다는 가정)를 팀에서 확정한 마켓 분류 체계로 교체. category_1(질병축)이 "만성질환"을 포함하는 것은 §3.2의 data_type 2분류(임상·진료 1차 구축 제외) 결정과 상충하지 않는다 — category_1/2는 **시장에서 어떤 경쟁사인지 분류**하는 축이고, data_type은 **GATE 규제 판단에 쓰는 데이터 유형** 축으로 서로 다른 목적의 별개 필드다. 즉 "만성질환 관리 앱"이라는 시장 카테고리에 속한 경쟁사라도, 그 앱이 실제 수집하는 데이터가 라이프스타일/생체지표(1차 구축 범위) 안에 있으면 data_type은 정상적으로 채워진다.
>
> **(2026-07-20 추가 조정) 유전자 삭제, 8종→7종**: category_1 초안에는 유전자가 있었으나, 팀 확인 결과 실제 시장에 유전자 관련 웰니스 경쟁사 사례가 거의 없어 수집 효율이 떨어진다는 판단으로 taxonomy에서 완전히 제외. 수면/정신건강/운동/식단/만성질환/여성건강/미용 7종으로 확정.

**`competitor_tier_score`** (signal_config 또는 별도 설정 테이블)

| tier | 체급 점수 |
|---|---|
| 플랫폼 | 5 |
| 카테고리 리더 | 3 |
| 일반 경쟁자 | 1 |

> ✅ **(2026-07-26 갱신) 캘리브레이션 불필요로 전환**: 포화도가 개수 기반으로 확정되면서(아래 "경쟁 포화도 산출 공식") 이 점수는 가중합에 곱해지지 않는다. 실제로는 `tier='플랫폼'` 존재 여부만 Saturated 오버라이드 판정에 쓰이므로, 5/3/1 수치 자체는 참고값으로만 남기고 캘리브레이션 대상에서 제외한다. §8.2의 관련 미결정 항목도 해소 처리.

**유사도 가중치 (데이터 유형 중심)**

> **판단 기준 방향**: 병명 중심이 아닌 **데이터 유형 중심**으로 경쟁사 유사도를 판단한다. 창업자는 "어떤 질환을 다루는지"보다 "어떤 데이터를 수집·활용하는지"를 기준으로 서비스를 설계하며, 규제 리스크 역시 데이터 유형에 따라 결정되기 때문에 데이터 유형이 실질적 경쟁 판단 기준에 더 적합하다.
>
> ✅ **결정 완료 (2026-07-12 갱신)**: `core_tags`의 "데이터 유형"은 **gate_matrix.data_type 2종(라이프스타일/생체지표)**으로 통일한다(2026-07-05에는 4종이었으나 Stage B data_type 2분류 축소에 맞춰 갱신). 기존에 쓰던 IMAGING/NUMERIC/TEXT(data_type_focus 값)는 §3.2 결정에 따라 위험도·규제 관련 판단에는 더 이상 사용하지 않으므로, "규제 리스크 기준 유사도"를 표방하는 이 표에도 데이터 유형은 gate_matrix.data_type만 사용해야 논리적으로 일관됨.

| 유사도 기준 | 판단 조건 | 가중치 |
|---|---|---|
| 데이터 유형 동일 + 핵심 기능 일치 | core_tags의 data_type(라이프스타일/생체지표)이 동일하고 주요 기능도 겹침 | 1.0 |
| 데이터 유형 동일 + 기능 부분 일치 | data_type은 같으나 기능 범위가 일부만 겹침 | 0.7 |
| 데이터 유형 상이 + 카테고리 일치 | data_type이 다르지만(2종뿐이므로 자동으로 유일한 상이 조합) 동일 카테고리 | 0.4 |
| 카테고리만 일치 | 동일 웰니스 카테고리지만 data_type도 상이 | 0.2 |

> ⚠️ **(2026-07-26) 이 가중치 표는 포화도 산출에서 폐기됨** — 포화도가 개수 기반으로 확정되어 유사도 가중치를 곱할 자리가 없어졌다. 표는 "어떤 경쟁사를 유사하다고 볼 것인가"라는 개념 정의로서 이력상 남겨두되, **판정 계산에는 사용하지 않는다**. 유사 경쟁사 범위는 §6.4의 4단계 완화 전략(exact→relaxed_service_type→relaxed_category_only)이 대체한다.
>
> 가중치 근거(이력): 동일 data_type은 동일 규제 리스크 구간에 놓이므로 실질적 경쟁 강도가 높다(1.0). data_type이 다른 경우 일부 법적 리스크를 공유하여 중간(0.4~0.7). 카테고리만 같은 경우 규제·데이터 구조가 달라 경쟁 강도 낮음(0.2).
>
> ✅ **"인접 관계 미확정" 항목 해소 (2026-07-12)**: data_type이 4종일 때는 어느 조합이 "인접"한지 별도 정의가 필요했으나, 2종(라이프스타일/생체지표)으로 축소되면서 "다른 data_type"의 경우의 수가 하나뿐이라 인접 관계를 따로 정의할 필요가 없어짐. §8.2의 관련 미결정 항목은 해소 처리.

**경쟁 포화도 산출 공식 (2026-07-26 재확정 — 개수 기반으로 환원)**

```
n = 조회 범위 내 경쟁사 COUNT

n = 0~2                        → Opportunity  (시장현실성 높음)
n = 3~4                        → Challenging  (시장현실성 중간)
n >= 5                         → Saturated 후보
n >= 5 AND tier='플랫폼' 존재   → Saturated    (시장현실성 낮음, 확정)
```

> ✅ **결정 완료 (2026-07-26) — 가중합 폐기, 개수 기반 채택**: 기존 가중합 공식(`Σ(체급점수 × 유사도가중치)`)은 미확정 수치를 **두 세트**(tier_score 5/3/1 + 유사도 가중치 1.0/0.7/0.4/0.2, 총 7개) 요구하는데다, "유사도"를 실제로 어떻게 계산하는지(core_tags 겹침 비율 등)에 대한 정의가 없어 90건 시드로는 캘리브레이션이 불가능하다고 판단. db_구축_계획서_V0.3 결정5의 **경쟁사 수 기반 임계값으로 환원**하고, 가중합이 잡으려 했던 "대형 플랫폼 1개 vs 소규모 5개" 구분은 `tier='플랫폼'` 존재 여부 오버라이드로 대체한다.
>
> 부수 효과: `competitor_tier_score`(5/3/1)가 **가중치가 아닌 플래그 용도**로만 쓰이게 되어 수치 캘리브레이션 자체가 불필요해졌고, `bm_mapping`의 frequency_score(COUNT 기반)와 산출 원리가 통일된다.

**조회 범위 (n을 세는 기준)**

포화도의 n은 §6.4 BM 모듈과 **동일한 4단계 완화(fallback) 전략**을 사용한다.

```
1) exact_match          : category_1 + category_2 + target + service_type 전부 일치
2) relaxed_service_type : service_type 조건 해제
3) relaxed_category_only: category_1 + category_2 만 일치
4) insufficient_data    : 위 3단계 모두 n=0
```

> 4개 키를 모두 맞춰 세면 시드 90건이 잘게 쪼개져 대부분 n≤2로 나와 무조건 Opportunity가 되는 문제가 있다. 완화 전략을 적용하면 시장현실성(§03)과 BM 추천(§04)이 **같은 조회 전략을 공유**하게 되어 구현·설명 모두 단순해진다. 리포트에는 어느 단계에서 매칭됐는지(match_level)를 함께 표기해 근거 신뢰도를 드러낸다.

**경쟁 서비스 카드 노출 개수 (2026-07-26 확정)**: 리포트 §2-3의 경쟁 서비스 카드는 **3개**이므로 competitors 조회 시 `LIMIT 3`을 적용한다(설계서에 명시된 바 없어 결과 리포트 명세 기준으로 확정). §04 BM 추천 카드는 리포트 명세·§6.4 SQL 모두 2개로 일치.

**시장현실성 신호등 매핑 (2026-07-26 확정)**

| 포화도 | 시장현실성 지표 |
|---|---|
| Opportunity | 높음 |
| Challenging | 중간 |
| Saturated (후보 포함) | 낮음 |

> ⚠️ **역관계 주의**: 포화도가 **낮을수록** 시장현실성 지표는 **높다**. 구현·리포트 문구 작성 시 혼동하기 쉬운 지점이므로 명시한다.

### 3.6 bm_mapping — BM 추천 (PREP §8.6, **공식 변경 2026-07-20: 저장 테이블 → VIEW**)

> 변천 과정: Stage D LLM 추출(최초안) → competitors 집계 기반 저장 테이블(1차 수정, 07-20 오전) → **저장하지 않는 VIEW**(최종, 07-20 오후). frequency_score/precedent_level/contributing_competitor_ids는 모두 competitors에서 그때그때 계산 가능한 값이라, 별도 테이블에 중복 저장하고 배치로 재집계할 이유가 없다는 판단. 저장 테이블이었다면 competitors가 바뀔 때마다 재집계·재저장(구 §6.4 파이프라인)과 정합성 관리가 필요했지만, VIEW는 조회 시점에 항상 최신 competitors로 계산되므로 그 부담이 없다. bm_pattern은 Business Model Navigator(가스만 외, 55개+확장5개 패턴) 중 웰니스향 서브셋을 닫힌 enum으로 사용 (근거: 프랩_기획서.pdf §6.4, 후보 12개는 §8.2).

```sql
CREATE VIEW bm_mapping AS
SELECT
  category_1,
  category_2,
  target,
  service_type,
  bm_pattern,
  COUNT(*) FILTER (WHERE country = '한국') AS frequency_score,
  COUNT(*) AS frequency_score_global,
  CASE
    WHEN COUNT(*) FILTER (WHERE country = '한국') >= 5 THEN '많음'
    WHEN COUNT(*) FILTER (WHERE country = '한국') >= 3 THEN '중간'
    WHEN COUNT(*) FILTER (WHERE country = '한국') >= 1 THEN '적음'
    WHEN COUNT(*) > 0 THEN '가능'          -- 국내 0, 해외 사례는 존재
    ELSE '어려움'                          -- 국내외 모두 0
  END AS precedent_level,
  STRING_AGG(competitor_id::text, ',') AS contributing_competitor_ids
FROM competitors
WHERE category_1 IS NOT NULL AND category_2 IS NOT NULL AND target IS NOT NULL AND service_type IS NOT NULL AND bm_pattern IS NOT NULL
GROUP BY category_1, category_2, target, service_type, bm_pattern;
```

| 출력 컬럼 | 설명 |
|---|---|
| category_1 | 질병축(7종) — §3.5 competitors.category_1과 동일 (2026-07-20 갱신: 기존 5종 category → category_1/category_2 2축으로 교체, 이후 유전자 제외로 8종→7종 조정) |
| category_2 | 기능축(4종) — §3.5 competitors.category_2와 동일 |
| target | 타겟 사용자군 (Step2 타겟 옵션과 동일 값) |
| service_type | 서비스 형태 (Step1·Step3 서비스형태 옵션과 동일 값) |
| bm_pattern | Business Model Navigator 패턴 (닫힌 enum, 후보 12개는 §8.2) |
| frequency_score | 국내(country='한국') 경쟁사 수 기준 빈도 |
| frequency_score_global | 국내+해외 전체 빈도 — precedent_level '가능' 판정 전용 |
| precedent_level | 많음/중간/적음/가능/어려움, 아래 표 기준 **100% 자동 산출**(기존 "0건-수동판단" 케이스를 국내/해외 분리로 제거) |
| contributing_competitor_ids | 집계에 포함된 competitor_id 목록 — 리포트에서 "이 BM을 쓰는 경쟁사" 근거로 직접 노출 |

> **(2026-07-20) category_1의 "만성질환" 포함은 data_type 2분류와 무관**: category_1/2는 시장 분류 전용 축이고, data_type(라이프스타일/생체지표, GATE 규제 판단용)은 별개 축이므로 "만성질환" 시장 카테고리와 1차 구축 data_type 범위(임상·진료 제외)는 서로 상충하지 않는다 (§3.5 참조).

**precedent_level 임계값 (국내 기준, 자동 산출)**

| precedent_level | 조건 |
|---|---|
| 많음 | 국내 frequency_score ≥ 5 |
| 중간 | 3 ≤ 국내 frequency_score < 5 |
| 적음 | 1 ≤ 국내 frequency_score < 3 |
| 가능 | 국내 frequency_score = 0, frequency_score_global ≥ 1 (해외 사례만 존재) |
| 어려움 | 국내외 모두 0 |

> **evidence_id는 MVP 범위 제외**: 가격·전환율 등 정량 근거 문서를 연결하는 기능은 3순위 데이터(BM 학술·사례 RAG)이자 VIEW로는 표현할 수 없는 수동 큐레이션 정보라 1차 구축에서는 두지 않는다. 필요해지면 (category_1, category_2, target, service_type, bm_pattern)을 참조키로 하는 별도 소형 테이블(예: `bm_evidence_note` — evidence_id, category_1, category_2, target, service_type, bm_pattern, note)을 추가해 이 VIEW 결과와 애플리케이션 레벨에서 LEFT JOIN 하는 방식으로 확장한다.

산출 절차: 별도 파이프라인 없음 — competitors에 데이터가 쌓이는 즉시 bm_mapping VIEW 조회 결과에 반영됨 (§6.3 참조). category_1/category_2/target/service_type으로 필터링 후 frequency_score 상위 2개를 추천안으로 사용 (PREP §8.6, §9.4).

### 3.7 evidence_documents / evidence_chunks — RAG 메타데이터 (PREP §9.3)

**`evidence_documents`**

| 컬럼 | 타입 | 설명 |
|---|---|---|
| document_id | UUID, PK | |
| title | VARCHAR | 법령·가이드·사례명 |
| doc_type | VARCHAR | LAW / GUIDE / CASE / REPORT |
| tag_regulatory | BOOLEAN | 규제(의료기기법·식약처 기준) 관련 문서 여부 |
| tag_privacy | BOOLEAN | 개인정보(개인정보보호법·GDPR 기준) 관련 여부 |
| tag_advertising | BOOLEAN | 광고(의료기기법 제24조·시행규칙 제45조·별표7 기준 — 주 근거; 의료법 제56조는 의료기관·의료인 직접 광고 시 보조 근거) 관련 여부 |
| effective_date | DATE | 시행·발행일 |
| version | VARCHAR | 문서 버전 |
| source_url | VARCHAR | 원문 위치 |
| indexed_at | TIMESTAMP | |

> **변경 이유 (교수 피드백 반영)**: 기존 `category_tag` 단일 VARCHAR 컬럼은 규제·개인정보·광고의 성격이 다른 항목을 하나로 묶어 필터링 정확도가 낮았음. 각 축을 독립 Boolean 컬럼으로 분리하여 복합 태깅(예: 규제+개인정보 동시 해당) 및 축별 검색 필터를 지원한다. 분류 근거: tag_regulatory=의료기기법·식약처 고시, tag_privacy=개인정보보호법·GDPR·민감정보 처리 기준, tag_advertising=의료기기법 제24조·시행규칙 제45조·별표7(주) + 의료법 제56조(보조, 의료기관·의료인 대상 한정).

**`evidence_chunks`**

| 컬럼 | 타입 | 설명 |
|---|---|---|
| chunk_id | UUID, PK | |
| document_id | UUID, FK | |
| chunk_index | INTEGER | |
| article_number | VARCHAR | 조문/섹션 |
| section_path | VARCHAR | |
| content | TEXT | 청크 본문 (ChromaDB 벡터의 RDB측 원문) |
| chroma_vector_id | VARCHAR | ChromaDB 문서 ID 매핑 |

### 3.8 funding_programs — 지원사업

| 컬럼 | 타입 | 설명 |
|---|---|---|
| program_id | UUID, PK | |
| title | VARCHAR | |
| region | VARCHAR | |
| stage | VARCHAR | |
| eligibility_json | JSON | funding_eligibility로 정규화 가능 |
| open_date / deadline | DATE | |
| source_url | VARCHAR | |

→ §6.3 사전구축 파이프라인에서 K-Startup API 등으로 수집 (PREP §20 미결정: API 제공범위 확인 필요)

### 3.9 신규 테이블 등급 기준 (2026-07-26 확정, B그룹)

> 본 절은 신규 구축 예정 테이블(C그룹)의 **등급 컬럼에 어떤 값을 어떤 기준으로 넣을지**를 확정한다. 테이블 전체 스키마는 별도 「신규 구축 테이블 명세」 문서를 참조하고, 여기서는 판정에 직접 쓰이는 등급 기준만 정의한다. **조사 착수 전에 이 기준이 공유되어야 담당자별 등급 편차를 막을 수 있다.**

**`data_sensitivity.sensitivity_level`** — §3.3.2 privacy_score 입력 (🔵 **런타임 조회 전용**)

> ⚠️ `item_label`은 아이디어 입력 Step2 UI 옵션 문자열과 **글자 단위로 일치**해야 한다. 런타임에 사용자 선택값으로 직접 조회하므로 불일치 시 조용히 누락된다(§3.3.2).

| level | 정의 | 예시 |
|---|---|---|
| 3 | 그 자체로 질병·치료·생식 이력이 드러나는 정보 | 복용약물, 과거병력, 심리상담기록, 유전자정보, 생리주기 |
| 2 | 신체 측정값이나 단독으로는 질병을 특정하기 어려운 정보 | 심박수, 혈압, 혈당, 체중, 체성분 |
| 1 | 라이프스타일 | 걸음수, 수면시간, 식단사진, 활동량, 기분기록 |

**`public_data_catalog.difficulty`** — 리포트 §2-2 데이터 소스 리스트

| difficulty | 기준 |
|---|---|
| 1 | 로그인 없이 즉시 다운로드 또는 API 조회 가능 |
| 2 | 회원가입·신청이 필요하나 승인이 자동이거나 간단 |
| 3 | 심사·IRB·기관 협약 필요, 또는 유료 |

> 판정 기준은 "데이터 품질이 좋은가"가 아니라 **"손에 넣기까지 몇 단계인가"**다. 복수 담당자가 나눠 조사해도 기준이 흔들리지 않도록 절차 기준으로 정의했다.

**`api_catalog.integration_difficulty`** — 리포트 §2-2 공개 API 항목

| difficulty | 기준 | 예시 |
|---|---|---|
| 1 | 공개 SDK, 개발자 계정만 있으면 즉시 | HealthKit, Health Connect |
| 2 | 앱 심사·승인 필요 | Fitbit, Garmin 일부 스코프 |
| 3 | 파트너십·유료 계약 필요 | 일부 의료기기 제조사 API |

**`action_templates.priority`** — 리포트 §2-1·부록·SECTION 3

| 대역 | 용도 |
|---|---|
| 900~999 | GATE FAIL 관련 (최우선) |
| 700~899 | 규제위험도 높음 |
| 500~699 | 데이터확보 어려움 |
| 300~499 | 시장현실성 낮음 |
| 100~299 | 일반·공통 |

> 높은 숫자부터 정렬해 **상위 3~4개만 노출**한다. 100 단위로 대역 사이를 비워두는 것은 후속 액션 추가 시 기존 값을 건드리지 않고 삽입할 수 있게 하기 위함이다.

> **필수 시드 액션 (2026-07-26)**: §3.3.2에서 동의 여부를 점수 산출에서 제외하는 대신, `sensitivity_level=3` 트리거 액션을 반드시 포함해야 한다. 이 액션이 없으면 민감정보 수집 서비스에 별도 동의 요건을 전혀 안내하지 못한다.
>
> | trigger_type | trigger_value | 안내 요지 |
> |---|---|---|
> | sensitivity_level | 3 | 개인정보보호법 제23조에 따른 **별도 동의** 필요. 일반 이용약관 동의·통합 동의로는 요건 미충족 |

**`app_store_ranking` → 국내 수요 등급** — 리포트 §2-3 판단근거 ①

| 해당 category_1 앱 중 최고 순위 | 판정 |
|---|---|
| 100위 이내 | 상위권 |
| 101~300위 | 중위권 |
| 300위 밖 또는 없음 | 낮음 |

> 건강·피트니스 카테고리 **무료 순위** 기준. "몇 개가 있는가"가 아니라 "가장 잘 되는 앱이 어디까지 올라가는가"로 판정하는 이유는, 개수 기준은 이미 §3.5 경쟁 포화도가 담당하고 있어 중복이기 때문이다.

---

## 4. LLM 기반 정보 추출 파이프라인

> ⚙️ **구현 프레임워크 (2026-07-05 결정)**: 본 §4 파이프라인은 **LangGraph** StateGraph로 구현한다. 노드·엣지·State 스키마·Human-in-the-loop(관리자 검수) 설계의 상세 내용은 별도 문서 `langgraph_파이프라인_설계서.md` 참조. 아래 §4.1~4.6은 프레임워크 중립적인 논리적 흐름 정의이며, LangGraph 노드 매핑은 해당 설계서 §11에 대응표로 정리돼 있음.

### 4.1 파이프라인 개요 (PREP ADMIN01 기준)

```
[1] 법령/가이드 PDF 업로드 (POST /admin/rule-documents)
       ↓
[2] 텍스트 추출 → 조문/제목 단위 청크 분할
       ↓
[3] Stage 라우팅 (gate_keywords / gate_matrix / correction_rules)
       ↓
[4] 프롬프트 주입 (추출스키마+판단축+신호어, JSON Schema 구조화 출력)
       ↓
[5] LLM 추출 실행 → JSON 룰 초안 (draft, rule_version_id=draft)
       ↓
[5.5] (Stage C 전용) 파생값 계산 — gate_keywords 조회로 regulatory_score 산출, LLM 미개입 (§3.3, §4.2 참조). ※ privacy_score는 2026-07-28부로 런타임 계산 이관되어 본 단계 대상이 아님(§3.3.2)
       ↓
[6] 자동 검증 (필수필드/enum/인용/중복/점수범위/파생값 일치)
       ↓
[7] 관리자 검수 (/admin/rule-drafts/{id}/publish)
       ↓
[8] rule_versions.status=active 전환, 해당 테이블 INSERT
```

### 4.2 Stage별 추출 스키마

#### Stage A — gate_keywords

```json
{
  "type": "DISEASE | PROHIBITED_ACTION | DOCTOR_REPLACEMENT",
  "keyword": "",
  "keyword_category": "DIAGNOSIS | TREATMENT | DATA_TYPE | OTHER",
  "data_type_focus": "IMAGING | NUMERIC | TEXT | LIFESTYLE | NONE",
  "verdict": "FAIL_CANDIDATE | CONTEXT_CHECK | FAIL_CONFIRMED",
  "weight": 0,
  "legal_basis": {"document_id": "", "article": "", "quote": ""}
}
```
- 판단축: 사용목적(의료용/비의료용), 데이터 유형(§3.2 데이터 유형 체계표 기준)
- 위해도 등급은 추출 스키마에 포함하지 않고 `risk_metadata`(§3.2.1)에서 런타임 로드하여 적용
- 신호어: FAIL=["해당한다","의료기기로 본다","제외한다","고위해도","아님"], PASS=["해당하지 않는다","저위해도","개인용건강관리제품"], CONDITIONAL=["단,","다만,","경우에 한하여"]

**weight 척도 정의 (1~5)**

> **조문 재정정 (2026-07-05)**: 아래 표는 지침서-0091-03(2026.2., 구 0091-02에서 개정) 확정 조문 번호로 갱신됨. 근거: 룰_추출_기준_현황_및_보완분석.md V1.5 Stage A "조문 재정정 대조표".

| weight | 의미 | 법적 근거 | 예시 키워드 |
|---|---|---|---|
| 5 | 고위해도 직접 해당 + 의료행위 명시 | 지침서-0091-03 **Ⅲ.2.가·나** 고위해도: ①생체적합성 문제 ②침습적 ③오작동 시 상해 ④위급상황 탐지 ⑤기기 통제·변경 | "진단", "치료", "삽입", "무호흡 측정", "혈당 조절", "의료기기 제어" |
| 4 | 의료 목적 강하게 암시 (단독 FAIL 후보) | 의료기기법(법률 제21263호) 제2조제1항: 질병의 진단·치료·경감·처치·예방, 상해·장애 보정 | "암 예측", "부정맥", "당뇨 진단", "상해 보정" |
| 3 | 의료 맥락 시 위험, 웰니스 맥락 시 허용 가능 | 지침서-0091-03 **Ⅳ.2.가**(만성질환 현상 관리용) 경계: 피드백·치료법 제공 여부가 기준 | "혈압 관리", "수면 무호흡", "혈당 모니터", "콜레스테롤" |
| 2 | 경계선 키워드 (웰니스 가능성 있음) | 지침서-0091-03 **Ⅲ.2.다**(저위해도): 질병 언급 없는 측정·모니터링 | "심박수", "산소포화도", "체지방", "스트레스 지수" |
| 1 | 웰니스 키워드 (참고용, PASS 가능성 높음) | 지침서-0091-03 **Ⅲ.가 + Ⅳ.1**(일상건강관리용): 체중, 피트니스, 수면 관리 등 | "수면", "체중", "운동", "칼로리", "스트레스 관리" |

> **소수점 없음**: weight는 정수 1~5만 사용. 추출 시 LLM은 위 표를 기준으로 가장 근접한 정수 배정.

**FAIL_CONFIRMED 지정 기준**

verdict = FAIL_CONFIRMED로 직접 지정하는 조건 (관리자 최종 확정):

| 조건 | 판단 근거 | 예시 |
|---|---|---|
| 고위해도 5가지 중 하나라도 해당 | 지침서-0091-03 **Ⅲ.2.가·나** | 체내 삽입, 위급상황 탐지(무호흡), 의료기기 통제, 오작동 시 상해 |
| 의료기기 정의 4가지 목적 명시 | 의료기기법(법률 제21263호) 제2조제1항 | "질병 진단", "치료", "경감", "처치", "예방", "상해 보정", "구조·기능 변형" |
| type = DOCTOR_REPLACEMENT | 의사 진단·처방 대체는 무조건 의료행위 | "AI가 진단합니다", "처방 추천", "의사 상담 대체" |
| weight = 5 AND type = DISEASE | 위해도 최고 + 질병 직접 언급 | "암 진단", "심근경색 예측", "당뇨 치료 보조" |

> **CONTEXT_CHECK 전환 조건**: weight 3~4이더라도 사용목적 표현이 "건강한 생활방식·습관 유도"에 한정되고, 치료법·피드백을 제공하지 않으면 관리자 판단으로 CONTEXT_CHECK로 낮출 수 있음. 근거: 지침서-0091-03 **Ⅲ.나(의사결정 흐름도) + Ⅳ.2.나**(만성질환 의료정보 제공용) 예외 조항.

#### Stage B — gate_matrix

```json
{
  "data_type": "라이프스타일 | 생체지표",
  "acquire_method": "수동입력 | 기기연동 | OS연동 | null",
  "function_type": "단순기록 | 비교·추이분석 | 수치예측·진단",
  "verdict": "PASS | CONDITIONAL | FAIL",
  "exemption_note": "",
  "avoidance_redesign": "",
  "avoidance_certification": "",
  "risk_code": "",
  "priority": 0,
  "legal_basis": {"document_id": "", "article": "", "quote": ""}
}
```
- function_type은 닫힌 3종 지정 목록(단순기록/비교·추이분석/수치예측·진단) 중에서만 분류 — 근거: 모바일 의료용 앱 안전관리 지침 Ⅲ.2(의료기기 해당 5유형)/Ⅲ.3(비해당 6유형)
- verdict는 닫힌 3종(PASS/CONDITIONAL/FAIL) — 6개 data_type×function_type 조합(2026-07-12: 라이프스타일/생체지표 2종 기준)의 확정 시드데이터는 §3.2 참조. LLM은 이 표에서 조회만 하고 신규 조합 발견 시에만 판단 수행
- acquire_method는 매트릭스 축이 아니라 침습적 하드체크 오버라이드용 보조 필드(§3.2 참조) — 대부분의 rule row는 null로 둠
- avoidance_redesign/avoidance_certification은 verdict=FAIL row에서만 채움(2026-07-26 복원, §3.2 참조)

#### Stage C — correction_rules

> ⚠️ **두 생성 경로 병행 (2026-08-13~)**: 아래는 **경로 ②(LLM 추출, 문서 청크 기반)** 스키마다.
> 이와 별개로 **경로 ①(코드 조합 생성, LLM 호출 없음)** 이 `verb_substitution`(§3.3.3) ×
> gate_keywords(DISEASE) 조합으로 risky_text/safe_text/regulatory_score를 직접 채운다
> (`scripts/generate_correction_rules.py`). 경로 ①은 advertising_score를 산출하지 않고
> 항상 0으로 둔다 — 광고 표현 판단은 실제 문서(별표7 신호어)가 있어야 하므로 경로 ②
> 전용이다. 두 경로 모두 같은 `correction_rules` 테이블에 적재되며, 경로 ①은
> `auto_validate`를 거치지 않는다(원문 인용이 없는 생성물이라 인용 대조가 성립하지 않음
> — gate_matrix 6칸 시드와 같은 처리). 아래는 경로 ②만의 스키마다.
>
> **LLM 추출 대상은 risky_text/safe_text/advertising_score뿐**. regulatory_score는 아래 [5]~[6] 사이 파생 계산 단계에서 gate_keywords 조회로 채움 (LLM 출력 스키마에서 제외). privacy_score는 오프라인 산출 대상이 아님(§3.3.2 — 런타임 계산).

```json
{
  "risky_text": "",
  "safe_text": "",
  "advertising_score": 0,
  "advertising_basis": {"attachment7_item": 0, "document_id": "", "quote": ""},
  "legal_basis": {"document_id": "", "article": "", "quote": ""}
}
```
- 신호어: HIGH=["금지","표방 불가","허가 없이","치료·진단·예방"], MID=["주의","오인 우려","과장"], LOW=["허용","대체 표현","웰니스 범위"]
- advertising_score 신호어(별표7 근거): 3점=["거짓","과대광고","확실히 보증","최고","최상","체험담","구매쇄도"], 2점=["오인","보증하는 것으로","지정·공인·추천"], 1점=["암시하는","사용 전후 비교"]

**[5]~[6] 사이 파생 계산 단계 (LLM 미개입)**

```json
{
  "regulatory_score": "gate_keywords 조회: weight=5|FAIL_CONFIRMED→3, weight=3~4→2, weight=1~2→1, 매칭없음→0",
  "_privacy_score": "2026-07-28 오프라인 산출 대상에서 제외 — 사용자 입력에서 결정되는 값이라 런타임(판정엔진)에서 계산한다. §3.3.2 참조",
  "derived_from_keyword_id": "regulatory_score 산출에 사용된 gate_keywords.keyword_id"
}
```

#### (구) Stage D — bm_mapping (2026-07-20부로 완전 폐지)

> bm_mapping은 더 이상 LLM 추출 대상도, 별도 적재 대상도 아니다. competitors 기반 VIEW로 실시간 계산됨 — 정의는 §3.6 참조. Stage는 A~C만 존재.

> data_difficulty / collection_difficulty / competitors / funding_programs는 본 LLM 파이프라인(§4) 대상이 아님 (고정표 또는 사전구축 수집). bm_mapping은 애초에 파이프라인이 필요 없는 VIEW (§3.6)

### 4.3 프롬프트 템플릿

```
[문서]: {pdf_text_chunk}
[Stage]: {stage_name}
[추출 스키마]: {json_schema}
[판단 축]: {axes}
[신호어]: FAIL={fail_words}, PASS={pass_words}, CONDITIONAL={cond_words}

[지시사항]
1. 위 문서에서 {stage} 룰을 추출하라.
2. data_type/function_type/category 등은 반드시 [지정 목록] 중에서만 선택.
3. legal_basis.quote는 입력 문서의 원문을 직접 인용 (재구성 금지).
4. 룰 판정값(verdict/risk_code 등)을 임의로 변경하지 말 것 — 추출만 수행, 최종 판정은 시스템이 결정.
5. 추출할 룰이 없으면 빈 배열([])을 반환.
6. 출력은 JSON 배열만, 설명 텍스트 금지.
```

> PREP §9.4 LLM 출력 통제 원칙(JSON Schema 구조화 출력, 룰 판정값 수정 금지 프롬프트, evidence_status: insufficient 처리)을 추출 파이프라인에도 동일 적용.

### 4.4 자동 검증 규칙

| 검증 항목 | 내용 | 실패 시 처리 |
|---|---|---|
| 필수 필드 존재 | 스키마 정의 필드 누락 여부. **단 Stage C `advertising_basis.quote`는 `advertising_score=0`(해당 없음)일 때 면제** — 인용할 별표7 항목이 존재하지 않는데 무조건 요구하면 정상 케이스(예: "조현병 조제")까지 전량 필드누락으로 탈락한다(2026-08-14 실전 발견) | 검수 큐, "필드누락" |
| enum 값 검증 | verdict/category/data_type 등이 허용값 내인지 | 검수 큐, "값오류" |
| 인용 검증 | legal_basis.quote가 원문 청크에 실존하는지. **공백을 제거한 뒤 비교한다** — pypdf가 2단 조판 법령 PDF를 뽑을 때 단어 중간에 줄바꿈을 넣어(예: "성생\n활") 원문을 정확히 인용해도 그대로 비교하면 전량 인용미확인으로 걸러진다(의료법 12회·의료기기법 9회 발생 확인, 2026-08-14). 별표7은 반대로 공백이 소실되므로 양쪽 다 공백 제거 후 비교가 필요하다. **경로 ①(코드 조합 생성)은 이 검증 자체를 거치지 않는다** | 검수 큐, "인용미확인" |
| 중복 검사 | 동일/유사 keyword·risky_text 존재 여부 | "중복후보" 병합 제안 |
| 점수 범위 검증 | axis_score, weight 등이 signal_config 범위 내인지 | 검수 큐 |
| 파생값 일치 검증 | regulatory_score가 gate_keywords.weight 매핑 규칙과 일치하는지 (§3.3 산출식 참조). ※ privacy_score는 런타임 계산이라 본 검증 대상 아님 | 검수 큐, "파생값불일치" |

### 4.5 관리자 검수 인터페이스 (PREP ADMIN01, /admin/rules 화면)

- 좌측: 원문 청크 + 인용구 하이라이트 / 우측: 추출 JSON 필드 편집 폼
- 검수자 수정 가능 필드: verdict, axis_score, risk_code, legal_basis.quote, safe_text
- "검수·배포"(POST /admin/rule-drafts/{id}/publish) 시 신규 rule_versions.status=active, 해당 Stage의 기존 active 버전을 승계(행 복사)한 뒤 deprecated 처리(누적 발행 B안, §3.1 참조 — 다른 Stage·다른 문서의 active는 영향받지 않음)

### 4.6 법령 개정 대응

```
국회의안정보시스템/공공데이터포털 API → 개정 감지
   ↓ 해당 PDF만 재투입 (POST /admin/rule-documents)
   ↓ 동일 Stage 파이프라인 재실행 → 신규 rule_version(draft)
   ↓ 기존 active 버전과 diff 비교 → 변경분만 검수자에게 제시
   ↓ 승인 시 publish → 신규 active. 해당 Stage의 구버전 active는 승계(행 복사) 후
     deprecated (누적 발행 B안, §3.1 — 다른 Stage·다른 문서의 active는 영향 없음)
```

---

## 5. RAG 파이프라인 설계 (PREP §9.2, 결정4)

### 5.1 인덱싱

```
법령/가이드 PDF
   ↓ 텍스트 추출
   ↓ 조문/제목 단위 정리 (evidence_chunks.article_number, section_path)
   ↓ 메타데이터 부여 (evidence_documents: doc_type, category_tag, effective_date, version)
   ↓ Embedding (OpenAI Embeddings)
   ↓ ChromaDB 적재 (chroma_vector_id ↔ evidence_chunks 동기화)
```

### 5.2 검색 (호출 방식: 항상 호출, 근거 전용 — 결정4)

```
판정 결과 → 검색 질의 생성
   ↓ 벡터·키워드 하이브리드 검색 (초기: 벡터 단독 → 확장: BM25+Vector+RRF+Re-ranker)
   ↓ 법령·기준일·카테고리 필터 (evidence_documents 메타)
   ↓ 최종 근거 chunk 선정
   ↓ 설명 생성 LLM → "관련 사례/근거" 섹션 출력 (판정 결과에는 영향 없음)
```

**검색 결과 개수 확정 (2026-07-26)**

| 용도 | 개수 | 근거 |
|---|---|---|
| 조문 근거 (ID 기반 조회) | **전량** | 룰 테이블의 `legal_basis_doc`/`legal_basis_article`이 이미 어느 조문인지 지정하므로, RAG는 해당 chunk 원문을 가져오기만 한다. 검색·판단이 없어 제한할 이유가 없고 매번 동일한 결과가 나온다 |
| 유사 사례 (벡터 검색) | **top-3** | 사례가 3개를 넘으면 리포트가 길어지고, 결과 수가 늘수록 실행할 때마다 문장이 달라지는 재현성 편차도 커진다 |

- 대상: GATE/§01(규제위반·샌드박스 RAG), §04(BM학술·IR RAG)
- 벡터DB: ChromaDB (MVP), 임베딩: OpenAI Embeddings (MVP) → 확장 시 하이브리드
- 근거 없을 시 `evidence_status: insufficient` 반환, 판정은 유지 (PREP §9.4, §14)

---

## 6. 판정 로직 ↔ DB 연동

### 6.1 모듈별 매핑 (PREP §6, §8 기준)

| PREP 모듈 | 요구사항ID | 조회 테이블 (판정) | RAG (근거) |
|---|---|---|---|
| Gate Engine | GATE01_ENG01~02 | gate_keywords, gate_matrix | evidence_documents/chunks (규제위반·샌드박스) |
| Regulatory | IDEA01_TAB01 | correction_rules, signal_config | 〃 |
| Data Feasibility | IDEA01_TAB02 | data_difficulty, collection_difficulty | - |
| Market | IDEA01_TAB03 | competitors, competitor_tier_score | - |
| BM | IDEA01_TAB04 | bm_mapping (VIEW) | - (evidence 연결은 MVP 범위 외, §3.6 참조) |
| Category Classifier | IDEA01_CLS01 | (별도 모델, 본 DB와 무관) | - |
| Funding | FUND01_MCH01 | funding_programs | - |

### 6.2 API 연동 (PREP §11 발췌 — 룰 구축 관련)

| Method | Endpoint | 본 설계서 연관 |
|---|---|---|
| POST | /admin/rule-documents | §4.1 [1] 법령 PDF 업로드 |
| POST | /admin/rule-drafts/{id}/publish | §4.5 검수·배포 → rule_versions 활성화 |
| POST | /analysis-sessions/{id}/assess | §6.1 모듈들이 룰 테이블 조회 |

### 6.3 사전구축 DB 수집 (competitors, funding_programs)

| 테이블 | 수집 방식 | 갱신 주기 |
|---|---|---|
| competitors | 수동조사(1단계, 시드 90건, 5인 역할분담) + 정기크롤링(2단계), tier/core_tags/sub_tags/bm_pattern 태깅 | 월 1회 |
| funding_programs | K-Startup API (범위 확인 필요, PREP §20) + 수동 | 수시 |

> competitors 1단계 시드: category_1(질병축 7종: 수면/정신건강/운동/식단/만성질환/여성건강/미용, 유전자는 시장 사례 부족으로 제외)별 9~18개씩 총 90개. 5인 역할분담(수면/운동/식단 각 1인 18개, 정신건강+만성질환 1인 9+9개, 여성건강+미용 1인 9+9개) 기준. 국내는 원스토어·앱스토어·플레이스토어 + 플랫텀·더브이씨 등 스타트업 미디어, 해외는 앱스토어 랭킹 기준으로 수동 리서치하여 core_tags/sub_tags/bm_pattern과 함께 category_2(기능축)도 태깅. tier는 다운로드수·MAU·투자단계(시리즈 여부)로 판정. 2단계는 app-store-scraper/google-play-scraper 등으로 월 1회 자동 크롤링해 신규 경쟁사 탐지·순위 변동을 추적(스토어 이용약관상 허용범위 사전 확인 필요).

> bm_mapping은 별도 수집·적재 파이프라인이 없다 — competitors에 bm_pattern까지 채워지는 즉시 §3.6의 VIEW로 조회 가능 (구 §6.4 자동 집계 파이프라인은 2026-07-20 VIEW 전환으로 폐지).

### 6.4 BM 모듈 조회 로직 (신설, 2026-07-20, ⚠️ 제안 — 팀 확정 필요)

> 본 절은 db_구축_설계서.md의 "DB에 무엇을 채우는가" 범위를 넘어 "판정 엔진이 그 데이터를 어떻게 조회하는가"까지 다룬다는 점에서 §1.1 원칙의 예외다. bm_mapping이 파이프라인 없는 VIEW인 만큼, BM 모듈 구현 시 참고할 조회 로직을 최소한으로 명시해 둔다.

**입력**: category_1, category_2(카테고리 분류 AI 모델 출력값 — 모델이 2축을 각각 출력하도록 되어 있는지 「AI 모델 설계서」에서 확인 필요), target, service_type(아이디어 입력 Step2·Step3 값)

**기본 조회**

```sql
SELECT bm_pattern, frequency_score, frequency_score_global,
       precedent_level, contributing_competitor_ids
FROM bm_mapping
WHERE category_1 = :c1 AND category_2 = :c2
  AND target = :target AND service_type = :service_type
ORDER BY frequency_score DESC
LIMIT 2;
```

**완화(fallback) 전략**: bm_mapping은 competitors에 실제로 존재하는 조합만 반환하는 VIEW라, 4개 조건이 모두 일치하는 행이 없으면 0건이 나올 수 있다(경쟁사 80~100건으로 모든 조합을 커버할 수 없음). 아래 단계로 조건을 순차적으로 완화한다.

| 단계 | 조건 | 결과 태그 |
|---|---|---|
| 1 | category_1 + category_2 + target + service_type 전부 일치 | exact_match |
| 2 | service_type 조건 제거, 나머지 3개만 일치 | relaxed_service_type |
| 3 | category_1 + category_2만 일치 | relaxed_category_only |
| 4 | 그래도 0건 | insufficient_data |

```python
async def get_bm_recommendation(db, category_1: str, category_2: str, target: str, service_type: str):
    query = """
        SELECT bm_pattern, frequency_score, frequency_score_global,
               precedent_level, contributing_competitor_ids
        FROM bm_mapping
        WHERE category_1 = :c1 AND category_2 = :c2
          AND target = :target AND service_type = :service_type
        ORDER BY frequency_score DESC
        LIMIT 2
    """
    return await db.fetch_all(query, {"c1": category_1, "c2": category_2,
                                        "target": target, "service_type": service_type})

async def get_bm_recommendation_with_fallback(db, c1: str, c2: str, target: str, service_type: str):
    result = await get_bm_recommendation(db, c1, c2, target, service_type)
    if result:
        return result, "exact_match"

    result = await query_bm_mapping(db, category_1=c1, category_2=c2, target=target)  # service_type 제거
    if result:
        return result, "relaxed_service_type"

    result = await query_bm_mapping(db, category_1=c1, category_2=c2)  # target도 제거
    if result:
        return result, "relaxed_category_only"

    return [], "insufficient_data"
```

**결과 처리**: 완화 단계 태그를 리포트까지 같이 전달해 "정확히 일치하는 사례"와 "유사 카테고리 참고 사례"를 구분 표시한다. `insufficient_data`면 bm_pattern 추천 없이 "검증 필요"로 표시하고 수치·근거를 임의 생성하지 않는다 (프랩_기획서.pdf §7.3, PREP §9.4 원칙과 동일).

**구현 위치**: 기획서 §9 시스템 구조 기준 Rule Engine 계층(`bm_service.py` 등)에 두고, `/analysis-sessions/{id}/assess`가 GATE PASS 이후 Regulatory·Data Feasibility·Market 서비스 함수와 병렬로 호출 (§6.1, §6.2 API 연동표와 동일 패턴 — Market 모듈이 competitors를 직접 SELECT하는 것과 대응).

> ✅ **채택 확정 (2026-07-26)**: 4단계 완화 전략을 확정하고, **§3.5 경쟁 포화도 산출의 조회 범위에도 동일하게 적용**한다. 시장현실성(§03)과 BM 추천(§04)이 같은 조회 전략을 공유한다.

---

### 6.5 모듈 실행 순서 (2026-07-26 확정)

```
[입력] 서비스설명 + 수집데이터(복수) + 서비스형태
   │
   ├─→ 카테고리 분류 모델 → category_1(질병축 7종) + category_2(기능축 4종)
   ▼
[GATE]  Stage A(gate_keywords) → Stage B(gate_matrix)      ← 순차 게이트
   │
   ├── FAIL ─→ §01 규제위험도만 실행, §02~04 스킵 ─→ 부록 리포트
   ▼ PASS
[§01 규제위험도] [§02 데이터확보] [§03 시장현실성] [§04 수익구조]   ← 병렬
   │
   ▼
[조립]  종합 신호등(§6.6) → SECTION 0 → SECTION 3 종합요약      ← 순차
```

> ✅ **병렬 확정 근거**: §01~§04는 서로 입력 의존이 없고 각기 다른 테이블만 조회하므로 병렬 실행이 가능하다. GATE만 선행 게이트 역할을 한다. §1.1·§2.1 아키텍처 도식의 `GATE → Regulatory → Data Feasibility → Market → BM` 화살표는 **논리적 나열이지 실행 순서가 아니다**(이 문구로 인해 순차 실행으로 오해될 소지가 있어 명시).
>
> 결과 리포트 §2-2의 "🔗 타 섹션 연결 안내"(의료기기 연동 필요→§01 GATE, 민감정보 수집→§01 규제위험도)는 §02가 §01 결과를 실행 시점에 참조하는 것이 아니라, **조립 단계에서 조건부 문구를 덧붙이는 것**이므로 병렬 실행을 막지 않는다.
>
> **GATE FAIL 분기**: FAIL이어도 리포트를 종료하지 않는다. §01 규제위험도는 끝까지 실행해 판단근거 4줄·Before→After 교정카드·다음 액션을 제공하고, §02~04만 스킵한다(결과 리포트 명세 §부록). SECTION 0에서는 규제위험도만 활성, 나머지 지표는 비활성 처리. GATE FAIL 시 제시할 회피 방향 2가지는 §3.2의 `avoidance_redesign`/`avoidance_certification`에서 조회한다.

### 6.6 종합 신호등 산출 (2026-07-26 확정, 결정3)

SECTION 0 최상단의 종합 판정 규칙.

```
빨강 = 규제위험도 '높음' OR 데이터확보 '어려움'

초록 = 규제위험도 '낮음'
       AND 데이터확보 IN ('쉬움','보통')
       AND 시장현실성 '높음'
       AND BM추천 존재 (§6.4 match_level != 'insufficient_data')

노랑 = 빨강·초록 어디에도 해당하지 않을 때
```

> ✅ **"수익 높음" 조건을 "BM추천 존재"로 대체한 이유 (2026-07-26)**: 결정3 원안은 `(시장 OR 수익 중 하나 높음)`이었으나, 시장현실성과 수익 선례는 **동일한 데이터(경쟁사 수)에서 파생되는 상관 지표**다. 경쟁사가 적으면 시장=높음/수익 선례=적음, 경쟁사가 많으면 시장=낮음/수익 선례=많음으로 갈리므로 OR 조건이 거의 항상 참이 되어 조건이 무력화된다.
>
> 또한 결과 리포트 명세 §2-4는 수익구조를 "BM 추천만, **지표 판단 없음**"으로 규정해 높/중/낮 등급 자체가 존재하지 않는다. 따라서 수익 축은 등급이 아니라 **"근거를 댈 수 있는가"라는 안전장치**로 재정의한다 — 경쟁사 데이터가 부족해 BM 추천조차 못 내는 경우(`insufficient_data`)에는 초록을 부여하지 않는다. 결정3의 원래 의도(수익 근거가 있어야 초록)는 유지하면서 상관관계 함정은 회피한다.
>
> **GATE FAIL 시**: 종합 신호등은 규제위험도만으로 판정하고, 데이터확보·시장현실성은 비활성 처리한다(§6.5 분기 참조).

### 6.7 LLM 호출 구조 (2026-07-26 확정)

> ✅ **"LLM 호출 3회 고정" 제약 폐기**: 호출 **횟수**는 비용·지연의 실제 결정 변수가 아니다(비용은 토큰량, 지연은 병렬화 여부가 좌우). 횟수를 고정하는 대신 아래 3가지를 관리한다.

| 단계 | 호출 | 실행 | 산출물 |
|---|---|---|---|
| 1단계 | ① 표현 대체어 생성 | 병렬 | 리포트 §2-1 Before→After 카드 |
| | ② 차별화 포인트 제안 | 병렬 | 리포트 §2-3 |
| | ③ BM 카드 4줄 요약 | 병렬 | 리포트 §2-4 |
| 2단계 | ④ 종합 요약 | 순차(1단계 결과 필요) | 리포트 SECTION 3 |
| | ⑤ 한 줄 총평 | 순차(1단계 결과 필요) | 리포트 SECTION 0 |

**관리 원칙 3가지**

1. **LLM 불가침 값 고정** — 판정 결과·축별 점수·신호등 등급은 LLM이 생성하거나 변경할 수 없다. 코드가 산출한 값을 프롬프트에 주입만 하고, 출력 스키마에서 해당 필드를 제외해 구조적으로 차단한다(Stage B의 "LLM은 data_type/function_type만 판단, verdict는 코드가 표 조회로 채움" 패턴과 동일).
2. **호출 간 모순 방지** — 2단계 호출(④⑤)에는 1단계 결과를 전부 주입한다. 미주입 시 "§2-3은 경쟁 치열이라 썼는데 SECTION 0 총평은 블루오션"과 같은 상호 모순이 발생할 수 있다.
3. **병렬/순차 구분** — 위 표대로 1단계 3개는 병렬, 2단계 2개는 후행. 총 지연은 `max(①②③) + max(④⑤)`.

### 6.8 검색 트렌드 임계값 산출 (2026-07-26 확정)

리포트 §2-3「시장 현실성」판단근거 ①의 국내 수요 판정에 쓰는 임계값. 네이버 데이터랩 검색어트렌드 API 기반.

**산출 절차 (4단계)**

```
[1단계] 성장 업종 10개 + 정체/하락 업종 10개 선정
[2단계] 각 업종 12개월 검색지수로 최소제곱법 1차함수 y = ax + b 산출, 기울기(a) 추출
[3단계] 두 그룹 기울기 분포의 교차점 = 임계값
[4단계] 성장 그룹 1사분위수로 최종 검증
        → 교차점이 Q1보다 높으면 성장 업종 하위 25%를 놓치는 것이므로 하향 조정
```

**판별 기준**

| 조건 | 판정 |
|---|---|
| 기울기 > 임계값 | 급성장 |
| 0 < 기울기 < 임계값 | 완만 |
| 기울기 < 0 | 하락 |

> ✅ **별도 정규화 불필요**: 네이버 데이터랩 API는 절대 검색량이 아니라 **검색지수(상대값)**를 반환하므로 기울기를 다시 정규화할 필요가 없다(검토 과정에서 "12개월 평균으로 나눠 %화" 안이 제기되었으나 불필요한 것으로 확인).
>
> ✅ **캘리브레이션 부담 작음**: 데이터랩 API는 한 호출에 검색어 그룹 5개(그룹당 검색어 최대 20개)까지 받으므로, 20개 업종이면 **4회 호출**로 데이터 수집이 끝난다.

**보완 사항 4가지 (필수 반영)**

| # | 항목 | 내용 |
|---|---|---|
| ① | **앵커 키워드** | 데이터랩 정규화는 한 호출 안에서만 유효하다. 4회로 나눠 호출하면 배치마다 스케일이 리셋되어 기울기 비교가 왜곡된다. 모든 배치에 공통 앵커 키워드(계절성이 적고 검색량이 안정적인 것, 예: "건강")를 1개씩 포함하고 그 값의 비율로 배치 간 스케일을 보정한다 |
| ② | **계절성 보정** | 12개월 단일 사이클로는 계절성과 성장을 구분할 수 없다. "다이어트"를 1월에 조사하면 급성장, 9월에 조사하면 하락이 된다 — 같은 아이디어인데 리포트를 뽑은 달에 따라 판정이 뒤집히는 신뢰도 문제. **24개월을 수집해 전년 동월 대비를 보조 지표로 병행** 확인 |
| ③ | **R² 하한선 0.3** | 기울기만 보면 변동이 심한 데이터도 추세로 오인한다. `R² < 0.3`이면 "변동성 큼 — 판별 불가"로 처리하고 급성장/하락 판정을 부여하지 않는다 (§6.4 `insufficient_data` 원칙과 동일) |
| ④ | **저검색량 제외** | 데이터랩은 검색량이 일정 수준 미만이면 0을 반환하거나 부정확하고, 지수화 과정에서 노이즈가 증폭된다. **12개월 중 0이 3개월 이상이면 "데이터 부족"**으로 처리 |

**업종 선정 기준**: 임계값을 사실상 좌우하는 것이 20개 업종 선정이므로 근거를 문서로 남긴다. **웰니스 인접 업종으로 한정**할 것 — 반도체·부동산처럼 성격이 다른 산업은 검색 패턴 자체가 달라 임계값이 웰니스 시장에 맞지 않게 산출된다. 각 업종을 성장/정체로 분류한 사유도 함께 기록한다.

**저장 위치**: `signal_config`는 축이 "의료행위표현/개인정보민감도/광고표현위험" 3개로 성격이 고정된 테이블이므로, 트렌드 임계값은 **별도 설정 테이블 또는 코드 상수**로 둔다.

---

## 7. 구축 우선순위 및 일정 (PREP §19 개발우선순위와 정렬)

| 순서 | 작업 | PREP 대응 | 산출물 |
|---|---|---|---|
| 1 | rule_versions + 핵심 룰 테이블 스키마 확정 | PREP #1 | schema.sql |
| 2 | Stage A·B(gate_keywords/gate_matrix) 추출·검수·적재 | PREP #2 (GATE·규제) | gate 데이터 |
| 3 | Stage C(correction_rules)+signal_config 적재 | PREP #2 | 규제판정 데이터 |
| 4 | data_difficulty/collection_difficulty 고정표 입력 | PREP #3 | §03 데이터 |
| 5 | evidence_documents/chunks + ChromaDB 인덱싱 (RAG, MVP) | PREP §9.2 | RAG 컬렉션 |
| 6 | competitors, competitor_tier_score 적재 | PREP #4 (시장) | §02 데이터 |
| 7 | bm_mapping VIEW 생성 (§3.6, competitors 데이터만 있으면 즉시 사용 가능) | PREP #4 (BM) | §04 데이터 |
| 8 | funding_programs 적재 | PREP #7 | 지원사업 데이터 |

---

## 8. 운영 및 유지보수

### 8.1 데이터 보존 정책과의 정합성

PREP §10.4에 따라 사용자 입력·분석 결과는 본 DB에 저장되지 않는다. 본 설계서가 다루는 테이블(rule_versions, gate_*, correction_rules, data_difficulty, collection_difficulty, competitors, evidence_*, funding_programs)은 모두 **기준 데이터**로 영구 저장 대상이며 PREP §10.4 삭제 정책의 영향을 받지 않는다. bm_mapping은 저장 테이블이 아닌 VIEW이므로 이 목록에서 제외 — competitors가 삭제 정책의 영향을 받지 않는 한 bm_mapping 조회 결과도 항상 유효함 (§3.6).

### 8.2 미결정 항목

- D 누락 2개 테이블 (db_구축_계획서_V0.3 결정6) — gate_matrix/competitors 외 추가 테이블 필요 여부 확인
- 관리자 룰 추출 LLM 모델 선정 (Claude vs OpenAI, PREP §20)
- ~~competitor_tier_score, signal_config, 서비스 유사도 가중치(§3.5)의 구체 수치 합의~~ **(2026-07-26 해소)** — signal_config는 축별 0/1~2/3 임계값으로 확정(§3.3.1), 유사도 가중치는 포화도 개수 기반 전환으로 폐기, competitor_tier_score는 플래그 용도로만 남아 캘리브레이션 불필요(§3.5)
- ~~**(2026-07-20 추가) BM 모듈 완화(fallback) 전략 확정 필요**~~ **(2026-07-26 채택 확정)** — 4단계 완화 로직(exact_match→relaxed_service_type→relaxed_category_only→insufficient_data)을 확정하고 §3.5 경쟁 포화도 조회 범위에도 공통 적용 (§6.4)
- **(2026-07-20 초안 확정, 팀 승인 대기) bm_mapping.bm_pattern 서브셋** — Business Model Navigator 공식 목록(businessmodelnavigator.com/explore, 원저 Gassmann·Frankenberger·Csik, 원본 55패턴+확장 5패턴=60패턴) 중 웰니스향 12개 선정: Freemium(프리미엄), Subscription(구독형), Add-on(애드온), Lock-in(락인), Two-sided Market(양면시장), Pay Per Use(사용량과금), Sensor As A Service(센서서비스), Leverage Customer Data(데이터활용), Digitization(디지털전환), Self-service(셀프서비스), Performance-based Contracting(성과기반계약), Razor And Blade(레이저블레이드). §3.5 competitors.bm_pattern, §3.6 bm_mapping.bm_pattern의 닫힌 enum 후보로 사용. 팀 회의에서 최종 승인 필요
- **(2026-07-20 추가) competitors 갱신 주기·담당자 지정** — 월 1회 갱신은 정했으나 담당자 미지정 (프랩_기획서.pdf §12 데이터 노후화 리스크 대응)
- **(2026-07-20 추가 → 2026-07-26 결론) data_type 범위와 UI 불일치** — 프랩_디자인_프로토타입.pdf Step2에는 수집데이터 옵션으로 '진료·병력'이 이미 존재하나, 본 설계서는 임상·진료를 2차 구축으로 제외함(§3.2). **2026-07-26 D축을 2종으로 확정**하면서 난이도 축에서도 임상·진료를 쓰지 않게 되어, UI에서 해당 옵션을 제거하거나 선택 시 "1차 구축 범위 외" 안내를 노출하는 방향으로 결론. 디자인 담당자에게 전달 필요(잔여 액션)
- **(2026-07-26 추가) 리포트 §2-2 🔴 분기 문구 수정 필요** — 결과 리포트 명세가 신호등 빨강 사유를 "임상·진료 데이터 등 직접 수집 불가"로 서술하나, 임상·진료 제외로 이 예시가 성립하지 않음. "생체지표를 기기연동·기관연동으로 확보해야 하는 경우"로 교체할 것 (§3.4)
- ~~🔴 의료기기법 시행규칙 별표7 본문·의료기기법 제24조 미확보~~ **(2026-07-28 합의 완료, 확보 진행 중)** — RAG 담당에 최우선 확보 요청 전달 완료. `advertising_score` 척도가 별표7 18개 항목 번호에 100% 의존한다는 근거를 함께 전달했고 필요성에 합의. **문서 실물 확보 여부는 계속 추적 필요**(확보 전까지 SECTION 2-1 광고 판단근거에 조문 표시 불가)
- ~~evidence_documents/chunks 스키마 확장 반영 대기~~ → **일부 확정**: `section_id` 표기 규칙은 2026-07-28 확정(§1.5.1). 나머지 스키마 항목(stable string ID, `law_id`, `source_subtype`, `usage_scope` 등)은 팀 합의 후 §3.7 전면 교체 예정
- ~~section_id 표기 정규화 규칙 합의 필요~~ **(2026-07-28 확정)** — 원문 목차 표기 + 정규화 규칙(로마숫자 ASCII 통일 / 마침표 구분자 / 공백 제거 / `별표7.제8호` 형식) 채택. **§1.5.1에 규칙 명문화 완료.** 룰베이스 `legal_basis_article`과 RAG `section_id` 양쪽에 동일 적용
- ~~별표7 chunk 분할 단위~~ **(2026-07-28 확정)** — 항목 번호 단위(제1호~제18호) 분할로 합의. §1.5.1 참조
- **(2026-07-26 추가) 트렌드 임계값 20개 업종 캘리브레이션 미수행** — §6.8에 산출 절차·보완사항은 확정했으나 실제 업종 선정과 임계값 산출은 미착수. 앵커 키워드 선정도 함께 필요
- **(2026-07-26 추가) 네이버 데이터랩·구글 트렌드 API 이용조건 미확인** — 데이터랩 오픈API 일일 호출 한도, 구글 트렌드 공식 API 제공 여부·이용약관 확인 필요(비공식 라이브러리 사용 시 차단 위험). 외부 API 호출 캐시 정책(24시간 권장)도 미확정
- **(2026-08-09 추가) MFDS-G-2026-05 RAG 적재 요청** — 국가법령정보센터 조문본(34쪽, 고시 제2026-6호)을 `usage_scope=RAG`로 적재 요청. 기존 행정예고본(91쪽)은 폐기하고 교체할 것. 제8조·제33조가 `avoidance_certification` 안내의 근거 조문이라 원문 표시가 필요함 (§1.5.2)
- **(2026-07-28 갱신) 약사법·보건복지부 비의료 건강관리 서비스 가이드라인 수집 요청 완료** — RAG 담당에 추가 수집 요청 전달·합의 완료. 확보 시 §1.5의 LAW-PHARM-01·MOHW-G-2026-01 서지정보(법률번호·시행일)를 채울 것
- **(2026-07-26 추가) 약사법 서지정보 미확보 + 약무 키워드 시딩 필요** — §1.5에 LAW-PHARM-01(약사법)을 추가했으나 법률 번호·시행일 미확인. 또한 약무행위를 regulatory_score에 흡수하기로 확정했으므로, gate_keywords에 약무 키워드(처방·조제·복약지도 등)를 `type=PROHIBITED_ACTION`으로 시딩해야 실제로 점수에 반영됨 (Stage A 추가 작업)
- ~~acquire_method 침습적 하드체크 대상 목록 미확정~~ **(2026-08-09 확정, 2026-08-13 구현 완료)** — 판단 기준을 **"각질층을 관통하는가"**로 통일. 근거: 지침서-0091-03 고위해도 2번 "피부 뚫어 혈액 채취, 체내 삽입". ① CGM(연속혈당측정) = 침습(센서 피하 삽입) ② 채혈형 기기 = 침습 ③ 피부 부착형 패치 = **관통 여부로 분기**(단순 부착형은 비침습 / 마이크로니들 등 관통형은 침습). "패치"를 단어 단위로 일괄 매칭하지 말고 관통 여부를 판단 기준으로 프롬프트에 명시할 것.
  >
  > **구현 상세 (2026-08-13, 2026-08-14 키워드 목록 갱신)**:
  > - 코드 측 교차확인 키워드 **13개**: 침습·CGM·연속혈당·채혈·**채취**·란셋·마이크로니들·미세침·피하삽입·체내삽입·이식형·삽입형·천자. "패치"는 의도적으로 미포함(위 관통 여부 분기 사유). "채취"는 2026-08-14 원문 재대조로 추가 — 고위해도 예시 "피부를 침투하여 혈액을 채취하는 제품"이 기존 목록(채혈·란셋 등)에 걸리지 않았다. "채혈"보다 넓어 타액·소변 채취 등 비침습 케이스까지 걸릴 수 있으나, 이 목록은 FAIL을 직접 만들지 않고 안전장치(아래)를 거치므로 과대 매칭의 최악 결과는 검수 대기에 그친다.
  > - 부정 표현 처리: "비침습"/"무침습"에 "침습"이, "비이식형"/"비삽입형"에 "이식형"/"삽입형"이 부분 문자열로 들어있어 정반대 판정이 나는 함정이 있어, 매칭 전에 부정 표현을 먼저 제거한다. 최초 구현(2026-08-13)은 "비침습/무침습"만 제거했으나, 원문에 "비침습적 및 비이식형 방법으로 측정한 혈압값"이 실제로 등장함을 2026-08-14 확인해 이식형/삽입형도 같은 함정이 있음을 발견 — 부정 표현 제거 범위를 침습·이식·삽입 공통으로 확장.
  > - 이 키워드 목록은 LLM 판정을 대체하지 않는다 — **판정 주체는 LLM**이고, 코드 목록은 재현율 보강용 교차확인이다. 청크 전체를 훑는 방식이라 정밀도가 낮다(무관한 내용까지 걸릴 수 있음).
  > - **3분기 처리**: ① 생체지표+기기연동+LLM이 침습 판정 → **FAIL 하드 오버라이드**(function_type·6칸 표 무시) ② 생체지표+기기연동인데 코드는 침습 신호를 잡았고 LLM은 아니라고 한 **불일치** → FAIL로 확정하지 않고 **CONDITIONAL(검수 대기)**로 뺀다(정밀도가 낮은 코드 신호 하나만으로 FAIL을 주지 않기 위한 안전장치) ③ 그 외 → 6칸 표 조회.
  > - 실전 검증: 모바일 의료용 앱 지침 투입 중 ②(CONDITIONAL 안전장치)가 실제로 1건 발동 — LLM이 "혈압 수집·병원 송신"을 정확히 비침습으로 판단했으나, 같은 청크(9,973자, 헤딩 중복으로 대형화)에 CGM 관련 서술이 섞여 있어 코드 신호와 충돌했다. 설계대로 CONDITIONAL로 빠져 오탐을 FAIL로 확정하지 않았다.
- ~~(구) acquire_method 침습적 하드체크 대상 목록 미확정~~ — §3.2에 acquire_method 필드는 복원했으나, "어떤 data_type+키워드 조합이 침습적으로 간주되는지"(구 룰베이스 구축방안 예시: 혈당 CGM) 구체 목록은 아직 없음. data_type이 2종으로 추상화된 이후라 개별 사례(CGM 등) 재정의 필요 — gate_keywords 고위해도 5요소 항목과 연계해 확정할 것
- **(2026-07-26 추가) avoidance_redesign/avoidance_certification 실제 문구 작성 주체 미지정** — 필드는 복원했으나 verdict=FAIL row마다 이 문구를 누가(관리자 검수 vs LLM 초안 생성) 채우는지 프로세스 미정. §4 LLM 추출 파이프라인에 반영 필요
- 카테고리 분류 모델(Category Classifier)과 본 DB 테이블 간 category 값 매핑 표 — 별도 「AI 모델 설계서」와 연계 필요
- ~~gate_keywords.data_type_focus ↔ gate_matrix.data_type 이중 체계 정리~~ **(2026-07-05 해결 완료)** — data_type_focus는 포맷 참고용 태그로, 위험도 판단은 gate_matrix.data_type만 사용하기로 결정 (§3.2 참조)
- ~~competitors.core_tags의 data_type 4종 간 "인접" 관계 정의~~ **(2026-07-12 해소)** — data_type이 2종(라이프스타일/생체지표)으로 축소되어 "다른 data_type" 조합이 하나뿐이므로 인접 관계를 별도 정의할 필요가 없어짐 (§3.5 참조)
- **(2026-07-12 추가) 임상·진료 data_type 2차 구축 반영** — 1차 구축에서는 제외. 관련 데이터 확보 후 별도 data_type으로 재도입 시 §3.2 매핑표·§3.3 privacy_score 규칙·§3.5 competitors 유사도 기준 전부 재검토 필요
- **(2026-07-05 추가) MFDS-G-2025-02(안내서-1425-01) 원문 미검증** — 소프트웨어 안전성 등급 A/B/C, 사용목적 분류 A~H 근거를 실물로 대조한 적 없음 (§1.5 참조)
- **(2026-07-05 추가) 개인정보 보호법 시행령(대통령령 제35343호) 원문 미확보** — 제18조(민감정보의 범위) 내용은 웹 검색으로만 확인, 논문 정식 인용 전 원문 PDF 확보 필요
- ~~**(2026-08-14 추가) correction_rules 두 생성 경로 간 동사 목록 불일치**~~ **(2026-08-14 해소)** 경로 ①(코드 조합 생성, §3.3.3 `verb_substitution`)은 "예방"·"보정"을 위험 동사에서 제외했으나(웰니스판단기준 0091-03 원문이 PASS 예시로 직접 씀), 경로 ②(LLM 추출, `extract_c.py` 프롬프트)는 여전히 "치료하다, 처방하다, 예방하다, 개선하다, 완화하다, 처치하다, 보정하다"를 위험 동사 힌트로 나열하고 있었다. `extract_c.py` 프롬프트에서 예방하다·보정하다를 제거하고, 대신 웰니스판단기준 0091-03의 PASS 예시 원문을 인용하는 경고 문구를 추가해 동기화 완료
- **(2026-08-15 추가) correction_rules.derived_from_keyword_id 이력 데이터 소급 미반영** — D-12(§3.1 참조) 재연결 로직은 그 로직이 배포된 **이후에 일어나는** Stage A 재발행부터만 작동한다. 로직 도입 이전에 Stage A가 여러 차례 재발행되며(v0.10~v0.39) FK가 갱신되지 않은 채 쌓인 이력 데이터는 소급 반영되지 않는다. 배포용 데이터 추출(active 행만 SQL로 뽑아 별도 DB에 임포트 검증) 중 FK 위반으로 발견 — active `correction_rules` 104건 중 70건이 이미 deprecated된 `gate_keywords` 행을 가리키고 있었다. `gate_keywords.keyword` 텍스트가 active 계보 내에서 유일함을 확인한 뒤, keyword 텍스트 매칭으로 현재 active 키워드에 재연결하는 일회성 UPDATE를 운영 DB에 실행해 해소(2026-08-15)

---

*본 설계서는 PREP 개발설계서(2026-06-11, 개발목표일 2026-11-06) 기준으로 db_구축_계획서_V0.3의 결정사항을 갱신함. 특히 결정5의 경쟁포화도 판정 기준은 PREP §8.5 공식으로 대체됨.*