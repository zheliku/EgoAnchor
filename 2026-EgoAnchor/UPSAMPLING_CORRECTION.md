# EgoAnchor 升采样机制 - 准确说明

**日期**: 2026-06-24
**感谢**: 用户纠正了我的错误理解

---

## ⚠️ 重要更正

我之前错误地描述了升采样机制为"基于速度的卡尔曼预测外推"，这是**不准确**的。

实际系统使用的是两种不同的策略，都**不是简单的速度外推**。

---

## 实际的两种升采样策略

### 策略 A: DelayedInterp（延迟插值）

#### 核心思想

**主动牺牲约 1-2 个观测周期的延迟，换取真正的插值而非外推**

```
时间轴:
观测到达:    O₀────────O₁────────O₂────────O₃
渲染输出:      ↑      ↑      ↑      ↑
            now-Δ  now-Δ  now-Δ  now-Δ
            (插值) (插值) (插值) (插值)
```

#### 工作原理

1. **延迟窗口**：渲染时刻 `now` 的输出取在 `now - Δ` 处

   - `Δ` ≈ 1-2 个观测周期（约 100-200 ms）
   - 因为 `now - Δ` 总落在两个**已到达**控制点之间
2. **插值而非外推**：

   - ✅ 在已知点之间插值
   - ✅ 严格过控制点
   - ✅ 样条保证 C¹ 连续
   - ✅ 无需"猜未来"
   - ✅ 不会 overshoot
3. **样条类型**：

   - **Hermite 样条**：使用控制点速度作为切线（来自 MotionModel）
   - **Catmull-Rom 样条**：用相邻点自动定切线
4. **位置与旋转**：

   - 位置：样条插值
   - 旋转：在相对旋转对数空间插值 + Exp 映射回四元数

#### 优点

- ✅ **无 overshoot**：永远在已知点之间
- ✅ **平滑轨迹**：样条保证连续性
- ✅ **稳定可靠**：不依赖预测

#### 缺点

- ❌ **额外延迟**：主动增加 100-200 ms 延迟
- ❌ **滞后感**：快速运动时输出落后于实际

---

### 策略 B: Blend（误差融合，零延迟）

#### 核心思想

**高频外推 + 误差融合（Error Blending），零延迟但平滑收敛**

参考工业实践：

- Source 引擎
- Oculus ASW（位置部分）

```
每渲染帧:
  render = model.PredictAt(now) ⊕ residual
  residual *= decay  // 指数衰减，每帧"还债"

新观测到达:
  residual = (旧渲染 pose) ⊖ (新 model 在该时刻的预测)
  // 下一帧 render ≈ 上一帧 render (C⁰ 连续，不跳)
```

#### 工作原理

1. **高频外推**：

   ```csharp
   // 每帧预测到当前时刻（但有 ClampPredictTime 限制）
   Pose basePose = model.PredictAt(now);
   ```
2. **残差叠加**：

   ```csharp
   // 叠加当前还没还完的"债"
   Vector3 pos = basePose.position + posResidual;
   Quaternion rot = basePose.rotation ⊗ Exp(rotResidual);
   ```
3. **残差衰减**：

   ```csharp
   // 每帧按指数衰减（默认 0.9）
   float decay = pow(decayPerFrame, frames_at_60fps);
   posResidual *= decay;
   rotResidual *= decay;
   ```
4. **新观测到达时**：

   ```csharp
   // 计算误差作为新的残差
   residual = oldRender ⊖ newModel.PredictAt(oldRenderTime);
   // 不直接跳到新观测，而是把误差分摊到未来几帧
   ```

#### ClampPredictTime 限制

```csharp
// 防止外推太远导致 overshoot/急停冲过头
float maxAhead = model.GetLatency() + safetyMargin;
predictTime = Mathf.Min(now, lastObservationTime + maxAhead);
```

#### 优点

- ✅ **零延迟**：不主动增加延迟
- ✅ **零跳变**：新观测到达时 C⁰ 连续
- ✅ **平滑收敛**：残差指数衰减
- ✅ **有限外推**：ClampPredictTime 防止飞出去

#### 缺点

- ❌ **依赖 MotionModel 质量**：外推准确性取决于模型
- ❌ **快速变向时滞后**：残差还没还完就变向

---

## 两种策略的对比

| 维度                | DelayedInterp (延迟插值) | Blend (误差融合)           |
| ------------------- | ------------------------ | -------------------------- |
| **延迟**      | +100-200 ms              | 0 ms                       |
| **方法**      | 真正的插值               | 外推 + 残差融合            |
| **Overshoot** | 无                       | 通过 ClampPredictTime 限制 |
| **跳变**      | 无（样条连续）           | 无（残差平滑）             |
| **快速运动**  | 滞后明显                 | 较好跟随                   |
| **稳定性**    | 极高                     | 依赖 MotionModel           |
| **适用场景**  | 物体缓慢移动、精度优先   | 快速交互、响应优先         |

---

## 升采样的实际流程

### 通用流程（60 fps 渲染帧）

