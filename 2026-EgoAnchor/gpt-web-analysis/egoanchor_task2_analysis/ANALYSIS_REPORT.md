# EgoAnchor Task 2 Analysis

## Scope
Formal `start_stop_6dof` session `20260717_203749_controller_right`; five paired cycles.
Event-level descriptive statistics are the analysis unit. Render frames are not independent samples.

## Main findings
- Temporal synthesis reduced median event P99 translation jump from **20.9 mm** to **6.7 mm** (**68%**), at the cost of **66 ms** additional output-target lag and **2.7 mm** higher median motion error.
- StaticLock reduced median settling time from **1170 ms** to **600 ms** (**49% faster**), while increasing visible response by **460 ms**.
- EgoAnchor's median event-level motion translation error was **30.1 mm**; median event P95 was **75.4 mm**.
- The defensible claim is a continuity/stability/lifecycle advantage under explicit latency trade-offs, not universal minimum instantaneous error.

## Frozen definitions
- Reference motion: 0.05 m/s OR 22 deg/s, 7-frame median; valid bout >=100 ms and >=5 mm or >=5 deg excursion.
- Visible response: First 100 ms sustained display displacement >5 mm or >3 deg from pre-onset 500 ms median pose.
- Settling: Earliest 500 ms window with position P95 spread <=2 mm and rotation P95 spread <=1 deg.

## Recommended paper placement

- **Main paper:** `task2_staticlock_transition_tradeoff.pdf`, `task2_temporal_synthesis_jump_ccdf.pdf`, and `task2_representative_timeline.pdf`.
- **Main quantitative table:** `task2_system_table.tex` plus `task2_ablation_table.tex`.
- **Supplement:** event-level box plot, ECDF, complete CSVs, event boundaries, and audit definitions.

The CCDF is preferred over the ECDF in the main paper because it directly exposes the probability of large, visually harmful frame-to-frame jumps. The operating-point plot should be used when discussing the explicit accuracy-continuity-lag trade-off.
