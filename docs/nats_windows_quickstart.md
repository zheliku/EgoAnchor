# EgoAnchor NATS Windows 快速上手教程

这份文档面向第一次接触 NATS 的同学。目标是让你在 Windows 上用 `winget` 安装 NATS，跑通命令行测试，再理解它怎么接入 EgoAnchor 的 Unity/Python 通信链路。

当前 EgoAnchor 的稳定主线仍是 ZMQ + MessagePack。NATS + Protobuf 是并行迁移轨道：先做独立验证，再逐步替换通信层，不要直接破坏旧端到端链路。

## 1. NATS 是什么

NATS 可以理解成一个很轻量的消息中转站。Unity、Python、调试工具都连接到同一个 NATS Server，然后按 subject 发送和接收消息。

常见角色：

- `nats-server`：消息服务器，默认监听 `4222` 端口。
- NATS CLI：命令行测试工具，命令通常叫 `nats`。
- client library：程序里使用的客户端库，例如 Python 的 `nats-py`、Unity/C# 的 `NATS.Net`。

常见通信模式：

- Publish/Subscribe：发布者往 subject 发消息，所有订阅者都能收到。适合图像帧、pose、状态事件。
- Request/Reply：请求方发送命令并等待一次回复。适合 reset、reacquire、pause/resume 这类命令。
- Queue Group：多个订阅者共享同一个 queue group 时，每条消息只会交给其中一个订阅者。EgoAnchor 初期通常不需要它。
- JetStream：NATS 的持久化/重放能力。EgoAnchor 实时链路初期优先使用 Core NATS，不先引入 JetStream。

EgoAnchor 的实时帧和 pose 更关心低延迟和最新状态，所以推荐先用 Core NATS：消息不落盘，程序慢了就丢旧帧，避免越积越慢。

## 2. Windows 安装

打开 PowerShell。建议使用普通 PowerShell 即可；如果要安装为 Windows Service，再用管理员 PowerShell。

先确认 `winget` 可用：

```powershell
winget --version
```

搜索 NATS 包：

```powershell
winget search NATS
```

安装 NATS Server：

```powershell
winget install -e --id NATSAuthors.NATSServer
```

安装 NATS CLI：

```powershell
winget install -e --id NATSAuthors.CLI
```

如果包名在你的机器上有变化，以 `winget search NATS` 显示的 `Id` 为准。安装后重新打开 PowerShell，让 PATH 刷新。

检查安装结果：

```powershell
nats-server --version
nats --version
```

## 3. 第一次启动 Server

最小启动方式：

```powershell
nats-server
```

看到类似下面的信息就说明启动成功：

```text
Listening for client connections on 0.0.0.0:4222
Server is ready
```

不要关闭这个窗口。另开一个 PowerShell 做测试。

查看 server 是否在线：

```powershell
nats server check connection
```

最小 pub/sub 测试：

```powershell
nats sub egoanchor.test
```

再开一个 PowerShell：

```powershell
nats pub egoanchor.test "hello nats"
```

订阅窗口能看到 `hello nats`，说明本机 NATS 已经跑通。

## 4. 最小配置文件

建议把本地开发配置放到仓库外或本机固定目录，例如：

```powershell
New-Item -ItemType Directory -Force C:\nats | Out-Null
notepad C:\nats\egoanchor-dev.conf
```

填入：

```conf
# EgoAnchor 本地开发 NATS 配置
server_name: egoanchor-dev

# 只允许本机连接，最安全，适合 Python 和 Unity 都在同一台 PC 上调试。
host: 127.0.0.1
port: 4222

# HTTP 监控端口。只监听本机，用于排查连接和统计。
http: 127.0.0.1:8222

# 本地开发日志可以稍微详细一点。
debug: false
trace: false
logtime: true
```

用配置启动：

```powershell
nats-server -c C:\nats\egoanchor-dev.conf
```

浏览器打开下面地址可以看监控信息：

```text
http://127.0.0.1:8222/
```

常用监控接口：

```text
http://127.0.0.1:8222/varz
http://127.0.0.1:8222/connz
http://127.0.0.1:8222/subsz
```

## 5. 让 Quest/局域网设备连接

如果 Unity 在 Quest 上运行，Quest 需要连接到 PC 的 NATS Server。这时 `host` 不能只绑定 `127.0.0.1`，要监听局域网网卡。

先查看 PC 局域网 IP：

```powershell
ipconfig
```

找到类似 `IPv4 地址 . . . . . . . . . . . . : 192.168.1.23` 的地址。

