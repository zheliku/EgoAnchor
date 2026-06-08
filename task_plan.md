
## Code-review 发现(按严重度排序)

### 🔴 高:无几何证据的帧反而得满分(融合层真实回归)

[pose_quality.py:177](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/pose_quality.py#L177) `_geometry_core` 在 reproj 和 depth **都 invalid** 时返回 `1.0`。触发链:TRACK 帧 + `track_reprojection<0` + `render_quality_expected=False` → reproj 返回 `(1.0, valid=False)` 被排除;depth 无信号 → `(0.5, valid=False)` 被排除;`weight_sum=0` → core=1.0;mask/jump 正常 → modulator≈1 →  **quality≈1.0** 。

后果:渲染质量未就绪/被禁用时, **任意 pose(包括错的)都拿 ~1.0 可靠性** ,通过 `GOOD_SCORE_THRESH=0.6` 积累 confidence、通过 Unity gate。旧的加权和模型会用中性 0.5 项把它压到中档。你的新测试 `test_missing_depth_signal_does_not_enter_geometry_core` 断言 `final_score > 0.7` ——  **等于把这个回归固化成了"预期行为"** ,需要重新审视。

> 附带:[pose_quality.py:62](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/pose_quality.py#L62) 两个权重都允许为 0,配错时同样静默退化为 1.0,无告警。

### 🟡 中:`_align_luminance` 观测亮度平坦时 gain=0 塌缩

[reprojection.py:219](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/reprojection.py#L219) 当观测核心区 L 近乎均匀(过曝白面/平光表面,`observed_p75-observed_p25≈0`)且 `render_span≥3` → `gain=0` → 所有渲染 L 映射成同一常数 = 观测 L → ΔL≡0 → L 项(权重 0.5)完全失效 → inlier 比例虚高 →  **错物体/遮挡也能当颜色 inlier** 。

### 🟡 中:`color_inlier_thresh` 一个旋钮控两件事

[reprojection.py:232](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/reprojection.py#L232) `inlier_thresh` 既是逐像素 inlier 距离,又是色度中心化的判定边界 `max(30, 2*thresh)`。调大它想"放宽容忍"时, **同时悄悄关掉了色相区分** (中心化阈值升到 80,几乎总是触发,把全局 a/b 偏移抹掉)→ 错色物体不再被惩罚。

### 🟡 中:色度中心化阈值(默认 36)过大

[reprojection.py:232](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/reprojection.py#L232) `center_delta ≤ 36` 就去偏。LAB 的 a/b 跨度约 ±127,系统性偏 36 以内的"中等错色物体"会被抹掉色差当 inlier → "惩罚错物体"分支只对极端错色生效。

### 🟢 低:下游阈值未随几何平均量级重标定

* [quest_pose_pipeline.py](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/perception/quest_pose_pipeline.py) `re_register_threshold=0.35`(仅 re_register 模式,当前 score_only 不触发)
* `GOOD_SCORE_THRESH=0.6`
* Unity `ReliabilityGate` 的 `0.35/0.12`

inlier 比例分布和几何平均量级都和旧加权和不同,这些常数没重标。**当前 score_only 模式下风险低,但切 re_register 或上 Unity 前必须回放重标。**

### 🟢 低:横幅被 cap 时四宫格塌成 1px

[debug_view.py:105](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/diagnostics/debug_view.py#L105) 窗口过小或 flag 行过多时 `banner_h` 被钳到 `height-2`,`half_h=1`,四宫格塌成 1px 而文本仍画。纯诊断,无崩溃,低优先级。

---

## 最终落地方案

分两阶段。**阶段一修融合层 bug(独立、紧急);阶段二把颜色度量换成最终的梯度方向版(顺带消灭中findings 3/4/5)。**

### 阶段一:修融合层(改 [pose_quality.py](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/pose_quality.py))

 **A1. 无证据帧不得给满分** (对应🔴)。`_geometry_core` 的 `weight_sum<=0` 分支不要返回 1.0。改为返回 **中性 0.5** ,并追加 flag `no_geometry_evidence`。这恢复旧模型"无信号→中性"的安全语义,且与 depth 的中性 0.5 哲学一致。同步**修正测试** `test_missing_depth_signal_does_not_enter_geometry_core`:断言从 `final_score>0.7` 改为落在中性档(~0.45–0.55),不再把回归固化为预期。

 **A2. 两权重全 0 保护** (对应🔴附带)。`PoseScoreConfig.__post_init__` 里若 `reproj_weight+depth_weight==0`,回退到默认 0.5/0.5 并记一条 warning,避免静默失效。

### 阶段二:颜色度量换成"梯度方向 inlier(主)+ 通用颜色 tiebreaker(辅)"(改 [reprojection.py](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/reprojection.py))

这一步把当前 `_color_similarity_lab`(仿射 L + 去偏 + inlier)整体替换。 **替换后,findings 3、4、5 自动消失** (不再有 `_align_luminance` 的 gain 塌缩、不再有 `inlier_thresh` 双重职责、不再有色度中心化阈值)。

**B1. `_gradient_inlier_score`(主)** — 渲染侧自适应闸门 + 方向 inlier 比例:

```
core = _erode_intersection_core(render & observed)
灰度 → Sobel gx,gy → mag, theta
thresh = percentile(render_mag[core], grad_percentile)   # 自适应,不挑物体
gate = core ∩ (render_mag > thresh)
若 count(gate) < edge_min_pixels: return 0.5             # 信号不足→中性(交给 mask/depth)
a = |cos(theta_render[gate] - theta_obs[gate])|          # mod π,吸收明暗翻转
score_grad = mean(a > cos(edge_angle_tol_deg))           # inlier 比例,容忍尖锐遮挡
```

* **渲染侧闸门** (只用 `render_mag` 选像素):手的边缘因渲染侧无对应而进不来。
* **inlier 比例** :尖锐/柔和遮挡都只是少数 outlier,被天然容忍。
* **自适应百分位阈值 + 只看方向** :光照不变、不挑物体。

**B2. `_color_tiebreaker_score`(辅,通用)** — 核心区转 HSV,按**饱和度加权**算 hue 直方图相关;低饱和(黑/白/灰/金属)权重≈0 → 自动退场,返回中性。 **不做任何对齐** ,对所有物体一视同仁。

 **B3. 合成** :`color_similarity = clamp01(score_grad^edge_exp · score_color^color_exp)`,默认 `edge_exp=0.85, color_exp=0.15`(梯度主导)。

 **B4. 诊断字段** :`ReprojectionResult` 加 `grad_score`/`color_tiebreak_score`(带默认值,纯诊断),经 `RenderQualityResult`→`FrameDiagnostics` 传到 debug 文本,显示 `reproj=0.82 (grad=0.86 col=0.55)`。

 **B5. 参数与配置** :`__init__` 删 `color_l_weight`/`color_inlier_thresh`,加 `grad_percentile=60`、`edge_angle_tol_deg=22.5`、`edge_min_pixels=50`、`edge_exp=0.85`、`color_exp=0.15`、`color_sat_min=30`。同步 4 处配置链([render_quality.py:88-97](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/render_quality.py#L88-L97)、[pipeline_factory.py](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/perception/pipeline_factory.py)、[quest_pose_pipeline.py:74-75](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/perception/quest_pose_pipeline.py#L74-L75)、[defaults.toml:67-68](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/config/defaults.toml#L67-L68))。

 **B6. 单测** (替换当前 4 个仿射颜色用例,它们测的是被删的逻辑):

* `test_grad_invariant_to_lighting` / `test_grad_invariant_to_contrast_flip`
* `test_grad_adaptive_threshold_low_contrast_object`(不挑物体)
* `test_grad_tolerates_sharp_occluder`(🎯尖锐遮挡,inlier 容忍,降幅<0.2)
* `test_color_tiebreaker_neutral_on_low_saturation`(低饱和退场)
* `test_color_tiebreaker_helps_textureless_colored`(无纹理彩色块靠 color 区分)
* `test_wrong_object_low`(护栏,<0.4)

### 阶段三:低优先级(可选,回放后)

* 横幅 cap 时保证四宫格最小高度(对应🟢),或 banner 超限时压缩字号。
* 切 re_register / 上 Unity 前,用 `data/eval/*/` 回放重标 `0.35`/`0.6`/Unity 阈值(对应🟢)。**现在 score_only 模式不动。**

---

## 验证

```powershell
cd p:\VSCode-Project\EgoAnchor\EgoAnchor_Python
pixi run python -m unittest egoanchor.tests.test_render_quality egoanchor.tests.test_pose_quality egoanchor.tests.test_debug_view
```

回放多物体序列(不只手柄):转动看 grad 压平光照波动、尖锐遮挡帧看 inlier 只小降、debug 文本看 grad/col 分别值。
