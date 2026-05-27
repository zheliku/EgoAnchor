"""异步 latest-only 分割 worker。"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from egoanchor.algorithms import SegmenterResult
from egoanchor.perception import DecodedQuestStereoFrame
from egoanchor.runtime import LatestValueStore

LOGGER = logging.getLogger(__name__)
"""异步分割 worker 日志记录器。"""


class SegmenterBackend(Protocol):
    """QuestPosePipeline 依赖的最小分割后端接口。"""

    def infer(self, image_bgr: np.ndarray, prompt: str | list[str] | None = None) -> SegmenterResult:
        """执行单帧分割并返回统一 SegmenterResult。"""


@dataclass(slots=True)
class AsyncSegmenterJob:
    """提交给后台分割线程的单帧数据包。"""

    decoded: DecodedQuestStereoFrame
    """解码后的 Quest 双目帧元数据和原图。"""

    session_id: str
    """Unity 发布会话 ID，用于丢弃旧 session 结果。"""

    left_bgr: np.ndarray
    """处理分辨率下的左目 BGR 图；SAM3 在该图上生成 mask。"""

    right_bgr: np.ndarray
    """处理分辨率下的右目 BGR 图；后续 FFS 与 register 使用同一帧。"""

    generation: int
    """pipeline reset/calibration 代数；结果回来时必须一致。"""


@dataclass(slots=True)
class AsyncSegmenterOutput:
    """后台分割线程完成的一次结果。"""

    job: AsyncSegmenterJob
    """产生该结果的输入帧包。"""

    result: SegmenterResult | None
    """分割结果；异常时为 None。"""

    elapsed_ms: float
    """后台线程测得的总耗时，单位毫秒。"""

    error: str = ""
    """异常文本；空字符串表示成功。"""


@dataclass(frozen=True, slots=True)
class AsyncSegmenterSnapshot:
    """后台分割 worker 的轻量状态快照。"""

    busy: bool
    """后台线程是否正在推理或已有待处理帧。"""

    submitted: int
    """累计接受的帧数。"""

    completed: int
    """累计完成的推理次数。"""

    dropped: int
    """因为 worker 忙或结果未消费而丢弃的提交次数。"""

    error: str
    """最近一次异常文本。"""


class AsyncSegmenterWorker:
    """单线程 latest-only 分割 worker。

    worker 只运行 SAM3/分割模型，不运行 FFS、FoundationPose 或 Cutie。完成后主
    pipeline 线程会用同一帧的 left/right RGB 与 mask 继续 register，避免 RGB/mask
    错帧。
    """

    def __init__(self, segmenter: SegmenterBackend) -> None:
        """保存分割器并初始化线程同步状态。"""

        self.segmenter = segmenter
        """实际分割后端。"""

        self._condition = threading.Condition()
        """保护 pending/completed 状态的条件变量。"""

        self._pending: AsyncSegmenterJob | None = None
        """等待后台处理的最新帧。"""

        self._completed_output: LatestValueStore[AsyncSegmenterOutput] = LatestValueStore()
        """等待主线程消费的最新完成结果。"""

        self._busy = False
        """后台线程是否正在推理。"""

        self._stopping = False
        """后台线程停止标记。"""

        self._submitted = 0
        """累计接受帧数。"""

        self._completed = 0
        """累计完成推理次数。"""

        self._dropped = 0
        """丢弃提交次数。"""

        self._error = ""
        """最近一次异常文本。"""

        self._thread = threading.Thread(target=self._run, name="EgoAnchorAsyncSegmenter", daemon=True)
        """后台分割线程。"""

    def start(self) -> None:
        """启动后台分割线程。"""

        self._thread.start()

    def stop(self) -> None:
        """请求后台线程退出并等待短暂收尾。"""

        with self._condition:
            self._stopping = True
            self._condition.notify_all()
        self._thread.join(timeout=2.0)

    def clear(self) -> None:
        """丢弃未开始处理的帧和未消费结果；正在推理的帧靠 generation 过滤。"""

        with self._condition:
            self._pending = None
            self._completed_output.clear()
            self._error = ""

    def submit(self, job: AsyncSegmenterJob) -> bool:
        """提交一帧给后台；忙或旧结果未消费时返回 False。"""

        with self._condition:
            if self._busy or self._pending is not None or self._completed_output.peek() is not None:
                self._dropped += 1
                return False
            self._pending = AsyncSegmenterJob(
                decoded=job.decoded,
                session_id=job.session_id,
                left_bgr=job.left_bgr.copy(),
                right_bgr=job.right_bgr.copy(),
                generation=int(job.generation),
            )
            self._submitted += 1
            self._condition.notify()
            return True

    def take_completed(self) -> AsyncSegmenterOutput | None:
        """取走最新完成结果；没有结果时返回 None。"""

        with self._condition:
            return self._completed_output.take()

    def snapshot(self) -> AsyncSegmenterSnapshot:
        """返回 worker 当前状态快照。"""

        with self._condition:
            return AsyncSegmenterSnapshot(
                busy=self._busy or self._pending is not None,
                submitted=self._submitted,
                completed=self._completed,
                dropped=self._dropped,
                error=self._error,
            )

    def _run(self) -> None:
        """后台线程主循环。"""

        while True:
            with self._condition:
                while self._pending is None and not self._stopping:
                    self._condition.wait()
                if self._stopping:
                    return
                job = self._pending
                self._pending = None
                self._busy = True

            t0 = time.perf_counter()
            try:
                result = self.segmenter.infer(job.left_bgr)
                error = ""
            except Exception as exc:
                result = None
                error = f"{type(exc).__name__}: {exc}"
                LOGGER.warning("异步分割 worker 推理失败: %s", error, exc_info=True)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            with self._condition:
                self._busy = False
                self._completed_output.put(AsyncSegmenterOutput(job=job, result=result, elapsed_ms=elapsed_ms, error=error))
                self._completed += 1
                if error:
                    self._error = error


__all__ = [
    "AsyncSegmenterJob",
    "AsyncSegmenterOutput",
    "AsyncSegmenterSnapshot",
    "AsyncSegmenterWorker",
    "SegmenterBackend",
]
