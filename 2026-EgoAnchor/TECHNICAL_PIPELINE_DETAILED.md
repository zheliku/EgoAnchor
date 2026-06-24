# EgoAnchor 技术路线详细说明

**版本**: 2026-06-24  
**状态**: 已审核，与代码一致

---

## 完整技术流程

### 1. 采集（Unity / Quest 3）

- Unity 读取左右相机的 passthrough 纹理、相机内参与镜头位姿
- 每个 `frame_id` 在采集时刻被记录并写入环形缓存（容量约 300 帧，覆盖 5 秒历史）
- **关键**：`frame_id` 与采集时刻的相机世界位姿 `T_world_camera(t_capture)` 绑定

---

### 2. 上行传输（Unity → Python）

#### 2.1 通信机制
- Unity 以 **ZMQ PUB** 模式发送：
  - 双目纹理（左/右相机图像）
  - 相机内参（焦距 fx, fy, 主点 cx, cy）
  - 相机世界位姿（采集时刻）
  - `frame_id`（唯一标识）

#### 2.2 Python 接收端处理
- 对最新帧进行解码
- **`frame_id` 去重**：Python 服务端维护已处理的 `frame_id` 集合，避免重复处理
- **旧帧不积压**：ZMQ 高水位（HWM=20）限制队列长度，业务层按 topic 仅处理最新帧

---

### 3. 标定与预处理

#### 3.1 相机内参映射
- 将原始相机内参 `K_original` 映射到算法处理分辨率下的内参 `K_processing`
- 支持两种映射模式：
  - **中心裁剪（Center Crop）**：保持主点不变，调整焦距
  - **线性缩放（Linear Scale）**：按比例缩放焦距和主点

#### 3.2 坐标系对齐
- Quest SDK 输出左目/右目相机位姿
- 选定参考相机（默认左目）
- 补偿轴约定差异（OpenGL vs Unity）

---

### 4. Python 服务端 Pipeline（约 5-12 fps）

#### 固定四步顺序：

#### ① 分割
- **默认**：YOLOE-26（更快，适合实时）
- **可选**：SAM3（文本提示、异步初始化，质量更高）
- 输出：单目标 mask（左/右相机各一个）

**示例**：
```
输入: 左相机图像 + 文本提示 "controller"
输出: 二值 mask (H×W)
```

#### ② 双目深度估计
- **Fast-FoundationStereo (FFS)**
- 在掩膜区域内估计度量深度图 `D_left`
- 为后续 6DoF 估计提供尺度信息

**关键**：深度图与掩膜对齐，只在目标区域计算

#### ③ 位姿注册
- **FoundationPose** 用物体 CAD 模型对齐出 6DoF
- 模式：
  - **Register**：初始化，完整优化
  - **Re-register**：重获取，完整优化
- 输出：相机坐标系位姿 `T_camera_object` (4×4 矩阵)

#### ④ 位姿跟踪
- **FoundationPose**：输出 pose（轻量迭代更新）
- **Cutie**：追踪 2D mask（视频分割）
- 模式：**Track**（在线追踪，低延迟）

---

### 5. 可靠性评分（详见 POSE_SCORING_MECHANISM.md）

#### 评分公式
```
final_score = gate × quality × confidence
quality = core × modulation
core = weighted_geometric_mean(reprojection, depth)
```

#### 5.1 颜色重投影 (score_reprojection)
- **原理**：将估计的 3D 模型投影回相机平面，对比原始图像与投影图像的 RGB 重合度
- **色彩空间**：LAB（比 RGB 对光照变化更鲁棒）
- **输出**：`score_reprojection ∈ [0,1]`，越高越好
- **权重**：`reproj_weight = 0.2`（辅助证据）

**可视化**：
- 左图：原始图像
- 右图：投影图像
- 对比：颜色差异越小，评分越高

#### 5.2 深度对齐 (score_depth)
- **原理**：对比 Fast-FoundationStereo 的估计深度与 pose 估计结果的表面深度重合度
- **方法**：
  1. 用估计的 pose 渲染物体表面深度图
  2. 与 FFS 估计的深度图对比
  3. 计算掩膜内深度差异
- **输出**：`score_depth ∈ [0,1]`，越高越好
- **权重**：`depth_weight = 0.8`（主要证据，对低纹理目标更可靠）

**可视化**：
- 左图：FFS 估计深度（伪彩色）
- 右图：Pose 渲染深度（伪彩色）
- 对比：深度差异越小，评分越高

#### 5.3 Mask 面积调制 (mask_modulation)
- **原理**：Cutie 追踪的 2D mask 面积与投影面积的比值，计算物体的遮挡面积
- **逻辑**：
  - 比值 ≤ 0.4：无遮挡，modulation = 1.0
  - 比值 0.4-0.65：轻度遮挡，线性降分
  - 比值 > 0.65：严重遮挡，评分显著降低（最低 0.3）
