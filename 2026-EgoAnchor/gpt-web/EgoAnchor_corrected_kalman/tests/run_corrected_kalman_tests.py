#!/usr/bin/env python3
"""Offline mirror and tests for the corrected EgoAnchor Kalman predictor.

The real-log tests use the capture-aligned accepted observations and render
timeline in task_1_complete.xlsx / task_3_complete.xlsx. The code mirrors the
C# implementation in ../code/KalmanModel.cs and ContinuousPredictStrategy.cs.
"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
FIGURES = ROOT / "figures"
RESULTS.mkdir(parents=True, exist_ok=True)
FIGURES.mkdir(parents=True, exist_ok=True)

CACHE_DIR = ROOT / "tests" / "cache"

def cache_path(name: str) -> Path:
    local = CACHE_DIR / name
    return local if local.exists() else Path("/mnt/data") / name

TASK1_CACHE = cache_path("kf_task1_cache.npz")
TASK3_CACHE = cache_path("kf_task3_cache.npz")
TRACE_FILE = cache_path("kf_issue_trace.npz")

# Frozen exploratory profile. It was selected from a small grid on the supplied
# logs, so results are characterization, not independent generalization.
PROFILE = {
    "position_acceleration_noise_density_m2_s3": 0.10,
    "position_measurement_std_m": 0.008,
    "initial_velocity_std_m_s": 0.50,
    "innovation_gate_sigma": 4.0,
    "max_prediction_seconds": 0.18,
    "correction_half_life_seconds": 0.06,
}


@dataclass
class Observation:
    arrival_ms: float
    measurement_ms: float
    position: np.ndarray


@dataclass
class RenderRow:
    time_ms: float
    logged: np.ndarray
    reference: np.ndarray


def load_cache(path: Path):
    z = np.load(path)
    obs = [Observation(float(x[0]), float(x[1]), x[2:5].astype(float)) for x in z["obs"]]
    rows = [RenderRow(float(x[0]), x[1:4].astype(float), x[4:7].astype(float)) for x in z["rows"]]
    return obs, rows, z["starts"].astype(float), z["ends"].astype(float)


class LegacyCvKalman1D:
    """Mirror of the recovered legacy covariance update."""

    def __init__(self):
        self.x = np.zeros(2, dtype=float)
        self.p = np.eye(2, dtype=float)

    def reset(self, measurement: float):
        self.x[:] = [measurement, 0.0]
        self.p[:] = [[4.0e-4, 0.0], [0.0, 1.0]]

    def predict(self, dt: float):
        if dt <= 0.0:
            return
        f = np.array([[1.0, dt], [0.0, 1.0]])
        self.x = f @ self.x
        self.p = f @ self.p @ f.T + np.eye(2) * (0.20 * dt)

    def correct(self, measurement: float):
        innovation = measurement - self.x[0]
        s = self.p[0, 0] + 4.0e-4
        k = self.p[:, 0] / s
        self.x += k * innovation
        self.p -= np.outer(k, self.p[0, :])
        return float(k[0]), float(innovation)


class CorrectedCvKalman1D:
    """Mirror of the replacement C# CvKalman1D."""

    def __init__(self, qa: float, r: float, gate_sigma: float, velocity_variance: float):
        self.qa = float(qa)
        self.r = float(r)
        self.gate_sigma = float(gate_sigma)
        self.velocity_variance = float(velocity_variance)
        self.x = np.zeros(2, dtype=float)
        self.p = np.zeros((2, 2), dtype=float)

    def reset(self, measurement: float):
        self.x[:] = [measurement, 0.0]
        self.p[:] = [[self.r, 0.0], [0.0, self.velocity_variance]]

    def predict(self, dt: float):
        if dt <= 0.0:
            return
        f = np.array([[1.0, dt], [0.0, 1.0]])
        q = self.qa * np.array(
            [[dt**3 / 3.0, dt**2 / 2.0], [dt**2 / 2.0, dt]], dtype=float
        )
        self.x = f @ self.x
        self.p = f @ self.p @ f.T + q
        self.p = 0.5 * (self.p + self.p.T)
        self._stabilize()

    def correct(self, measurement: float):
        innovation = float(measurement - self.x[0])
        used_r = self.r
        if self.gate_sigma > 0.0:
            nominal_s = max(float(self.p[0, 0] + used_r), 1e-15)
            gate2 = self.gate_sigma**2
            if innovation * innovation / nominal_s > gate2:
                used_r = max(used_r, innovation * innovation / gate2 - float(self.p[0, 0]))

        s = max(float(self.p[0, 0] + used_r), 1e-15)
        k = self.p[:, 0] / s
        self.x += k * innovation

        # Joseph form.
        h = np.array([[1.0, 0.0]])
        a = np.eye(2) - np.outer(k, h[0])
        self.p = a @ self.p @ a.T + used_r * np.outer(k, k)
        self.p = 0.5 * (self.p + self.p.T)
        self._stabilize()
        return float(k[0]), innovation

    def _stabilize(self):
        self.p[0, 0] = max(float(self.p[0, 0]), 0.0)
        self.p[1, 1] = max(float(self.p[1, 1]), 0.0)
        bound = math.sqrt(max(float(self.p[0, 0] * self.p[1, 1]), 0.0))
        self.p[0, 1] = np.clip(self.p[0, 1], -bound, bound)
        self.p[1, 0] = self.p[0, 1]


