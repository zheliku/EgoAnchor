# EgoAnchor corrected new-data revision v2

This package supersedes `EgoAnchor_corrected_newdata_package.zip`.

## Main reporting changes
- Experiment 1 Table 1 is restored to cover world consistency, rest stability, translation and rotation fidelity, failure containment, and start-transition cost.
- The main table now includes stationary frame-increment P95, angular lag / RMSE, catastrophic occlusion counts, and the newly recomputed start-transition response.
- Rotation remains in the table as an unfavorable guardrail rather than being omitted.
- The paper now uses a frozen transition definition: 5 mm sustained displacement, 250 ms pre-motion baseline, and 100 ms persistence.
- The obsolete numerical macro block from the previous dataset was removed.
- Runtime-performance wording is now grounded in the new workbooks: TRACK 75.3 ms median / 90.1 ms P95; candidate interval 104.5 ms median (~9.6 Hz).

## Key expanded-table values for EgoAnchor
- Head-motion leakage P95: 1.631 mm
- Absolute registration P95: 6.894 mm
- Stationary frame-increment P95: 0.098 mm
- Translation lag / aligned RMSE: 320.0 ms / 4.960 mm
- Rotation lag / aligned RMSE: 372.5 ms / 4.691 deg
- Occlusion P95: 1.980 mm
- Catastrophic occlusion episodes (>40 mm): 0/9
- Start-transition response: 591.1 ms

See `documentation/FULL_TEXT_AUDIT.md` for the full audit.

## Analysis workbook
- `data/EgoAnchor_corrected_analysis_v2.xlsx` contains the expanded system summary, transition segments, rotation segments, corrected static metrics, capture-alignment candidates, occlusion episodes, runtime audit, and reporting audit.