- **作用**：防止遮挡时的错误 pose 通过门控

#### 5.4 连续高质量置信 (confidence)
- **原理**：根据前几次的可靠性评分，预估这次的质量
- **机制**：
  - 初始 confidence ≈ 0.5
  - 连续高质量帧（quality ≥ 0.6）累积，最多 10 帧到满分 1.0
  - 低质量帧快速衰减（-2 计数）
- **作用**：惩罚间歇性抖动，奖励持续稳定

#### 5.5 Gate 层
- **Phase score**：
  - TRACK/REGISTER/RE_REGISTER：1.0
  - 其他：0.7
- **Reject score**：近期 track reject 次数越多，分数越低（最低 0.25）

#### 输出
- 相机坐标系 4×4 位姿 `pose`
- 追踪状态 `phase`（SEARCHING/TRACKING/LOST）
- `frame_id`（对应采集时刻）
- 各类可靠性中间量（`score_reprojection`, `score_depth`, `final_score`, `flags`）

---

### 6. 下行传输（Python → Unity）

- **通信机制**：NATS Protobuf 消息面
- **发布主题**：`egoanchor.pose_result`
- **消息内容**：
  - 相机坐标系位姿
  - `frame_id`
  - 可靠性评分
  - 追踪状态

---

### 7. Unity 四层协同锚定运行时

#### 第一层：时间/帧对齐

**关键机制**：
```python
# 伪代码
def OnPoseReceived(pose_camera, frame_id, reliability_score):
    # 按 frame_id 回查采集时刻的相机世界位姿
    T_world_camera_capture = ring_buffer.Get(frame_id)
    
    # 刚体组合：世界空间物体位姿
    T_world_object = T_world_camera_capture @ pose_camera
    
    # 禁止使用到达时刻 HMD 位姿替代！
    # ❌ 错误做法: T_world_object = T_world_camera_current @ pose_camera
```

**核心价值**：
- **消除头动打滑**：头部在采集到回传期间的任何运动都不会耦合进结果
- **物理正确**：映射到采集时刻的真实世界位置
- **与时间扭曲对偶**：时间扭曲对齐到"当前"，帧对齐对齐回"采集时刻"

**注意事项**：
- 环形缓存容量约 300 帧（5 秒）
- 如果 `frame_id` 过期（超出缓存范围），记录警告并降级处理

---

#### 第二层：质量门控

**门控逻辑**：
```python
def QualityGate(reliability_score, phase):
    # 门控阈值（可配置）
    GATE_THRESH = 0.6
    
    if phase != "TRACKING":
        return False  # 非追踪状态，拒绝
    
    if reliability_score < GATE_THRESH:
        return False  # 低质量，拒绝
    
    return True  # 通过门控，进入时序平滑层
```

**作用**：
- 拦截异常观测（位姿跃变、严重遮挡）
- 防止低质量 pose 污染下游卡尔曼滤波器
- 触发保持（Coasting）或重获取（Lost）

---

#### 第三层：时序平滑

##### 3.1 卡尔曼状态估计（观测更新，5-12 fps）

**状态向量**：
```
x = [position, velocity, rotation]ᵀ
  = [p_x, p_y, p_z, v_x, v_y, v_z, r_w, r_x, r_y, r_z]ᵀ
```

**观测更新**（当新的 pose 通过门控时）：
```python
def KalmanUpdate(observation_pose, reliability_score):
    # 观测噪声 R 根据可靠性评分自适应调整
    R = base_R / max(reliability_score, 0.1)
    
    # 卡尔曼更新
    kalman.Update(observation_pose, R)
```

**关键特性**：
- **自适应噪声**：可靠性评分高 → 观测噪声小 → 更信任观测
- **速度估计**：不仅估计位置，还估计速度，为预测提供依据

##### 3.2 静止锁定

**进入条件**：
- 连续观测速度和角速度低于极低门槛（如 0.01 m/s、1 deg/s）
- 持续时间达到沉降周期 `τ_settle`（如 0.5 s）

**锁定行为**：
```python
def StaticLock():
    # 锁定输出为进入时刻的世界位姿
    locked_pose = kalman.GetCurrentPose()
    
    # 每帧直接输出锁定位姿，不进行预测
    return locked_pose
```

**解锁判定**（三路证据累积）：
1. **速度逃逸**：卡尔曼估计速度超出阈值
2. **漂移绳索**：观测共识点与锁定时刻锚点的距离超出阈值
3. **CUSUM 偏差累积**：残差累积和超出死区

