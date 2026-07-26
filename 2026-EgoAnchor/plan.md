# EgoAnchor 论文与实验路线

## 论文定位

EgoAnchor 研究如何把开放视觉后端输出的低频、异步、质量不均的相机系 6DoF 位姿，
转换为混合现实应用可持续使用的世界系对象锚点。平台能力和零样本感知只作为系统背景；
论文主线是 observation-to-anchor runtime。

## 主方法

完整 EgoAnchor 固定使用：

1. 基于 `frame_id` 的采集时刻世界对齐；
2. VCD 接纳；
3. 连续白噪声加速度 Kalman 状态估计；
4. 自适应历史目标时刻上的位置 Linear / 旋转 SLERP；
5. StaticLock；
6. 与重获取协同的生命周期管理。

实验二另比较两种关闭 StaticLock 的逐帧输出策略：

- `Smoothed KF Extrapolation`：有限 180 ms 外推，并以 60 ms 真实时间半衰期平滑
  Kalman 校正残差；
- `Hermite Interpolation`：在相同历史目标时间线上使用 Kalman 速度切线做 6DoF Hermite
  插值，不在最新控制点之后外推。

180/60 ms 与 Hermite 的 `1.15 / 0.25 / 3` 目前是 pilot 初值，正式 v4 采集前冻结。
两路策略共享采集时刻对齐、VCD、Kalman、生命周期、重获取、候选序列、渲染时间线和关闭
StaticLock 的配置，只改变输出策略。这个比较不改变完整 EgoAnchor 的主方法定义。

## 实验组织

### 实验一：端到端系统表征

比较 Arrival-Hold、Capture-Hold、One-Euro Anchor 和 EgoAnchor。五项任务覆盖静止头动、
起停 6DoF、持续平移、持续旋转和遮挡恢复。每个场景分别报告世界一致性、静止稳定性、
lag--fidelity、遮挡稳健性和转换代价，不汇总成全局排名。遮挡稳健性以 episode-level
平移误差 P95 为主指标；40 mm 超限次数与最大值仅保留在完整指标和审计输出中。

### 实验二：系统设计归因与时序策略比较

三个单组件消融为：

- EgoAnchor w/o capture-time alignment；
- EgoAnchor w/o VCD；
- EgoAnchor w/o StaticLock。

图 3(d) 和对应表格比较 `Smoothed KF Extrapolation vs. Hermite Interpolation`。
除 lag--residual 外，还报告候选生效边界步长、静止帧间增量、起动响应、停止前向过冲、
反向回动、settling time、旋转误差和遮挡期平移误差 P95。候选生效边界步长按 `source_frame_id`
改变前后相邻 render pose 的差计算，只作为同一时间线上的配对显示护栏，不称为 Kalman
innovation。

Task 2 每轮使用成对 marker：拿起前记录 `transition_started`，完全停止后记录
`transition_stopped`。QC 要求两者严格交替闭合。

v4 正式批次已在同一冻结代码和参数下完整采完 Task 1--5（见"数据与论文交付"）。更早的 v3 数据
来自旧 Kalman 过程协方差和旧矩阵，仅保留为只读工程诊断，不得混入活动批次或按场景拼接。

### 实验三：日常物体上的跨对象感知评价

**完整设计、测量、分析与汇报方案固定在 `2026-EgoAnchor/experiment_3_questionnaire_design_zh.md`（v5，唯一权威文件），改动前必须先读该文件。** 本节只保留摘要。原结构文档 `experiment_3_design_zh.md` 已于 2026-07-26 并入该文件并删除。

**实验三是纯主观评价，不采集任何客观任务数据**（2026-07-25 起；无任务时间、无成功率、无行为探针）。`2 方法 x 3 物体 = 6 区块`，被试内；物体最外层（工程硬约束：`--object` 只在服务启动时读取），方法嵌套在物体内（同物体相邻 A/B 最紧配对）。条件只有 `One-Euro Anchor` 与完整 `EgoAnchor`，A/B 匿名呈现；`Arrival-Hold` 只作训练演示。交叉核心物体 `blue_mouse`、`stapler`、`gamepad`（手柄强制单手握持单侧搬移），`earphone` 只由操作员采集并兼作训练物体。顺序平衡为 **24 单元**：6 种物体全排列 × S1/S2 互补方法序列 × A/B 标签映射，N=24 目标、N=18 下限。

每区块三项固定顺序任务（T1 静止观察、T2 拿起放下、T3 遮挡恢复，合计 45--60 s）后统一评分。**遮挡时长 0.6--0.9 s 起预实验校准后冻结，目标状态是 `FrozenUncertain` 而不是 `Lost`**（`<=0.45 s` 滑行、`0.45--1.0 s` 冻结、`>=1.0 s` 丢失；须避开两个边界；2 s/2.5 s 会使两方法共享同一次服务器重注册、压缩相对差异）。运行时常数不得为实验三修改。

