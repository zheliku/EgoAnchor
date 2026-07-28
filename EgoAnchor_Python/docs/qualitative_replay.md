# Quest Link 六行连续轨迹图采集手册

这套流程只用于论文中的二维定性示意。它在 Unity Editor 的 Quest Link 串流模式下，同步保存左目原图、Quest 官方右手柄参考和四种实验一方法的显示位姿。数据直接写入电脑，不需要构建 APK，也不需要 ADB 导出。

最终图片默认使用 5 列，可设置为 2--20 列；默认显示 6 行：

1. `Passthrough`
2. `Quest Reference`（默认在图中分成两行）
3. `Arrival`
4. `Capture`
5. `One-Euro`
6. `EgoAnchor`

`selection.row_keys` 使用稳定的小写键 `passthrough`、`reference`、`arrival`、`capture`、`one-euro`、`egoanchor` 来选择和排列数据行。`selection.rows` 与它逐项对应，内容就是图左侧实际显示的文字，不再经过第二套标题映射；默认把 `Quest Reference` 和 `EgoAnchor (Ours)` 分为两行，避免标签区过宽。

每一列来自同一条原子样本。该列所有显示行共用左目图像、相机标定、图像时刻相机位姿和裁剪框。离线工具按固定的已保存帧间隔 `N` 取列，不按误差大小挑帧。

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

这里会生成原图、Quest Reference 和四张方法叠加图。默认使用 GLB 内嵌的 base-color 纹理、方法色轮廓和 XYZ 坐标轴。纹理渲染优先复用 VCD 同类的 nvdiffrast CUDA 路径，不可用时由 `auto` 回退到 CPU。先检查轮廓方向、尺度和位置是否合理。若所有轮廓都以相同方式偏离真实控制器，优先检查模型坐标、`apply_scale` 和相机标定，而不是用裁剪隐藏问题。

离线脚本不会把 Unity 的显示根节点 pose 直接套到原始 OpenCV GLB。它会读取四个 runtime 的 `flip`、`anchor-pos` 和 `anchor-rot` 配置指纹，先把 FoundationPose mesh 转到 Unity 实际渲染模型的局部坐标基，再投影到左目图像。XYZ 轴使用同一条 `K · P · C` 投影链，不能只套 display pose。以当前右手柄场景为例，Unity 使用 `flipY` 和 `anchor-rot=(0,0,180)`；恢复出的局部矩阵等价于把 GLB 顶点的 `x、y` 同时取反。最终矩阵会写入 `replay_grid.json` 的 `projection_mesh_local_matrix`，不能手工平移轮廓来替代这一步。

也可以指定样本：

```powershell
pixi run replay frame .\data\replay_capture\<capture_id> --sample-id 000000151
```

## 六、先找出可用的起始帧

`grid` 只会判断参考是否有效、四种方法是否有可显示 pose。它不能判断 YOLO 是否识别了正确物体。遇到“启动时先识别错、随后才恢复”的录制，先用 `inspect` 查看一段连续样本：

```powershell
pixi run replay inspect .\data\replay_capture\<capture_id> `
  --start-sample-id 000000245 --count 15 --frame-step 1