def corrected_factory():
    return CorrectedCvKalman1D(
        qa=PROFILE["position_acceleration_noise_density_m2_s3"],
        r=PROFILE["position_measurement_std_m"] ** 2,
        gate_sigma=PROFILE["innovation_gate_sigma"],
        velocity_variance=PROFILE["initial_velocity_std_m_s"] ** 2,
    )


def replay_position(
    observations: list[Observation],
    rows: list[RenderRow],
    model_kind: str,
    strategy: str,
    max_prediction_seconds: float | None = None,
    correction_half_life_seconds: float | None = None,
):
    if model_kind == "legacy":
        filters = [LegacyCvKalman1D() for _ in range(3)]
    elif model_kind == "corrected":
        filters = [corrected_factory() for _ in range(3)]
    else:
        raise ValueError(model_kind)

    output = []
    posterior = []
    gains = []
    innovations = []
    observation_index = 0
    last_measurement_ms = None

    residual = np.zeros(3, dtype=float)
    has_rendered = False
    last_rendered = np.zeros(3, dtype=float)
    last_render_time_ms = None

    def predict_at(time_ms: float):
        if last_measurement_ms is None:
            return np.full(3, np.nan)
        ahead = (time_ms - last_measurement_ms) / 1000.0
        if max_prediction_seconds is not None:
            ahead = min(ahead, max_prediction_seconds)
        return np.array([f.x[0] + f.x[1] * ahead for f in filters], dtype=float)

    for row in rows:
        render_ms = row.time_ms
        while observation_index < len(observations) and observations[observation_index].arrival_ms <= render_ms + 1e-9:
            obs = observations[observation_index]
            if last_measurement_ms is None:
                for axis in range(3):
                    filters[axis].reset(float(obs.position[axis]))
                last_measurement_ms = obs.measurement_ms
            elif obs.measurement_ms > last_measurement_ms + 1e-6:
                dt = (obs.measurement_ms - last_measurement_ms) / 1000.0
                axis_gains = []
                axis_innovations = []
                for axis in range(3):
                    filters[axis].predict(dt)
                    gain, innovation = filters[axis].correct(float(obs.position[axis]))
                    axis_gains.append(gain)
                    axis_innovations.append(innovation)
                gains.append(axis_gains)
                innovations.append(axis_innovations)
                last_measurement_ms = obs.measurement_ms

                if strategy == "continuous" and has_rendered:
                    residual = last_rendered - predict_at(last_render_time_ms)
            # Non-increasing timestamps are rejected.
            observation_index += 1

        if last_measurement_ms is None:
            output.append(np.full(3, np.nan))
            posterior.append(np.full(3, np.nan))
            continue

        base = predict_at(render_ms)
        posterior.append(np.array([f.x[0] for f in filters], dtype=float))
        if strategy == "direct":
            rendered = base
        elif strategy == "continuous":
            rendered = base + residual
        else:
            raise ValueError(strategy)

        output.append(rendered.copy())

        if strategy == "continuous" and has_rendered:
            dt = max((render_ms - last_render_time_ms) / 1000.0, 0.0)
            half_life = max(float(correction_half_life_seconds), 1e-6)
            residual *= math.exp(-math.log(2.0) * dt / half_life)

        has_rendered = True
        last_rendered = rendered.copy()
        last_render_time_ms = render_ms

    return {
        "output": np.asarray(output),
        "posterior": np.asarray(posterior),
        "gains": np.asarray(gains),
        "innovations": np.asarray(innovations),
    }


def lag_residual(time_ms, display, reference, start_ms, end_ms):
    select = (
        (time_ms >= start_ms)
        & (time_ms < end_ms)
        & np.all(np.isfinite(display), axis=1)
        & np.all(np.isfinite(reference), axis=1)
    )
    tt = time_ms[select]
    dd = display[select]
    rr0 = reference[select]
    if len(tt) < 10:
        return np.nan, np.nan

    best = (np.inf, np.nan)
    for lag_ms in np.arange(0.0, 600.1, 5.0):
        query = tt - lag_ms
        valid = (query >= start_ms) & (query <= end_ms)
        if valid.sum() < 10:
            continue
        rr = np.column_stack([np.interp(query[valid], tt, rr0[:, axis]) for axis in range(3)])
        rmse = float(np.sqrt(np.mean(np.sum((dd[valid] - rr) ** 2, axis=1))))
        if rmse < best[0]:
            best = (rmse, lag_ms)
    return float(best[1]), float(best[0] * 1000.0)


def correction_steps(time_ms, output, observations):
    values = []
    for obs in observations[1:]:
        index = int(np.searchsorted(time_ms, obs.arrival_ms))
        if 1 <= index < len(time_ms) and np.all(np.isfinite(output[index - 1 : index + 1])):
            values.append(float(np.linalg.norm(output[index] - output[index - 1]) * 1000.0))
    return np.asarray(values)


