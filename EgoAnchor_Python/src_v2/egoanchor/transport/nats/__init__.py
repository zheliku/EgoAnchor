"""v2 NATS 控制面包级入口。

该包文件名和 Unity `Transport/NatsControlClient.cs` 保持语义对齐：
- `nats_control_settings.py`：控制面配置；
- `nats_control_client.py`：NATS 连接、底层 publish/request/request handler；
- `pose_result_publisher.py`：只发布已经构造好的 PoseResult。
- `anchor_command_service.py`：reset/reacquire/control request/reply parse/ack/enqueue。

注意：transport 层不导入 perception；`PoseObservation -> PoseResult` 映射在 runtime 层。
"""

from .nats_control_client import NatsControlClient
from .nats_control_settings import NatsControlSettings
from .anchor_command_service import AnchorCommandService
from .pose_result_publisher import PoseResultPublisher

__all__ = ["AnchorCommandService", "NatsControlClient", "NatsControlSettings", "PoseResultPublisher"]