```

每条诊断记录会给出：

- `grid_complete` 和 `issues`：该帧是否具备六行绘图所需的数据；
- `has_output_pose`、`has_display_pose` 和 `pose_source`：当前显示来自新输出还是 hold-last；
- `reference_position_difference_cm`：方法显示位置相对 Quest 右手柄参考的位置差；
- `reference_rotation_difference_deg`：方法显示姿态相对 Quest 右手柄参考的最短角差。

后两项只用于发现明显的错误锁定和辅助人工看图，不是外部光学真值，也不能作为正式论文指标。正确做法是先看诊断找到候选切换点，再对切换前后分别运行 `frame` 检查原图和轮廓。

例如，本手册开发时检查的 `20260722_203752_143_controller_right` 中：

- `000000151` 四种方法都没有 display pose，因此不能作为首列；
- `000000190` 已经具备六行数据，但仍是错误目标；
- 错误锁定一直保持到 `000000251`；
- `000000252` 四种方法同时切换到正确目标，是这次 capture 的可用起点。

这也说明不能让脚本自动取“第一条完整帧”来代替人工确认识别结果。

## 七、生成连续轨迹图

默认使用 5 列，推荐先每隔 3 个已保存帧取一列：

```powershell
pixi run replay grid .\data\replay_capture\<capture_id> --columns 5 --frame-step 3
```

参数含义：

- `--columns 5`：默认显示 5 个连续时刻；可改为 2--20 的任意整数，例如 `--columns 6`。
- `--frame-step 3`：列索引为 `s, s+3, s+6, ...`。这里的 3 是已保存样本数，不是假定的 30 Hz 时间。
- `selection.start_sample_id` 留空且不写 `--start-sample-id` 时，工具从头寻找第一段参考有效且四种方法都有显示 pose 的完整序列。把起点写入 TOML 后可固定复现；命令行显式 `--start-sample-id` 优先覆盖它。
- 默认在第一行图像上方绘制横向 `Δt (s)` 时间轴，刻度与每列中心对齐，第一列固定为 `0.00`。左侧六个行名从上到下构成方法轴。时间来自每个样本实际记录的 `image_mono_ms`，不是 capture 的绝对时钟。
- 各列仍按统一宽度排列，因此横向几何间距不按时间比例缩放；刻度文字显示真实相对时间。可用 `--timeline-mode none` 关闭时间轴，或用 `--timeline-placement bottom` 移到底部。
- `--column-label` 是独立的逐列标题，默认是 `none`。需要审计样本时，可改为 `sample-id` 或 `both`，不会取代时间轴。

常用选择：

```powershell
# 看细小的逐帧抖动
pixi run replay grid .\data\replay_capture\<capture_id> --columns 5 --frame-step 1

# 看约 0.5 秒内更明显的连续轨迹
pixi run replay grid .\data\replay_capture\<capture_id> --columns 5 --frame-step 3

# 从人工确认过的正确识别时刻开始，仍保持固定 N 帧间隔
pixi run replay grid .\data\replay_capture\<capture_id> --columns 5 --frame-step 7 --start-sample-id 000000397
```

当前本机两份 capture 中，`20260722_203655_652_controller_right` 没有任何“平台参考和四种方法同时可显示”的完整样本，不能排成六行图。更适合观察差异的是下面这段。这也是本次最终图片实际使用的命令：

```powershell
pixi run replay grid .\data\replay_capture\20260723_125041_569_controller_right `
  --output .\data\replay_capture\20260723_104214_928_controller_right\rendered\jitter_user_targets_step77
```

这段使用 `000000761, 000000838, 000000915, 000000992, 000001069`，覆盖约 12.85 秒。`000000838` 是原 `820 + step 6` 的 0.75 秒列，`000000992` 是原 `890 + step 34` 的 4.25 秒列；两者分别处在这张图的第 2 列和第 4 列。窗口严格保持固定间隔 `N=77`，同时覆盖多个手柄视角。平台参考只用于同一 Quest 时间线内的定性诊断，不是外部真值，论文结论仍以 schema-v2 分析为准。

这组画面使用 TOML 默认配置，包含物体局部 XYZ 轴和 PDF 输出。

上面的短命令读取默认 TOML。下面是等价的详细命令，显式列出这次出图用到的主要参数，便于以后复现或只改其中一项：

```powershell
pixi run replay grid `
  .\data\replay_capture\20260723_125041_569_controller_right `
  --config .\src\egoanchor\qualitative_replay\config\qualitative_replay.toml `
  --columns 5 --frame-step 77 --start-sample-id 000000761 `
  --output .\data\replay_capture\20260723_104214_928_controller_right\rendered\jitter_user_targets_step77
```

`layout.gutter_px`、`layout.canvas_color_hex`、时间轴的字号/颜色/线宽/刻度长度/留白、四方法颜色、XYZ 三轴颜色和六个默认标题仍以 TOML 为完整配置入口；`--row-titles` 也可一次覆盖六个标题，但含换行时更适合写 TOML。`replay_grid.json` 会保存最终解析后的参数、实际/过滤后的 mesh 面数、纹理请求后端与实际后端、mesh 哈希、严格校验状态和 `configuration.effective_sha256`；复现时应同时保留 PNG、JSON 和所用 TOML。

也可以明确写出每一列的 sample id。所有 id 必须按 capture 顺序严格递增，并保持同一个样本间隔 `N`；工具会拒绝乱序或不等距的输入。这个形式只用于复现已经确定的图，不能借它逐列挑选各方法的极端帧：

```powershell
pixi run replay grid .\data\replay_capture\<capture_id> `
  --sample-ids 000000761 000000838 000000915 000000992 000001069
