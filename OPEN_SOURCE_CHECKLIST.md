# 开源发布清单

这份清单记录把仓库推向公开前需要处理的事项。代码层面的清理与文档已经完成（见文末"本次已完成的清理"）；剩下的每一条都需要你拍板，因为它们涉及授权、身份信息或论文时序，不适合由工具自动决定。

## 一、发布阻断项（必须处理）

### 1. 选择 LICENSE

仓库目前没有任何 LICENSE 文件。建议 MIT 或 Apache-2.0（学术代码常用两者之一；Apache-2.0 额外提供专利授权条款）。注意：这只覆盖我们自己写的代码，`Cutie`、`FoundationPose`、`Fast-FoundationStereo`、`SAM3` 等外部依赖保留各自原有许可，且这些目录本来就不入库。

### 2. 清除内网拓扑与用户名

当前被 git 跟踪的文件里有实验室内网 IP 和机器用户名。发布前必须处理，复查命令：

```bash
git grep -nE "172\.24\.|192\.168\."
```

涉及位置：

| 位置 | 内容 |
| --- | --- |
| `EgoAnchor_Python/mutagen.yml` | 三台同步机器的用户名 + IP（多行） |
| `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Client/ServerEndpointConfig.cs` | RTX4090/RTX5090 两个预设 IP |
| `EgoAnchor_Unity/Assets/Scene/` 下四个 `.unity` | `ServerEndpointConfig` 的序列化预设与 `natsUrl`/`serverIp` 覆盖值 |
| `EgoAnchor_Unity/Assets/Resources/DevAgentSettings.asset` | 一个 192.168 地址 |
| `AGENTS.md` | 服务器 IP 记录 |

处理方式二选一：把 IP 改成占位符（`192.0.2.x` 文档地址或 `YOUR_BACKEND_IP`），或在发布版中不包含这些文件。`ServerEndpointConfig.cs` 与场景里序列化的值是部署配置，改前请注意场景会覆盖脚本默认值，两处都要改。本次已删除的 `Assets/Net Samples/` 里也硬编码过一个内网 IP，该隐患已随删除消失。

### 3. 内部工作文件不随仓库发布

- `AGENTS.md`（124 KB，AI 协作手册：署名决策、投稿策略、内网信息）
- `mutagen.yml`（同步配置，见上条）
- `.claude/`、`.mcp.json`（本次已取消跟踪并加入 `.gitignore`，本地文件保留）
- `EgoAnchor_Unity/.vscode/`、`EgoAnchor_Unity.slnx`（同上，已取消跟踪）

AGENTS.md 与 mutagen.yml 目前仍在跟踪中（考虑到你的日常工作流依赖它们），发布前执行 `git rm --cached AGENTS.md EgoAnchor_Python/mutagen.yml` 即可移出，本地文件不受影响。

### 4. `2026-EgoAnchor/`（论文工程）不发布

论文目录含作者实名与邮箱、基金号、审稿参考材料，且论文处于双盲评审流程。发布版不应包含该目录。注意 `EgoAnchor_Unity/README.md` 引用了其中的中文采集手册（`experiment_1_2_collection_manual_zh.md`），发布前把手册迁到开源仓库的文档目录并更新引用。

### 5. Unity 商业插件的再分发授权

工程内包含三个 Asset Store 商业插件的完整源码：

- **HighlightPlus**（Kronnect）——场景中的高亮与轨迹描边正在使用它；
- **Proxima**（Virtual Maker）——远程调试面板；
- **vTools 系列**（vFavorites/vFolders/vHierarchy/vInspector/vTabs）——纯编辑器增强。

公开再分发这些源码通常超出 Asset Store 授权范围。可选路径：换成开源或自写实现（需要同时改场景引用，工作量集中在 HighlightPlus）；或联系作者获得再分发授权；或仓库保持受限访问。`Assets/Packages/` 下的 NuGet DLL（NetMQ、NATS.Net、Google.Protobuf 等）多为 MIT/Apache 宽松许可，可以保留，但更干净的做法是不入库、依赖 NuGetForUnity 还原。

### 6. git 历史清洗或新建公开仓库

历史提交里存在上述 IP、个人化提交信息，论文相关内容也曾在历史中。两个做法：

- **推荐**：把当前快照作为公开仓库的初始提交，本仓库继续私有使用。省事，且不破坏现有工作流。
- 或者用 `git filter-repo` 清洗现有历史后公开。需要逐条核对历史里的敏感串，成本高。

## 二、建议完成

7. **权重获取说明**：`weights/` 不入库（正确），但 README 需要给出 YOLOE-26 权重、FFS checkpoint 的上游下载地址；也可以写一个下载脚本。
8. **pip 打包**：目前包不可 `pip install`（依赖 pixi 激活环境的 PYTHONPATH）。可加一个只含元数据的 `pyproject.toml`（注意与 `pixi.toml` 共存的解析顺序），把"作为可调用 API"的路径打通；或保持 pixi-only 并在 README 里说清楚。
9. **`pixi.toml` 作者字段**：`authors = ["zheliku <302734905@qq.com>"]`，发布前决定是否换成团队身份。
10. **Unity ProjectSettings**：`companyName: zheliku` 同上。
11. **模型资产许可核查**：`data/model/MetaQuestTouchPlus_*.glb` 是 Meta 官方控制器模型，公开分发前核对 Meta 的模型使用条款；自建物体的 GLB 没有问题。
12. **CI**：GitHub Actions 跑 `compileall` + unittest（eval 侧测试是纯 CPU 的，适合 CI；CUDA 构建任务留给本地）+ `dotnet build` 两个工程。
13. **英文版 README**：面向国际读者在公开前补一份，或至少在根 README 顶部加英文简介段。

## 三、可选

14. **色盲安全配色**：四方法配色中的绿/红对在绿色盲模拟下难区分（AGENTS.md 有记录）。要换需全文一次性换成 Okabe-Ito 并重跑全部论文图，开源前顺手决定。
15. **社区文件**：CONTRIBUTING.md、issue/PR 模板、CITATION.cff。
16. **发布归档**：打 tag 并在 Zenodo 拿 DOI，配合论文的"代码随论文发表"承诺。

## 本次已完成的清理

- 取消跟踪并 gitignore：`.claude/`、`.mcp.json`、`EgoAnchor_Unity/.vscode/`、`EgoAnchor_Unity.slnx`（本地文件均保留）。
- 删除冗余内容：`EgoAnchor_Python/samples/`（7 个 ZMQ 教程 demo）、`EgoAnchor_Python/tmp/`（14 个临时脚本与产物）、根目录空文件 `design.md`、`EgoAnchor_Unity/Assets/Net Samples/`（8 个早期 ZMQ 练习脚本与配套场景，含内网 IP）、`Assets/TutorialInfo/` 与 `Assets/Readme.asset`（URP 模板残留）。
- 修复构建场景列表：`EditorBuildSettings.asset` 原来指向已不存在的 `Assets/Scenes/EgoAnchor.unity`，已改回真实主场景 `Assets/Scene/EgoAnchor.unity`。
- 代码修复：NATS 发布计数器补互斥锁（主线程与后台 loop 线程同时递增）；`DynamicObjectAnchor.SetVisualHidden` 缩进修复；补齐 `QuestPosePipeline` 类 docstring 与 4 个测试方法的中文 docstring。
- 新增文档：根 README、三个子目录 README、本清单。