```csharp
void Update() {
    float nowSeconds = Time.time;
  
    // 1. 检查是否有新观测到达（5-12 fps）
    if (HasNewObservation()) {
        PoseObservation obs = GetLatestObservation();
      
        // 帧对齐
        Pose worldPose = FrameAlign(obs);
      
        // 质量门控
        if (QualityGate(obs.reliability)) {
            // 更新 MotionModel（Kalman/OneEuro/Raw）
            motionModel.AddControlPoint(worldPose, nowSeconds);
          
            // 如果是 Blend 策略，计算残差
            if (strategy is BlendStrategy) {
                UpdateResidual(worldPose, nowSeconds);
            }
        }
    }
  
    // 2. 升采样输出（每帧都执行）
    Pose outputPose = smoothingStrategy.GetPose(motionModel, nowSeconds);
  
    // 3. 静止锁定检查
    if (staticLock.IsLocked()) {
        outputPose = staticLock.GetLockedPose();
    }
  
    // 4. 驱动虚拟内容
    anchor.SetPose(outputPose);
}
```

### DelayedInterp 的 GetPose

```csharp
Pose GetPose(MotionModel model, float nowSeconds) {
    // 1. 延迟时刻
    float delayedTime = nowSeconds - delaySeconds;  // delaySeconds ≈ 0.1-0.2s
  
    // 2. 从 MotionModel 获取控制点队列
    List<ControlPoint> points = model.GetControlPoints();
  
    // 3. 找到 delayedTime 所在的区间 [points[i], points[i+1]]
    int i = FindInterval(points, delayedTime);
  
    // 4. 计算插值参数 u ∈ [0,1]
    float u = (delayedTime - points[i].time) / (points[i+1].time - points[i].time);
  
    // 5. 样条插值
    if (splineKind == Hermite) {
        return InterpHermite(points, i, u);  // 使用速度作为切线
    } else {
        return InterpCatmullRom(points, i, u);  // 自动计算切线
    }
}
```

### Blend 的 GetPose

```csharp
Pose GetPose(MotionModel model, float nowSeconds) {
    // 1. 外推到当前（有限制）
    float predictTime = ClampPredictTime(model, nowSeconds);
    Pose basePose = model.PredictAt(predictTime);
  
    // 2. 叠加残差
    Vector3 pos = basePose.position + posResidual;
    Quaternion rot = basePose.rotation * Exp(rotResidual);
  
    // 3. 残差衰减（还债）
    float decay = pow(decayPerFrame, deltaTime * 60);
    posResidual *= decay;
    rotResidual *= decay;
  
    return new Pose(pos, rot);
}
```

---

## MotionModel 的作用

升采样策略依赖 **MotionModel** 提供控制点和预测：

### MotionModel 类型

1. **RawPassthrough**：

   - 直接传递原始观测
   - 无平滑
2. **KalmanModel**：

   - 恒速卡尔曼滤波
   - 估计位置 + 速度
   - 提供 `PredictAt(t)` 外推
3. **OneEuroModel**：

   - One Euro Filter（CHI'12）
   - 自适应低通滤波
   - 抖动-延迟折衷

### MotionModel 与升采样的关系

```
观测到达 (5-12 fps)
  ↓
MotionModel 更新
  ├─ 存储控制点（带时间戳）
  ├─ 更新状态（Kalman/OneEuro）
  └─ 提供 PredictAt(t) 接口
  ↓
SmoothingStrategy 调用 (60 fps)
  ├─ DelayedInterp: 从控制点队列插值
  └─ Blend: 调用 PredictAt(now) 外推
```

---

## 论文中应该如何描述？

### 准确的描述

**第三层：时序平滑（包含升采样）**

系统支持两种升采样策略：

1. **延迟插值（DelayedInterp）**：

   - 主动牺牲 1-2 个观测周期（约 100-200 ms）的延迟
   - 渲染时刻 `now` 的输出取在 `now - Δ` 处
   - 在已到达的控制点之间进行样条插值（Hermite 或 Catmull-Rom）
   - 优点：无 overshoot、平滑稳定
   - 适用：精度优先、物体缓慢移动
2. **误差融合（Blend）**：

   - 零延迟，每帧外推到当前时刻（有安全限制）
   - 新观测到达时不直接跳变，而是计算残差并在后续帧指数衰减
   - 优点：零延迟、零跳变、平滑收敛
   - 适用：响应优先、快速交互

两种策略都依赖 **MotionModel**（Kalman/OneEuro/Raw）提供控制点和预测接口，实现从感知频率（5-12 fps）到渲染频率（60 fps）的转换。

---

## 关键区别总结

### 我之前的错误理解

❌ "卡尔曼滤波器在每个渲染帧通过预测步骤前向推演状态"
❌ "基于速度的外推"
❌ "简单的速度外推"

### 实际情况

✅ **DelayedInterp**：延迟 + 样条插值（在已知点之间）
✅ **Blend**：外推 + 残差融合（有限外推 + 平滑收敛）
✅ MotionModel（Kalman）只是提供控制点和预测接口，不直接等于升采样

---

## 感谢

感谢用户的纠正！这让我重新仔细阅读了代码，理解了真正的实现机制。

**关键教训**：不要假设实现方式，一定要查看实际代码。

---

**结论**：EgoAnchor 的升采样**不是**简单的卡尔曼预测外推，而是两种精心设计的策略：延迟插值（牺牲延迟换稳定）或误差融合（零延迟但平滑收敛）。
