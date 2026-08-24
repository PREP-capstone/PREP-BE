# PREP-BE
PREP SERVER

## RAG Evidence Vector Search

Postgres stores evidence document/chunk metadata. ChromaDB stores vector embeddings.

### Setup

```bash
docker compose up -d postgres redis
.venv/bin/alembic upgrade head
.venv/bin/python scripts/import_evidence_csv.py
```

### Generate embeddings

`OPENAI_API_KEY` must be configured before running embedding generation.
Embeddings are persisted to `CHROMA_PERSIST_DIRECTORY`.

```bash
.venv/bin/python scripts/embed_evidence_chunks.py --dry-run
.venv/bin/python scripts/embed_evidence_chunks.py
```

Useful options:

```bash
.venv/bin/python scripts/embed_evidence_chunks.py --document-id kr-medical-device-act-rule-annex7-20260701
.venv/bin/python scripts/embed_evidence_chunks.py --force
```

### Search

```bash
.venv/bin/python scripts/search_evidence_chunks.py "허위 과대 광고" --advertising
```

API endpoint:

```text
POST /api/v1/rag/search
```

## 카테고리 분류 모델 (STEP 1)

`category_1`(8종)·`category_2`(4종) 동시 추론(`POST /api/v1/category-classifier/predict`)은
klue/roberta-base 인코더 + 헤드 2개(category_head/function_head)로 구성된 커스텀
멀티태스크 체크포인트(`best_healthcare_model_2line`, Avg Macro F1 0.6775 — 축1
0.7033/축2 0.6518, 2026-08-23 기준, 계속 학습 중)를 로컬에서 로드한다. 체크포인트는
git에 없다(`data/models/`는 `.gitignore`) — 배치 후 `CATEGORY_MODEL_DIR`(기본값
`data/models/best_healthcare_model_2line`)이 그 경로를 가리키게 한다.

```bash
mkdir -p data/models
unzip best_healthcare_model_2line.zip -d data/models
.venv/bin/pip install -r requirements.txt
```

모델이 없어도 나머지 API는 정상 동작한다 — 이 엔드포인트만 503
`CATEGORY_MODEL_UNAVAILABLE`을 반환한다. 관련 회귀 테스트는
`@pytest.mark.ml_model`로 표시돼 있고, 모델 없이 실행하려면
`pytest -m "not ml_model"`.

⚠️ 이 모델을 다른 곳에서도 로드할 계획이면 `app/domain/category_classifier.py`
모듈 docstring의 두 함정(AutoTokenizer 대신 BertTokenizerFast, pooler_output
대신 last_hidden_state[:,0])을 꼭 참고할 것 — 둘 다 겉보기엔 에러 없이
돌아가면서 예측만 조용히 틀어진다.

## 국내 수요(검색 트렌드) 연동

`POST /api/v1/feasibility/market`의 `domestic_demand` 필드는 NAVER API HUB(Cloud
Platform, `naverapihub.apigw.ntruss.com`)의 검색어 트렌드 API를 실시간 호출한다.
`NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET`이 필요하고, [네이버 클라우드 플랫폼
콘솔](https://console.ncloud.com)에서 애플리케이션에 **"데이터랩(검색어트렌드)"**
API를 추가해야 호출된다 — developers.naver.com의 개인용 오픈API(다른 서비스,
다른 인증 헤더)와 헷갈리지 않도록 주의. 자세한 내용은
`app/domain/trend_client.py` 모듈 docstring과
`docs/시장성_BM_API_명세서.md`의 "국내 수요" 절 참고.

키가 없어도 나머지 API는 정상 동작하고 `domestic_demand`만 `null`로 빠진다.
실제 호출 테스트는 `@pytest.mark.naver`로 표시돼 있고, 기본 `pytest` 실행에서는
제외된다(`-m "not naver"`가 기본).

## 🚀 Git 컨벤션 규칙

### Commit 규칙

| Gitmoji | Tag | Description |
|:-------:|:---:| --- |
| ✨ | `feat` | 새로운 기능 추가 |
| 🔧 | `fix` | 버그 수정 |
| 🐛 | `bug` | 버그 이슈 |
| 📋 | `docs` | 문서 추가, 수정, 삭제 |
| ✅ | `test` | 테스트 코드 추가, 수정, 삭제 |
| ♻️ | `refactor` | 코드 리팩토링 |
| ⚙️ | `chore` | 설정 및 기타 변경사항 |
| 🔄 | `ci-cd` | CI/CD 관련 설정 수정 |

#### Commit Message Format
- **헤더(Header)**: `<타입>(스코프): <주제>`
- **본문(Body)**: 커밋의 상세 내용 (선택적)
- **바닥글(Footer)**: 관련 이슈 번호