**接缝消除**：
```python
def SeamRemoval():
    # 解锁瞬间，锁定输出与当前卡尔曼估计间存在接缝残差
    seam_residual = kalman.GetCurrentPose() - locked_pose
    
    # 指数衰减至零，平滑过渡回正常滤波状态
    for frame in range(seam_removal_frames):
        alpha = exp(-frame / tau)
        output_pose = locked_pose + (1 - alpha) * seam_residual
```

**作用**：完全抑制物体与头显相对静止时的残余微抖

##### 3.3 升采样输出（卡尔曼预测，60 fps）

**核心机制**：
```python
def Update(deltaTime):
    # 检查是否有新的观测到达（5-12 fps）
    if HasNewObservation():
        observation = GetLatestObservation()
        
        # 时间对齐
        world_pose = FrameAlignedAnchoring(observation)
        
        # 质量门控
        if QualityGate(observation.reliability_score, observation.phase):
            # 卡尔曼观测更新
            kalman.Update(world_pose, observation.reliability_score)
    
    # ===== 升采样关键步骤 =====
    # 每个渲染帧都执行卡尔曼预测（60 fps）
    predicted_pose = kalman.Predict(deltaTime)
    
    # 检查是否处于静止锁定
    if IsStaticLocked():
        output_pose = static_lock.GetLockedPose()
    else:
        output_pose = predicted_pose
    
    # 输出 60 fps 锚点驱动虚拟内容
    anchor.SetPose(output_pose)
```

**升采样的工作原理**：

1. **观测更新频率**：5-12 fps
   - 只有当 Python 后端返回新的 pose 时才更新卡尔曼状态
   - 更新包括位置和速度的校正

2. **预测输出频率**：60 fps
   - 每个渲染帧（60 fps）都执行卡尔曼预测步骤
   - 预测公式（恒速模型）：
     ```
     position(t+Δt) = position(t) + velocity(t) × Δt
     rotation(t+Δt) = rotation(t) ⊕ angular_velocity(t) × Δt
     ```

3. **与简单插值的区别**：

| 方法 | 简单线性插值 | 卡尔曼预测升采样 |
|------|-------------|-----------------|
| **输入信息** | 仅位置 | 位置 + 速度 |
| **物理意义** | 无 | 有（基于速度的外推） |
| **噪声处理** | 无 | 有（协方差传播） |
| **适应性** | 固定 | 自适应（根据可靠性评分调整） |
| **延迟补偿** | 无 | 有（前向预测） |

4. **升采样的优势**：
   - ✅ **视觉流畅性**：60 fps 锚点更新，无卡顿感
   - ✅ **物理合理性**：利用速度信息进行有意义的外推
   - ✅ **延迟补偿**：在观测到达前就已经预测到未来位置
   - ✅ **平滑轨迹**：自然连接观测帧之间的运动
   - ✅ **噪声抑制**：预测步骤天然平滑观测噪声

5. **静止锁定的影响**：
   - 当物体处于静止锁定状态时：
     - **不执行预测**：直接输出锁定位姿
     - **完全消除微抖**：无论渲染频率
     - **零延迟零噪声**：输出固定值

6. **频率转换效果**：
```
时间轴 (秒):     0.0    0.1    0.2    0.3    0.4    0.5
─────────────────────────────────────────────────────
观测到达 (5fps):  O─────────────O─────────────O
预测输出 (60fps): P─P─P─P─P─P─P─P─P─P─P─P─P─P─P─P─P─P
                  ↑           ↑           ↑
                更新+预测    仅预测      更新+预测
```

**实现细节**：
- **时间步长**：`deltaTime = Time.deltaTime`（Unity 提供，约 16.67 ms @ 60 fps）
- **协方差传播**：预测步骤同时传播状态协方差，量化不确定性
- **自适应调整**：过程噪声 Q 根据运动模式动态调整

**性能开销**：
- 卡尔曼预测步骤非常轻量（矩阵乘法）
- 相比神经网络推理（5-12 fps），预测开销可忽略
- 在 Unity 中 60 fps 预测完全可行

---

#### 第四层：生命周期管理

##### 4.1 状态机

```
┌──────────┐   初始化成功   ┌──────────┐   质量持续高   ┌──────────┐
│SEARCHING │───────────────▶│ TRACKING │───────────────▶│ TRACKING │
└──────────┘                └──────────┘                └──────────┘
                                  │                           │
                                  │ 质量下降                  │
                                  ▼                           │
                            ┌──────────┐   质量恢复          │
                            │ COASTING │────────────────────▶│
                            └──────────┘                      │
                                  │                           │
                                  │ 超时                      │
                                  ▼                           │
                            ┌──────────┐   重获取成功        │
                            │   LOST   │────────────────────▶│
                            └──────────┘                      │
                                  ▲                           │
                                  │                           │
                                  └───────────────────────────┘
                                      质量持续低/出视野
```

**状态说明**：

1. **SEARCHING**：
   - 初始化或重获取中
   - 等待首次成功的 pose
   - 虚拟内容隐藏