把配置改成：

```conf
server_name: egoanchor-dev-lan
host: 0.0.0.0
port: 4222
http: 127.0.0.1:8222
logtime: true
```

启动：

```powershell
nats-server -c C:\nats\egoanchor-dev.conf
```

Windows 防火墙如果弹窗，允许当前网络访问。Unity/Quest 侧连接地址改成：

```text
nats://192.168.1.23:4222
```

把 `192.168.1.23` 换成你的 PC 实际 IP。

安全提醒：`0.0.0.0` 会让同一网络里的其他设备也能连到这个 NATS Server。实验室/家庭网络调试可以这样做；公共网络不要这样裸跑。

## 6. 加用户名密码

如果需要让局域网连接更稳妥，可以给 NATS 加简单用户名密码：

```conf
server_name: egoanchor-dev-lan
host: 0.0.0.0
port: 4222
http: 127.0.0.1:8222

authorization {
  user: egoanchor
  password: change_me_dev_password
}
```

启动后，CLI 连接方式：

```powershell
nats --server nats://egoanchor:change_me_dev_password@127.0.0.1:4222 server check connection
```

Unity/Python 连接地址：

```text
nats://egoanchor:change_me_dev_password@192.168.1.23:4222
```

开发阶段可以先不用鉴权，确认链路跑通后再加。真正多人网络或公开网络请不要使用明文弱密码。

## 7. 安装为 Windows Service

本地开发不一定需要服务化，直接开 PowerShell 跑 `nats-server -c ...` 更方便看日志。

如果希望开机自动启动，使用管理员 PowerShell：

```powershell
nats-server -c C:\nats\egoanchor-dev.conf --install
nats-server --service start
```

常用服务命令：

```powershell
nats-server --service stop
nats-server --service restart
nats-server --service uninstall
```

修改配置文件后要重启服务：

```powershell
nats-server --service restart
```

如果 `--install` 失败，通常是没有管理员权限。

## 8. CLI 常用命令

检查连接：

```powershell
nats --server nats://127.0.0.1:4222 server check connection
```

订阅一个 subject：

```powershell
nats --server nats://127.0.0.1:4222 sub egoanchor.test
```

发布文本：

```powershell
nats --server nats://127.0.0.1:4222 pub egoanchor.test "hello"
```

发 request/reply 请求：

```powershell
nats --server nats://127.0.0.1:4222 request egoanchor.v1.cmd.anchor.reset "{}"
```

通配订阅：

```powershell
nats sub "egoanchor.v1.>"
```

通配符说明：

- `*` 匹配一个 token，例如 `egoanchor.v1.*.result`。
- `>` 匹配后面所有 token，只能放在末尾，例如 `egoanchor.v1.>`。

## 9. 用 Python 跑通 request/reply

仓库里已经有一个最小实验目录：

```text
try_nats/
```

它使用 `nats-py`，配置在 `try_nats/pixi.toml`。

先启动 NATS Server：

```powershell
nats-server -c C:\nats\egoanchor-dev.conf
```

再开一个 PowerShell，启动 responder：

```powershell
cd P:\VSCode-Project\EgoAnchor\try_nats
pixi run python responder.py
```

再开一个 PowerShell，发送 request：

```powershell
cd P:\VSCode-Project\EgoAnchor\try_nats
pixi run python request.py
```

成功时，`request.py` 会打印类似：

```text
reply: {"accepted":true,"applied":true,"message":"reset from python ok"}
```

注意：当前 `try_nats/responder.py` 使用的是早期实验 subject：

```text
egoanchor.command.reset_tracking
```

正式 v2 约定应使用：

```text
egoanchor.v1.cmd.anchor.reset
```

迁移时优先以 `EgoAnchor_Protocol/subjects.v1.json` 为准。

## 10. 用 Unity 跑通测试

Unity 侧已有测试脚本：

```text
EgoAnchor_Unity/Assets/Scripts/Nats/NatsResetTest.cs
EgoAnchor_Unity/Assets/Scripts/Nats/NatsImageStreamTest.cs
```

测试步骤：

1. 启动 `nats-server`。
2. 打开 Unity 测试场景，例如 `EgoAnchor_Unity/Assets/Scenes/Test/Test-Nats.unity`。
3. 确认 Inspector 里的 `natsUrl`：
   - PC 本机编辑器：`nats://127.0.0.1:4222`
   - Quest 真机：`nats://你的PC局域网IP:4222`