def compute_episode_metrics(method, output, rows, starts, ends, observations, scenario):
    time_ms = np.asarray([r.time_ms for r in rows])
    reference = np.asarray([r.reference for r in rows])
    records = []
    if scenario == "static":
        error = output - reference
        for episode, (start, end) in enumerate(zip(starts, ends), 1):
            select = (time_ms >= start) & (time_ms < end) & np.all(np.isfinite(error), axis=1)
            episode_error = error[select]
            episode_output = output[select]
            if len(episode_error) < 10:
                continue
            centered = episode_error - np.median(episode_error, axis=0)
            records.append(
                {
                    "scenario": "static_head_motion",
                    "episode": episode,
                    "method": method,
                    "static_centered_p95_mm": float(np.percentile(np.linalg.norm(centered, axis=1), 95) * 1000.0),
                    "frame_increment_p95_mm": float(np.percentile(np.linalg.norm(np.diff(episode_output, axis=0), axis=1), 95) * 1000.0),
                }
            )
    else:
        for episode, (start, end) in enumerate(zip(starts, ends), 1):
            lag, residual = lag_residual(time_ms, output, reference, start, end)
            records.append(
                {
                    "scenario": "continuous_translation",
                    "episode": episode,
                    "method": method,
                    "translation_lag_ms": lag,
                    "translation_residual_mm": residual,
                }
            )
    return records


def summarize(method, static_output, dynamic_output, task1, task3):
    obs1, rows1, starts1, ends1 = task1
    obs3, rows3, starts3, ends3 = task3
    static_records = compute_episode_metrics(method, static_output, rows1, starts1, ends1, obs1, "static")
    dynamic_records = compute_episode_metrics(method, dynamic_output, rows3, starts3, ends3, obs3, "dynamic")
    time3 = np.asarray([r.time_ms for r in rows3])
    all_steps = np.linalg.norm(np.diff(dynamic_output, axis=0), axis=1) * 1000.0
    arrival_steps = correction_steps(time3, dynamic_output, obs3)
    return {
        "method": method,
        "static_centered_p95_mm": float(np.median([r["static_centered_p95_mm"] for r in static_records])),
        "static_frame_increment_p95_mm": float(np.median([r["frame_increment_p95_mm"] for r in static_records])),
        "translation_lag_ms": float(np.nanmedian([r["translation_lag_ms"] for r in dynamic_records])),
        "translation_residual_mm": float(np.nanmedian([r["translation_residual_mm"] for r in dynamic_records])),
        "render_step_p95_mm": float(np.nanpercentile(all_steps, 95)),
        "render_step_max_mm": float(np.nanmax(all_steps)),
        "correction_step_p95_mm": float(np.percentile(arrival_steps, 95)),
        "correction_step_max_mm": float(np.max(arrival_steps)),
        "episode_records": static_records + dynamic_records,
        "correction_steps": arrival_steps,
    }


def ecdf(values):
    x = np.sort(values[np.isfinite(values)])
    y = np.arange(1, len(x) + 1) / len(x)
    return x, y


def create_real_trace_figure(time_ms, reference, observations, outputs):
    legacy = outputs["Legacy direct"]
    steps = np.linalg.norm(np.diff(legacy, axis=0), axis=1)
    largest = int(np.nanargmax(steps)) + 1
    center = time_ms[largest]
    select = (time_ms >= center - 700.0) & (time_ms <= center + 700.0)

    centered_ref = reference[select] - np.median(reference[select], axis=0)
    _, _, vt = np.linalg.svd(centered_ref, full_matrices=False)
    axis = vt[0]
    origin = np.median(reference[select], axis=0)
    relative_time = (time_ms[select] - center) / 1000.0

    fig = plt.figure(figsize=(9.5, 5.2))
    ax = fig.add_subplot(111)
    ax.plot(relative_time, (reference[select] - origin) @ axis * 1000.0, label="Reference")
    for name in ["Legacy direct", "Corrected direct", "Corrected continuous", "Buffered-Hermite"]:
        ax.plot(relative_time, (outputs[name][select] - origin) @ axis * 1000.0, label=name)

    arrivals = [o for o in observations if center - 700.0 <= o.arrival_ms <= center + 700.0]
    if arrivals:
        ax.scatter(
            [(o.arrival_ms - center) / 1000.0 for o in arrivals],
            [(o.position - origin) @ axis * 1000.0 for o in arrivals],
            marker="x",
            label="Accepted candidate at arrival",
        )
    ax.set_xlabel("Time relative to largest legacy correction (s)")
    ax.set_ylabel("Position on local motion axis (mm)")
    ax.set_title("Real log: asynchronous correction discontinuity and corrected output")
    ax.grid(True, alpha=0.25)
    ax.legend(ncol=2)
    fig.tight_layout()
    fig.savefig(FIGURES / "01_real_trace_correction.png", dpi=220)
    fig.savefig(FIGURES / "01_real_trace_correction.pdf")
    plt.close(fig)


def create_ecdf_figure(summaries):
    fig = plt.figure(figsize=(8.5, 5.0))
    ax = fig.add_subplot(111)
    for summary in summaries:
        x, y = ecdf(summary["correction_steps"])
        ax.plot(x, y, label=summary["method"])
    ax.set_xlabel("Render-frame displacement at observation arrival (mm)")
    ax.set_ylabel("Empirical cumulative probability")
    ax.set_title("Real log: correction-associated display steps")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIGURES / "02_correction_step_ecdf.png", dpi=220)
    fig.savefig(FIGURES / "02_correction_step_ecdf.pdf")
    plt.close(fig)


def create_tradeoff_figure(summaries):
    fig = plt.figure(figsize=(7.8, 5.4))
    ax = fig.add_subplot(111)
    for summary in summaries:
        ax.scatter(summary["translation_lag_ms"], summary["translation_residual_mm"], s=70)
        ax.annotate(
            summary["method"],
            (summary["translation_lag_ms"], summary["translation_residual_mm"]),
            xytext=(5, 5),
            textcoords="offset points",
        )
    ax.set_xlabel("Effective lag (ms; lower is better)")
    ax.set_ylabel("Lag-aligned translation residual (mm; lower is better)")
    ax.set_title("Real log: latency–trajectory-fidelity trade-off")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIGURES / "03_lag_residual_tradeoff.png", dpi=220)
    fig.savefig(FIGURES / "03_lag_residual_tradeoff.pdf")
    plt.close(fig)


