# EgoAnchor Task 4 Analysis

Formal `continuous_rotation` session `20260717_204943_controller_right`. The first
14.4 s form a setup/static interval; the three marker-defined
rotation segments are the paired analysis units.

## Main findings

- **EgoAnchor consistently improves the rotation median over One-Euro.**
  Median segment rotation error decreased from
  **14.2°** to
  **13.2°**, improving in
  **3/3 segments**.
- The median segment P95 decreased from
  **22.8°** to
  **22.3°**, but the direction
  was favorable in only **2/3 segments**; this tail result should be presented
  cautiously.
- Effective rotation lag decreased from
  **380 ms**
  to **340 ms**,
  improving in **3/3 segments**.
- Lag-compensated residual decreased from
  **2.61°**
  to **2.48°**,
  again improving in **3/3 segments**.
- Temporal synthesis reduced angular-jump P99 from
  **8.02°** to
  **2.34°**
  (**71% lower**), at the cost of
  **75 ms** effective lag and
  **2.6°** higher raw median rotation error.
- Capture-time alignment reduced raw median rotation error from
  **17.7°** to
  **13.2°** and effective lag by
  **145 ms**.

## Interpretation

Capture-Hold and Arrival-Hold exhibit smaller raw instantaneous rotation error,
but they update at only about
7.5 Hz and retain
large angular-jump tails. EgoAnchor instead provides a substantially denser,
more continuous rotational trajectory. The defensible claim is therefore an
improved lag-residual-continuity operating point, not universal minimum raw
error.

Because Task 4 contains only three formal rotation segments, all results are
paired descriptive evidence. No population-level significance claim is made.