```

输出默认位于：

```text
data\replay_capture\<capture_id>\rendered\grid\replay_grid.png
data\replay_capture\<capture_id>\rendered\grid\replay_grid.json
data\replay_capture\<capture_id>\rendered\grid\replay_grid.pdf
```

`grid` 使用与 PNG 完全相同的最终网格像素默认生成单页 300 dpi PDF，可直接用 `\includegraphics` 导入 LaTeX。`replay_grid.json` 记录固定间隔 `N`、每列 `delta_time_ms`、顶部时间轴的刻度和来源、方法轴的行顺序、样本 id、Unity 图像帧号、参考来源 `transform/held`、裁剪方式、实际字体、模型透明度、XYZ 轴参数、PDF 导出状态、最终配置 SHA-256、配置和 mesh 来源以及模型局部变换矩阵。论文选用哪一段时，应保留这个文件。

## 八、TOML 出图配置

默认配置位于：

```text
EgoAnchor_Python/src/egoanchor/qualitative_replay/config/qualitative_replay.toml
```

直接运行 `replay frame` 或 `replay grid` 时会读取这份文件。也可以新建一个只包含改动项的 TOML，再通过 `--config` 叠加：

```powershell
pixi run replay grid .\data\replay_capture\<capture_id> `
  --config .\my_replay_figure.toml `
  --start-sample-id 000000397
```

合并顺序固定为“内置 TOML、自定义 TOML、命令行显式参数”。命令行没有出现的参数不会覆盖 TOML。未知表、拼错的字段、非法颜色和越界数值都会直接报错。

| TOML 字段                                  | 含义                                                                    |
| ------------------------------------------ | ----------------------------------------------------------------------- |
| `selection.columns`                      | 列数，范围 2--20，默认 5                                                |
| `selection.frame_step`                   | 相邻列的固定已保存样本间隔`N`                                         |
| `selection.start_sample_id`              | 默认首列 sample id；空字符串表示自动寻找完整起点                        |
| `selection.row_keys`                     | 数据行稳定键及顺序，与`selection.rows` 逐项对应                       |
| `selection.rows`                         | 左侧实际显示的标题，按原样绘制，可含`\n`                              |
| `layout.cell_width`                      | 每个图像单元的输出宽度                                                  |
| `layout.column_label`                    | `none`、`delta-t`、`sample-id` 或 `both`                        |
| `layout.label_font_size`                 | 左侧行名字号                                                            |
| `layout.column_font_size`                | 顶部列标题字号                                                          |
| `layout.label_padding_px`                | 行名区域的水平留白                                                      |
| `layout.label_min_width_px`              | 行名区域最小宽度                                                        |
| `layout.gutter_px`                       | 相邻单元间距                                                            |
| `layout.border_thickness_px`             | 单元边框线宽，0 表示关闭                                                |
| `layout.canvas_color_hex`                | 标签区和间隙的背景色                                                    |
| `layout.border_color_hex`                | 单元边框颜色                                                            |
| `layout.row_label_color_hex`             | 左侧行名颜色                                                            |
| `layout.column_label_color_hex`          | 顶部列标题颜色                                                          |
| `layout.header_padding_px`               | 列标题区域在字号之外增加的高度                                          |
| `layout.row_label_line_spacing_px`       | 多行行标题的行间距                                                      |
| `timeline.mode`                          | `none`、`relative-time` 或 `frame-sequence`；后者显示 sample 序号 |
| `timeline.placement`                     | `top` 或 `bottom`；默认放在第一行图像上方                           |
| `timeline.font_size_px`                  | 时间刻度和`Δt (s)` 标题字号                                          |
| `timeline.color_hex`                     | 时间轴线条、箭头、刻度和文字颜色                                        |
| `timeline.line_thickness_px`             | 时间轴主线和刻度线宽                                                    |
| `timeline.tick_length_px`                | 与每列中心对齐的刻度线长度                                              |
| `timeline.padding_px`                    | 时间轴内部以及与图像网格之间的留白                                      |
| `timeline.right_extension_px`            | 横轴箭头相对最后一列图像实际右边缘额外伸出的精确长度                    |
| `crop.mode`                              | `auto` 或 `fixed`                                                   |
| `crop.padding`                           | 自动裁剪留白比例                                                        |
| `crop.fixed_xywh`                        | 固定裁剪`[x, y, width, height]`；自动模式留空                         |
| `crop.aspect_ratio`                      | 自动裁剪和网格单元的宽高比；固定裁剪时不生效                            |
| `overlay.model_alpha`                    | 四方法模型填充不透明度                                                  |
| `overlay.reference_alpha`                | Quest Reference 模型填充不透明度                                        |
| `overlay.fill_mode`                      | `texture` 或 `color`；纹理缺失时回退纯色                            |
| `overlay.texture_backend`                | `auto`、`nvdiffrast` 或 `cpu`                                     |
| `overlay.texture_max_size_px`            | CUDA 纹理预滤波最长边；0 保留原始尺寸                                   |
| `overlay.minimum_component_faces`        | 保留不连通 mesh 组件的最小面数；1 完整保留                              |
| `overlay.texture_brightness`             | unlit base-color 纹理亮度倍率                                           |
| `overlay.model_color_hex`                | 纯色模式或纹理缺失时的回退填充色                                        |
| `overlay.method_colors_hex`              | Arrival、Capture、One-Euro、EgoAnchor 的轮廓色                          |
| `overlay.method_contour_thickness_px`    | 四种方法的彩色轮廓线宽                                                  |
| `overlay.reference_contour_color_hex`    | Quest Reference 内轮廓颜色                                              |
| `overlay.reference_contour_thickness_px` | Quest Reference 内轮廓线宽                                              |
| `overlay.reference_halo_color_hex`       | Quest Reference 外沿颜色                                                |
| `overlay.reference_halo_thickness_px`    | Quest Reference 外沿总线宽                                              |
| `axes.enabled`                           | 是否显示 XYZ 坐标轴                                                     |
| `axes.length_m`                          | 坐标轴物理长度，单位米                                                  |
| `axes.thickness_px`                      | 轴线宽                                                                  |
| `axes.label_font_size_px`                | X/Y/Z 端点字号                                                          |
| `axes.colors_hex`                        | X、Y、Z 三根轴的颜色                                                    |
| `axes.halo_color_hex`                    | 轴线、箭头和文字外沿颜色                                                |
| `axes.halo_thickness_px`                 | 坐标轴和文字外沿总线宽                                                  |
| `axes.tip_length`                        | 箭头尖端长度占轴长比例                                                  |
| `axes.label_offset_px`                   | XYZ 文字相对端点的`[x, y]` 偏移                                       |
| `axes.origin_color_hex`                  | 坐标轴原点颜色                                                          |
| `axes.origin_radius_px`                  | 坐标轴原点半径                                                          |

例如，只想减淡模型、缩短坐标轴并只保留四行，可以创建：

```toml
[selection]
rows = ["passthrough", "reference", "arrival", "egoanchor"] # 只显示需要比较的四行。