def create_static_increment_figure(summaries):
    names = [s["method"] for s in summaries]
    values = [s["static_frame_increment_p95_mm"] for s in summaries]
    fig = plt.figure(figsize=(8.6, 5.0))
    ax = fig.add_subplot(111)
    ax.bar(names, values)
    ax.set_ylabel("Median episode frame-increment P95 (mm)")
    ax.set_title("Real log: static render stability without StaticLock")
    ax.tick_params(axis="x", rotation=18)
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIGURES / "04_static_frame_increment.png", dpi=220)
    fig.savefig(FIGURES / "04_static_frame_increment.pdf")
    plt.close(fig)


def create_synthetic_online_figure():
    rng = np.random.default_rng(20260723)
    render_t = np.arange(0.0, 12.0, 1.0 / 90.0)

    # Piecewise hand-like position: rest, accelerate, constant, stop, reverse.
    position = np.zeros_like(render_t)
    velocity = np.zeros_like(render_t)
    for i in range(1, len(render_t)):
        t = render_t[i]
        if 1.0 <= t < 1.8:
            acceleration = 0.35
        elif 1.8 <= t < 4.0:
            acceleration = 0.0
        elif 4.0 <= t < 4.7:
            acceleration = -0.45
        elif 6.2 <= t < 6.8:
            acceleration = -0.30
        elif 6.8 <= t < 8.8:
            acceleration = 0.0
        elif 8.8 <= t < 9.4:
            acceleration = 0.30
        else:
            acceleration = 0.0
        dt = render_t[i] - render_t[i - 1]
        velocity[i] = velocity[i - 1] + acceleration * dt
        if (4.7 <= t < 6.2) or t >= 9.4:
            velocity[i] *= math.exp(-18.0 * dt)
        position[i] = position[i - 1] + velocity[i] * dt

    capture_t = np.arange(0.0, 12.0, 0.10)
    true_capture = np.interp(capture_t, render_t, position)
    measurements = true_capture + rng.normal(0.0, PROFILE["position_measurement_std_m"], len(capture_t))
    arrival_t = capture_t + 0.17 + rng.normal(0.0, 0.012, len(capture_t))

    observations = [
        Observation(float(a * 1000.0), float(c * 1000.0), np.array([m, 0.0, 0.0]))
        for a, c, m in zip(arrival_t, capture_t, measurements)
    ]
    rows = [
        RenderRow(float(t * 1000.0), np.zeros(3), np.array([p, 0.0, 0.0]))
        for t, p in zip(render_t, position)
    ]

    legacy = replay_position(observations, rows, "legacy", "direct")["output"][:, 0]
    corrected_direct = replay_position(observations, rows, "corrected", "direct")["output"][:, 0]
    corrected_continuous = replay_position(
        observations,
        rows,
        "corrected",
        "continuous",
        PROFILE["max_prediction_seconds"],
        PROFILE["correction_half_life_seconds"],
    )["output"][:, 0]

    fig = plt.figure(figsize=(9.5, 5.0))
    ax = fig.add_subplot(111)
    ax.plot(render_t, position * 1000.0, label="Truth")
    ax.plot(render_t, legacy * 1000.0, label="Legacy direct")
    ax.plot(render_t, corrected_direct * 1000.0, label="Corrected direct")
    ax.plot(render_t, corrected_continuous * 1000.0, label="Corrected continuous")
    ax.scatter(arrival_t, measurements * 1000.0, marker="x", s=18, label="Measurements at arrival")
    ax.set_xlim(0.5, 10.5)
    ax.set_xlabel("Wall-clock time (s)")
    ax.set_ylabel("Position (mm)")
    ax.set_title("Synthetic causal test: 10 Hz measurements, 170 ms arrival delay, 90 Hz rendering")
    ax.grid(True, alpha=0.25)
    ax.legend(ncol=2)
    fig.tight_layout()
    fig.savefig(FIGURES / "05_synthetic_online_start_stop.png", dpi=220)
    fig.savefig(FIGURES / "05_synthetic_online_start_stop.pdf")
    plt.close(fig)

    valid = np.isfinite(legacy)
    return {
        "legacy_current_time_rmse_mm": float(np.sqrt(np.mean((legacy[valid] - position[valid]) ** 2)) * 1000.0),
        "corrected_direct_current_time_rmse_mm": float(np.sqrt(np.mean((corrected_direct[valid] - position[valid]) ** 2)) * 1000.0),
        "corrected_continuous_current_time_rmse_mm": float(np.sqrt(np.mean((corrected_continuous[valid] - position[valid]) ** 2)) * 1000.0),
    }


def wrap_angle(angle):
    return (angle + np.pi) % (2.0 * np.pi) - np.pi


