# EgoAnchor 投影评分改造实施计划

## 0. 背景与不可违背的约束(交付前必读)

* 渲染输出是 **无光照纯反照率** (albedo),观测图带光照/阴影/高光/白平衡。任何颜色度量必须对"逐通道仿射光照变换(增益+偏置)"免疫。这是 [reprojection.py:177-181](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/reprojection.py#L177-L181) 注释已声明的前提。
* 目标物体是低纹理/单色/双色(cube、controller、blue_mouse 等,见 `EgoAnchor_Python/data/model/`)。 **梯度方向 inlier 不做、自适应 grad/color 选择器不做** ——理由:这些物体内部无稳定纹理边缘,梯度信号长期为空。
* 当前运行模式 `render_quality.mode = "score_only"`([defaults.toml:58](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/config/defaults.toml#L58)),只降分写 flag、不触发重注册。本计划 **不改变这个模式** ,因此下游阈值(`re_register_threshold`、`GOOD_SCORE_THRESH`、Unity gate)暂不重标,留作回放后单独处理。
* 分两个独立提交。**Commit A 与 Commit B 之间必须各自跑通测试再继续。**

验证命令(每个 commit 结束都要跑):

```powershell
cd p:\VSCode-Project\EgoAnchor\EgoAnchor_Python
pixi run python -m unittest egoanchor.tests.test_render_quality egoanchor.tests.test_pose_quality egoanchor.tests.test_debug_view
```

---

# Commit A:融合层根治 + 颜色降权(零风险止血)

目标:修掉"无几何证据帧虚攒 confidence"的 🔴 bug,并把颜色分降权。 **不动颜色度量算法本身** ,所以此 commit 风险最低,应先落地、先回放。

## A1. 修 confidence 虚攒(核心)

### 问题精确定义

[pose_quality.py:256-278](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/pose_quality.py#L256-L278) `_geometry_core`:当 reproj 和 depth 两路都 `valid=False` 时 `weight_sum=0` → 返回 `1.0`。两路同时 invalid 精确等价于"本帧渲染质量检查没运行"(状态为 `disabled` / `no_k` / `warmup` / `no_mask`,见 [quest_pose_pipeline.py:931-943](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/perception/quest_pose_pipeline.py#L931-L943))。后果是 `quality_score≈1.0` → 喂给 [ConfidenceAccumulator.update:83-91](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/pose_quality.py#L83-L91) 后 `consecutive_good` 持续 +1, **没被任何证据验证过的帧把 confidence 顶满** 。

### 采用方案:拆分"单帧信任"与"跨帧信用"(不要返回 0.5 魔法值)

保持 `_geometry_core` 无证据时返回 `1.0`(不拖累刚 register 成功、几何最可信的 warmup 帧),但 **无证据帧不得推进 confidence 累加器** 。

**改动 A1.1** — `ConfidenceAccumulator.update` 增加 `evidence` 参数([pose_quality.py:83](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/pose_quality.py#L83)):

```python
def update(self, quality_score: float, *, evidence: bool = True) -> float:
    """evidence=False 时原地保持计数(不累加不衰减),用于无几何证据帧。"""
    if not evidence:
        ramp = float(self.consecutive_good) / float(self.warmup_frames)
        return clamp01(0.5 + 0.5 * ramp)
    if clamp01(float(quality_score)) >= self.good_score_thresh:
        self.consecutive_good = min(self.consecutive_good + 1, self.warmup_frames)
    else:
        self.consecutive_good = max(0, self.consecutive_good - 2)
    ramp = float(self.consecutive_good) / float(self.warmup_frames)
    return clamp01(0.5 + 0.5 * ramp)
```

**改动 A1.2** — `score_observation_breakdown` 传 evidence 标志([pose_quality.py:174-192](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/pose_quality.py#L174-L192))。在已经拿到 `reprojection_valid`、`depth_valid` 之后:

```python
has_evidence = reprojection_valid or depth_valid
if not has_evidence:
    flags.append("quality_pending")
...
confidence_score = 1.0
if confidence_accumulator is not None:
    confidence_score = confidence_accumulator.update(quality_score, evidence=has_evidence)
```

注意:`reprojection_valid` 和 `depth_valid` 分别来自 [_reprojection_score:174](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/pose_quality.py#L174) 和 [_depth_score:175](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/pose_quality.py#L175),已是现成局部变量,无需新算。

**改动 A1.3** — `_geometry_core` 的 `weight_sum<=0` 分支 **保持返回 `1.0` 不变** ([pose_quality.py:276-277](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/pose_quality.py#L276-L277))。仅在上方补一行注释说明"无证据时几何核不拖累可信帧,confidence 累加由 evidence 标志兜底"。

## A2. 两权重清零保护(附带 🔴)

[PoseScoreConfig. **post_init** :58-65](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/pose_quality.py#L58-L65) 末尾追加:若 `reproj_weight + depth_weight <= 0`,回退默认 `0.5 / 0.5` 并 `LOGGER.warning` 一次(模块目前无 logger,用 `egoanchor.utils.get_logger(__name__, ...)`,参照 [render_quality.py:16](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/render_quality.py#L16) 写法)。理由:A3 要手调权重,防止误配成 0/0 静默退化为 core=1.0。

## A3. 颜色降权(Q11)

仅改配置默认值,不改代码逻辑:

| 文件                                                                                                                                                  | 位置                         | 改动                                                         |
| ----------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------- | ------------------------------------------------------------ |
| [defaults.toml:72-73](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/config/defaults.toml#L72-L73) | `[reliability.pose_score]` | `reproj_weight = 0.5 → 0.2`,`depth_weight = 0.5 → 0.8` |

`pipeline_factory.py:249-250` 用 `_cfg_get(..., 0.5)` 读取,会自动跟随 TOML, **无需改 factory 默认** (但建议把 factory 的 fallback 默认也同步成 0.2/0.8,保持一致)。

> 量级自检:几何平均下 color 给中性 0.5、权重 0.2 时拉力仅 `0.5^0.2≈0.87`;depth=0.9、权重 0.8 时 `0.9^0.8≈0.92`,合成≈0.80。颜色温和拖一点,depth 主导。符合预期。

## A4. Commit A 测试改动

文件 [test_pose_quality.py](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/tests/test_pose_quality.py):

* **修 `test_missing_depth_signal_does_not_enter_geometry_core`([:62-76](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/tests/test_pose_quality.py#L62-L76))** :`final_score > 0.7` 的断言保留(单帧仍被信任),但 **新增断言** :连续多次对同一个"无证据帧"调用 `score_observation_breakdown` 后,`confidence_score`  **不上涨** (验证 evidence=False 不累加)。
* **新增 `test_warmup_frames_do_not_ramp_confidence`** :构造无证据帧(`render_quality_status="warmup"`、`track_reprojection<0`、depth 无信号),循环 N 帧,断言 `confidence_score` 恒定。
* **新增 `test_both_weights_zero_falls_back`** :`PoseScoreConfig(reproj_weight=0, depth_weight=0)`,断言回退到 0.5/0.5(可断言两权重字段值,或断言有证据帧不再塌成满分)。
* **检查 `test_confidence_accumulator_warms_up_final_score`([:158-168](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/tests/test_pose_quality.py#L158-L168))** :它用的 `_track_observation()` 默认是否带证据。若默认无 depth/reproj 信号,加 evidence 参数后该测试会失效——需给它显式传 `track_reprojection=0.9, render_quality_depth_alignment=0.9` 保证 evidence=True,使 warmup 断言继续成立。**这是最容易被改漏的回归点,务必确认。**

## A5. Commit A 回放验收

用 `data/eval/*/` 现有序列(含手柄),确认:

* warmup 帧的 `conf` 子分不再单调爬升;
* 手柄稳定追踪靠 depth 维持高分,颜色降权后总分无异常跳变;
* debug 窗口 `flags` 出现 `quality_pending`(无证据帧标记)。

---

# Commit B:颜色度量换 ZNCC + 差异三联可视化

依赖 Commit A 已合入。本 commit 替换颜色算法、清三个 🟡 bug、加可视化。

## B1. 颜色度量替换为 ZNCC(Q9/Q14,清 3 个 bug)

### 替换范围

重写 [reprojection.py](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/reprojection.py) 的 `_color_similarity_lab:168-204`;**删除** `_align_luminance:206-221`、`_normalize_chroma:223-235`。保留 `_erode_intersection_core:237-253`(继续取核心区)和 `_ensure_rgb_u8:255-276`。

替换后这三个 🟡 bug 自动消失:① `_align_luminance` gain=0 塌缩;② `color_inlier_thresh` 一钮控两事;③ 色度中心化阈值过大。

### 新算法:逐通道 LAB ZNCC

在核心区(`_erode_intersection_core(intersection)`,空则退回 intersection)内,对 L/a/b 三通道分别做 **零均值归一化互相关** :

```
对通道 c ∈ {L, a, b}:
    x = render_core[:,c],  y = observed_core[:,c]
    x0 = x - mean(x);  y0 = y - mean(y)
    denom = sqrt(sum(x0^2) * sum(y0^2))
    若 denom < eps(该通道方差≈0,纯色)→ 该通道标记为"无信息",不计入
    否则 zncc_c = clip(sum(x0*y0)/denom, -1, 1);  s_c = (zncc_c + 1) / 2   # 映射到 0..1
color_similarity = 加权平均(有信息通道的 s_c, 权重: L=color_l_weight, a=1, b=1)
若所有通道都无信息(整块纯色)→ 见 B2 valid 处理
```

ZNCC 对每通道 `y = α·x + β`(α>0)结构免疫,无需任何对齐/阈值。`color_l_weight` 旧含义(LAB 的 L 权重)在 ZNCC 里仍合理保留,默认仍 0.5(可后续调 0.3,但本计划不强制改默认,减少变量)。

### B1.1 纯色区的 valid 处理(关键决策)

当核心区 **所有通道方差≈0** (纯单色物体,albedo 平):

* **方案(采纳)** :`ReprojectionResult.valid` 不因此变 False(valid 仍由面积条件决定),但 **颜色这一路在 `_geometry_core` 中被排除** 。实现上让 `RenderQualityResult.reprojection_score` 在"颜色无信息"时返回 `-1.0`(沿用现有哨兵语义,见 [render_quality.py:173](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/render_quality.py#L173) 和 [pose_quality.py:222-228](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/pose_quality.py#L222-L228) 对 `<0` 的处理),从而 `_reprojection_score` 走 `no_reprojection_signal → (1.0, valid=False)` 被几何核排除,depth 独扛。
* 为此需在 `ReprojectionResult` 增加一个布尔/状态:`color_informative: bool`(默认 True),`_color_similarity_lab` 的替代函数同时返回 similarity 和 informative 标志;`render_quality.py` 据此决定 reprojection_score 是否置 -1。
* **理由** :这是数学定义域兜底(0/0 无相关可算),不是"信号弱就策略退出"。比注入 0.5 干净,且不无谓拖累纯色物体的好 depth。

> 替代选项(若实现方嫌改 informative 标志麻烦):纯色区直接返回 similarity=0.5。配合 Commit A 的低权重(0.2),误差被 `0.5^0.2≈0.87` 限住,可接受。**二选一,优先 informative 排除方案。**

### B1.2 删除 `color_inlier_thresh` 配置链(4 处)

| 文件                                                                                                                                                                                                                                                                                                                   | 位置                                  | 改动                                                                                   |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- | -------------------------------------------------------------------------------------- |
| [reprojection.py:63-78](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/reprojection.py#L63-L78)                                                                                                                                                         | `ReprojectionChecker.__init__`      | 删 `color_inlier_thresh` 参数及 `self.color_inlier_thresh`;保留 `color_l_weight` |
| [reprojection.py:99-109](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/reprojection.py#L99-L109)                                                                                                                                                       | `_score_from_maps` / `score_maps` | 删 `color_inlier_thresh` 传参                                                        |
| [render_quality.py:82-98](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/render_quality.py#L82-L98)                                                                                                                                                     | `RenderQualityChecker.__init__`     | 删 `color_inlier_thresh` 参数与透传                                                  |
| [quest_pose_pipeline.py:75](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/perception/quest_pose_pipeline.py#L75), [:174](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/perception/quest_pose_pipeline.py#L174) | 构造参数与透传                        | 删 `render_quality_color_inlier_thresh`                                              |
| [pipeline_factory.py:291](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/perception/pipeline_factory.py#L291)                                                                                                                                                       | factory 读取                          | 删该行                                                                                 |
| [defaults.toml:68](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/config/defaults.toml#L68)                                                                                                                                                                         | `color_inlier_thresh = 18.0`        | 删除该行,并更新 `color_l_weight` 注释为 ZNCC 语义                                    |

`color_l_weight` 整条链保留。

### B1.3 simplify(顺手)

删 [reprojection.py:141](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/reprojection.py#L141) 与 :153 的重复 `clamp01`(`score` 已 clamp);清理替换后产生的死分支。

## B2. 重投影诊断字段(可选但建议)

若要在 debug 文本里分通道看 ZNCC,可给 `ReprojectionResult` 加 `zncc_l/zncc_a/zncc_b`(带默认值,纯诊断)。 **这些字段不入 protocol、不入 JSONL** ——确认过 [message_factories.py:45](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/runtime/message_factories.py#L45)、[runtime_log_writer.py:138](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/runtime/runtime_log_writer.py#L138)、[schemas.py:282](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/eval/io/schemas.py#L282) 只落 `score_reprojection`/`track_reprojection`,无需扩 schema,降低改动面。若实现方想省事,B2 可整体跳过。

## B3. 差异三联可视化(Q19)

### B3.1 共享 helper(防漂移,关键)

在 `ReprojectionChecker` 新增**公开**静态方法,例如 `color_diff_maps(render_rgb, observed_rgb, intersection) -> (aligned_render, observed, residual)`,内部复用与 ZNCC 评分**完全相同**的零均值/归一化变换,返回:对齐后的投影核心区图、观测核心区图、逐像素 LAB 残差图。`debug_view.py` 必须调用这个 helper, **禁止在 debug 侧重写一套归一化** 。

> 红线:差异图必须在归一化之后算。直接拿原始像素相减,会因渲染无光照、观测有光照而整片爆红,即使 pose 完美也误导调参。

### B3.2 扩展窗口布局

[make_score_debug_view:93-164](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/diagnostics/debug_view.py#L93-L164) 当前是 banner + 2×2。改为 banner + 2×3(或在现有四宫格下方新增一行三联)。三联面板:

1. `观测核心区 RGB`(原图)
2. `归一化对齐后的投影 RGB`(投影图)
3. `LAB 残差热力图`(`cv2.applyColorMap(..., COLORMAP_JET)`,差异图),并把 `color_similarity`(及 zncc 分,如启用)数值用 `_put_panel_title` 标在面板上。

* 数据通路已就绪:`render_quality_render_rgb`/`observed_rgb`/`render_mask`/`observed_mask` 已在 `FrameDiagnostics`(确认 [pipeline_types.py:161-177](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/perception/pipeline_types.py#L161-L177))且在 [quest_pose_pipeline.py:967-972](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/perception/quest_pose_pipeline.py#L967-L972) 已填充。
* `_score_banner_height:181-186` 与布局尺寸计算需相应更新,保证新增行有最小高度(顺带缓解 task_plan 提到的"banner cap 时四宫格塌 1px"🟢 问题:给每个面板设最小高度下限)。

### B3.3 None 兜底

任一图为 None 时用现有 `_ensure_bgr(None, "...")` 黑底占位,不得崩溃。

## B4. Commit B 测试改动

文件 [test_render_quality.py](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/tests/test_render_quality.py):

* **替换/重写**以下 4 个测的是被删逻辑的用例:`test_brightness_gain_invariant_stays_high`([:71](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/tests/test_render_quality.py#L71))、`test_double_peak_brightness_invariant`([:88](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/tests/test_render_quality.py#L88))、`test_white_balance_offset_invariant`([:107](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/tests/test_render_quality.py#L107))、`test_wrong_object_hue_scores_low`([:128](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/tests/test_render_quality.py#L128))。改成 ZNCC 断言:
  * `test_zncc_invariant_to_affine_lighting`:`observed = clip(render * α + β)`,断言 `color_similarity > 0.85`。
  * `test_zncc_flat_object_neutral_or_excluded`:整块纯色 → informative=False(或 similarity=0.5),按 B1.1 采纳方案断言。
  * `test_zncc_wrong_object_low`:结构不相关的错物体 → `color_similarity < 0.4`。
  * 保留 `test_reprojection_scores_lab_color_in_overlap`([:16](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/tests/test_render_quality.py#L16)) 与 `test_reprojection_does_not_mix_area_into_color_score`([:49](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/tests/test_render_quality.py#L49)) 的非颜色断言(mask_iou/area_ratio 部分),颜色断言按 ZNCC 调整。
* 注意 `_score_from_maps` 调用处都传了 `min_render_area_px=1`,删 `color_inlier_thresh` 后这些调用签名要同步。

文件 [test_debug_view.py](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/tests/test_debug_view.py):

* 新增 `test_score_debug_view_has_diff_triptych`:构造带 `render_quality_render_rgb`/`observed_rgb`/`render_mask`/`observed_mask` 的 `FrameDiagnostics`,断言输出尺寸符合新布局且不抛异常;可断言三联区域非全黑。
* 检查 `test_score_debug_view_reserves_top_banner`([:82](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/tests/test_debug_view.py#L82))、`test_score_debug_view_default_size_matches_config`([:102](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/tests/test_debug_view.py#L102)) 是否因布局变化失效,相应更新。

## B5. Commit B 回放验收

回放多物体序列(cube / controller / blue_mouse, **不只手柄** ):

* 转动物体看光照波动下 `reproj` 是否被 ZNCC 压平(不再随光照剧烈抖);
* 纯色物体(blue_mouse)确认颜色路按 B1.1 退场、depth 独扛,总分稳定;
* 差异三联图:pose 准时残差热力图整体冷色,人为给个错 pose 时残差结构性变红;
* 确认无需为换物体重调任何颜色阈值(验证"去旋钮→通用"达成)。

---

# 明确不做(守住简单初衷)

* ❌ 梯度方向 inlier(Q9)、❌ 自适应 grad/color 选择器(Q10)。
* ❌ 饱和度加权 hue 护栏: **仅当 B5 回放发现"锁到同形异色物体"才追加** ,作为与 ZNCC 取几何平均的固定轻量第二路(各自无信息时自动退中性),不是运行时选择器。当前不实现,留为 backlog。
* ❌ 下游阈值重标(`re_register_threshold` / `GOOD_SCORE_THRESH` / Unity gate):`score_only` 模式下风险低,切 `re_register` 或上 Unity 前再用回放统一重标。

---

# 落地顺序总览

1. **Commit A** :A1(confidence evidence 拆分)+ A2(权重清零保护)+ A3(降权 0.2/0.8)→ 改 A4 测试 → 跑测试 → A5 回放。
2. **Commit B** :B1(ZNCC 替换 + 删 inlier_thresh 链 + 纯色 informative 排除)+ B3(共享 helper + 三联图)→ 改 B4 测试 → 跑测试 → B5 多物体回放。

每个 commit 自包含、测试独立通过后再进入下一个。
