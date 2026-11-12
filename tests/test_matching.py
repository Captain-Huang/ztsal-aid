from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from lastz_assistant.matching import find_best_match, load_template_bgr, score_is_match
from lastz_assistant.models import TemplateError
from tests.fakes import blank, paint, unique_patch, write_png


def test_perfect_match_reports_location_and_score() -> None:
    needle = unique_patch(20, 16, seed=7)
    scene = blank(100, 80)
    paint(scene, needle, 40, 22)
    hit = find_best_match(scene, needle)
    assert (hit.x, hit.y) == (40, 22)
    assert hit.center == (50, 30)
    assert hit.score == pytest.approx(1.0, abs=1e-6)
    assert score_is_match(hit.score, 0.85)


def test_below_threshold_is_not_a_match() -> None:
    scene = blank(90, 70)
    hit = find_best_match(scene, unique_patch(18, 14, seed=3))
    assert not score_is_match(hit.score, 0.85)


def test_bgra_scene_matches_the_same_bgr_template() -> None:
    needle = unique_patch(18, 12, seed=9)
    scene = blank(70, 60)
    paint(scene, needle, 8, 9)
    bgra = np.dstack([scene, np.full(scene.shape[:2], 255, dtype=np.uint8)])
    hit = find_best_match(bgra, needle)
    assert (hit.x, hit.y) == (8, 9)
    assert hit.score == pytest.approx(1.0, abs=1e-6)


def test_template_larger_than_scene_is_an_error() -> None:
    with pytest.raises(TemplateError, match="大于"):
        find_best_match(blank(20, 20), unique_patch(30, 10, seed=1))


def test_load_template_roundtrip_and_unicode_path(tmp_path: Path) -> None:
    image = unique_patch(16, 12, seed=4)
    path = tmp_path / "联盟帮助.png"
    write_png(path, image)
    loaded = load_template_bgr(path)
    assert loaded.shape == image.shape
    assert np.array_equal(loaded, image)


def test_load_template_rejects_missing_corrupt_and_tiny_files(tmp_path: Path) -> None:
    with pytest.raises(TemplateError, match="不存在"):
        load_template_bgr(tmp_path / "missing.png")
    corrupt = tmp_path / "bad.png"
    corrupt.write_bytes(b"this is not a png")
    with pytest.raises(TemplateError, match="无法解码"):
        load_template_bgr(corrupt)
    tiny = tmp_path / "tiny.png"
    write_png(tiny, unique_patch(4, 4, seed=2))
    with pytest.raises(TemplateError, match="过小"):
        load_template_bgr(tiny)
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    with pytest.raises(TemplateError, match="为空"):
        load_template_bgr(empty)
