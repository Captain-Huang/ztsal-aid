"""随程序发布的动作目录。

增加动作时只在这里追加一条描述，并准备对应模板。引擎和界面都读取这份目录，
不单独编写联盟帮助或断线重连的点击逻辑。
"""

from __future__ import annotations

from lastz_assistant.models import ActionSpec, ConfigError

ACTION_CATALOG: tuple[ActionSpec, ...] = (
    ActionSpec(
        id="alliance_help",
        name="联盟帮助",
        description="在游戏窗口客户区内匹配“联盟帮助”按钮，连续确认后点击按钮中心。",
        default_threshold=0.85,
        default_cooldown_sec=5.0,
        confirm_frames=2,
    ),
    ActionSpec(
        id="reconnect",
        name="断线重连",
        description="匹配断线弹窗上的“重连”按钮，连续确认后点击。窗口不在前台时不会点。",
        default_threshold=0.88,
        default_cooldown_sec=8.0,
        confirm_frames=2,
    ),
)


def index_catalog(catalog: tuple[ActionSpec, ...] | list[ActionSpec]) -> dict[str, ActionSpec]:
    indexed: dict[str, ActionSpec] = {}
    for spec in catalog:
        if spec.id in indexed:
            raise ConfigError(f"动作目录存在重复 id：{spec.id}")
        indexed[spec.id] = spec
    if not indexed:
        raise ConfigError("动作目录为空")
    return indexed
