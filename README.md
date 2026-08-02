# PREP-BE
PREP SERVER

## RAG Evidence Vector Search

### Setup

```bash
docker compose up -d postgres redis
.venv/bin/alembic upgrade head
.venv/bin/python scripts/import_evidence_csv.py
```

### Generate embeddings

`OPENAI_API_KEY` must be configured before running embedding generation.

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
