# EgoAnchor_Protocol

Python 感知后端与 Unity 锚定运行时之间的通信契约。这个目录是唯一事实源：`.proto` 消息定义、subject 路由表 `subjects.v1.json`、代码生成脚本。两端仓库里的 `*_pb2.py`、`Generated/*.cs` 与 `SubjectNames.cs` 都是这里的生成产物。

## 目录

```
subjects.v1.json              # 全部 subject 的 transport/direction/protobuf/mode/latest_only 声明
proto/protocol/v1/
├── common.proto              # MessageHeader、Vec3/Quat/Pose3D、TimingStats、CommandAck 等共享消息
├── quest.proto               # QuestStereoFrame（双目 JPEG）、QuestCameraInfo（双目内参）
└── anchor.proto              # PoseResult、AnchorStatusEvent、reset/reacquire/control 命令
tools/generate_proto.ps1      # 双端代码生成脚本（需要 PATH 里有 protoc）
```

## 三条语义平面

| 平面 | 传输 | 方向 | 内容 |
| --- | --- | --- | --- |
| Data | ZMQ PUB/SUB，multipart，latest-drain | Unity → Python | `QuestStereoFrame`、`QuestCameraInfo` |
| Message | NATS Core pub/sub | Python → Unity | `PoseResult`、`AnchorStatusEvent`、`ServerHeartbeat` |
| Command | NATS request/reply，`request_id` 幂等 | Unity → Python | reset、reacquire、control |

设计要点：Python 只输出 camera-space 位姿，不替 Unity 做世界系合成；位姿候选携带 `frame_id`，Unity 用它回查采集时刻的相机位姿。业务代码不手写 subject 字符串——Python 从 `egoanchor.protocol` 包级入口导入，Unity 使用 `SubjectNames` 常量。

## 重新生成

```bash
pixi run pwsh -File EgoAnchor_Protocol/tools/generate_proto.ps1
```

脚本做四件事：生成 Python 侧 `EgoAnchor_Python/src/egoanchor/protocol/v1/*_pb2.py`（并把 `protocol.v1` 导入路径改写为 `egoanchor.protocol.v1`、剥掉与运行环境不匹配的 protobuf runtime 版本守卫）；生成 Unity 侧 `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Protocol/Generated/*.cs`；从 `subjects.v1.json` 生成 `SubjectNames.cs`；把 `subjects.v1.json` 复制进 Python 包。生成完成后两端重编译即可。

## 修改规则

- 字段号不得重排；删除字段时同时 `reserved` 该字段号与字段名（`anchor.proto` 里有现成示例）。
- 新增 subject 先改 `subjects.v1.json`，再动 `.proto`，最后跑生成脚本；`generate_proto.ps1` 会把路由表同步到两端。
- 时间戳与单调时钟的语义由 header 约定：`MessageHeader` 携带采集/发送两侧时钟，跨进程单调时钟不可相减。
- 生成产物（`*_pb2.py`、`Generated/*.cs`、`SubjectNames.cs`）不要手改，下一次生成会覆盖。
