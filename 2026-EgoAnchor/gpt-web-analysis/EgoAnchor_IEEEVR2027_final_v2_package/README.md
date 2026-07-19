# EgoAnchor IEEE VR 2027 - Final v2 revision

This revision implements two presentation changes:

1. The paper no longer exposes the internal term `event` as the primary statistical unit. It reports the acquisition scale (5 continuous sessions, 29,316 unique render timestamps, 6,838 visual candidates, and 234,528 configuration-frame records) while retaining a statistically valid segment-wise analysis. Frames reconstruct continuous trajectories and are not treated as independent samples.
2. Experiment 2 is merged into two logical panels: three compact targeted component-effect plots and one temporal-synthesis lag-residual trade-off plot.

The package includes the final PDF, standalone and VGTC TeX sources, vector/PNG figures, LaTeX table snippets, segment-level plot data, collection-scale metadata, and the rebuild script.

User-facing CSV files use `segment` or `episode` terminology; internal software event IDs are not exposed as the paper's statistical unit.
