import csv
from pathlib import Path
from artifact_tool import Workbook, SpreadsheetFile

ROOT = Path(__file__).resolve().parents[1]
summary_path = ROOT / 'results' / 'summary_metrics.csv'
episode_path = ROOT / 'results' / 'episode_metrics.csv'
out_path = ROOT / 'EgoAnchor_corrected_kalman_summary.xlsx'

with summary_path.open(encoding='utf-8-sig', newline='') as f:
    summary_rows = list(csv.DictReader(f))
with episode_path.open(encoding='utf-8-sig', newline='') as f:
    episode_rows = list(csv.DictReader(f))

numeric_summary = {
    'static_centered_p95_mm', 'static_frame_increment_p95_mm',
    'translation_lag_ms', 'translation_residual_mm', 'render_step_p95_mm',
    'render_step_max_mm', 'correction_step_p95_mm', 'correction_step_max_mm',
    'start_response_ms', 'occlusion_p95_mm', 'occlusion_failures_gt40',
    'rotation_lag_ms', 'rotation_residual_deg'
}
for row in summary_rows:
    for key in numeric_summary:
        if row.get(key) not in (None, ''):
            row[key] = float(row[key])

wb = Workbook.create()
summary = wb.worksheets.add('Summary')

summary.get_range('A1:N1').merge()
summary.get_range('A1').values = [['EgoAnchor Corrected Kalman — Offline Test Summary']]
summary.get_range('A1:N1').format = {
    'fill': '#1F4E78',
    'font': {'bold': True, 'color': '#FFFFFF', 'size': 16},
    'horizontal_alignment': 'center',
    'vertical_alignment': 'center',
    'row_height': 28,
}

summary.get_range('A3:B9').values = [
    ['Frozen parameter', 'Value'],
    ['Position acceleration noise density', '0.10 m²/s³'],
    ['Position measurement std', '8 mm'],
    ['Initial velocity std', '0.50 m/s'],
    ['Innovation gate', '4 sigma'],
    ['Prediction horizon', '180 ms'],
    ['Correction half-life', '60 ms'],
]
summary.get_range('A3:B3').format = {
    'fill': '#D9EAF7', 'font': {'bold': True}, 'horizontal_alignment': 'center'
}
summary.get_range('A3:B9').format.borders = {
    'top': {'style': 'continuous', 'color': '#B7C9D6'},
    'bottom': {'style': 'continuous', 'color': '#B7C9D6'},
    'left': {'style': 'continuous', 'color': '#B7C9D6'},
    'right': {'style': 'continuous', 'color': '#B7C9D6'},
}

headers = [
    'Method', 'Static centered P95 (mm)', 'Static frame increment P95 (mm)',
    'Translation lag (ms)', 'Translation residual (mm)',
    'Correction step P95 (mm)', 'Start response (ms)',
    'Occlusion P95 (mm)', 'Occlusion failures >40',
    'Rotation lag (ms)', 'Rotation residual (deg)'
]
summary.get_range('A12:K12').values = [headers]
summary.get_range('A12:K12').format = {
    'fill': '#4472C4', 'font': {'bold': True, 'color': '#FFFFFF'},
    'horizontal_alignment': 'center', 'wrap_text': True, 'row_height': 34,
}
values = []
for row in summary_rows:
    values.append([
        row['method'], row['static_centered_p95_mm'], row['static_frame_increment_p95_mm'],
        row['translation_lag_ms'], row['translation_residual_mm'],
        row['correction_step_p95_mm'], row['start_response_ms'],
        row['occlusion_p95_mm'], row['occlusion_failures_gt40'],
        row['rotation_lag_ms'], row['rotation_residual_deg'],
    ])
summary.get_range(f'A13:K{12+len(values)}').values = values
summary.get_range(f'B13:K{12+len(values)}').format.number_format = '0.000'
summary.get_range(f'I13:I{12+len(values)}').format.number_format = '0'
summary.get_range(f'A12:K{12+len(values)}').format.borders = {
    'top': {'style': 'continuous', 'color': '#D0D7DE'},
    'bottom': {'style': 'continuous', 'color': '#D0D7DE'},
    'left': {'style': 'continuous', 'color': '#D0D7DE'},
    'right': {'style': 'continuous', 'color': '#D0D7DE'},
}

summary.get_range('M3:N9').values = [
    ['Key conclusion', 'Measured value'],
    ['Residual reduction vs legacy', '45.6%'],
    ['Correction-step reduction', '82.8%'],
    ['Static increment reduction', '27.8%'],
    ['Corrected continuous lag', '165 ms'],
    ['Buffered-Hermite lag', '320 ms'],
    ['Fresh capture required', 'Yes'],
]
summary.get_range('M3:N3').format = {
    'fill': '#E2F0D9', 'font': {'bold': True}, 'horizontal_alignment': 'center'
}
summary.get_range('M3:N9').format.borders = {
    'top': {'style': 'continuous', 'color': '#C6D9B5'},
    'bottom': {'style': 'continuous', 'color': '#C6D9B5'},
    'left': {'style': 'continuous', 'color': '#C6D9B5'},
    'right': {'style': 'continuous', 'color': '#C6D9B5'},
}

