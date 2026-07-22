# Quest Link 六行连续轨迹图采集手册

这套流程只用于论文中的二维定性示意。它在 Unity Editor 的 Quest Link 串流模式下，同步保存左目原图、Quest 官方右手柄参考和四种实验一方法的显示位姿。数据直接写入电脑，不需要构建 APK，也不需要 ADB 导出。

最终图片固定为 5-10 列、6 行：

1. Input RGB
2. Quest Reference
3. Arrival-Hold
4. Capture-Hold
5. One-Euro Interpolation
6. EgoAnchor

每一列来自同一条原子样本，六行共用左目图像、相机标定、图像时刻相机位姿和裁剪框。离线工具按固定的已保存帧间隔 `N` 取列，不按误差大小挑帧。

## 一、采集前准备

1. 将 Quest 通过 Link 连接到电脑，确认 Unity Editor 进入 Play Mode 后能够正常显示头显画面和 Passthrough 左目图像。
2. 使用右手 Quest 控制器作为被检测对象和平台参考。专用场景已把平台参考绑定到：

   ```text
   OVRCameraRig/OVRInteractionComprehensive/OVRControllerVisualRight/OVRControllerPrefab
   ```

3. 控制器放在一个不会移动的位置。采集时只移动头显，不移动控制器。否则图片同时包含物体真实运动与锚点抖动，无法解释。
4. 在 PowerShell 中启动 `controller_right` 感知服务：

   ```powershell
   cd P:\VSCode-Project\EgoAnchor\EgoAnchor_Python
   pixi run controller_right
   ```

5. 在 Unity 中打开：

   ```text
   EgoAnchor_Unity/Assets/Scene/EgoAnchor-ReplayCapture.unity
   ```

不要打开正式实验一/二采集场景来代替它。Replay 场景只有四种实验一方法，不写正式 schema-v2 数据。

## 二、右手柄参考的实际语义

Quest 右手柄静止一段时间后可能进入非激活状态。这里不会把参考写成 `null`，也不会从另一个 OVR API 重新计算一套 pose：

- 手柄当前激活并可追踪时，从上述 Prefab 的 `Transform` 刷新 world pose，记录为 `fresh=true`、`pose_source=transform`。
- 手柄静止失活后，继续使用最近一次有效的同一个 `Transform` pose，记录为 `keep_alive=true`、`pose_source=held`。
- 进入 Play Mode 后从未获得过有效参考时，才记录为 `valid=false`。这些启动帧会完整保存，但不会被六行网格选中。

因此，进入 Play Mode 后先轻微移动一下右手柄，确认平台至少获得过一次有效追踪；随后把手柄放稳，再开始头动。手柄之后因静止失活没有关系，录制器会一直保持上一次有效参考。

Quest Reference 只是同一 Quest 追踪系统提供的平台参考，不是外部光学真值。它可能隐藏头显与控制器的共模世界漂移。

## 三、录制完整序列

1. 保持 Python 服务运行，点击 Unity Editor 的 Play。
2. 场景中的 `ReplayCaptureRecorder` 会自动开始录制。`captureFps=0`，表示保存 `QuestStreamPublisher` 产生的每一条已编码左目帧，不主动降采样。
3. 轻微移动右手柄一次，让平台参考进入 `fresh` 状态；然后把它放回固定位置。
4. 等待四种虚拟模型都出现，并确认它们叠加在真实控制器附近。
5. 做一次平滑、可解释的头动。建议持续 5-10 秒，可采用以下任一种：

   - 左到右平移，再停住；
   - 小幅左右转头，再回到中间；
   - 缓慢靠近，再退回原位。

6. 不要追求每次重复同一条头动轨迹。四种方法在同一个 Play Mode 中并行运行，每条已保存样本已经同时包含四路显示 pose 和官方参考。
7. 结束后点击 Unity Editor 的 Stop。组件会停止接收新帧，排空后台写入队列，然后发布最终目录。

默认输出位置：

```text
P:\VSCode-Project\EgoAnchor\EgoAnchor_Python\data\replay_capture\<capture_id>\
```

一个完成目录至少包含：

```text
replay_manifest.json
samples.jsonl
images\000000001.jpg
images\000000002.jpg
...
```

正常完成后目录名不带后缀。若看到 `<capture_id>.inprogress`，说明 Unity 尚未停止、写入未完成或发布失败，不要把它用于论文图片。

## 四、检查录制是否完整

先列出最近的 capture：

```powershell
cd P:\VSCode-Project\EgoAnchor\EgoAnchor_Python
Get-ChildItem .\data\replay_capture | Sort-Object LastWriteTime -Descending
```

执行契约校验：

```powershell
pixi run replay validate .\data\replay_capture\<capture_id>
```

严格校验要求：

- capture 已完成发布；
- JPEG 数量、字节数和 JSONL 行数一致；
- 队列丢帧、相机 pose 缺失、标定缺失和写入失败均为 0；
- 参考绑定为指定右手柄 Prefab；
- 四种方法顺序、颜色和投影矩阵完整；
- 清单中的 `reference_held_samples` 与逐帧状态一致。

