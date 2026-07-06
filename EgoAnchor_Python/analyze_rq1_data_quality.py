#!/usr/bin/env python3
"""
RQ1 Data Quality Analysis
Analyzes CSV data from RQ1 experiments to assess data quality, detect anomalies, and provide filtering recommendations.
"""

import pandas as pd
import numpy as np
from pathlib import Path
import sys

def load_data(data_dir):
    """Load all relevant CSV files."""
    data_dir = Path(data_dir)

    anchor_detail = pd.read_csv(data_dir / "anchor_error_detail.csv")
    anchor_summary = pd.read_csv(data_dir / "anchor_error_summary.csv")
    segments = pd.read_csv(data_dir / "segments.csv")

    return anchor_detail, anchor_summary, segments

def detect_invalid_frames(df):
    """Detect frames that should be filtered out."""
    invalid_masks = {
        'searching_state': df['anchor_state'] == 'Searching',
        'invalid_source_frame': df['source_frame_id'] == -1,
        'missing_data': df['translation_error_m'].isna() | df['rotation_error_deg'].isna()
    }

    return invalid_masks

def detect_outliers(df, column, method='iqr', threshold=3.0):
    """Detect outliers using IQR or Z-score method."""
    if method == 'iqr':
        Q1 = df[column].quantile(0.25)
        Q3 = df[column].quantile(0.75)
        IQR = Q3 - Q1
        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR
        outliers = (df[column] < lower_bound) | (df[column] > upper_bound)
    elif method == 'zscore':
        z_scores = np.abs((df[column] - df[column].mean()) / df[column].std())
        outliers = z_scores > threshold
    else:
        raise ValueError(f"Unknown method: {method}")

    return outliers

def compute_statistics(df, column):
    """Compute comprehensive statistics for a column."""
    stats = {
        'count': len(df),
        'mean': df[column].mean(),
        'median': df[column].median(),
        'std': df[column].std(),
        'min': df[column].min(),
        'max': df[column].max(),
        'p25': df[column].quantile(0.25),
        'p75': df[column].quantile(0.75),
        'p95': df[column].quantile(0.95),
        'p99': df[column].quantile(0.99),
    }
    return stats

