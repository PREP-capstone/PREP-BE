from datetime import datetime

from app.api.analysis_sessions import generate_session_id


def test_generate_session_id_uses_date_prefix() -> None:
    session_id = generate_session_id(datetime(2026, 8, 18, 9, 30))

    assert session_id.startswith("session_20260818_")
    assert len(session_id) == len("session_20260818_") + 8