`reference_held_samples` 大于 0 是正常现象，表示静止手柄使用了最近一次有效 pose；它不是丢帧或错误。

## 五、先做单帧贴合检查

生成第一条“Quest 参考和四种方法都有效”的同步样本：

```powershell
pixi run replay frame .\data\replay_capture\<capture_id>
```

输出默认位于：

```text
data\replay_capture\<capture_id>\rendered\frame\
```

这里会生成原图、Quest Reference 和四张方法叠加图。先检查轮廓方向、尺度和位置是否合理。若所有轮廓都以相同方式偏离真实控制器，优先检查模型坐标、`apply_scale` 和相机标定，而不是用裁剪隐藏问题。

也可以指定样本：

```powershell
pixi run replay frame .\data\replay_capture\<capture_id> --sample-id 000000151
```

## 六、生成 5-10 列、6 行论文图

推荐先用 8 列、每隔 3 个已保存帧取一列：

```powershell
pixi run replay grid .\data\replay_capture\<capture_id> --columns 8 --frame-step 3
```

参数含义：

- `--columns 8`：最终显示 8 个连续时刻；允许范围为 5-10。
- `--frame-step 3`：列索引为 `s, s+3, s+6, ...`。这里的 3 是已保存样本数，不是假定的 30 Hz 时间。
- 不写 `--start-sample-id` 时，工具从头寻找第一段参考有效且四种方法都有显示 pose 的完整序列。
- 每列标题使用真实 `image_mono_ms` 显示相对时间，因此即使实际帧率波动，时间轴仍是诚实的。

常用选择：

```powershell
# 看细小的逐帧抖动
pixi run replay grid .\data\replay_capture\<capture_id> --columns 10 --frame-step 1

# 看约 0.5-1 秒内更明显的连续轨迹
pixi run replay grid .\data\replay_capture\<capture_id> --columns 8 --frame-step 3

# 从人工确认过的时刻开始，仍保持固定 N 帧间隔
pixi run replay grid .\data\replay_capture\<capture_id> --columns 8 --frame-step 4 --start-sample-id 000000151
```

输出默认位于：

```text
data\replay_capture\<capture_id>\rendered\grid\replay_grid.png
data\replay_capture\<capture_id>\rendered\grid\replay_grid.json
```

`replay_grid.json` 记录每列的样本索引、样本 id、Unity 图像帧号、真实相对时间、参考来源 `transform/held` 和裁剪框。论文选用哪一段时，应保留这个文件作为选择依据。

## 七、裁剪和比较规则

- 同一列六行使用同一张原始 RGB，不分别换背景。
- 同一列六行使用完全相同的裁剪框；不同方法不能单独放大或平移。
- 所有列使用同样大小的 4:3 裁剪框，裁剪中心跟随 Quest Reference，减少头动造成的背景大位移。
- 裁剪框同时覆盖参考和四种方法的轮廓，不能把偏移较大的方法裁掉。
- 蓝、绿、橙、红分别对应 Arrival-Hold、Capture-Hold、One-Euro Interpolation 和 EgoAnchor；Quest Reference 使用带白色外沿的深灰轮廓，并在左上角显示 `LIVE` 或 `HELD`。

这张图表达的是：在同一段 Quest Link 录制中，固定间隔的连续时刻下，各方法相对于平台参考的二维视觉稳定性。它不使用“挑最抖两帧”的策略，也不把像素偏移当作正式配对指标。

## 八、常见问题

### 网格提示找不到完整连续序列

先确认右手柄进入 Play Mode 后至少被移动过一次。若起始阶段参考无效，可以指定稍后的 `--start-sample-id`；不要把 `valid=false` 的启动帧硬当作参考。

### `reference_held_samples` 很多

这是静止手柄的预期行为。只要前面已经有一次有效追踪，held 状态仍使用最近一次有效 Prefab Transform，不会变成 `null`。

### 轮廓没有出现在图像内

先运行 `frame` 检查指定样本。常见原因是物体不在左目视野、模型尺度错误、对象配置不匹配，或录制前四路模型尚未出现。

### 出现队列丢帧

完整保存的帧数较多，磁盘写入跟不上时 `queue_dropped` 会大于 0。优先关闭占用磁盘的软件，缩短单次录制，或在 Inspector 中增大 `writerQueueCapacity`。论文素材应重新采集到严格校验通过，而不是使用 `--allow-incomplete` 绕过。

### 想换一段更能说明问题的轨迹

可以查看完整序列后人工指定 `--start-sample-id`，但必须继续使用固定 `--frame-step`，并在图注中说明这是二维定性示意。不要按每种方法各自的最大误差选择不同帧。

## 九、论文表述边界

这套图只能标为基于 Quest Link 同步 replay 的二维定性可视化。Quest 控制器参考不是外部光学真值，逐帧图也不替代 schema-v2 工作簿生成的定量指标。正文或图注应同时说明平台参考与头显共享追踪系统，可能隐藏共模世界漂移。