def analyze_scenario(df_scenario, scenario_name):
    """Analyze a single scenario."""
    print(f"\n{'='*80}")
    print(f"Scenario: {scenario_name.upper()}")
    print(f"{'='*80}")

    # Basic info
    total_frames = len(df_scenario)
    print(f"\nTotal frames: {total_frames}")

    # Detect invalid frames
    invalid_masks = detect_invalid_frames(df_scenario)

    print(f"\nInvalid frame detection:")
    for name, mask in invalid_masks.items():
        count = mask.sum()
        pct = 100 * count / total_frames if total_frames > 0 else 0
        print(f"  - {name}: {count} frames ({pct:.2f}%)")

    # Filter valid frames
    valid_mask = ~(invalid_masks['searching_state'] |
                   invalid_masks['invalid_source_frame'] |
                   invalid_masks['missing_data'])
    df_valid = df_scenario[valid_mask]
    valid_count = len(df_valid)
    valid_pct = 100 * valid_count / total_frames if total_frames > 0 else 0

    print(f"\nValid frames: {valid_count} ({valid_pct:.2f}%)")

    if valid_count == 0:
        print("  WARNING: No valid frames!")
        return None

    # Statistics for translation error
    print(f"\nTranslation Error (m):")
    trans_stats = compute_statistics(df_valid, 'translation_error_m')
    for key, val in trans_stats.items():
        print(f"  {key:8s}: {val:.6f}")

    # Statistics for rotation error
    print(f"\nRotation Error (deg):")
    rot_stats = compute_statistics(df_valid, 'rotation_error_deg')
    for key, val in rot_stats.items():
        print(f"  {key:8s}: {val:.6f}")

    # Detect outliers
    trans_outliers = detect_outliers(df_valid, 'translation_error_m', method='iqr')
    rot_outliers = detect_outliers(df_valid, 'rotation_error_deg', method='iqr')

    print(f"\nOutlier detection (IQR method):")
    print(f"  Translation error outliers: {trans_outliers.sum()} ({100*trans_outliers.sum()/valid_count:.2f}%)")
    print(f"  Rotation error outliers: {rot_outliers.sum()} ({100*rot_outliers.sum()/valid_count:.2f}%)")

    # Analyze anchor states
    print(f"\nAnchor state distribution:")
    state_counts = df_valid['anchor_state'].value_counts()
    for state, count in state_counts.items():
        pct = 100 * count / valid_count
        print(f"  {state}: {count} ({pct:.2f}%)")

    # Analyze policy actions
    print(f"\nPolicy action distribution:")
    policy_counts = df_valid['policy_action'].value_counts()
    for action, count in policy_counts.items():
        pct = 100 * count / valid_count
        print(f"  {action}: {count} ({pct:.2f}%)")

    # Data quality score
    quality_score = calculate_quality_score(
        valid_pct,
        trans_outliers.sum() / valid_count if valid_count > 0 else 1.0,
        rot_outliers.sum() / valid_count if valid_count > 0 else 1.0,
        trans_stats['std'],
        rot_stats['std']
    )

    print(f"\nData Quality Score: {quality_score:.1f}/100")
    print(f"Quality Rating: {get_quality_rating(quality_score)}")

    return {
        'scenario': scenario_name,
        'total_frames': total_frames,
        'valid_frames': valid_count,
        'valid_pct': valid_pct,
        'trans_stats': trans_stats,
        'rot_stats': rot_stats,
        'trans_outliers': trans_outliers.sum(),
        'rot_outliers': rot_outliers.sum(),
        'quality_score': quality_score
    }

def calculate_quality_score(valid_pct, trans_outlier_ratio, rot_outlier_ratio, trans_std, rot_std):
    """Calculate overall data quality score (0-100)."""
    # Valid frame ratio (weight: 40%)
    valid_score = valid_pct * 0.4

    # Outlier ratio (weight: 30%, lower is better)
    outlier_score = (1 - min(1.0, (trans_outlier_ratio + rot_outlier_ratio) / 2)) * 30

    # Data consistency - lower std is better (weight: 30%)
    # Normalize std values
    trans_consistency = max(0, 1 - trans_std / 0.5) * 15  # Assuming 0.5m is high std
    rot_consistency = max(0, 1 - rot_std / 50) * 15  # Assuming 50deg is high std

    total_score = valid_score + outlier_score + trans_consistency + rot_consistency
    return min(100, max(0, total_score))

def get_quality_rating(score):
    """Get quality rating from score."""
    if score >= 90:
        return "Excellent - Ready for publication"
    elif score >= 80:
        return "Good - Minor issues, acceptable for publication"
    elif score >= 70:
        return "Fair - Some concerns, review recommended"
    elif score >= 60:
        return "Poor - Significant issues, filtering recommended"
    else:
        return "Unacceptable - Major issues, re-collection recommended"

