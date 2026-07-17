# EgoAnchor Task 5 Analysis

The formal `occlusion_recovery` trial contains seven static-target occlusions
with a median duration of 3.20 s. The
platform reference did not move during the occluded intervals; this task tests
update suppression, pose holding, and reacquisition, not hidden-motion
prediction.

EgoAnchor maintained 100% display availability and reduced the event-level
median occlusion translation P95 to
1.82 mm, compared
with 13.00
mm for One-Euro Anchor. It produced no harmful occlusion output jumps, whereas
One-Euro produced 14.

Disabling VCD increased median occlusion P95 from 1.82 to
23.97 mm and introduced
10 harmful output jumps. At the
observed threshold, VCD retained 98.3% of pose
candidates. Nine of ten rejected candidates were harmful, but only
43% of all harmful candidates were rejected.
The ranking therefore provides useful protection against low-score failures
without guaranteeing rejection of high-confidence drift.

Fresh output arrived after a median of
208 ms. Six events
recovered promptly, while Event 7 required
6436 ms because a sequence
of high-score erroneous candidates passed the gate. This counterexample should
be reported explicitly as the boundary of the current VCD design.

Event direction counts use a 0.001-mm numerical-equivalence tolerance: 4 improved, 3 equivalent, and 0 worse.
