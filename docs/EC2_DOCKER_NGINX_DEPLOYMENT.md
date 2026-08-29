# PREP-BE EC2 배포 가이드

> 목표 구조: EC2 + Nginx(HTTPS/reverse proxy) + Docker Compose(FastAPI/Redis) + Chroma volume + RDS PostgreSQL + GitHub Actions

## 1. 배포 구조

```text
Client
  ↓ HTTPS
Nginx on EC2
  ↓ http://127.0.0.1:8000
Docker Compose
  ├─ api: FastAPI + Uvicorn
  ├─ redis
  └─ prep_chroma_data volume

RDS PostgreSQL
```

현재 ChromaDB는 별도 서버가 아니라 `chromadb.PersistentClient`를 사용하는 파일 기반 저장소다.
운영에서는 Docker volume `prep_chroma_data`를 `/app/data/chroma`에 마운트한다.

## 2. AWS Console 설정

### 2.1 EC2 인스턴스 생성

AWS Console 한국어 기준:

1. AWS Console 접속
2. 상단 검색창에서 `EC2` 검색
3. 왼쪽 메뉴 `인스턴스` 선택
4. `인스턴스 시작` 클릭
5. 이름: `prep-be-api`
6. 애플리케이션 및 OS 이미지:
   - Ubuntu Server 24.04 LTS 또는 22.04 LTS
7. 인스턴스 유형:
   - 프리티어/저비용: `t3.micro` 또는 `t4g.micro`
   - Docker build가 느리면 `t3.small` 권장
8. 키 페어:
   - 기존 키 페어 선택 또는 새 키 페어 생성
   - `.pem` 파일은 다시 다운로드할 수 없으므로 안전하게 보관
9. 네트워크 설정:
   - `SSH 트래픽 허용`: 내 IP
   - `HTTP 트래픽 허용`: 체크
   - `HTTPS 트래픽 허용`: 체크
10. 스토리지:
   - 최소 20 GiB
   - Chroma volume과 Docker image를 고려하면 30 GiB 권장
11. `인스턴스 시작`

### 2.2 Elastic IP 연결 권장

EC2 public IP는 인스턴스를 중지/시작하면 바뀔 수 있다.

1. EC2 왼쪽 메뉴 `탄력적 IP`
2. `탄력적 IP 주소 할당`
3. 생성된 IP 선택
4. `작업` → `탄력적 IP 주소 연결`
5. 방금 만든 EC2 인스턴스 선택 후 연결

### 2.3 RDS 보안 그룹 수정

운영에서는 RDS를 public으로 열어두지 않고 EC2에서만 접근하게 하는 것이 좋다.

1. AWS Console에서 `RDS` 검색
2. 왼쪽 메뉴 `데이터베이스`
3. PREP RDS 선택
4. `연결 & 보안` 탭
5. VPC 보안 그룹 클릭
6. `인바운드 규칙 편집`
7. PostgreSQL 5432 규칙 추가
   - 유형: `PostgreSQL`
   - 포트: `5432`
   - 소스: EC2 보안 그룹 ID

초기 테스트 중에는 `내 IP`로 열어도 되지만, 배포 후에는 EC2 보안 그룹 기준으로 잠그는 것을 권장한다.

## 3. EC2 서버 초기 설정

EC2 접속:

```bash
ssh -i /path/to/key.pem ubuntu@<EC2_PUBLIC_IP>
```