4. Play 后查看 Unity Console。
5. 对 `NatsResetTest` 右键组件菜单执行 `Send Reset Request`，Python responder 应收到请求并返回 reply。

如果测试图片流：

1. 给 `NatsImageStreamTest.sourceImage` 绑定一张 `Texture2D`。
2. Python 端运行：

```powershell
cd P:\VSCode-Project\EgoAnchor\try_nats
pixi run python image_viewer.py
```

3. Unity Play 后开始发布，Python 窗口应显示图像流。

同样注意：Unity 测试脚本目前也使用早期实验 subject。进入正式 v2 后需要改成 `EgoAnchor_Protocol/subjects.v1.json` 中的 subject，并把 JSON/JPEG 裸包迁移到 Protobuf payload。

## 11. EgoAnchor v2 subject 约定

正式 v2 协议目录：

```text
EgoAnchor_Protocol/
```

subject 契约文件：

```text
EgoAnchor_Protocol/subjects.v1.json
```

当前约定：

| Subject | 方向 | 类型 | 模式 | 说明 |
| --- | --- | --- | --- | --- |
| `egoanchor.v1.quest.stereo` | Unity -> Python | `QuestStereoFrame` | pub/sub | 双目 JPEG，latest-only |
| `egoanchor.v1.quest.camera_info` | Unity -> Python | `QuestCameraInfo` | pub/sub | 相机信息，latest-only |
| `egoanchor.v1.pose.result` | Python -> Unity | `PoseResult` | pub/sub | 位姿结果，latest-only |
| `egoanchor.v1.anchor.status` | Python -> Unity | `AnchorStatusEvent` | pub/sub | 锚定状态事件 |
| `egoanchor.v1.server.heartbeat` | Python -> Unity | `ServerHeartbeat` | pub/sub | 服务心跳，latest-only |
| `egoanchor.v1.cmd.anchor.reset` | Unity -> Python | `ResetTrackingRequest -> CommandAck` | request/reply | 重置跟踪 |
| `egoanchor.v1.cmd.anchor.reacquire` | Unity -> Python | `ReacquireAnchorRequest -> CommandAck` | request/reply | 请求重定位 |
| `egoanchor.v1.cmd.anchor.control` | Unity -> Python | `AnchorControlRequest -> CommandAck` | request/reply | 控制 stage/pause/resume |

重要原则：

- subject 名不要散落硬编码，优先从 `subjects.v1.json` 或统一常量读取。
- 高频图像和 pose 是 latest-only，消费端处理慢时只保留最新消息。
- reset/reacquire/control 的 `CommandAck` 只表示命令已接受或拒绝，不代表已经获得新 pose。
- Protobuf 字段号进入共享协议后不要重排；删除字段时用 `reserved`。
- v2 接入期间不要替换旧 ZMQ 主入口，先并行跑通。

## 12. Python 客户端最小模板

安装依赖：

```powershell
pixi add nats-py
```

最小订阅：

```python
import asyncio
from nats.aio.client import Client as NATS

async def main():
    nc = NATS()
    await nc.connect("nats://127.0.0.1:4222")

    async def on_msg(msg):
        print(msg.subject, msg.data)

    await nc.subscribe("egoanchor.v1.>", cb=on_msg)
    while True:
        await asyncio.sleep(1)

asyncio.run(main())
```

最小发布：

```python
import asyncio
from nats.aio.client import Client as NATS

async def main():
    nc = NATS()
    await nc.connect("nats://127.0.0.1:4222")
    await nc.publish("egoanchor.v1.anchor.status", b"hello")
    await nc.drain()

asyncio.run(main())
```

最小 request/reply responder：

```python
import asyncio
from nats.aio.client import Client as NATS

async def main():
    nc = NATS()
    await nc.connect("nats://127.0.0.1:4222")

    async def on_reset(msg):
        await msg.respond(b'{"accepted":true,"status":"accepted"}')

    await nc.subscribe("egoanchor.v1.cmd.anchor.reset", cb=on_reset)
    while True:
        await asyncio.sleep(1)

asyncio.run(main())
```

正式代码里不要用 JSON 字符串替代 Protobuf。JSON 只适合初期确认 NATS server、subject、request/reply 是否正常。

## 13. Unity/C# 客户端要点

Unity 当前已引入 `NATS.Net` 相关包，测试脚本用法大致是：

```csharp
using NATS.Net;

var client = new NatsClient("nats://127.0.0.1:4222", "EgoAnchor Unity");
await client.ConnectAsync();
await client.PublishAsync<byte[]>("egoanchor.v1.quest.stereo", payloadBytes);
```