def create_rotation_wrap_figure():
    rng = np.random.default_rng(17)
    capture_t = np.arange(0.0, 12.0, 0.10)
    truth_capture = np.deg2rad(40.0) * capture_t
    measured_wrapped = wrap_angle(truth_capture + rng.normal(0.0, np.deg2rad(2.0), len(capture_t)))

    # Legacy fixed chart relative to the first orientation.
    legacy = CorrectedCvKalman1D(0.30, np.deg2rad(2.0) ** 2, 0.0, 1.0)
    legacy.reset(measured_wrapped[0])
    legacy_estimate = [legacy.x[0]]
    for i in range(1, len(capture_t)):
        legacy.predict(capture_t[i] - capture_t[i - 1])
        legacy.correct(measured_wrapped[i])
        legacy_estimate.append(legacy.x[0])

    # Rebased tangent chart: estimate local increment, inject into reference,
    # reset local position to zero while preserving angular velocity.
    local = CorrectedCvKalman1D(0.30, np.deg2rad(2.0) ** 2, 4.0, 1.0)
    reference = measured_wrapped[0]
    local.reset(0.0)
    rebased = [reference]
    for i in range(1, len(capture_t)):
        local.predict(capture_t[i] - capture_t[i - 1])
        measured_local = wrap_angle(measured_wrapped[i] - reference)
        local.correct(measured_local)
        reference = reference + local.x[0]
        local.x[0] = 0.0
        rebased.append(reference)

    legacy_unwrapped = np.unwrap(np.asarray(legacy_estimate))
    rebased_unwrapped = np.asarray(rebased)

    fig = plt.figure(figsize=(8.8, 5.0))
    ax = fig.add_subplot(111)
    ax.plot(capture_t, np.rad2deg(truth_capture), label="Truth")
    ax.plot(capture_t, np.rad2deg(legacy_unwrapped), label="Fixed tangent reference")
    ax.plot(capture_t, np.rad2deg(rebased_unwrapped), label="Rebased tangent reference")
    ax.scatter(capture_t, np.rad2deg(np.unwrap(measured_wrapped)), marker="x", s=16, label="Noisy measurements")
    ax.set_xlabel("Capture time (s)")
    ax.set_ylabel("Unwrapped yaw (deg)")
    ax.set_title("Synthetic rotation test: fixed log-map chart fails at large rotation")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIGURES / "06_rotation_rebase_test.png", dpi=220)
    fig.savefig(FIGURES / "06_rotation_rebase_test.pdf")
    plt.close(fig)

    return {
        "fixed_reference_rmse_deg": float(np.sqrt(np.mean((legacy_unwrapped - truth_capture) ** 2)) * 180.0 / np.pi),
        "rebased_reference_rmse_deg": float(np.sqrt(np.mean((rebased_unwrapped - truth_capture) ** 2)) * 180.0 / np.pi),
    }


def covariance_unit_test():
    rng = np.random.default_rng(3)
    f = corrected_factory()
    f.reset(0.0)
    minimum_eigenvalue = np.inf
    for _ in range(10000):
        dt = float(rng.uniform(0.003, 0.25))
        f.predict(dt)
        f.correct(float(rng.normal(0.0, 0.02)))
        minimum_eigenvalue = min(minimum_eigenvalue, float(np.linalg.eigvalsh(f.p).min()))
    return minimum_eigenvalue


def first_sustained_crossing(time_ms, displacement, after_ms, end_ms, threshold_m=0.005, sustain_ms=100.0):
    for index in np.where((time_ms >= after_ms) & (time_ms < end_ms) & np.isfinite(displacement))[0]:
        if displacement[index] <= threshold_m:
            continue
        window = (time_ms >= time_ms[index]) & (time_ms <= time_ms[index] + sustain_ms) & (time_ms < end_ms)
        if window.sum() >= 2 and np.all(displacement[window] > threshold_m):
            return float(time_ms[index])
    return np.nan


def add_start_response_metrics(summary_by_method, output_by_method, task2):
    observations, rows, starts, ends = task2
    del observations
    time_ms = np.asarray([row.time_ms for row in rows])
    reference = np.asarray([row.reference for row in rows])
    episode_records = []
    for method, output in output_by_method.items():
        responses = []
        for episode, (start, end) in enumerate(zip(starts, ends), 1):
            baseline = (time_ms >= start) & (time_ms < start + 250.0)
            reference_baseline = np.nanmedian(reference[baseline], axis=0)
            output_baseline = np.nanmedian(output[baseline], axis=0)
            reference_crossing = first_sustained_crossing(
                time_ms,
                np.linalg.norm(reference - reference_baseline, axis=1),
                start + 250.0,
                end,
            )
            output_crossing = first_sustained_crossing(
                time_ms,
                np.linalg.norm(output - output_baseline, axis=1),
                start + 250.0,
                end,
            )
            response = output_crossing - reference_crossing
            responses.append(response)
            episode_records.append(
                {
                    "scenario": "start_stop_6dof",
                    "episode": episode,
                    "method": method,
                    "start_response_ms": float(response),
                }
            )
        summary_by_method[method]["start_response_ms"] = float(np.nanmedian(responses))
    return episode_records


def add_occlusion_metrics(summary_by_method, output_by_method, task5):
    observations, rows, starts, ends = task5
    del observations
    time_ms = np.asarray([row.time_ms for row in rows])
    reference = np.asarray([row.reference for row in rows])
    episode_records = []
    for method, output in output_by_method.items():
        p95_values = []
        failures = 0
        for episode, (start, end) in enumerate(zip(starts, ends), 1):
            select = (
                (time_ms >= start)
                & (time_ms < end)
                & np.all(np.isfinite(output), axis=1)
                & np.all(np.isfinite(reference), axis=1)
            )
            error_mm = np.linalg.norm(output[select] - reference[select], axis=1) * 1000.0
            p95 = float(np.percentile(error_mm, 95))
            maximum = float(np.max(error_mm))
            failure = int(p95 > 40.0)
            failures += failure
            p95_values.append(p95)
            episode_records.append(
                {
                    "scenario": "occlusion_recovery",
                    "episode": episode,
                    "method": method,
                    "occlusion_p95_mm": p95,
                    "occlusion_max_mm": maximum,
                    "failure_gt40": failure,
                }
            )
        summary_by_method[method]["occlusion_p95_mm"] = float(np.median(p95_values))
        summary_by_method[method]["occlusion_failures_gt40"] = int(failures)
    return episode_records


