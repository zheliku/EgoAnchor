"""Quest pose server entrypoint.

职责边界：
- 本文件只负责参数解析、资源创建、主循环编排和退出清理。
- camera_info 缓存、OpenCV debug、统计和热键处理放在 server 包中。
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Protocol

# 允许直接脚本运行：python src/pose_server.py
if __package__ is None or __package__ == "":
    SRC_DIR = Path(__file__).resolve().parent
    if str(SRC_DIR) not in sys.path:
        sys.path.append(str(SRC_DIR))

from pipeline.quest_pipeline import (  # noqa: E402
    PosePipelineOutput,
    QuestStereoPosePipeline,
    build_arg_parser as build_pipeline_arg_parser,
    build_quest_pipeline,
)
from server import (  # noqa: E402
    PoseServerDebugView,
    PoseServerStats,
    handle_debug_key,
    save_camera_info,
)
from zmq_utils import PayloadSender, PoseEncoder  # noqa: E402


class _KeyboardControllablePipeline(Protocol):
    """本地调试热键需要的最小 pipeline 接口。"""

    stage: int

    def reset_tracking_state(self) -> None: ...

    def set_stage(self, stage: int) -> None: ...


def build_arg_parser() -> argparse.ArgumentParser:
    """在 Quest Pipeline 参数基础上扩展 pose_server 参数。"""
    parser = build_pipeline_arg_parser()

    parser.description = "Quest 位姿服务：接收双目和相机信息，向 Unity 发布 pose。"
    parser.add_argument(
        "--run_stage",
        type=int,
        default=4,
        help="Pipeline 执行阶段（1~4）。默认 4。",
    )
    parser.add_argument(
        "--pose_pub_host",
        type=str,
        default="*",
        help="位姿发布端绑定地址。",
    )
    parser.add_argument(
        "--pose_pub_port",
        type=int,
        default=15556,
        help="位姿发布端口（ZMQ PUB）。",
    )
    parser.add_argument(
        "--pose_topic",
        type=str,
        default="pose",
        help="位姿消息 topic。",
    )
    parser.add_argument(
        "--pose_pub_hwm",
        type=int,
        default=1,
        help="位姿发布端高水位。",
    )
    parser.add_argument(
        "--send_when_no_pose",
        type=int,
        default=1,
        help="无 pose 时是否仍发送状态包（1=发送，0=跳过）。",
    )
    parser.add_argument(
        "--pub_log_interval",
        type=int,
        default=60,
        help="每处理多少帧打印一次发布统计。",
    )
    parser.add_argument(
        "--local_debug",
        type=int,
        default=1,
        help="是否开启本地 OpenCV 调试窗口。",
    )
    parser.add_argument(
        "--latency_ema_alpha",
        type=float,
        default=0.15,
        help="延迟统计 EMA alpha。",
    )
    parser.add_argument(
        "--enable_keyboard_control",
        type=int,
        default=1,
        help="是否启用 OpenCV 窗口热键。",
    )
    parser.add_argument(
        "--reset_interval_sec",
        type=float,
        default=0.0,
        help="自动重置跟踪状态的周期（秒）；<=0 关闭。",
    )

    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_arg_parser().parse_args(argv)


def _clip_alpha(value: float) -> float:
    return min(max(float(value), 0.01), 1.0)


def _maybe_save_camera_info(
    *,
    pipeline: QuestStereoPosePipeline,
    camera_cache_dir: Path,
    last_saved_version: int,
) -> int:
    """收到新的 camera_info 时落盘缓存，并返回最新已保存版本号。"""
    camera_info = pipeline.camera.get_camera_info()
    if camera_info is None:
        return last_saved_version

    info_version = pipeline.camera.get_camera_info_version()
    if info_version != last_saved_version:
        save_camera_info(camera_info, camera_cache_dir)
        return int(info_version)

    return last_saved_version


def _log_waiting_state(pipeline: QuestStereoPosePipeline) -> None:
    """等待首帧时输出低频诊断，区分缺标定还是缺 stereo。"""
    input_state = pipeline.camera.get_input_state()
    recv_stats = pipeline.camera.get_stats()
    logging.info(
        "[pose_server] waiting... calib_ready=%s camera_info=%s stereo=%s recv=%s decoded=%s",
        "YES" if getattr(pipeline, "_calib_initialized", False) else "NO",
        "OK" if input_state.has_camera_info else "None",
        "OK" if input_state.has_stereo else "None",
        recv_stats.get("received", 0),
        recv_stats.get("decoded", 0),
    )


def _auto_reset_if_due(
    *,
    pipeline: _KeyboardControllablePipeline,
    stats: PoseServerStats,
    reset_interval_sec: float,
    last_reset_t: float,
) -> float:
    """按配置周期自动重置跟踪状态，返回最新 reset 时间。"""
    if reset_interval_sec <= 1e-6:
        return last_reset_t

    now_t = time.perf_counter()
    if now_t - last_reset_t < reset_interval_sec:
        return last_reset_t

    pipeline.reset_tracking_state()
    stats.record_reset()
    logging.info("[pose_server] auto reset tracking (interval=%.2fs)", reset_interval_sec)
    return now_t


def _encode_pose_payload(encoder: PoseEncoder, output: PosePipelineOutput) -> bytes | None:
    """把 pipeline 输出封装成 Unity 可消费的 PoseMsg payload。"""
    return encoder.encode(
        timestamp_ms=output.timestamp_ms,
        frame_id=int(output.frame_id or 0),
        stage=output.stage,
        phase=output.phase,
        det_count=output.det_count,
        depth_valid_ratio=output.depth_valid_ratio,
        fps=output.fps,
        timing_ms={
            "yolo": output.timing.yolo_ms,
            "depth": output.timing.depth_ms,
            "cutie": output.timing.cutie_ms,
            "pose": output.timing.pose_ms,
        },
        pose_4x4=output.pose_4x4,
    )


def _record_latency(
    *,
    stats: PoseServerStats,
    output: PosePipelineOutput,
    loop_t0: float,
    after_run_t: float,
    send_ms: float,
) -> None:
    """更新 run/proc/wait/send/end-to-end 延迟统计。"""
    run_ms = (after_run_t - loop_t0) * 1000.0
    proc_ms = (
        float(output.timing.yolo_ms)
        + float(output.timing.depth_ms)
        + float(output.timing.cutie_ms)
        + float(output.timing.pose_ms)
    )
    wait_ms = max(run_ms - proc_ms, 0.0)
    e2e_ms = max(time.perf_counter() * 1000.0 - float(output.timestamp_ms), 0.0)
    stats.record_latency(
        run_ms=run_ms,
        proc_ms=proc_ms,
        wait_ms=wait_ms,
        send_ms=send_ms,
        e2e_ms=e2e_ms,
    )


def _log_publish_stats(stats: PoseServerStats, phase: str) -> None:
    logging.info(
        "[pose_server] frames=%d sent=%d dropped=%d pub_fps=%.1f pose_ratio=%.1f%% drop=%.1f%% phase=%s "
        "lat(ms):quest_rx->unity_tx=%.1f run=%.1f wait=%.1f proc=%.1f send=%.2f reset=%d",
        stats.frame_count,
        stats.sent_count,
        stats.dropped_count,
        stats.pub_fps,
        stats.pose_ratio * 100.0,
        stats.drop_ratio * 100.0,
        phase,
        stats.e2e_ms_ema,
        stats.run_ms_ema,
        stats.wait_ms_ema,
        stats.proc_ms_ema,
        stats.send_ms_ema,
        stats.reset_count,
    )


def run_pose_server(args: argparse.Namespace) -> None:
    """运行端到端位姿服务主循环。"""
    endpoint = f"tcp://{args.pose_pub_host}:{int(args.pose_pub_port)}"
    topic = str(args.pose_topic)
    log_interval = max(int(args.pub_log_interval), 1)
    send_when_no_pose = bool(int(args.send_when_no_pose))
    local_debug = bool(int(args.local_debug))
    enable_keyboard_control = bool(int(args.enable_keyboard_control))
    reset_interval_sec = max(float(args.reset_interval_sec), 0.0)
    camera_cache_dir = Path(args.camera_cache_dir)

    pipeline = build_quest_pipeline(args)
    pipeline.set_stage(int(args.run_stage))

    sender = PayloadSender(
        endpoint=endpoint,
        hwm=max(int(args.pose_pub_hwm), 1),
        bind=True,
    )
    encoder = PoseEncoder()
    stats = PoseServerStats(latency_alpha=_clip_alpha(args.latency_ema_alpha))

    calib_ready_at_start = bool(getattr(pipeline, "_calib_initialized", False))
    waiting_text = (
        "Waiting for Quest stereo..."
        if calib_ready_at_start
        else "Waiting for Quest camera_info & stereo..."
    )
    debug_view = PoseServerDebugView(enabled=local_debug, waiting_text=waiting_text)

    last_saved_camera_info_version = 0
    last_reset_t = time.perf_counter()
    last_wait_log_t = time.perf_counter()

    try:
        pipeline.start()
        logging.info(
            "[pose_server] started recv=tcp://%s:%d pub=%s topic=%s stage=%d camera_source=%s calib_ready=%s preload_cache=%s",
            args.listen_host,
            int(args.listen_port),
            endpoint,
            topic,
            int(args.run_stage),
            args.camera_source,
            "YES" if calib_ready_at_start else "NO",
            int(getattr(args, "preload_camera_cache", 1)),
        )

        while True:
            loop_t0 = time.perf_counter()
            output = pipeline.run(return_debug=local_debug)
            if output is None:
                action = handle_debug_key(
                    debug_view.show_waiting(),
                    pipeline,
                    enable_keyboard_control,
                )
                if action == "quit":
                    break
                if action == "reset":
                    stats.record_reset()
                    last_reset_t = time.perf_counter()

                now_wait = time.perf_counter()
                if now_wait - last_wait_log_t >= 3.0:
                    _log_waiting_state(pipeline)
                    last_wait_log_t = now_wait
                continue

            after_run_t = time.perf_counter()

            last_saved_camera_info_version = _maybe_save_camera_info(
                pipeline=pipeline,
                camera_cache_dir=camera_cache_dir,
                last_saved_version=last_saved_camera_info_version,
            )
            last_reset_t = _auto_reset_if_due(
                pipeline=pipeline,
                stats=stats,
                reset_interval_sec=reset_interval_sec,
                last_reset_t=last_reset_t,
            )

            stats.record_output(has_pose=output.pose_4x4 is not None)
            if output.pose_4x4 is None and not send_when_no_pose:
                continue

            payload = _encode_pose_payload(encoder, output)
            if payload is None:
                stats.record_payload_drop()
                continue

            send_t0 = time.perf_counter()
            sent = sender.send_payload(payload, topic=topic)
            send_ms = (time.perf_counter() - send_t0) * 1000.0
            stats.record_send(sent)
            _record_latency(
                stats=stats,
                output=output,
                loop_t0=loop_t0,
                after_run_t=after_run_t,
                send_ms=send_ms,
            )

            key = debug_view.show_output(output, stats.debug_overlay_lines())
            action = handle_debug_key(key, pipeline, enable_keyboard_control)
            if action == "quit":
                break
            if action == "reset":
                stats.record_reset()
                last_reset_t = time.perf_counter()

            if stats.frame_count % log_interval == 0:
                _log_publish_stats(stats, output.phase)
    except KeyboardInterrupt:
        logging.info("\n[pose_server] interrupted by user")
    finally:
        pipeline.stop()
        sender.close()
        debug_view.close()


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_pose_server(args)


if __name__ == "__main__":
    main()
