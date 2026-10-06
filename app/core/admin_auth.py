"""관리자 검수(/admin/rule-*) 전용 HTTP Basic Auth.

캡스톤 규모라 별도 admin_users 테이블·로그인 플로우 없이, env(ADMIN_CREDENTIALS)에 박아둔
팀원 계정 몇 개로 최소한의 인증만 한다(2026-09-27 결정). 인증된 username을
rule_review_queue.reviewed_by에 그대로 남겨서 "누가 검수했는지"는 실제 인증값으로 남는다.
"""

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.core.config import settings

_security = HTTPBasic()


def require_admin(credentials: HTTPBasicCredentials = Depends(_security)) -> str:
    known_password = settings.admin_credential_map.get(credentials.username)
    # 타이밍 공격 방지 — 계정이 없어도 항상 compare_digest를 한 번은 돌려서 존재 여부가
    # 응답 시간으로 새지 않게 한다. str끼리 비교하면 비ASCII 문자가 섞였을 때
    # compare_digest가 TypeError를 던져 401이 아니라 500이 나가므로 바이트로 맞춘다.
    is_valid = known_password is not None and secrets.compare_digest(
        credentials.password.encode("utf-8"), known_password.encode("utf-8")
    )
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증 실패",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
