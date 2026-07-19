# EgoAnchor IEEE VR 2027 revision package

## Paper

- `paper/egoanchor_ieeevr2027_revised.pdf`: compiled review PDF.
- `paper/egoanchor_ieeevr2027_revised_vgtc.tex`: source intended for the official IEEE VR/VGTC template. Compile it together with the official `vgtc.cls`, bibliography style, the included `.bib`, and the `figures/` directory.
- `paper/egoanchor_ieeevr2027_revised_standalone.tex`: self-contained review-layout source used to generate the included PDF in this environment.
- `paper/egoanchor_cn_refs.bib`: bibliography database.

## Figures

Both PDF and PNG versions of the revised evaluation figures are included. The pipeline figure is also included as PNG.

## Derived data

- `experiment1_paper_metrics.csv`: source values for the revised Experiment 1 table and overview figure.
- `experiment2_ablation_metrics.csv`: source values for the revised ablation table and figure.
- `session_structure.csv`: session/trial/event structure recovered from the workbooks.
- `task1_static_event_metrics.csv`: event-level audit data for Task 1.
- `raw_workbook_manifest.csv`: size and SHA-256 provenance for the five original workbooks.

The large raw XLSX files are intentionally not duplicated. They remain the authoritative inputs supplied with the conversation.

## Important interpretation

This is a system-characterization dataset: one continuous trial per scenario with repeated marked events. The revised manuscript therefore uses descriptive event-level pairing and does not treat render frames as independent statistical samples.