def q_normalize(q):
    q = np.asarray(q, dtype=float)
    return q / max(float(np.linalg.norm(q)), 1e-15)


def q_multiply(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array(
        [
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz,
        ],
        dtype=float,
    )


def q_inverse(q):
    q = q_normalize(q)
    return np.array([-q[0], -q[1], -q[2], q[3]], dtype=float)


def q_exp(rotation_vector):
    vector = np.asarray(rotation_vector, dtype=float)
    angle = float(np.linalg.norm(vector))
    if angle < 1e-12:
        return q_normalize(np.r_[0.5 * vector, 1.0])
    return np.r_[vector / angle * math.sin(0.5 * angle), math.cos(0.5 * angle)]


def q_relative_log(a, b):
    relative = q_normalize(q_multiply(q_inverse(a), b))
    if relative[3] < 0.0:
        relative = -relative
    sine = float(np.linalg.norm(relative[:3]))
    if sine < 1e-12:
        return np.zeros(3)
    angle = 2.0 * math.atan2(sine, max(float(relative[3]), -1.0))
    return relative[:3] / sine * angle


def q_rotate(q, vector):
    pure = np.r_[np.asarray(vector, dtype=float), 0.0]
    return q_multiply(q_multiply(q, pure), q_inverse(q))[:3]


def q_slerp(a, b, u):
    a = q_normalize(a)
    b = q_normalize(b)
    dot = float(np.dot(a, b))
    if dot < 0.0:
        b = -b
        dot = -dot
    dot = float(np.clip(dot, -1.0, 1.0))
    if dot > 0.9995:
        return q_normalize((1.0 - u) * a + u * b)
    theta = math.acos(dot)
    return q_normalize(math.sin((1.0 - u) * theta) / math.sin(theta) * a + math.sin(u * theta) / math.sin(theta) * b)


def q_slerp_series(query_times, sample_times, quaternions):
    output = []
    for query in query_times:
        index = int(np.searchsorted(sample_times, query))
        if index <= 0:
            output.append(quaternions[0])
        elif index >= len(sample_times):
            output.append(quaternions[-1])
        else:
            u = (query - sample_times[index - 1]) / (sample_times[index] - sample_times[index - 1])
            output.append(q_slerp(quaternions[index - 1], quaternions[index], u))
    return np.asarray(output)


def q_angle_deg(a, b):
    dot = np.abs(np.sum(a * b, axis=1))
    dot = np.clip(dot, -1.0, 1.0)
    return np.rad2deg(2.0 * np.arccos(dot))


def load_rotation_cache(path: Path):
    z = np.load(path)
    return z["obs"].astype(float), z["rows"].astype(float), z["starts"].astype(float), z["ends"].astype(float)


def replay_rotation(observations, rows, model_kind, strategy, max_prediction_seconds=None, correction_half_life_seconds=None):
    if model_kind == "legacy":
        filters = [LegacyCvKalman1D() for _ in range(3)]
    elif model_kind == "corrected":
        filters = [
            CorrectedCvKalman1D(
                qa=0.30,
                r=np.deg2rad(2.0) ** 2,
                gate_sigma=4.0,
                velocity_variance=1.0,
            )
            for _ in range(3)
        ]
    else:
        raise ValueError(model_kind)

    observation_index = 0
    last_measurement_ms = None
    rotation_reference = None
    output = []
    residual = np.zeros(3)
    has_rendered = False
    last_rendered = np.array([0.0, 0.0, 0.0, 1.0])
    last_render_ms = None

    def current_rotation():
        return q_normalize(q_multiply(rotation_reference, q_exp([f.x[0] for f in filters])))

    def predict_at(time_ms):
        ahead = (time_ms - last_measurement_ms) / 1000.0
        if max_prediction_seconds is not None:
            ahead = min(ahead, max_prediction_seconds)
        vector = np.array([f.x[0] + f.x[1] * ahead for f in filters])
        return q_normalize(q_multiply(rotation_reference, q_exp(vector)))

    for row in rows:
        render_ms = row[0]
        while observation_index < len(observations) and observations[observation_index, 0] <= render_ms + 1e-9:
            observation = observations[observation_index]
            measurement_ms = observation[1]
            measured = q_normalize(observation[2:6])
            if last_measurement_ms is None:
                rotation_reference = measured.copy()
                for f in filters:
                    f.reset(0.0)
                last_measurement_ms = measurement_ms
            elif measurement_ms > last_measurement_ms + 1e-6:
                dt = (measurement_ms - last_measurement_ms) / 1000.0
                for f in filters:
                    f.predict(dt)
                predicted = current_rotation()
                if np.dot(predicted, measured) < 0.0:
                    measured = -measured
                measured_local = q_relative_log(rotation_reference, measured)
                for axis, f in enumerate(filters):
                    f.correct(float(measured_local[axis]))

                if model_kind == "corrected":
                    injected = np.array([f.x[0] for f in filters])
                    delta = q_exp(injected)
                    rotation_reference = q_normalize(q_multiply(rotation_reference, delta))
                    angular_velocity = np.array([f.x[1] for f in filters])
                    rebased_velocity = q_rotate(q_inverse(delta), angular_velocity)
                    for axis, f in enumerate(filters):
                        f.x[0] = 0.0
                        f.x[1] = rebased_velocity[axis]

                last_measurement_ms = measurement_ms
                if strategy == "continuous" and has_rendered:
                    residual = q_relative_log(predict_at(last_render_ms), last_rendered)
            observation_index += 1

        if last_measurement_ms is None:
            output.append([np.nan] * 4)
            continue

        base = predict_at(render_ms)
        rendered = base if strategy == "direct" else q_normalize(q_multiply(base, q_exp(residual)))
        output.append(rendered)

        if strategy == "continuous" and has_rendered:
            dt = max((render_ms - last_render_ms) / 1000.0, 0.0)
            residual *= math.exp(-math.log(2.0) * dt / max(correction_half_life_seconds, 1e-6))
        has_rendered = True
        last_rendered = rendered.copy()
        last_render_ms = render_ms

    return np.asarray(output)


def rotation_episode_metrics(display, rows, starts, ends):
    time_ms = rows[:, 0]
    reference = rows[:, 5:9]
    records = []
    for episode, (start, end) in enumerate(zip(starts, ends), 1):
        select = (
            (time_ms >= start)
            & (time_ms < end)
            & np.all(np.isfinite(display), axis=1)
            & np.all(np.isfinite(reference), axis=1)
        )
        tt = time_ms[select]
        dd = display[select]
        rr = reference[select]
        best = (np.inf, np.nan)
        for lag_ms in np.arange(0.0, 500.1, 5.0):
            query = tt - lag_ms
            valid = (query >= start) & (query <= end)
            if valid.sum() < 10:
                continue
            interpolated = q_slerp_series(query[valid], tt, rr)
            rmse = float(np.sqrt(np.mean(q_angle_deg(dd[valid], interpolated) ** 2)))
            if rmse < best[0]:
                best = (rmse, lag_ms)
        records.append((episode, float(best[1]), float(best[0])))
    return records


def add_rotation_metrics(summary_by_method, output_by_method, rotation_cache):
    observations, rows, starts, ends = rotation_cache
    del observations
    episode_records = []
    for method, output in output_by_method.items():
        records = rotation_episode_metrics(output, rows, starts, ends)
        summary_by_method[method]["rotation_lag_ms"] = float(np.median([r[1] for r in records]))
        summary_by_method[method]["rotation_residual_deg"] = float(np.median([r[2] for r in records]))
        for episode, lag, residual in records:
            episode_records.append(
                {
                    "scenario": "continuous_rotation",
                    "episode": episode,
                    "method": method,
                    "rotation_lag_ms": lag,
                    "rotation_residual_deg": residual,
                }
            )
    return episode_records


def create_rotation_tradeoff_figure(summaries):
    fig = plt.figure(figsize=(7.8, 5.4))
    ax = fig.add_subplot(111)
    for summary in summaries:
        ax.scatter(summary["rotation_lag_ms"], summary["rotation_residual_deg"], s=70)
        ax.annotate(
            summary["method"],
            (summary["rotation_lag_ms"], summary["rotation_residual_deg"]),
            xytext=(5, 5),
            textcoords="offset points",
        )
    ax.set_xlabel("Effective rotation lag (ms; lower is better)")
    ax.set_ylabel("Lag-aligned rotation residual (deg; lower is better)")
    ax.set_title("Real log: rotation latency–fidelity trade-off")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIGURES / "07_rotation_lag_residual_tradeoff.png", dpi=220)
    fig.savefig(FIGURES / "07_rotation_lag_residual_tradeoff.pdf")
    plt.close(fig)