def main():
    if len(sys.argv) < 2:
        data_dir = r"P:\VSCode-Project\EgoAnchor\EgoAnchor_Python\data\research\rq1\20260706_163825_controller_right"
    else:
        data_dir = sys.argv[1]

    print("="*80)
    print("RQ1 Data Quality Analysis")
    print("="*80)
    print(f"\nData directory: {data_dir}")

    # Load data
    anchor_detail, anchor_summary, segments = load_data(data_dir)

    print(f"\nLoaded files:")
    print(f"  - anchor_error_detail.csv: {len(anchor_detail)} rows")
    print(f"  - anchor_error_summary.csv: {len(anchor_summary)} rows")
    print(f"  - segments.csv: {len(segments)} segments")

    # Analyze overall data
    print(f"\n{'='*80}")
    print("OVERALL DATA ANALYSIS")
    print(f"{'='*80}")

    print(f"\nCondition distribution:")
    condition_counts = anchor_detail['condition'].value_counts()
    for condition, count in condition_counts.items():
        pct = 100 * count / len(anchor_detail)
        print(f"  {condition}: {count} frames ({pct:.2f}%)")

    # Analyze each labeled scenario
    results = []
    scenarios = ['static_observation', 'occlusion_recovery', 'slow_translation', 'rotation', 'fast_motion']

    for scenario in scenarios:
        df_scenario = anchor_detail[anchor_detail['condition'] == scenario]
        if len(df_scenario) > 0:
            result = analyze_scenario(df_scenario, scenario)
            if result:
                results.append(result)

    # Analyze unlabeled data
    df_unlabeled = anchor_detail[anchor_detail['condition'] == 'unlabeled']
    if len(df_unlabeled) > 0:
        unlabeled_result = analyze_scenario(df_unlabeled, 'unlabeled')
        if unlabeled_result:
            results.append(unlabeled_result)

    # Summary comparison
    print(f"\n{'='*80}")
    print("SUMMARY COMPARISON")
    print(f"{'='*80}\n")

    print(f"{'Scenario':<25} {'Valid%':>8} {'Trans P95':>10} {'Rot P95':>10} {'Quality':>8}")
    print("-" * 80)
    for result in results:
        trans_p95 = result['trans_stats']['p95']
        rot_p95 = result['rot_stats']['p95']
        print(f"{result['scenario']:<25} {result['valid_pct']:>7.1f}% "
              f"{trans_p95:>9.4f}m {rot_p95:>9.2f}° {result['quality_score']:>7.1f}")

    # Recommendations
    print(f"\n{'='*80}")
    print("RECOMMENDATIONS")
    print(f"{'='*80}\n")

    print("1. Data Filtering:")
    print("   - MUST filter: anchor_state=='Searching' and source_frame_id==-1")

    for result in results:
        if result['valid_pct'] < 95:
            print(f"   - {result['scenario']}: {100-result['valid_pct']:.1f}% invalid frames detected")

    print("\n2. Scenario-specific issues:")
    for result in results:
        if result['quality_score'] < 80:
            print(f"   - {result['scenario']}: Quality score {result['quality_score']:.1f} - Review recommended")
            if result['trans_stats']['p95'] > 0.3:
                print(f"     * High translation error (P95={result['trans_stats']['p95']:.3f}m)")
            if result['rot_stats']['p95'] > 90:
                print(f"     * High rotation error (P95={result['rot_stats']['p95']:.1f}°)")

    print("\n3. Unlabeled data:")
    unlabeled_res = next((r for r in results if r['scenario'] == 'unlabeled'), None)
    if unlabeled_res:
        print(f"   - {unlabeled_res['total_frames']} unlabeled frames detected")
        print(f"   - Quality score: {unlabeled_res['quality_score']:.1f}")
        if unlabeled_res['quality_score'] < 70:
            print("   - WARNING: Poor quality unlabeled data, should be excluded from analysis")

    print("\n4. Publication readiness:")
    avg_quality = np.mean([r['quality_score'] for r in results if r['scenario'] != 'unlabeled'])
    print(f"   - Average quality score (labeled scenarios): {avg_quality:.1f}/100")

    if avg_quality >= 85:
        print("   - READY: Data quality is suitable for publication")
    elif avg_quality >= 75:
        print("   - ACCEPTABLE: Data quality is acceptable with minor filtering")
    elif avg_quality >= 65:
        print("   - REVIEW: Significant filtering recommended before publication")
    else:
        print("   - NOT READY: Consider re-collection or major data cleaning")

    print("\n5. Suggested filters:")
    print("   df_filtered = df[")
    print("       (df['anchor_state'] != 'Searching') &")
    print("       (df['source_frame_id'] != -1) &")
    print("       (df['condition'] != 'unlabeled')  # Optional: exclude unlabeled")
    print("   ]")

if __name__ == "__main__":
    main()
