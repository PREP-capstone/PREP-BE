# RDS 백업 — 2026-10-06, 이슈 #145·#144 데이터 반영 직전

운영 RDS에 아래 변경을 적용하기 직전의 네 테이블 전체 행이다. 되돌려야 할 때 쓴다.

## 무엇이 들어 있나

| 파일 | 내용 | 행 수 |
| --- | --- | --- |
| `competitors.jsonl` | 반영 전 competitors (예시행 CP001, CP002 포함) | 101 |
| `bm_mapping.jsonl` | 반영 전 bm_mapping (2026-08-14 계산값) | 59 |
| `mvp_strategy_templates.jsonl` | 반영 전 MVP 템플릿 ("무료 표준 설문" 문구 2건 포함) | 72 |
| `gate_matrix.jsonl` | 반영 전 gate_matrix 전 버전 (활성 v0.36의 기기연동 2행 포함) | 14 |
| `applied_changes.sql` | 실제로 RDS에 실행한 SQL (단일 트랜잭션) | — |

한 줄이 한 행이고, `to_jsonb(행)`으로 뽑은 JSON이다. RDS가 PostgreSQL 18이라 로컬의 `pg_dump`(16)를
쓸 수 없어 이 형식으로 받았다.

## 적용한 변경

| 테이블 | 반영 전 | 반영 후 |
| --- | --- | --- |
| competitors | 101행 | 99행 (예시행 2개 삭제) |
| bm_mapping | 59행 | 93행 (competitors에서 재집계해 전체 교체) |
| mvp_strategy_templates | "무료 표준 설문" 2건 | "표준 설문(상업적 사용 시 유료·허가 필요)"로 수정 |
| gate_matrix (활성) | 8행 | 6행 (기기연동 2행 삭제) |

로컬 DB에도 같은 변경을 적용했다. 코드(임포터) 변경은 PR #147에 있다.

## 되돌리는 방법

테이블 하나를 반영 전 상태로 되돌리는 예시다. 파일을 임시 테이블에 올린 뒤 `jsonb_populate_record`로
원래 컬럼 형식에 맞춰 넣는다. 운영 DB에 쓰는 작업이므로 팀 확인 후 트랜잭션 안에서 실행한다.

```sql
BEGIN;
CREATE TEMP TABLE restore_rows (doc jsonb);
\copy restore_rows FROM 'bm_mapping.jsonl'
DELETE FROM bm_mapping;
INSERT INTO bm_mapping SELECT (jsonb_populate_record(NULL::bm_mapping, doc)).* FROM restore_rows;
SELECT count(*) FROM bm_mapping;  -- 59여야 한다
COMMIT;
```

- `competitors`의 예시행 2개만 되살리려면 `WHERE doc->>'competitor_id' IN ('CP001', 'CP002')`로 걸러서 넣는다.
- `gate_matrix`의 기기연동 2행만 되살리려면 `WHERE doc->>'acquire_method' = '기기연동'`으로 걸러서 넣는다
  (`rule_version_id`가 활성 버전 v0.36을 가리킨다).
- `\copy`는 JSON 안의 역슬래시를 이스케이프로 읽으므로, 값에 `\`가 있는 행이 깨지면
  `\copy ... WITH (FORMAT csv, QUOTE E'\x01', DELIMITER E'\x02')`처럼 구분자를 바꿔 올린다.
