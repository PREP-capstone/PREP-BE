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

`category_1` 추론(`POST /api/v1/category-classifier/predict`)은 KLUE-RoBERTa large
체크포인트를 로컬에서 로드한다. 체크포인트는 1.3GB 바이너리라 git에 없다
(`data/models/`는 `.gitignore`) — 배치 후 `CATEGORY_MODEL_DIR`(기본값
`data/models/best_healthcare_model_large`)이 그 경로를 가리키게 한다.

```bash
mkdir -p data/models
unzip best_healthcare_model_large.zip -d data/models
.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install -r requirements.txt
```

모델이 없어도 나머지 API는 정상 동작한다 — 이 엔드포인트만 503
`CATEGORY_MODEL_UNAVAILABLE`을 반환한다. 관련 회귀 테스트는
`@pytest.mark.ml_model`로 표시돼 있고, 모델 없이 실행하려면
`pytest -m "not ml_model"`.

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
