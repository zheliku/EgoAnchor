"""v2 perception 层：把 Quest 输入转换为 pose observation。"""

from egoanchor.perception.pose_observation import PoseObservation
from egoanchor.perception.quest_calibration import QuestStereoCalibration
from egoanchor.perception.quest_frame import DecodedQuestStereoFrame, decode_quest_stereo_frame, preprocess_stereo_pair


def __getattr__(name: str):
    """惰性导出 pose pipeline，避免 import perception 包时加载模型相关依赖。"""

    if name in {"FrameDiagnostics", "PipelineStepTiming", "QuestPosePipeline", "QuestPosePipelineOutput", "build_quest_pose_pipeline"}:
        from egoanchor.perception import quest_pose_pipeline

        value = getattr(quest_pose_pipeline, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
	"PoseObservation",
	"QuestStereoCalibration",
	"DecodedQuestStereoFrame",
	"decode_quest_stereo_frame",
	"preprocess_stereo_pair",
	"FrameDiagnostics",
	"PipelineStepTiming",
	"QuestPosePipeline",
	"QuestPosePipelineOutput",
	"build_quest_pose_pipeline",
]