request/reply：

```csharp
var reply = await client.RequestAsync<byte[], byte[]>(
    "egoanchor.v1.cmd.anchor.reset",
    requestBytes,
    cancellationToken: cts.Token
);
```

正式接 Protobuf 时：

- Unity 使用生成的 C# Protobuf 类型。
- 发布前调用 `ToByteArray()` 得到 payload。
- 收到 bytes 后用对应类型的 `Parser.ParseFrom(...)` 解码。
- subject 和 message 类型必须匹配 `subjects.v1.json`。

## 14. 推荐接入顺序

建议按这个顺序推进，容易定位问题：

1. 本机启动 `nats-server`，CLI 跑通 `pub/sub`。
2. Python 跑通 `try_nats/request.py` 和 `try_nats/responder.py`。
3. Unity Editor 连接 `127.0.0.1:4222`，跑通 reset request/reply。
4. Quest 连接 PC 局域网 IP，跑通一个小文本或小图片 subject。
5. 生成并使用 Protobuf bytes，不再使用 JSON。
6. 接入 `QuestStereoFrame` 和 `QuestCameraInfo`。
7. Python 侧实现按 subject latest-only 的输入缓存。
8. Python 发布 `PoseResult`，Unity 解码并暂时只打印。
9. Unity 把 `PoseResult` 接入现有 anchor 应用链路。
10. 保留 ZMQ 主线可运行，等 v2 完整验证后再决定切换入口。

## 15. 排错清单

`nats-server` 命令不存在：

- 重新打开 PowerShell。
- 检查 `winget install` 是否成功。
- 用 `where nats-server` 查看 PATH。

`nats` CLI 命令不存在：

- 确认安装的是 CLI 包，不只是 server 包。
- 运行 `winget search NATS` 检查当前包名。

端口被占用：

```powershell
netstat -ano | findstr :4222
```

如果已有旧 server 在跑，先关闭旧窗口或停止服务：

```powershell
nats-server --service stop
```

Unity Editor 能连，Quest 连不上：

- NATS 配置是否用了 `host: 0.0.0.0`。
- Quest 和 PC 是否在同一个局域网。
- Unity 的 `natsUrl` 是否填了 PC 的局域网 IP，不是 `127.0.0.1`。
- Windows 防火墙是否允许 `4222` 入站。
- PC 是否连了 VPN，导致 Quest 无法访问该网卡。

request 超时：

- responder 是否已启动。
- subject 是否完全一致。
- responder 是否真的调用了 `msg.respond(...)`。
- request timeout 是否太短。

订阅不到消息：

- 用 `nats sub "egoanchor.v1.>"` 观察所有 v2 消息。
- 检查 publish 和 subscribe 连接的是同一个 server 地址。
- 检查 subject 是否大小写、点号、版本号一致。

高频图像延迟越来越大：

- 不要在订阅 callback 里做重型 GPU 推理。
- callback 只做解析和 latest-store 写入。
- pipeline 主循环只取最新帧处理。
- 不要对实时图像启用 JetStream 持久化。

Protobuf 解码失败：

- 确认 subject 对应的 Protobuf 类型正确。
- 确认 Python/C# 代码由同一份 `EgoAnchor_Protocol/proto` 生成。
- 不要手改生成的 `*_pb2.py` 或 C# `.cs`。

## 16. 常用命令速查

```powershell
# 安装
winget search NATS
winget install -e --id NATSAuthors.NATSServer
winget install -e --id NATSAuthors.CLI

# 启动
nats-server
nats-server -c C:\nats\egoanchor-dev.conf

# 检查
nats-server --version
nats --version
nats server check connection

# 调试
nats sub "egoanchor.v1.>"
nats pub egoanchor.test "hello"
nats request egoanchor.v1.cmd.anchor.reset "{}"

# Windows Service
nats-server -c C:\nats\egoanchor-dev.conf --install
nats-server --service start
nats-server --service stop
nats-server --service restart
nats-server --service uninstall
```

## 17. 参考资料

- NATS Server 安装文档：https://docs.nats.io/running-a-nats-service/introduction/installation
- NATS Windows Service 文档：https://docs.nats.io/running-a-nats-service/introduction/windows_srv
- NATS 配置文档：https://docs.nats.io/running-a-nats-service/configuration
- NATS CLI 文档：https://docs.nats.io/using-nats/nats-tools/nats_cli
- Core NATS Pub/Sub 概念：https://docs.nats.io/nats-concepts/core-nats/pubsub
