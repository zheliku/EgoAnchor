# EgoAnchor corrected Kalman package

- `code/`: Unity C# replacement model and continuous predictive renderer.
- `tests/`: reproducible Python offline mirror.
- `results/`: summary and episode-level metrics.
- `figures/`: PNG and vector PDF test figures.
- `REPORT.md`: Chinese diagnosis, results and integration recommendation.

Run:

```bash
cd tests
python run_corrected_kalman_tests.py
```

The script expects the supplied cache files in `/mnt/data`. Raw XLSX cache-building scripts from the prior analysis package can be used to regenerate them.
