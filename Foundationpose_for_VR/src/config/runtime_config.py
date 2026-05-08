"""Single-file TOML runtime configuration loader.

The runtime config intentionally stays lightweight: TOML is validated against a
small unknown-key schema, converted to ``SimpleNamespace`` for dot access, and
known path fields are resolved relative to ``Foundationpose_for_VR``.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

SRC_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = SRC_DIR.parent
DEFAULT_CONFIG_PATH = PROJECT_DIR / "config" / "runtime.toml"

CONFIG_SCHEMA: dict[str, Any] = {
    "server": {
        "run_stage",
        "send_when_no_pose",
        "reset_interval_sec",
    },
    "network": {
        "receiver": {"listen_host", "listen_port", "hwm", "timeout_ms"},
        "sender": {"host", "port", "topic", "hwm"},
    },
    "pipeline": {
        "calibration": {
            "camera_source",
            "preload_camera_cache",
            "network_calib_update",
            "camera_cache_dir",
            "assume_center_crop",
            "process_width",
            "process_height",
        },
        "depth": {"min_depth", "max_depth"},
    },
    "module": {
        "segmenter": {"type", "prompt", "max_det", "mask_threshold"},
        "sam3": {
            "checkpoint_path",
            "confidence_threshold",
            "resolution",
            "device",
            "async_enabled",
            "interval_sec",
            "refresh_when_tracking",
            "max_result_age_ms",
            "allow_stale_register",
        },
        "yoloe": {"model_path", "mobileclip2_path", "conf", "imgsz", "use_half", "device"},
        "ffs": {
            "model_path",
            "device",
            "scale",
            "valid_iters",
            "max_disp",
            "optimize_build_volume",
            "seed",
            "cudnn_benchmark",
            "use_trt",
            "trt_precision",
            "trt_strict",
            "trt_tag",
            "trt_platform_tag",
            "trt_feature_engine_path",
            "trt_post_engine_path",
        },
        "foundationpose": {
            "mesh_path",
            "est_refine_iter",
            "track_refine_iter",
            "symmetry_mode",
            "register_min_depth_valid_in_mask",
            "re_register_on_track_lost",
            "pose_jump_translation_m",
            "pose_jump_rotation_deg",
            "debug",
            "debug_dir",
        },
        "cutie": {"enabled", "seg_threshold", "erosion_size", "adjust_pose"},
    },
    "debug": {
        "local_debug",
        "enable_keyboard_control",
        "pipeline_stats_interval",
        "publish_log_interval",
        "latency_ema_alpha",
        "wait_log_interval_sec",
        "show_mask_snapshot",
        "mask_snapshot_window",
    },
}

REQUIRED_SECTIONS = set(CONFIG_SCHEMA.keys())

PATH_FIELDS: set[tuple[str, ...]] = {
    ("pipeline", "calibration", "camera_cache_dir"),
    ("module", "sam3", "checkpoint_path"),
    ("module", "yoloe", "model_path"),
    ("module", "yoloe", "mobileclip2_path"),
    ("module", "ffs", "model_path"),
    ("module", "ffs", "trt_feature_engine_path"),
    ("module", "ffs", "trt_post_engine_path"),
    ("module", "foundationpose", "mesh_path"),
    ("module", "foundationpose", "debug_dir"),
}


def to_namespace(value: Any) -> Any:
    """Recursively convert dictionaries to SimpleNamespace."""
    if isinstance(value, dict):
        return SimpleNamespace(**{k: to_namespace(v) for k, v in value.items()})
    if isinstance(value, list):
        return [to_namespace(item) for item in value]
    return value


def namespace_to_dict(value: Any) -> Any:
    """Recursively convert SimpleNamespace/Path values to JSON-friendly data."""
    if isinstance(value, SimpleNamespace):
        return {k: namespace_to_dict(v) for k, v in vars(value).items()}
    if isinstance(value, dict):
        return {k: namespace_to_dict(v) for k, v in value.items()}
    if isinstance(value, list):
        return [namespace_to_dict(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def validate_unknown_keys(data: dict[str, Any]) -> None:
    """Raise ValueError when the TOML contains unknown sections or fields."""
    _validate_table(data, CONFIG_SCHEMA, path="")


def _validate_table(data: dict[str, Any], schema: dict[str, Any], path: str) -> None:
    for section in sorted(set(schema.keys()) - set(data.keys())):
        section_path = f"{path}.{section}" if path else section
        raise ValueError(f"Missing config section: {section_path}")

    for key, value in data.items():
        key_path = f"{path}.{key}" if path else key
        if key not in schema:
            if path:
                raise ValueError(f"Unknown config key: {key_path}")
            raise ValueError(f"Unknown config section: {key_path}")

        allowed = schema[key]
        if isinstance(allowed, dict):
            if not isinstance(value, dict):
                raise ValueError(f"Config section must be a table: {key_path}")
            _validate_table(value, allowed, key_path)
            continue

        if not isinstance(value, dict):
            raise ValueError(f"Config section must be a table: {key_path}")
        for field in value.keys():
            if field not in allowed:
                raise ValueError(f"Unknown config key: {key_path}.{field}")


def _resolve_project_path(value: str | Path, project_dir: Path) -> Path | str:
    if value == "":
        return ""
    path = Path(value)
    if path.is_absolute():
        return path
    return (project_dir / path).resolve()


def resolve_paths(cfg: SimpleNamespace, project_dir: Path = PROJECT_DIR) -> None:
    """Resolve known path fields in-place relative to the project directory."""
    for field_path in PATH_FIELDS:
        parent = cfg
        for part in field_path[:-1]:
            parent = getattr(parent, part)
        key = field_path[-1]
        value = getattr(parent, key)
        setattr(parent, key, _resolve_project_path(value, project_dir))


def load_runtime_config(config_path: str | Path | None = None) -> SimpleNamespace:
    """Load, validate, and resolve the runtime TOML config."""
    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    if not path.is_absolute():
        path = (PROJECT_DIR / path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Runtime config not found: {path}")

    with path.open("rb") as f:
        data = tomllib.load(f)

    validate_unknown_keys(data)
    cfg = to_namespace(data)
    cfg.config_path = path
    cfg.project_dir = PROJECT_DIR
    resolve_paths(cfg, PROJECT_DIR)
    return cfg


def print_effective_config(cfg: SimpleNamespace) -> None:
    """Print the effective config after path resolution."""
    print(json.dumps(namespace_to_dict(cfg), ensure_ascii=False, indent=2, sort_keys=True))
