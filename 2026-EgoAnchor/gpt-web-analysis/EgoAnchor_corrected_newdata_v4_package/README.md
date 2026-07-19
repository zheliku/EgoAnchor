# EgoAnchor corrected new-data v3

This revision updates Experiment 1 distribution reporting.

- Main Table 1 now reports median [Q1, Q3] across repeated action segments or occlusion episodes.
- The scenario-level n is shown in the table header: static n=4, translation n=30, rotation n=10, occlusion n=9, and start-transition n=9.
- Supplementary Table S1 reports between-segment P5 / median / P95 / n for every continuous Table 1 metric.
- P5 and P95 are descriptive between-segment percentiles, not confidence intervals. With n=4, they lie near the observed endpoints and should be interpreted cautiously.
- Metrics whose names contain P95 are first calculated over render frames inside each segment, then summarized across segments.


## v4 axis-alignment revision
- The dynamic-translation panel and temporal-synthesis trade-off panel now use identical limits: 150-400 ms on the x-axis and 0-21 mm on the y-axis.
- Both panels use identical major ticks, making their visual distances directly comparable.
