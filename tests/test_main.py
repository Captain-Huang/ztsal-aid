from __future__ import annotations

import sys

import pytest

from lastz_assistant.main import main


def test_main_refuses_to_start_off_windows(capsys: pytest.CaptureFixture[str]) -> None:
    if sys.platform == "win32":
        pytest.skip("Windows 上会进入图形界面")
    assert main() == 2
    assert "Windows" in capsys.readouterr().err
