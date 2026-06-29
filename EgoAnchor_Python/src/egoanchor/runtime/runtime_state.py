"""Python runtime 状态定义。"""

from __future__ import annotations

from enum import Enum


class RuntimeState(str, Enum):
    """Python perception/runtime 生命周期状态。

    该状态只描述 Python server 的输入、标定、pipeline 与命令执行状态；
    Unity world anchor 的显示状态由 Unity 侧 AnchorStateMachine 独立维护。
    """

    BOOTING = "BOOTING"
    """配置、网络或模型初始化中。"""

    WAITING_INPUT = "WAITING_INPUT"
    """尚未收到 Quest stereo 输入。"""

    WAITING_CALIBRATION = "WAITING_CALIBRATION"
    """已有图像但尚未收到可用 QuestCameraInfo。"""

    DETECTING = "DETECTING"
    """等待有效 mask/depth/register 的检测阶段。"""

    REGISTERING = "REGISTERING"
    """正在尝试 6DoF register。"""

    TRACKING = "TRACKING"
    """持续 tracking 或 register 已产生有效 pose。"""

    LOST = "LOST"
    """可恢复的跟踪丢失状态。"""

    REACQUIRING = "REACQUIRING"
    """用户或系统主动重新获取 anchor 中。"""

    PAUSED = "PAUSED"
    """runtime 暂停处理新图像，但仍可接收输入和发布心跳。"""

    ERROR = "ERROR"
    """不可恢复或需要人工介入的 runtime 错误。"""

    STOPPED = "STOPPED"
    """runtime 已正常停止。"""


def runtime_state_value(state: RuntimeState | str) -> str:
    """把 RuntimeState 或字符串统一转换成协议字段中的状态名。"""

    if isinstance(state, RuntimeState):
        return state.value
    return str(state or RuntimeState.ERROR.value)


__all__ = ["RuntimeState", "runtime_state_value"]