2. **TRACKING**：
   - 正常追踪状态
   - 可靠性评分持续高于阈值
   - 虚拟内容正常显示

3. **COASTING**：
   - 短暂遮挡或质量下降
   - 保持卡尔曼预测输出
   - 虚拟内容带视觉反馈（如半透明、边框闪烁）

4. **LOST**：
   - 长时间失去追踪
   - 触发重获取请求
   - 虚拟内容隐藏

##### 4.2 重获取机制

**触发条件**：
- 可靠性评分持续低于阈值（如遮挡严重）
- 物体丢失出视野
- Coasting 超时（如 2 秒）

**重获取流程**：
```python
def TriggerReacquire():
    # Unity 通过 NATS 命令面向后端发送重获取请求
    nats_client.Request(
        subject="egoanchor.command.reacquire",
        payload={"target_id": target_id}
    )
    
    # 状态切换到 LOST
    state = "LOST"
    
    # 等待后端执行 FoundationPose Re-register
    # 成功后收到新的 pose → 切换到 SEARCHING
```

**命令通道**：
- **协议**：NATS Request/Reply
- **主题**：`egoanchor.command.reacquire`
- **超时**：3 秒
- **重试**：最多 2 次

##### 4.3 保持策略

**Coasting 期间**：
- 继续执行卡尔曼预测（基于最后已知速度）
- 虚拟内容保持可见但带视觉提示
- 设置超时定时器（如 2 秒）

**保持的价值**：
- 用户体验：短暂遮挡不会立即隐藏虚拟内容
- 快速恢复：遮挡移除后立即恢复 Tracking
- 减少重获取：避免频繁的 Re-register

---

## 关键设计决策

### 1. 为什么选择 5-12 fps 作为感知频率？

**约束**：
- FoundationPose 推理时间：~80-200 ms（取决于 GPU）
- FFS 推理时间：~50-100 ms
- 分割 + 深度 + pose = ~150-300 ms

**权衡**：
- 更高频率（如 30 fps）：GPU 不够快，会积压
- 更低频率（如 1 fps）：物体运动时跟踪不上

**结论**：5-12 fps 是消费级 GPU 上感知质量与实时性的最优平衡

### 2. 为什么升采样必不可少？

**原因**：
- 头显渲染频率：90-120 fps（Quest 3 为 90 fps）
- 虚拟内容更新频率低于 60 fps 会导致视觉卡顿
- 5-12 fps 直接驱动虚拟内容会严重影响用户体验

**解决**：
- 卡尔曼预测升采样到 60 fps
- 保证视觉流畅性的同时保持系统实时性

### 3. 为什么深度权重（0.8）远高于颜色权重（0.2）？

**原因**：
- 手柄、白色立方体等目标纹理少，颜色重投影信号弱
- 深度几何一致性更可靠、更稳定
- 实践中这个权重分配对低纹理目标表现更好

### 4. 为什么需要静止锁定？

**原因**：
- 即使经过卡尔曼平滑，静止物体仍会有亚毫米级微抖
- 微抖在近距观察时明显影响视觉稳定性
- 静止锁定通过死区 + CUSUM 完全抑制微抖

---

## 性能指标

| 指标 | 数值 | 说明 |
|------|------|------|
| **感知频率** | 5-12 fps | RTX 5080 约 5 fps，RTX 5090 约 12 fps |
| **锚点输出频率** | 60 fps | 通过卡尔曼预测升采样 |
| **端到端时延** | ~150-300 ms | 从采集到锚点更新（P50/P90） |
| **静态抖动** | <0.5 mm | 启用静止锁定后 |
| **头动打滑** | ~0 mm | 帧对齐消除 |
| **恢复时间** | <1 s | 从遮挡移除到稳定追踪 |

---

## 补充说明

### 勘误与补充

1. ✅ **升采样部分已补全**：详细说明了卡尔曼预测的工作原理、与简单插值的区别、频率转换效果
2. ✅ **静止锁定对升采样的影响**：明确了锁定状态下不执行预测，直接输出固定值
3. ✅ **性能开销**：说明了预测步骤的轻量性
4. ✅ **设计决策**：补充了为什么选择 5-12 fps 和为什么升采样必不可少

### 与论文的对应关系

- **第一层（时间对齐）**：对应"时间/帧对齐"
- **第二层（质量门控）**：对应"质量门控"
- **第三层（时序平滑）**：对应"卡尔曼状态估计 + 静止锁定 + **升采样输出**"
- **第四层（生命周期）**：对应"生命周期管理"

---

**总结**：你的技术路线总结非常准确！我补充了升采样的详细工作原理、与简单插值的对比、静止锁定的影响，以及一些关键设计决策的理由。整个流程现在更加完整清晰。
