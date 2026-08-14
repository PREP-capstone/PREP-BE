import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings
from app.core.redis_client import redis_client
from app.db.session import engine
from app.rag.vector_store import get_evidence_collection


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def mask_database_url(url: str) -> str:
    if "@" not in url or "://" not in url:
        return url

    scheme, rest = url.split("://", 1)
    credentials, host = rest.split("@", 1)
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


async def check_postgres() -> CheckResult:
    try:
        async with engine.connect() as connection:
            database = await connection.scalar(text("select current_database()"))
            version = await connection.scalar(text("select version()"))

        version_summary = str(version).split(",", 1)[0]
        return CheckResult(
            name="postgres",
            ok=True,
            detail=f"connected to {database} ({version_summary})",
        )
    except Exception as exc:  # noqa: BLE001 - deployment diagnostics should show connection failures.
        return CheckResult("postgres", False, f"{type(exc).__name__}: {exc}")


async def check_evidence_tables() -> CheckResult:
    try:
        async with engine.connect() as connection:
            documents = await connection.scalar(text("select count(*) from evidence_documents"))
            chunks = await connection.scalar(text("select count(*) from evidence_chunks"))

        return CheckResult(
            name="evidence_tables",
            ok=True,
            detail=f"documents={documents}, chunks={chunks}",
        )
    except Exception as exc:  # noqa: BLE001 - deployment diagnostics should show missing tables or connection failures.
        return CheckResult(
            "evidence_tables",
            False,
            f"{type(exc).__name__}: run alembic/import first if tables are missing",
        )


async def check_redis() -> CheckResult:
    try:
        await redis_client.ping()
        return CheckResult("redis", True, "ping ok")
    except Exception as exc:  # noqa: BLE001 - deployment diagnostics should show any connection failure.
        return CheckResult("redis", False, f"{type(exc).__name__}: {exc}")


def check_chroma() -> CheckResult:
    try:
        collection = get_evidence_collection()
        return CheckResult(
            name="chroma",
            ok=True,
            detail=(
                f"collection={settings.chroma_collection_name}, "
                f"count={collection.count()}, "
                f"path={settings.chroma_persist_directory}"
            ),
        )
    except Exception as exc:  # noqa: BLE001 - deployment diagnostics should show any local store failure.
        return CheckResult("chroma", False, f"{type(exc).__name__}: {exc}")


def print_result(result: CheckResult) -> None:
    status = "OK" if result.ok else "FAIL"
    print(f"[{status}] {result.name}: {result.detail}")


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check whether the deployment database, Redis, and Chroma stores are ready."
    )
    parser.add_argument("--skip-redis", action="store_true", help="Skip Redis ping.")
    parser.add_argument("--skip-chroma", action="store_true", help="Skip Chroma collection check.")
    args = parser.parse_args()

    print(f"APP_ENV={settings.app_env}")
    print(f"DATABASE_URL={mask_database_url(settings.database_url)}")
    print(f"CHROMA_PERSIST_DIRECTORY={settings.chroma_persist_directory}")

    results = [
        await check_postgres(),
        await check_evidence_tables(),
    ]

    if not args.skip_redis:
        results.append(await check_redis())

    if not args.skip_chroma:
        results.append(check_chroma())

    for result in results:
        print_result(result)

    await redis_client.aclose()
    await engine.dispose()

    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
