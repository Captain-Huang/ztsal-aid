from __future__ import annotations

import pytest

from lastz_assistant.catalog import ACTION_CATALOG, index_catalog
from lastz_assistant.models import ActionSpec, ConfigError


def test_shipped_catalog_is_only_the_two_mvp_actions() -> None:
    assert [spec.id for spec in ACTION_CATALOG] == ["alliance_help", "reconnect"]
    assert [spec.name for spec in ACTION_CATALOG] == ["联盟帮助", "断线重连"]
    assert all(spec.confirm_frames >= 2 for spec in ACTION_CATALOG)
    blob = " ".join(f"{spec.id} {spec.name} {spec.description}" for spec in ACTION_CATALOG)
    assert "治疗" not in blob
    assert "heal" not in blob


def test_catalog_rejects_duplicates_and_empty_lists() -> None:
    spec = ACTION_CATALOG[0]
    with pytest.raises(ConfigError, match="重复"):
        index_catalog([spec, spec])
    with pytest.raises(ConfigError, match="为空"):
        index_catalog([])


def test_action_spec_requires_two_confirming_frames() -> None:
    with pytest.raises(ValueError, match="2 帧"):
        ActionSpec(id="too_fast", name="过快", description="x", confirm_frames=1)
    with pytest.raises(ValueError, match="id"):
        ActionSpec(id="Bad-Id", name="名称", description="x")