def create_occlusion_figure(summaries):
    names = [s["method"] for s in summaries]
    values = [s["occlusion_p95_mm"] for s in summaries]
    fig = plt.figure(figsize=(8.6, 5.0))
    ax = fig.add_subplot(111)
    ax.bar(names, values)
    ax.axhline(40.0, linestyle="--", label="40 mm failure threshold")
    ax.set_ylabel("Median episode occlusion P95 (mm)")
    ax.set_title("Real log: bounded prediction prevents occlusion runaway")
    ax.tick_params(axis="x", rotation=18)
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIGURES / "08_occlusion_p95.png", dpi=220)
    fig.savefig(FIGURES / "08_occlusion_p95.pdf")
    plt.close(fig)


def create_start_response_figure(summaries):
    names = [s["method"] for s in summaries]
    values = [s["start_response_ms"] for s in summaries]
    fig = plt.figure(figsize=(8.6, 5.0))
    ax = fig.add_subplot(111)
    ax.bar(names, values)
    ax.set_ylabel("Median start response (ms)")
    ax.set_title("Real log: corrected continuous prediction retains lower onset delay than buffering")
    ax.tick_params(axis="x", rotation=18)
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIGURES / "09_start_response.png", dpi=220)
    fig.savefig(FIGURES / "09_start_response.pdf")
    plt.close(fig)