[overlay]
model_alpha = 0.10 # 降低手柄模型填充强度。
method_contour_thickness_px = 4 # 加粗四种方法的彩色轮廓。

[axes]
length_m = 0.02 # 缩短 XYZ 轴，减少对模型的遮挡。
thickness_px = 2 # 使用较细轴线。
```

默认画面仍使用真实左目 RGB。半透明层只覆盖模型投影区域。四种方法严格复用论文图 2 在 `egoanchor.eval.experiments.experiment_1_2.figures` 中的颜色：Arrival `#4C78A8`、Capture `#59A14F`、One-Euro `#F28E2B`、EgoAnchor `#E15759`。capture 清单中原始记录的颜色只作为 provenance 保留，不再决定论文 replay 图的轮廓色。XYZ 轴采用带白色 halo 的 X 红、Y 绿、Z 蓝，并带字母标记，避免与方法轮廓颜色混淆。纹理后端的颜色是 unlit base-color；它不声称复现 Unity 的法线、金属度、粗糙度和光照。

## 九、自定义显示行、裁剪和文字

### 只输出指定行

用 `--row-keys` 可临时改写数据行顺序。可选值固定为 `passthrough`、`reference`、`arrival`、`capture`、`one-euro`、`egoanchor`；此时标题使用这些键的默认标题。若要修改实际显示文字，直接编辑 TOML 的 `selection.rows`：

```powershell
pixi run replay grid .\data\replay_capture\<capture_id> `
  --columns 5 --frame-step 7 --start-sample-id 000000397 `
  --row-keys reference arrival one-euro egoanchor
```

不写 `--row-keys` 时使用 TOML 中逐项对应的 `selection.row_keys` 和 `selection.rows`。

### 调整自动裁剪

默认裁剪以每列 `reference` 质心为中心，所有列使用相同裁剪尺寸，同一列的所有行共享同一个框。`--crop-padding` 控制轮廓外的留白比例：

```powershell
# 更紧凑
--crop-padding 0.20

# 保留更多背景
--crop-padding 0.60
```

