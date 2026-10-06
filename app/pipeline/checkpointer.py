"""LangGraph Postgres 체크포인터 — human_review의 interrupt/resume 상태를 영속화한다.

FastAPI lifespan(app/main.py)에서 열고 닫는다. 요청마다 새로 열면 커넥션 낭비고,
human_review가 몇 시간 뒤에 resume돼도 이어갈 수 있어야 한다.

`from_conn_string`이 아니라 AsyncConnectionPool을 쓴다 — 전자는 커넥션 하나를 앱 수명 내내
붙들기 때문에 RDS idle timeout으로 끊기면 재연결 경로가 없어, 정작 "몇 시간 뒤 resume"이
필요한 시점에 실패한다. 풀은 죽은 커넥션을 버리고 새로 맺는다.
"""

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.config import settings

_checkpointer: AsyncPostgresSaver | None = None
_pool: AsyncConnectionPool | None = None


async def init_checkpointer() -> AsyncPostgresSaver:
    global _checkpointer, _pool
    _pool = AsyncConnectionPool(
        conninfo=settings.database_url_psycopg,
        min_size=1,
        max_size=5,
        open=False,
        # AsyncPostgresSaver가 요구하는 설정. autocommit이 아니면 setup()의 DDL이 커밋되지
        # 않고, dict_row가 아니면 체크포인트 조회가 컬럼명을 못 찾는다.
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await _pool.open(wait=True)
    _checkpointer = AsyncPostgresSaver(_pool)
    await _checkpointer.setup()  # 멱등 — 체크포인터 전용 테이블 없으면 생성, 있으면 no-op
    return _checkpointer


async def close_checkpointer() -> None:
    global _pool, _checkpointer
    if _pool is not None:
        await _pool.close()
    _pool = None
    _checkpointer = None


def get_checkpointer() -> AsyncPostgresSaver:
    if _checkpointer is None:
        raise RuntimeError("checkpointer가 초기화되지 않았습니다 — lifespan에서 init_checkpointer()를 먼저 호출하세요.")
    return _checkpointer
