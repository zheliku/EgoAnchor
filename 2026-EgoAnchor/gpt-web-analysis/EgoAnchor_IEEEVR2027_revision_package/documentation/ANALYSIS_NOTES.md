# EgoAnchor evaluation analysis notes

## What changed in the paper

The quantitative evaluation is reorganized around four application-facing properties rather than a flat list of scene metrics:

1. **World consistency** under headset motion.
2. **Rest stability** for a stationary or newly placed object.
3. **Dynamic fidelity**, separating fitted lag from lag-aligned trajectory residual.
4. **Failure containment** during occlusion and low-quality observations.

Experiment 2 is reframed as component attribution: each ablation is evaluated only in the physical scenario that matches its design objective, with a guardrail metric reported alongside the primary metric.

## Statistical contract

- There are five scenario-specific sessions and one continuous trial per scenario.
- Repeated marked events within a session are the descriptive pairing unit: 4 static-head events, 5 start-stop events, 18 translation events, 3 rotation events, and 7 occlusion episodes.
- Render frames form trajectories but are **not** treated as independent samples.
- Results are event-level median [IQR] and paired deltas. They should not be described as population-level significance or cross-environment generalization.
- The Quest controller pose is a synchronized platform reference, not external physical ground truth.

## Key conclusions

- Static head motion: EgoAnchor reduces translation event-P95 from 22.237 mm (Arrival-Hold) to 3.679 mm.
- Continuous translation: EgoAnchor increases fitted lag from 182.5 ms to 325 ms relative to Arrival-Hold, while lowering lag-aligned residual from 10.568 mm to 5.697 mm.
- Continuous rotation: the translation advantage does not uniformly extend to rotation; Capture-Hold has lower fitted angular lag and residual than EgoAnchor in this batch.
- Occlusion: EgoAnchor reduces occlusion-window translation P95 from 12.999 mm (One-Euro) to 1.822 mm.
- VCD removal increases occlusion P95 by a paired median of 21.857 mm without changing the shared candidate-bound recovery time.
- Temporal synthesis redistributes the jump tail: P95 and P99 deltas have opposite signs, so no unconditional “jump reduction” claim is made.

## Large-workbook handling

The original workbooks are not duplicated in this package. `scripts/xlsx_stream.py` reads XLSX worksheet XML incrementally from the ZIP container, avoiding full in-memory loading of 25–39 MB files and their large render sheets. `raw_workbook_manifest.csv` records exact file sizes and SHA-256 hashes for provenance.
