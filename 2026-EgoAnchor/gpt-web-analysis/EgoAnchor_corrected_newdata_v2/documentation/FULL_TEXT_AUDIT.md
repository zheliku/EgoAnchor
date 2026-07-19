# Full-text audit and changes in corrected v2

## Restored Experiment 1 coverage
- Rest stability restored as stationary frame-increment P95.
- Continuous rotation restored as a lag / angular-RMSE guardrail.
- Failure containment now includes both median occlusion P95 and >40 mm episode counts.
- Start-transition response restored using an explicit frozen operational definition.

## Corrected or removed stale content
- Removed the obsolete auto-generated macro block containing the previous dataset's values.
- Replaced the ambiguous cross-GPU timing paragraph with timing values directly audited from the five new workbooks.
- The Experiment 1 introduction now names five application-facing properties rather than three.
- The metric-contract section now defines centered leakage, frame increment, catastrophic failure, angular lag fitting, and start-transition response separately.
- Figure 1 caption explicitly states which guardrail and cost metrics are reported only in the table.
- Replaced remaining reader-facing “event” terminology with action segment / occlusion episode where applicable.

## Metrics intentionally not ranked as primary wins
- Absolute registration is a guardrail because it includes session-specific fixed bias.
- Translation and rotation lag are not independently bolded; they must be interpreted with aligned residual.
- Start-transition is a policy cost and is not included in the primary-benefit ranking.
- Rotation is retained despite being unfavorable to EgoAnchor, preventing selective reporting.
