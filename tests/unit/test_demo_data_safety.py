"""The synthetic demo loader refuses every target that is not a clearly disposable demo database.

These tests never write: each refusal happens before any row is touched, and the connection is
only opened (read-only checks) for a target that passes the name and configuration guards.
"""

from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from scripts import demo_data


def test_requires_explicit_confirmation() -> None:
    url = make_url("postgresql+psycopg://u:p@127.0.0.1:5435/ct_demo")
    with pytest.raises(demo_data.DemoRefused, match="confirm-disposable"):
        demo_data.check_target(url, object(), confirmed=False)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "database", ["concepttrail_db", "concepttrail", "postgres", "demo_ct", "CT_DEMO", ""]
)
def test_refuses_any_database_not_named_ct_demo(database: str) -> None:
    url = make_url(f"postgresql+psycopg://u:p@127.0.0.1:5435/{database}")
    with pytest.raises(demo_data.DemoRefused, match="must start with 'ct_demo'"):
        demo_data.check_target(url, object(), confirmed=True)  # type: ignore[arg-type]


def test_refuses_the_applications_configured_database(monkeypatch: pytest.MonkeyPatch) -> None:
    configured = make_url(get_settings().database_url.get_secret_value())
    clash = configured.set(database="ct_demo_clash")
    patched = get_settings().model_copy(
        update={"database_url": type(get_settings().database_url)(clash.render_as_string(False))}
    )
    monkeypatch.setattr(demo_data, "get_settings", lambda: patched)
    with pytest.raises(demo_data.DemoRefused, match="configured database"):
        demo_data.check_target(clash, object(), confirmed=True)  # type: ignore[arg-type]


def test_cli_exit_code_and_no_secret_in_refusal(capsys: pytest.CaptureFixture[str]) -> None:
    code = demo_data.main(
        ["load", "--database-url", "postgresql+psycopg://u:hunter2@127.0.0.1:5433/concepttrail_db"]
    )
    captured = capsys.readouterr()
    assert code == 2 and "REFUSED" in captured.err
    assert "hunter2" not in captured.out + captured.err


def test_demo_identities_are_deterministic_and_labelled() -> None:
    assert demo_data._id("teacher-a") == demo_data._id("teacher-a")
    assert demo_data._id("room-7") != demo_data._id("room-8")
    assert demo_data.MARK == "SYNTHETIC-DEMO" and demo_data.SECTION.startswith("DEMO")