def main():
    required = [
        TASK1_CACHE,
        cache_path("kf_task2_cache.npz"),
        TASK3_CACHE,
        cache_path("kf_task4_rot_cache.npz"),
        cache_path("kf_task5_cache.npz"),
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing cache files: {missing}")

    task1 = load_cache(TASK1_CACHE)
    task2 = load_cache(cache_path("kf_task2_cache.npz"))
    task3 = load_cache(TASK3_CACHE)
    task5 = load_cache(cache_path("kf_task5_cache.npz"))
    rotation_cache = load_rotation_cache(cache_path("kf_task4_rot_cache.npz"))

    position_tasks = {1: task1, 2: task2, 3: task3, 5: task5}
    replays = {}
    for task_number, task in position_tasks.items():
        observations, rows, _, _ = task
        replays[("Legacy direct", task_number)] = replay_position(observations, rows, "legacy", "direct")["output"]
        replays[("Corrected direct", task_number)] = replay_position(observations, rows, "corrected", "direct")["output"]
        replays[("Corrected continuous", task_number)] = replay_position(
            observations,
            rows,
            "corrected",
            "continuous",
            PROFILE["max_prediction_seconds"],
            PROFILE["correction_half_life_seconds"],
        )["output"]
        replays[("Buffered-Hermite", task_number)] = np.asarray([row.logged for row in rows])

    summaries = [
        summarize("Legacy direct", replays[("Legacy direct", 1)], replays[("Legacy direct", 3)], task1, task3),
        summarize("Corrected direct", replays[("Corrected direct", 1)], replays[("Corrected direct", 3)], task1, task3),
        summarize("Corrected continuous", replays[("Corrected continuous", 1)], replays[("Corrected continuous", 3)], task1, task3),
        summarize("Buffered-Hermite", replays[("Buffered-Hermite", 1)], replays[("Buffered-Hermite", 3)], task1, task3),
    ]
    summary_by_method = {summary["method"]: summary for summary in summaries}

    output2 = {method: replays[(method, 2)] for method in summary_by_method}
    output5 = {method: replays[(method, 5)] for method in summary_by_method}
    extra_episode_records = []
    extra_episode_records.extend(add_start_response_metrics(summary_by_method, output2, task2))
    extra_episode_records.extend(add_occlusion_metrics(summary_by_method, output5, task5))

    observations4, rows4, starts4, ends4 = rotation_cache
    rotation_outputs = {
        "Legacy direct": replay_rotation(observations4, rows4, "legacy", "direct"),
        "Corrected direct": replay_rotation(observations4, rows4, "corrected", "direct"),
        "Corrected continuous": replay_rotation(
            observations4,
            rows4,
            "corrected",
            "continuous",
            PROFILE["max_prediction_seconds"],
            PROFILE["correction_half_life_seconds"],
        ),
        "Buffered-Hermite": rows4[:, 1:5],
    }
    extra_episode_records.extend(add_rotation_metrics(summary_by_method, rotation_outputs, rotation_cache))

    validation = {}
    if TRACE_FILE.exists():
        trace = np.load(TRACE_FILE)
        diff = np.linalg.norm(replays[("Legacy direct", 3)] - trace["pred"], axis=1) * 1000.0
        validation = {
            "legacy_mirror_median_abs_difference_mm": float(np.nanmedian(diff)),
            "legacy_mirror_p95_abs_difference_mm": float(np.nanpercentile(diff, 95)),
            "legacy_mirror_max_abs_difference_mm": float(np.nanmax(diff)),
        }

    serializable_summaries = []
    episode_records = list(extra_episode_records)
    for summary in summaries:
        serializable_summaries.append({k: v for k, v in summary.items() if k not in ("episode_records", "correction_steps")})
        episode_records.extend(summary["episode_records"])

    summary_fields = list(serializable_summaries[0].keys())
    with (RESULTS / "summary_metrics.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_fields)
        writer.writeheader()
        writer.writerows(serializable_summaries)

    all_episode_fields = sorted({key for row in episode_records for key in row})
    with (RESULTS / "episode_metrics.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=all_episode_fields)
        writer.writeheader()
        writer.writerows(episode_records)

    obs3, rows3, _, _ = task3
    time3 = np.asarray([row.time_ms for row in rows3])
    reference3 = np.asarray([row.reference for row in rows3])
    outputs3 = {method: replays[(method, 3)] for method in summary_by_method}
    create_real_trace_figure(time3, reference3, obs3, outputs3)
    create_ecdf_figure(summaries)
    create_tradeoff_figure(summaries)
    create_static_increment_figure(summaries)
    create_rotation_tradeoff_figure(summaries)
    create_occlusion_figure(summaries)
    create_start_response_figure(summaries)

    synthetic = create_synthetic_online_figure()
    rotation_synthetic = create_rotation_wrap_figure()
    min_eigenvalue = covariance_unit_test()

    test_results = {
        "profile": PROFILE,
        "validation": validation,
        "covariance_minimum_eigenvalue": min_eigenvalue,
        "synthetic": synthetic,
        "rotation_synthetic": rotation_synthetic,
        "summary": serializable_summaries,
        "notes": [
            "All real-log methods use the same capture-aligned accepted observations and render timeline.",
            "Buffered-Hermite is the logged pre-StaticLock output for the same variant.",
            "The corrected profile was selected exploratorily on the supplied logs and requires a fresh validation capture before paper claims are updated.",
            "The C# files require a Unity project compile/runtime test because the execution environment does not contain UnityEngine assemblies.",
        ],
    }
    (RESULTS / "test_results.json").write_text(json.dumps(test_results, indent=2), encoding="utf-8")
    print(json.dumps(test_results, indent=2))


if __name__ == "__main__":
    main()
