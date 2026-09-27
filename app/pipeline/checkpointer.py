"""LangGraph Postgres 체크포인터 — human_review의 interrupt/resume 상태를 영속화한다.

FastAPI lifespan(app/main.py)에서 열고 닫는다. 요청마다 새로 열면 커넥션 풀 낭비고,
human_review가 몇 시간 뒤에 resume돼도 같은 커넥션 풀에서 이어갈 수 있어야 한다.
"""

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import settings

_checkpointer: AsyncPostgresSaver | None = None
_cm = None


async def init_checkpointer() -> AsyncPostgresSaver:
    global _checkpointer, _cm
    _cm = AsyncPostgresSaver.from_conn_string(settings.database_url_psycopg)
    _checkpointer = await _cm.__aenter__()
    await _checkpointer.setup()  # 멱등 — 체크포인터 전용 테이블 없으면 생성, 있으면 no-op
    return _checkpointer


async def close_checkpointer() -> None:
    global _cm, _checkpointer
    if _cm is not None:
        await _cm.__aexit__(None, None, None)
    _cm = None
    _checkpointer = None


def get_checkpointer() -> AsyncPostgresSaver:
    if _checkpointer is None:
        raise RuntimeError("checkpointer가 초기화되지 않았습니다 — lifespan에서 init_checkpointer()를 먼저 호출하세요.")
    return _checkpointer
