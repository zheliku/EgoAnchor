# Payload Protocol Contract

`protocol_contract.json` 是 Unity 与 Python 双端网络协议的契约文件。JSON 本身不支持注释，所以协议说明放在这个相邻 README 中，契约文件只保留可被测试直接读取的结构化数据。

维护规则：

- 修改 topic、端口方向、MessagePack 字段名、必填性或坐标约定时，必须同步修改 `protocol_contract.json`、Python message/encoder/decoder、Unity message/encoder/decoder。
- `pose_matrix_flat = null` 与 `has_pose = false` 是合法状态包，表示本帧没有有效 6D 位姿，但仍可携带 stage、phase、耗时和检测统计。
- `frame_id` 必须从 `QuestStereoMsg` 传递到 `PoseMsg`，Unity 依赖它查找发送该帧时缓存的参考节点世界姿态。
- Python 测试 `src/test/test_protocol_contract.py` 会校验契约字段、Unity `[Key]` 顺序、Pose 编解码回环和 receiver 多 topic latest-drain。

