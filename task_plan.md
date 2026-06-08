
# EgoAnchor 重投影颜色评分改进执行手册

## 背景与目标

当前 `reproj=0.44` 偏低的根因:渲染是 **无光照纯反照率** (`use_light=False`),真实图有光照;而 [reprojection.py:161-166](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/reprojection.py#L161-L166) 把 LAB 的**亮度通道 L** 全额计入距离、 **无亮度归一化** 、 **除数 180 偏小** 、用 **mean** 受边缘离群拖累。

改造目标:让颜色度量 **对光照不变** ——只惩罚"色相错"(投到错物体),不惩罚"渲染没打光"(亮度系统差)。共  **3 处源码改动 + 1 处配置 + 单测 + code-review 修补** ,全部可回放调参。

配置注入链(已核实):
`defaults.toml` → [pipeline_factory.py:268-277](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/perception/pipeline_factory.py#L268-L277) → `QuestPosePipeline.__init__` → [render_quality.py:92-94](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/render_quality.py#L92-L94) → `ReprojectionChecker`

---

## 改动 1 — 重写颜色度量(核心)

**文件:** [reprojection.py](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/reprojection.py)

### 1.1 `__init__`(当前 66-70 行)新增两个参数

```python
def __init__(self, min_render_area_px: int = 50, color_l_weight: float = 0.3, color_divisor: float = 70.0) -> None:
    """保存最小渲染面积与颜色度量参数。"""

    self.min_render_area_px = max(1, int(min_render_area_px))
    """渲染前景过小时判为无效信号的像素阈值。"""

    self.color_l_weight = clamp01(float(color_l_weight))
    """LAB 亮度通道 L 在颜色距离中的权重；低值降低对光照差的敏感度。"""

    self.color_divisor = max(1.0, float(color_divisor))
    """颜色距离归一化除数;越小越严格,需配合 L 对齐后的距离量级调参。"""
```

### 1.2 `score_maps`(当前 72-87 行)把新参数透传

在 `_score_from_maps(...)` 调用里追加:

```python
        return self._score_from_maps(
            render_color_rgb,
            observed_rgb,
            render_mask,
            observed_mask,
            min_render_area_px=self.min_render_area_px,
            color_l_weight=self.color_l_weight,
            color_divisor=self.color_divisor,
        )
```

### 1.3 `_score_from_maps`(当前 89-97 行)签名加 keyword-only 默认值

> 必须给默认值——现有单测 [test_render_quality.py:24-37](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/tests/test_render_quality.py#L24-L37) 直接以 `min_render_area_px=1` 调用这个 staticmethod,不能破坏。

```python
    @staticmethod
    def _score_from_maps(
        render_color_rgb: np.ndarray,
        observed_rgb: np.ndarray,
        render_mask: np.ndarray,
        observed_mask: np.ndarray,
        *,
        min_render_area_px: int,
        color_l_weight: float = 0.3,
        color_divisor: float = 70.0,
    ) -> ReprojectionResult:
```

然后把当前第 123 行的调用改成:

```python
        color_similarity = ReprojectionChecker._color_similarity_lab(
            render_rgb, observed_rgb_u8, intersection, l_weight=color_l_weight, divisor=color_divisor
        )
```

### 1.4 重写 `_color_similarity_lab`(当前 152-166 行)

核心三步: **L 中位数对齐 → L 低权重加权 → median 聚合** 。

```python
    @staticmethod
    def _color_similarity_lab(
        render_rgb: np.ndarray,
        observed_rgb: np.ndarray,
        intersection: np.ndarray,
        *,
        l_weight: float = 0.3,
        divisor: float = 70.0,
    ) -> float:
        """在重叠核心区域计算光照不变的 LAB 颜色相似度。

        渲染为无光照纯反照率,真实图含光照,二者亮度存在系统性偏移。这里先把渲染 L
        的中位数对齐到观测 L,再以低权重计入 L、全权重计入 a/b,最后用 median 聚合,
        使分数主要反映色相一致性而非曝光差异。
        """

        if int(np.count_nonzero(intersection)) <= 0:
            return 0.0
        core_mask = ReprojectionChecker._erode_intersection_core(intersection)
        if int(np.count_nonzero(core_mask)) <= 0:
            core_mask = intersection
        render_lab = cv2.cvtColor(render_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
        observed_lab = cv2.cvtColor(observed_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
        render_core = render_lab[core_mask].copy()
        observed_core = observed_lab[core_mask]
        if render_core.shape[0] <= 0:
            return 0.0
        l_offset = float(np.median(observed_core[:, 0]) - np.median(render_core[:, 0]))
        render_core[:, 0] += l_offset
        weights = np.array([clamp01(l_weight), 1.0, 1.0], dtype=np.float32)
        diff = np.linalg.norm((render_core - observed_core) * weights, axis=1)
        if diff.size <= 0:
            return 0.0
        return clamp01(1.0 - float(np.median(diff)) / max(1.0, float(divisor)))
```

**除数取值依据:** OpenCV 对 uint8 做 `RGB2LAB` 时 L/a/b 均缩放到 `[0,255]`,中性灰 a=b=128。L 对齐后,"色相完全错"(a、b 各偏 ~80)的加权距离 ≈ `sqrt(80²+80²) ≈ 113`,故除数 60–80 能让错色映射到接近 0;先用 **70** 起步,再按回放调。

---

## 改动 2 — 参数配置化(贯通全链)

### 2.1 `RenderQualityChecker.__init__`([render_quality.py:82-95](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/render_quality.py#L82-L95))

入参加 `color_l_weight: float = 0.3, color_divisor: float = 70.0`,并传入 `ReprojectionChecker`:

```python
        self.reprojection = ReprojectionChecker(
            min_render_area_px=min_render_area_px,
            color_l_weight=color_l_weight,
            color_divisor=color_divisor,
        )
```

### 2.2 `QuestPosePipeline.__init__`([quest_pose_pipeline.py:64-73](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/perception/quest_pose_pipeline.py#L64-L73) 入参 + 164-174 构造)

入参列表加:

```python
        render_quality_color_l_weight: float = 0.3,
        render_quality_color_divisor: float = 70.0,
```

`RenderQualityChecker(...)` 构造处(164-174)加:

```python
                color_l_weight=render_quality_color_l_weight,
                color_divisor=render_quality_color_divisor,
```

### 2.3 工厂 `build_quest_pose_pipeline`([pipeline_factory.py:268-277](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/perception/pipeline_factory.py#L268-L277) 末尾)

在 `render_quality_min_render_area_px=...` 之后追加:

```python
        render_quality_color_l_weight=float(_cfg_get(render_quality_cfg, "color_l_weight", 0.3)),
        render_quality_color_divisor=float(_cfg_get(render_quality_cfg, "color_divisor", 70.0)),
```

### 2.4 `defaults.toml`([defaults.toml:56-66](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/config/defaults.toml#L66) `[reliability.render_quality]` 末尾)

```toml
color_l_weight = 0.3 # LAB 亮度 L 在颜色距离中的权重；渲染无光照、真实图有光照时调低可降低误罚。
color_divisor = 70.0 # 颜色距离归一化除数；L 对齐后距离量级变小，越小越严格，建议回放调参。
```

---

## 改动 3 — 单测

**文件:** [test_render_quality.py](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/tests/test_render_quality.py)

现有 `test_reprojection_scores_lab_color_in_overlap`(红 vs 绿,色相差大)仍应通过(`diff.score < same.score`)。**新增两个用例**锁定新语义:

```python
    def test_same_hue_different_brightness_stays_high(self) -> None:
        """同色相、仅亮度不同(模拟无光照渲染 vs 有光照真实图)应保持高分。"""

        mask = np.ones((4, 4), dtype=bool)
        render_rgb = np.full((4, 4, 3), 90, dtype=np.uint8)    # 暗灰
        observed_rgb = np.full((4, 4, 3), 200, dtype=np.uint8)  # 亮灰、同色相

        result = ReprojectionChecker._score_from_maps(
            render_rgb, observed_rgb, mask, mask, min_render_area_px=1
        )
        self.assertGreater(result.color_similarity, 0.85)

    def test_different_hue_scores_low(self) -> None:
        """色相明显不同(投到错物体)应被显著降分。"""

        mask = np.ones((4, 4), dtype=bool)
        render_rgb = np.full((4, 4, 3), (40, 40, 220), dtype=np.uint8)   # 蓝
        observed_rgb = np.full((4, 4, 3), (220, 120, 40), dtype=np.uint8)  # 橙

        result = ReprojectionChecker._score_from_maps(
            render_rgb, observed_rgb, mask, mask, min_render_area_px=1
        )
        self.assertLess(result.color_similarity, 0.5)
```

> 注意:用 `4x4` 而非 `2x2`,避免 `_erode_intersection_core` 的 `< 9 像素` 早退分支干扰断言。

---

## 改动 4 — code-review 修补(同段代码顺手清理)

1. **`_ensure_rgb_u8` 浮点判定隐患** — [reprojection.py:200-206](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/reprojection.py#L200-L206):`max(finite) <= 1.0` 才乘 255,对 `(1.0, 255]` 中间范围浮点会误判。当前路径(renderer 输出已归一)安全,但建议加一行注释说明假设:`# 约定:浮点 color 要么在 [0,1],要么已是 [0,255];不支持其它中间范围`。低优先级, **不改逻辑只加注释** 。
2. **深度魔法数 `3.0`** — [depth_alignment.py:142](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/reliability/depth_alignment.py#L142):`median_residual / (thresh * 3.0)`。本次不动逻辑,补注释:`# 残差达 inlier 阈值 3 倍时 median_score 归零`。若后续要调,再提为配置项。
3. **mean→median** — 已在改动 1.4 内一并解决(颜色聚合改 median),无需单独处理。

---

## 验证步骤

1. **跑相关单测** (在 `EgoAnchor_Python` 目录,PowerShell):

```powershell
   python -m pytest src/egoanchor/tests/test_render_quality.py src/egoanchor/tests/test_pose_quality.py -q
```

   (该项目测试基于 `unittest`,`pytest` 可直接收集;若无 pytest 则 `python -m unittest egoanchor.tests.test_render_quality`)

1. **回放调参** — 用 `data/eval/*/...python_runtime.jsonl` 已有帧回放,对比改前/改后 `reproj` 分布。目标:`IoU>0.7` 的几何正确帧颜色分普遍升到  **0.7+** ,真正投错物体的帧仍  **<0.4** 。据此微调 `color_divisor`(更严→调小)和 `color_l_weight`(光照差仍误罚→调更小)。

## 注意的连带影响(不用改,但要心里有数)

* **`re_register_threshold = 0.35`** ([defaults.toml:59](vscode-webview://0ing7s3qthfm1egtmcptmcesnb5om9gpk2n7io0qq2pr7figqgvn/EgoAnchor_Python/src/egoanchor/config/defaults.toml#L59)):分数整体抬升后,该阈值语义变化。当前 `mode="score_only"` 不触发重注册, **安全** ;若将来切到 `re_register` 模式,需重新标定此阈值。
* **`pose_quality.py` 下游阈值** (`reprojection_low` 的 0.5、`GOOD_SCORE_THRESH=0.6`):颜色分抬升后这些会更易满足,confidence 积累更顺,正是期望效果, **无需改** 。