# Helper ranges for chart sources (placed outside the visible report area).
summary.get_range('U1:V5').values = [['Method', 'Correction step P95 (mm)']] + [[r['method'], r['correction_step_p95_mm']] for r in summary_rows]
summary.get_range('W1:X5').values = [['Method', 'Translation residual (mm)']] + [[r['method'], r['translation_residual_mm']] for r in summary_rows]

chart1 = summary.charts.add('bar', summary.get_range('U1:V5'))
chart1.title_text = 'Correction-step P95 by method'
chart1.has_legend = False
chart1.set_position('M12', 'T27')

chart2 = summary.charts.add('bar', summary.get_range('W1:X5'))
chart2.title_text = 'Translation residual by method'
chart2.has_legend = False
chart2.set_position('M29', 'T44')

summary.freeze_panes.freeze_rows(12)
summary.get_range('A1:T45').format.wrap_text = True
for col, width in [('A:A', 24), ('B:K', 16), ('M:M', 28), ('N:N', 18)]:
    summary.get_range(col).format.column_width = width

# Episode metrics sheet
episode = wb.worksheets.add('Episode Metrics')
fields = sorted({k for r in episode_rows for k in r.keys()})
episode.get_range_by_indexes(0, 0, 1, len(fields)).values = [fields]
episode.get_range_by_indexes(0, 0, 1, len(fields)).format = {
    'fill': '#4472C4', 'font': {'bold': True, 'color': '#FFFFFF'},
    'horizontal_alignment': 'center', 'wrap_text': True,
}
rows_out = []
for r in episode_rows:
    row = []
    for k in fields:
        v = r.get(k, '')
        if v not in ('', None) and k not in ('scenario', 'method'):
            try: v = float(v)
            except ValueError: pass
        row.append(v)
    rows_out.append(row)
if rows_out:
    episode.get_range_by_indexes(1, 0, len(rows_out), len(fields)).values = rows_out
episode.freeze_panes.freeze_rows(1)
episode.get_range_by_indexes(0, 0, len(rows_out)+1, len(fields)).format.wrap_text = False
episode.get_range_by_indexes(0, 0, len(rows_out)+1, len(fields)).format.autofit_columns()
for i in range(len(fields)):
    rng = episode.get_range_by_indexes(0, i, len(rows_out)+1, 1)
    if rng.format.column_width > 24:
        rng.format.column_width = 24

# Notes sheet
notes = wb.worksheets.add('Notes')
notes.get_range('A1:F1').merge()
notes.get_range('A1').values = [['Interpretation and Limitations']]
notes.get_range('A1:F1').format = {
    'fill': '#1F4E78', 'font': {'bold': True, 'color': '#FFFFFF', 'size': 15},
    'horizontal_alignment': 'center', 'row_height': 26,
}
notes.get_range('A3:B10').values = [
    ['Item', 'Statement'],
    ['Primary recommendation', 'Use corrected KalmanModel with ContinuousPredictStrategy for a responsive production configuration.'],
    ['Do not use alone', 'Corrected direct prediction remains discontinuous and can run away during observation gaps.'],
    ['Buffered comparison', 'Buffered-Hermite remains substantially more accurate but has much higher latency.'],
    ['Parameter status', 'The frozen profile was selected exploratorily on these logs.'],
    ['Paper status', 'Do not replace paper values until a fresh Task 1–5 capture is completed.'],
    ['Compilation', 'UnityEngine assemblies were unavailable in the analysis environment; compile in the project.'],
    ['Reproducibility', 'Legacy offline mirror matched the prior prediction trace exactly.'],
]
notes.get_range('A3:B3').format = {'fill': '#D9EAF7', 'font': {'bold': True}}
notes.get_range('A3:B10').format.wrap_text = True
notes.get_range('A:A').format.column_width = 24
notes.get_range('B:B').format.column_width = 75
notes.get_range('A3:B10').format.borders = {
    'top': {'style': 'continuous', 'color': '#D0D7DE'},
    'bottom': {'style': 'continuous', 'color': '#D0D7DE'},
    'left': {'style': 'continuous', 'color': '#D0D7DE'},
    'right': {'style': 'continuous', 'color': '#D0D7DE'},
}

# Compact verification
check = wb.inspect({'kind': 'table', 'range': 'Summary!A1:N17', 'include': 'values,formulas', 'table_max_rows': 20, 'table_max_cols': 14})
print(check.ndjson)
errors = wb.inspect({'kind': 'match', 'search_term': '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A', 'options': {'use_regex': True, 'max_results': 100}, 'summary': 'formula error scan'})
print(errors.ndjson)
SpreadsheetFile.export_xlsx(wb).save(str(out_path))
print(out_path)
