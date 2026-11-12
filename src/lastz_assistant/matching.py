"""在单张 BGR 画面里做模板匹配。不访问窗口，也不移动鼠标。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from lastz_assistant.models import TemplateError

MIN_TEMPLATE_SIDE = 8


@dataclass(frozen=True)
class MatchHit:
    x: int
    y: int
    width: int
    height: int
    score: float

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2


def load_template_bgr(path: str | Path) -> np.ndarray:
    """读取模板。使用 imdecode，避免 Windows 上非 ASCII 路径让 cv2.imread 失败。"""

    file_path = Path(path)
    if not file_path.is_file():
        raise TemplateError(f"模板文件不存在：{file_path}")
    try:
        raw = np.fromfile(file_path, dtype=np.uint8)
    except OSError as exc:
        raise TemplateError(f"无法读取模板：{file_path}") from exc
    if raw.size == 0:
        raise TemplateError(f"模板文件为空：{file_path}")
    decoded = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if decoded is None or decoded.size == 0:
        raise TemplateError(f"无法解码模板图片：{file_path}")
    image = _as_bgr_uint8(decoded, f"模板 {file_path.name}")
    if image.shape[0] < MIN_TEMPLATE_SIDE or image.shape[1] < MIN_TEMPLATE_SIDE:
        raise TemplateError(
            f"模板过小（至少 {MIN_TEMPLATE_SIDE}×{MIN_TEMPLATE_SIDE}）：{file_path}"
        )
    return image


def find_best_match(haystack: np.ndarray, needle: np.ndarray) -> MatchHit:
    """返回归一化相关系数的最佳位置。分数可能是 NaN（画面太平坦）。"""

    scene = _as_bgr_uint8(haystack, "窗口画面")
    template = _as_bgr_uint8(needle, "模板")
    if template.shape[0] > scene.shape[0] or template.shape[1] > scene.shape[1]:
        raise TemplateError("模板大于当前窗口画面，无法匹配")
    result = cv2.matchTemplate(scene, template, cv2.TM_CCOEFF_NORMED)
    if result.size == 0:
        raise TemplateError("模板匹配没有返回结果")
    _min_value, max_value, _min_loc, max_loc = cv2.minMaxLoc(result)
    return MatchHit(
        x=int(max_loc[0]),
        y=int(max_loc[1]),
        width=int(template.shape[1]),
        height=int(template.shape[0]),
        score=float(max_value),
    )


def score_is_match(score: float, threshold: float) -> bool:
    return math.isfinite(score) and score >= threshold


def _as_bgr_uint8(image: np.ndarray, label: str) -> np.ndarray:
    if not isinstance(image, np.ndarray) or image.size == 0:
        raise TemplateError(f"{label} 不是有效图像")
    if image.ndim == 2:
        converted = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.ndim == 3 and image.shape[2] == 4:
        converted = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    elif image.ndim == 3 and image.shape[2] == 3:
        converted = image
    else:
        raise TemplateError(f"{label} 的图像通道无法识别")
    if converted.dtype != np.uint8:
        raise TemplateError(f"{label} 必须是 8 位图像")
    if converted.shape[0] <= 0 or converted.shape[1] <= 0:
        raise TemplateError(f"{label} 尺寸无效")
    return np.ascontiguousarray(converted)