**测量（v5，2026-07-26 用户批准；同日 v5.1 增补）**：区块级 13 项统一七点同意度 = 5 项自制运行时条目（Q1 静止稳定、Q2 运动附着、Q9 姿态一致、Q3 恢复一致、Q8 位置正确）+ **Augmentation Quality 的 Embedding/Interaction 两个已验证子量表 6 项**（Schein et al. 2025，CC BY，对象化最小替换）+ 2 项应用侧条目（Q6 依赖意愿、Q7 稳定--响应平衡）；可选 Q10 默认不启用。**Q2 措辞已于 v5.1 锐化为"始终附着在真实物体上的同一位置"**（与 AQ-IQ3 运动平滑正交）。方法级（**全部六区块完成后**，按 S1 先 A、S2 先 B 平衡顺序，不插入区块之间）= **adapted TiA 两分量表 + adapted S-TIAS 三项**（原文已核对：TiA 6+4、反向项 6−raw；S-TIAS 作者 McGrath 等，bib 键 `mcgrath2025stias`）。最终 = 2 强制选择（总体偏好 + 信任选择）+ 偏好强度与区分信心（v5.1，描述性）+ 2 开放题 + SSQ 衍生安全检查。共 32 个独立条目、每人 108 个评分。**v4 的 Q4/Q5 已退役**（构念由 AQ 接管，CRIQ 署名疑难随之消除；任何场合不得以 CRIQ 之名署名条目）。信任动机引用 Gottsacker et al. 2024（AR 跟踪偏移/抖动每增 1 度信任显著下降）。

统计：主证实家族 7 项（Q1/Q8/Q2/Q9/Q3/Q6/Q7）三物体取均值后逐条目 Wilcoxon + 家族内 Holm（N=24 最严 MDE dz=0.801）；已发表量表家族 5 检验（AQ-EQ、AQ-IQ、TiA-R/C、TiA-U/P、S-TIAS）独立 Holm，仅该家族报告当前样本信度；CLMM 为次级分析（含物体、顺序固定效应），方法 x 物体交互只作探索；不使用 ART/ART-C。自制单项不合并总分、不报 alpha。操纵检验必须报告候选/VCD/接纳一致性与生命周期状态分布。

诚实边界：不报绝对配准误差、不提供任务表现证据、不作中介效应主张；结论只覆盖当前对象、设备、参数与任务条件。量表原文核对已于 2026-07-26 完成（AQ/TiA/S-TIAS/Gottsacker，见权威文件〇节）；三量表一律以 adapted 署名。剩余前置：中文施测版的回译与认知访谈未完成前，AQ/TiA/S-TIAS 不得进入正式采集。正式采集与分析工作簿为 `material/EgoAnchor_Experiment3_DataCollection_24P_v5_1_Verified_VSCodeSafe.xlsx`（6 表精简版，由 `material/build_exp3_collection_template.py` 可复现生成）。

## v4 启动条件（实验一/二已满足，实验三沿用）

正式采集前完成一次不启动 recorder 的 Quest 功能 pilot：

- 72/90/120 Hz 下残差半衰期行为一致；
- 实际外推时域不超过配置上限；
- 平移和旋转起停无异常跳变、持续回动或非有限输出；
- Hermite 不在最新控制点之后外推；
- 遮挡恢复、VCD、生命周期与九路日志正常；
- 正式场景矩阵门禁和 EditMode 测试通过。

pilot 冻结参数后不再根据 v4 正式结果调参。

实验三沿用同一原则但门禁项不同：九路矩阵门禁和外推诊断只属于实验一/二；实验三使用 2 runtime
的独立 `variant_matrix_id` 与独立启动门禁，并额外要求预实验完成任务参数校准
（头动幅度、操作节奏、遮挡时长），且确认遮挡时长使锚点停留在 `FrozenUncertain` 而不进入 `Lost`。
运行时参数本身不得为实验三修改，否则破坏与实验一/二的可比性。

## 数据与论文交付

实验一/二的 v4 正式采集已完成：活动 `batch.json` 指向
`batch_20260724_005757_20260724_054822_20260724_233436_20260724_045132_20260724_035344`，
五项 session 均为 `run_kind=formal`、`variant_matrix_id=exp12_9_smoothed_hermite_v4`、
`config_hash=05e5edecf737bf34`。论文表格与当前 `analyze` 输出逐字节一致，主稿中不应再出现
"v3 证据"或"待回填"的措辞。

分析契约只接受 `variant_matrix_id=exp12_9_smoothed_hermite_v4`。若后续替换或补采 session，
停止 Python 后依次运行：

```text
pixi run eval stage --promote
pixi run eval analyze
```

最新中文工作稿是 `egoanchor_cn_ai_v8.tex`，其中 `ai` 表示该版本使用 AI 辅助撰写。该稿目前尚不可用，只供继续修改和内部审阅；`egoanchor_cn_v6.tex`、`egoanchor_cn_v7.tex` 与 `egoanchor_cn_v8.tex` 作为旧稿保留，当前编译产物为 `pdf/egoanchor_cn_ai_v8.pdf`。Stage 1 和指标按 Task 独立
缓存，活动 `batch.json` 选择五本 XLSX 后合并回填实验一/二；`analyze` 不读取 raw JSON/JSONL。
IEEE VR 2027 的投稿上限是正文、图和表最多 9 页，参考文献另占 2 页。**撰写阶段页数不作硬约束**：
可以适当超出 9 页，先把论述、证据和细节写足，最后统一浓缩到上限。不要为压页数提前删减实质内容，
也不要因为超页而拒绝补写章节。压缩留到定稿前的专门一轮，届时优先压公式展开、审计指标叙述和重复
的边界说明，而不是删证据或删章节。

## 诚实边界

- 控制器 pose 是同一 Quest 平台参考，不是外部光学真值。
- frame alignment 只修正采集/到达时刻错配，不补偿采集后的物体运动。
- 系统需要目标三维模型；“纯视觉”只修饰物体位姿估计链路。
- 单操作员、多 session 的帧不是独立样本，统计单位是 event 或 segment。
- 正式结论只描述当前对象、设备、参数和任务条件。
