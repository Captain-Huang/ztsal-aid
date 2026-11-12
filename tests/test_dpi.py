from __future__ import annotations

import sys

from lastz_assistant.dpi import enable_dpi_awareness


def test_dpi_helper_is_stable_on_this_platform() -> None:
    first = enable_dpi_awareness()
    second = enable_dpi_awareness()
    assert first == second
    if sys.platform != "win32":
        assert first == "not-windows"
    else:
        assert first in {"per-monitor-v2", "per-monitor", "system", "unaware"}