如果需要所有列都使用完全相同的原图坐标范围，可指定 `x y width height`：

```powershell
--crop 96 48 448 336
```

固定裁剪必须落在原图边界内，而且必须完整包含所有已选行的模型、轴线、箭头和端点字母；发生截断时工具会报出具体 sample 和行。使用 `--crop` 时不能同时写 `--crop-padding`。工具会把最终每列的 `crop_xywh` 写入 JSON，不能为不同方法单独设置裁剪。

### 调整文字

```powershell
--label-font-size 24 `
--column-label sample-id `
--column-font-size 16 `
--label-padding 8
```

- `--label-font-size` 控制左侧行名；
- `--column-font-size` 控制 sample id 或 `Δt`；
- `--label-padding` 和 `--label-min-width` 控制行名区域宽度；默认仅保留足以容纳最长名称的窄边距；
- `--timeline-mode relative-time` 以所选首列为零点显示横向时间轴，也是 TOML 默认值；`--timeline-mode frame-sequence` 显示可直接用于 `--start-sample-id` 的 sample 序号；
- `--timeline-placement top` 把时间轴放在第一行图像上方，改为 `bottom` 可移到网格底部；
- `--column-label sample-id` 可额外显示样本 id，`--column-label none` 不显示独立列标题。

### 顶部时间轴和方法纵轴

默认 `timeline.placement = "top"`。横轴从左上方第一列图像单元的左边界开始，向右表示相对首列的 `Δt (s)`；时间刻度仍放在各列中心，因为每列代表一个离散样本。纵轴从同一个左上角向下，行中心刻度依次对应 Passthrough、Quest Reference、Arrival、Capture、One-Euro 和 EgoAnchor。左侧文字是类别型行标签，不是数值误差轴。

默认轴线宽为 3 px、刻度长为 10 px，横轴从最后一列图像的实际右边缘精确延伸 64 px 后再绘制箭头。`timeline.line_thickness_px`、`timeline.tick_length_px` 和 `timeline.right_extension_px` 都可在 TOML 中调整。`coordinate_axes` sidecar 会记录图像网格右边缘、原点、横轴终点、额外延伸长度以及横纵刻度中心，可直接核对实际延伸量。

### 调整半透明模型、轮廓和坐标轴

```powershell
--model-alpha 0.12 `
--model-color "#D8DCE2" `
--reference-alpha 0.08 `
--method-contour-thickness 3 `
--reference-contour-thickness 3 `
--reference-halo-thickness 6 `
--fill-mode texture --texture-backend auto --texture-max-size 0 `
--minimum-component-faces 1 `
--axis-length 0.03 `
--axis-thickness 2 `
--axis-label-font-size 10
```

`--axis-length` 的单位是米，其余线宽是原始保存图像的像素。论文图应显式使用 `--axes`；自动裁剪会把坐标轴和标签一并计入范围。

`Quest Reference` 的换行不需要改代码，直接在 TOML 中修改固定六项标题即可：

```toml
[selection]
row_keys = ["passthrough", "reference", "arrival", "capture", "one-euro", "egoanchor"] # 数据源稳定键。
rows = ["Passthrough", "Quest\nReference", "Arrival", "Capture", "One-Euro", "EgoAnchor\n(Ours)"] # 每一项即图中实际显示的标题。

[layout]
row_label_line_spacing_px = 4 # 两行之间的像素间距。
```

也可以用 `--row-titles` 一次覆盖六项标题；命令行中包含换行时要按当前 shell 的字符串转义规则处理。

### 另一段完整示例

```powershell
pixi run replay grid .\data\replay_capture\20260722_203752_143_controller_right `
  --columns 5 --frame-step 7 --start-sample-id 000000397 `
  --row-keys passthrough reference arrival capture one-euro egoanchor `
  --crop-padding 0.35 --cell-width 320 `
  --column-label none --timeline-mode relative-time --timeline-placement top `
  --label-font-size 30 --column-font-size 30 --label-padding 8 `
  --model-alpha 0.18 --axis-length 0.06 --axis-thickness 2 --axis-label-font-size 16 `
  --output .\data\replay_capture\20260722_203752_143_controller_right\rendered\paper_grid_axes
```

## 十、裁剪和比较规则

