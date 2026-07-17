# EgoAnchor Task 3 Analysis

Formal `continuous_translation` session `20260717_204156_controller_right` with 17 paired traversals.

- EgoAnchor vs One-Euro: median translation error **98.8 -> 84.9 mm**; P95 **139.5 -> 111.5 mm**, both improving in 17/17 traversals.
- Effective lag: **380 -> 320 ms**.
- Lag-compensated residual: **8.1 -> 4.5 mm**.
- Temporal synthesis: jump P99 **41.0 -> 9.0 mm** (78% lower), at +65 ms lag and +19.0 mm raw median error.
- Capture-time alignment: median error **97.2 -> 84.9 mm**; cross-track **11.1 -> 6.9 mm**.

Arrival-Hold's lowest raw error is not a semantic win: incorrect arrival-time alignment implicitly time-warps the trajectory. Report raw error, effective lag, and lag-compensated residual together.
