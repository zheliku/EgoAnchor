# EgoAnchor Task 2 analysis package

## Core deliverables
- `egoanchor_task2_analysis.xlsx`: formatted workbook with dashboard, system summary, event metrics, ablations, and metric definitions.
- `ANALYSIS_REPORT.md`: interpretation, guardrails, and recommended paper placement.
- `figures/*.pdf`: vector figures for LaTeX/IEEE publication.
- `figures/*.png`: 300-dpi raster copies for quick review.
- `tables/task2_system_summary.csv`: four main end-to-end configurations.
- `tables/task2_event_metrics.csv`: metrics for all five cycles and all variants.
- `tables/task2_ablation_summary.csv`: temporal-synthesis and StaticLock attribution.
- `tables/task2_event_definitions.csv`: detected onset/stop boundaries.
- `tables/task2_data_audit.*`: completeness checks and frozen operational definitions.
- `generated/task2_results_draft.tex`: paper-ready result paragraphs.
- `generated/task2_system_table.tex`: main quantitative table.
- `generated/task2_ablation_table.tex`: component attribution table.
- `generated/task2_numbers.tex`: reusable LaTeX macros.

## Recommended main-paper figures
1. `task2_representative_timeline.pdf`
2. `task2_temporal_synthesis_jump_ccdf.pdf`
3. `task2_staticlock_transition_tradeoff.pdf`
4. `task2_accuracy_continuity_tradeoff.pdf` when space permits