- 同一列六行使用同一张原始 RGB，不分别换背景。
- 同一列六行使用完全相同的裁剪框；不同方法不能单独放大或平移。
- 所有列默认使用同样大小的 4:3 裁剪框，比例由 `crop.aspect_ratio` 配置；裁剪中心跟随 Quest Reference，减少头动造成的背景大位移。
- 裁剪框同时覆盖参考和四种方法的轮廓，不能把偏移较大的方法裁掉。
- 蓝、绿、橙、红分别对应 Arrival-Hold、Capture-Hold、One-Euro Interpolation 和 EgoAnchor；Quest Reference 使用带白色外沿的深灰轮廓。`transform/held` 只保留在 sidecar 中，不写进图片。
- X、Y、Z 轴分别使用红、绿、蓝，并通过白色 halo 和端点字母与方法轮廓区分。

这张图表达的是：在同一段 Quest Link 录制中，固定间隔的连续时刻下，各方法相对于平台参考的二维视觉稳定性。它不使用“挑最抖两帧”的策略，也不把像素偏移当作正式配对指标。

## 十一、常见问题

### 网格提示找不到完整连续序列

新错误信息会列出具体 sample id，并区分 `reference invalid` 与 `missing display pose`。先确认右手柄进入 Play Mode 后至少被移动过一次，再用 `inspect` 检查候选起点。若起始阶段参考无效，可以指定稍后的 `--start-sample-id`；不要把 `valid=false` 的启动帧硬当作参考。

### 数据完整，但轮廓仍落在错误物体上

这是识别语义错误，不是网格排版错误。运行 `inspect` 找出 pose 突然切换的附近帧，再用 `frame --sample-id` 比较切换前后。确认正确后，把后一帧写入 `--start-sample-id`。脚本不会根据参考误差自动跳过一段，因为这种自动筛选会把人工选择伪装成固定协议。

### `reference_held_samples` 很多

这是静止手柄的预期行为。只要前面已经有一次有效追踪，held 状态仍使用最近一次有效 Prefab Transform，不会变成 `null`。

### 轮廓没有出现在图像内

先运行 `frame` 检查指定样本。常见原因是物体不在左目视野、模型尺度错误、对象配置不匹配，或录制前四路模型尚未出现。

### 坐标轴超出图像或固定裁剪框

工具不会输出被截断的半根坐标轴。先减小 TOML 中的 `axes.length_m`，或改用更大的固定裁剪框。自动裁剪已经包含箭头和 X/Y/Z 标签，通常不需要额外处理。

### 轮廓存在，但方向或位置与 VR 中看到的不一致

不要继续生成 grid。先确认 `frame` 使用的是当前代码，并检查 capture 中四路 `runtime_configuration_fingerprint` 的 `flip`、`anchor-pos`、`anchor-rot` 是否一致。脚本会拒绝四路局部补偿不同的数据。当前右手柄场景正确恢复出的 `projection_mesh_local_matrix` 接近：

```text
-1  0  0  0
 0 -1  0  0
 0  0  1  0
 0  0  0  1
```

这是 Unity FBX 与 Python GLB 的对象局部基转换，不是对结果图做人工旋转。

### 白色握把上有黑色斑点和条纹

旧版本曾把全部投影三角形一次性交给 OpenCV `fillPoly`。重叠三角形触发奇偶填充后，实心 silhouette 会出现大量小孔，背景从孔中漏出，看起来像黑斑或条纹。这不是 GLB 纹理细节，也不是 Quest 参考失活或坐标转换造成的。

当前实现逐三角形累积并集，其并集语义与 VCD 的实心 raster mask 一致。若新生成的图片仍有同类斑点，先确认运行的是当前分支代码，再重新执行 `replay frame` 或 `replay grid`。不要用 `texture_max_size_px`、`minimum_component_faces` 或纯色填充掩盖这类 mask 错误。

### 出现队列丢帧

完整保存的帧数较多，磁盘写入跟不上时 `queue_dropped` 会大于 0。优先关闭占用磁盘的软件，缩短单次录制，或在 Inspector 中增大 `writerQueueCapacity`。论文素材应重新采集到严格校验通过，而不是使用 `--allow-incomplete` 绕过。

### 想换一段更能说明问题的轨迹

可以查看完整序列后人工指定 `--start-sample-id`，但必须继续使用固定 `--frame-step`，并在图注中说明这是二维定性示意。不要按每种方法各自的最大误差选择不同帧。

## 十二、论文表述边界

这套图只能标为基于 Quest Link 同步 replay 的二维定性可视化。Quest 控制器参考不是外部光学真值，逐帧图也不替代 schema-v2 工作簿生成的定量指标。正文或图注应同时说明平台参考与头显共享追踪系统，可能隐藏共模世界漂移。