Docker 설치:

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg git nginx certbot python3-certbot-nginx
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker ubuntu
```

권한 적용을 위해 재접속:

```bash
exit
ssh -i /path/to/key.pem ubuntu@<EC2_PUBLIC_IP>
```

## 4. 애플리케이션 배포

repo clone:

```bash
cd /home/ubuntu
git clone https://github.com/PREP-capstone/PREP-BE.git
cd PREP-BE
```

운영 env 생성:

```bash
nano .env.production
```

예시:

```env
APP_ENV=production
DATABASE_URL=postgresql+asyncpg://prep_user:<password>@<rds-endpoint>:5432/postgres
REDIS_URL=redis://redis:6379/0
ANALYSIS_TTL_SECONDS=1800
OPENAI_API_KEY=<openai-api-key>
OPENAI_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_EMBEDDING_DIMENSIONS=1536
RAG_RETRIEVAL_TOP_K=5
CHROMA_PERSIST_DIRECTORY=/app/data/chroma
CHROMA_COLLECTION_NAME=evidence_chunks
```

컨테이너 실행:

```bash
docker compose -f compose.prod.yml up -d --build
docker compose -f compose.prod.yml exec -T api alembic upgrade head
docker compose -f compose.prod.yml exec -T api python scripts/check_deploy_ready.py --skip-chroma
```

Chroma embedding이 EC2 volume에 아직 없다면 1회 생성:

```bash
docker compose -f compose.prod.yml exec -T api python scripts/embed_evidence_chunks.py --dry-run
docker compose -f compose.prod.yml exec -T api python scripts/embed_evidence_chunks.py
docker compose -f compose.prod.yml exec -T api python scripts/check_deploy_ready.py
```

API 확인:

```bash
curl http://127.0.0.1:8000/api/v1/health
```

## 5. Nginx 설정

도메인의 A record를 EC2 Elastic IP로 연결한 뒤 진행한다.

Nginx 설정 복사:

```bash
sudo cp deploy/nginx/prep-be.conf /etc/nginx/sites-available/prep-be
sudo nano /etc/nginx/sites-available/prep-be
```

`server_name api.example.com;`을 실제 도메인으로 수정한다.

활성화:

```bash
sudo ln -s /etc/nginx/sites-available/prep-be /etc/nginx/sites-enabled/prep-be
sudo nginx -t
sudo systemctl reload nginx
```

HTTP 확인:

```bash
curl http://<도메인>/api/v1/health
```

HTTPS 발급:

```bash
sudo certbot --nginx -d <도메인>
```

HTTPS 확인:

```bash
curl https://<도메인>/api/v1/health
```

자동 갱신 확인:

```bash
sudo certbot renew --dry-run
```

## 6. GitHub Actions Secrets

GitHub repo → `Settings` → `Secrets and variables` → `Actions` → `New repository secret`

필요한 Secret:

| 이름 | 예시 |
| --- | --- |
| `EC2_HOST` | EC2 Elastic IP 또는 도메인 |
| `EC2_USER` | `ubuntu` |
| `EC2_SSH_KEY` | EC2 접속 private key 전체 내용 |
| `EC2_APP_DIR` | `/home/ubuntu/PREP-BE` |
| `ENV_PRODUCTION` | `.env.production` 전체 내용 |

`main` 브랜치에 push되면 `.github/workflows/deploy.yml`이 아래 작업을 수행한다.

1. `.env.production` 갱신(secret이 설정된 경우)
2. PREP-AI release에서 카테고리 모델(ONNX) 다운로드 후 EC2로 rsync(9절 참고, release가 없으면 건너뜀)
3. EC2 접속 → `git fetch origin main` → `git reset --hard origin/main`
4. `docker compose -f compose.prod.yml up -d --build`
5. `alembic upgrade head`
6. `check_deploy_ready.py --skip-chroma`
7. `/api/v1/health` 확인

## 7. 운영 명령어

로그 확인:

```bash
docker compose -f compose.prod.yml logs -f api
docker compose -f compose.prod.yml logs -f redis
```

재시작:

```bash
docker compose -f compose.prod.yml restart api
```

배포 수동 실행:

```bash
git pull --ff-only
docker compose -f compose.prod.yml up -d --build
docker compose -f compose.prod.yml exec -T api alembic upgrade head
```

Chroma volume 확인:

```bash
docker volume ls | grep prep_chroma
```

## 8. 주의사항

- `.env.production`은 절대 Git에 커밋하지 않는다.
- RDS 보안 그룹은 배포 후 EC2 보안 그룹에서만 접근하도록 제한한다.
- Chroma는 RDS가 아니라 Docker volume에 저장된다.
- EC2를 삭제하면 volume도 같이 사라질 수 있으므로 필요하면 snapshot/backup 정책을 별도로 잡는다.
- FastAPI 컨테이너를 여러 개로 scale-out하기 전에는 Chroma server 전환을 먼저 검토한다.

## 9. 카테고리 분류 모델(ONNX) 자동 배포

카테고리 분류 모델(`app/domain/category_classifier.py`)이 쓰는 체크포인트는 수백MB
단위 바이너리라 이 저장소(`data/models/`, `.dockerignore`로도 제외됨)에도, 이미지
빌드에도 포함하지 않는다. 대신 [PREP-AI](https://github.com/PREP-capstone/PREP-AI)
저장소의 GitHub Release에서 받아 배포 시점에 EC2에 배치한다.

### 9.1 산출물 규칙 (PREP-AI 쪽)

PREP-AI의 GitHub Release에 아래 이름의 zip 자산이 올라와 있어야 한다.

```text
best_healthcare_model_onnx.zip
```

zip 안 구조(풀었을 때):

```text
category_classifier_onnx/
├── model.onnx 또는 model_quantized.onnx
├── vocab.txt
├── tokenizer_config.json
├── special_tokens_map.json
├── labels.json
└── model_meta.json
```

release가 아직 없으면 `deploy.yml`이 경고만 남기고 이 단계를 건너뛴다 — 배포 자체가
막히지는 않는다(카테고리 분류 API는 모델이 없으면 503 `CATEGORY_MODEL_UNAVAILABLE`로
정상 응답하도록 이미 설계돼 있다).

### 9.2 경로

```text
EC2:     $EC2_APP_DIR/data/models/category_classifier_onnx/
컨테이너: /app/data/models/category_classifier_onnx/   (compose.prod.yml volumes, :ro)
```

`compose.prod.yml`이 `./data/models`를 컨테이너의 `/app/data/models`에 읽기 전용으로
마운트한다 — 이미지를 다시 빌드하지 않아도 모델 파일만 갱신하면 반영된다(컨테이너
재시작은 필요).

### 9.3 자동화 흐름 (`.github/workflows/deploy.yml`)

추가 secret 설정 없이(같은 조직 소유의 public 저장소라 workflow 기본 `GITHUB_TOKEN`으로
충분) 배포 시 다음을 수행한다.

1. `gh release download --repo PREP-capstone/PREP-AI --pattern "best_healthcare_model_onnx.zip"`
2. zip 압축 해제
3. `rsync -az --delete`로 EC2의 `$EC2_APP_DIR/data/models/category_classifier_onnx/`에 반영
4. (이후 기존 단계) `docker compose up -d --build`로 컨테이너 재기동 — 새 모델 파일이 마운트에 반영됨

release가 여러 개면 `gh release download`는 최신 release를 받는다 — 모델을 갱신하려면
PREP-AI에 새 release를 올리기만 하면 된다(태그 고정 아님).

### 9.4 배포 후 확인

```bash
docker compose -p prep-be -f compose.prod.yml exec api \
  ls -la /app/data/models/category_classifier_onnx

curl -X POST https://api.prepwell.shop/api/v1/category-classifier/predict \
  -H "Content-Type: application/json" \
  -d '{"service_description":"사용자의 혈당 수치를 기록하고 변화 추이를 보여주는 건강관리 앱"}'
```

### 9.5 함께 필요한 나머지 작업 (별도 담당, 아직 미완료)

이 문서의 9절은 **배포(모델 파일을 서버/컨테이너까지 옮기는 것)** 만 다룬다. 아래 두
가지는 이 PR 범위 밖이고, 완료되기 전까지는 파일이 배치돼도 실제로 쓰이지 않는다.

- PREP-AI 쪽에서 위 9.1 형식의 release를 실제로 올리는 것
- `app/core/config.py`/`app/domain/category_classifier.py`가 ONNX Runtime으로
  추론하도록 바뀌는 것(`CATEGORY_MODEL_BACKEND`/`CATEGORY_MODEL_FILE` 설정 추가 포함) —
  지금 이 코드는 여전히 PyTorch(`model.pt`/`label_config.pt`)만 읽는다.
