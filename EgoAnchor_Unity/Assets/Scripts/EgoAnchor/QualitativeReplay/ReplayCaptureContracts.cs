using System;
using UnityEngine;

namespace EgoAnchor.QualitativeReplay
{
    /// <summary>定性 replay 文件格式的固定标识和版本。</summary>
    public static class ReplayCaptureFormat
    {
        /// <summary>与正式 schema-v2 明确区分的格式名。</summary>
        public const string Name = "egoanchor_qualitative_replay";

        /// <summary>当前不兼容格式版本。</summary>
        public const int Version = 1;
    }

    /// <summary>JSON 中使用的 Unity world pose。</summary>
    [Serializable]
    public sealed class ReplayPoseDto
    {
        /// <summary>位置 xyz，单位米。</summary>
        public float[] position = new float[3];

        /// <summary>四元数 xyzw。</summary>
        public float[] rotation_xyzw = new float[4];

        /// <summary>从 Unity Pose 构造可序列化对象。</summary>
        /// <param name="pose">待记录的 pose。</param>
        /// <returns>只包含有限 float 的 JSON DTO。</returns>
        public static ReplayPoseDto FromPose(Pose pose)
        {
            return new ReplayPoseDto
            {
                position = new[] { pose.position.x, pose.position.y, pose.position.z },
                rotation_xyzw = new[] { pose.rotation.x, pose.rotation.y, pose.rotation.z, pose.rotation.w },
            };
        }
    }

    /// <summary>某一方法在指定 image-time 渲染帧上的输出和显示位姿。</summary>
    [Serializable]
    public sealed class ReplayVariantPoseDto
    {
        /// <summary>稳定方法标识。</summary>
        public string variant_id = string.Empty;

        /// <summary>论文叠加颜色，十六进制 RGB。</summary>
        public string color_hex = string.Empty;

        /// <summary>runtime 在该渲染帧是否产生输出 pose。</summary>
        public bool has_output_pose;

        /// <summary>runtime 输出的 Unity world pose。</summary>
        public ReplayPoseDto output_world_pose = new ReplayPoseDto();

        /// <summary>用户在该渲染帧是否实际看到 pose，包括 hold-last。</summary>
        public bool has_display_pose;

        /// <summary>用户实际看到的 Unity world pose。</summary>
        public ReplayPoseDto display_world_pose = new ReplayPoseDto();

        /// <summary>显示来源：transform、hold_last 或 none。</summary>
        public string pose_source = "none";

        /// <summary>当前显示 pose 的候选来源 frame_id；无显示时为 -1。</summary>
        public long source_frame_id = -1;

        /// <summary>
        /// 把最终显示 world pose 置于本样本左目相机后得到的 OpenCV camera-space 4x4，row-major。
        /// 该矩阵包含实际显示补偿，Python 可直接用于模型重投影。
        /// </summary>
        public float[] projection_pose_cv_camera = new float[16];

        /// <summary>runtime 的坐标补偿和时间对齐配置指纹。</summary>
        public string runtime_configuration_fingerprint = string.Empty;
    }

    /// <summary>保存分辨率下的左目相机标定与 image-time world pose。</summary>
    [Serializable]
    public sealed class ReplayCameraDto
    {
        /// <summary>固定为 Left，防止误用 CenterEye/HMD pose。</summary>
        public string reference = "Left";

        /// <summary>图像时间代理对应的左目 Unity world pose。</summary>
        public ReplayPoseDto world_pose = new ReplayPoseDto();

        /// <summary>保存 JPEG 分辨率下的 fx。</summary>
        public double fx;

        /// <summary>保存 JPEG 分辨率下的 fy。</summary>
        public double fy;

        /// <summary>保存 JPEG 分辨率下的 cx。</summary>
        public double cx;

        /// <summary>保存 JPEG 分辨率下的 cy。</summary>
        public double cy;

        /// <summary>标定坐标系宽度，优先取 active array。</summary>
        public int calibration_width;

        /// <summary>标定坐标系高度，优先取 active array。</summary>
        public int calibration_height;

        /// <summary>Passthrough 相机传感器宽度。</summary>
        public int sensor_width;

        /// <summary>Passthrough 相机传感器高度。</summary>
        public int sensor_height;

        /// <summary>active array 左边界。</summary>
        public int active_left;

        /// <summary>active array 上边界。</summary>
        public int active_top;

        /// <summary>active array 右边界。</summary>
        public int active_right;

        /// <summary>active array 下边界。</summary>
        public int active_bottom;

        /// <summary>当前 Passthrough texture 宽度。</summary>
        public int current_width;

        /// <summary>当前 Passthrough texture 高度。</summary>
        public int current_height;

        /// <summary>左目请求宽度。</summary>
        public int requested_width;

        /// <summary>左目请求高度。</summary>
        public int requested_height;

        /// <summary>畸变模型；Quest 当前未提供可直接离线校正的模型时写 unknown。</summary>
        public string distortion_model = "unknown";
    }

    /// <summary>与图像时刻对齐的 Quest 官方右手柄平台参考。</summary>
    [Serializable]
    public sealed class ReplayReferenceDto
    {
        /// <summary>是否已经获得可用参考位姿。</summary>
        public bool valid;

        /// <summary>该帧是否由当前激活且可追踪的 Transform 直接更新。</summary>
        public bool fresh;

        /// <summary>该帧是否保持最后一次可追踪参考位姿。</summary>
        public bool keep_alive;

        /// <summary>距最后一次新鲜参考位姿的毫秒数；无效时为 -1。</summary>
        public double fresh_age_ms = -1.0;

        /// <summary>平台参考 world pose；无效时为 identity。</summary>
        public ReplayPoseDto world_pose = new ReplayPoseDto();

        /// <summary>平台参考在本样本左目相机下的 OpenCV 4x4，row-major。</summary>
        public float[] projection_pose_cv_camera = new float[16];

        /// <summary>平台参考 Transform 的完整场景路径。</summary>
        public string transform_path = string.Empty;

        /// <summary>固定为 RTouch。</summary>
        public string controller = "RTouch";

        /// <summary>transform、held 或 none。</summary>
        public string pose_source = "none";
    }

    /// <summary>一条 JPEG、image-time 左目相机和四路显示状态的原子样本。</summary>
    [Serializable]
    public sealed class ReplaySampleDto
    {
        /// <summary>本 capture 内单调递增的样本标识。</summary>
        public string sample_id = string.Empty;

        /// <summary>背景 JPEG 的 QuestStereoFrame frame_id。</summary>
        public long background_frame_id;

        /// <summary>相对 capture 目录的 JPEG 路径。</summary>
        public string image_path = string.Empty;

        /// <summary>JPEG 字节数。</summary>
        public int image_bytes;

        /// <summary>JPEG 宽度。</summary>
        public int image_width;

        /// <summary>JPEG 高度。</summary>
        public int image_height;

        /// <summary>JPEG 编码质量。</summary>
        public int jpeg_quality;

        /// <summary>图像时间代理的 Unity 单调时钟毫秒。</summary>
        public double image_mono_ms;

        /// <summary>图像时间代理对应的 Unity 帧号。</summary>
        public int image_unity_frame;

        /// <summary>图像代理相对 payload-ready 回退的成功采集样本数。</summary>
        public int image_time_offset_frames;

        /// <summary>JPEG payload-ready 的 Unity 单调时钟毫秒。</summary>
        public double sender_mono_ms;

        /// <summary>JPEG payload-ready 的 Unity 帧号。</summary>
        public int sender_unity_frame;

        /// <summary>ZMQ 发布尝试的 Unity 单调时钟毫秒。</summary>
        public double publish_attempt_mono_ms;

        /// <summary>该 JPEG 是否成功进入 ZMQ 发送队列。</summary>
        public bool publish_succeeded;

        /// <summary>四路 pose 快照对应的 Unity 渲染帧。</summary>
        public int render_tick_id;

        /// <summary>四路 pose 快照的 Unity 单调时钟毫秒。</summary>
        public double snapshot_mono_ms;

        /// <summary>左目标定和 image-time world pose。</summary>
        public ReplayCameraDto camera = new ReplayCameraDto();

        /// <summary>同一 image-time 渲染帧上的 Quest 官方右手柄参考。</summary>
        public ReplayReferenceDto platform_reference = new ReplayReferenceDto();

        /// <summary>固定顺序的四种实验一方法。</summary>
        public ReplayVariantPoseDto[] variants = Array.Empty<ReplayVariantPoseDto>();
    }

    /// <summary>一个定性 replay capture 的审计清单。</summary>
    [Serializable]
    public sealed class ReplayManifestDto
    {
        /// <summary>格式名；不得与正式评估 manifest 混用。</summary>
        public string format = ReplayCaptureFormat.Name;

        /// <summary>格式版本。</summary>
        public int format_version = ReplayCaptureFormat.Version;

        /// <summary>capture 唯一标识。</summary>
        public string capture_id = string.Empty;

        /// <summary>目标对象配置名。</summary>
        public string object_id = string.Empty;

        /// <summary>专用 Unity 场景名。</summary>
        public string scene_name = string.Empty;

        /// <summary>Unity Editor/Player 版本。</summary>
        public string unity_version = string.Empty;

        /// <summary>应用版本。</summary>
        public string application_version = string.Empty;

        /// <summary>固定为 editor_link，明确该 capture 来自 Quest Link 串流。</summary>
        public string run_mode = "editor_link";

        /// <summary>本机 capture 输出根目录。</summary>
        public string output_root = string.Empty;

        /// <summary>Quest 官方右手柄参考 Transform 的完整场景路径。</summary>
        public string platform_reference_transform_path = string.Empty;

        /// <summary>平台参考控制器，固定为 RTouch。</summary>
        public string platform_reference_controller = "RTouch";

        /// <summary>平台参考语义说明。</summary>
        public string platform_reference_semantics = "quest_controller_transform_with_held_last_active_pose";

        /// <summary>采集器保存帧率；0 表示保存发布器产生的全部已编码帧。</summary>
        public float capture_fps;

        /// <summary>开始时 UTC Unix 毫秒。</summary>
        public long created_unix_ms;

        /// <summary>停止时 UTC Unix 毫秒；录制中为 0。</summary>
        public long stopped_unix_ms;

        /// <summary>后台队列是否已完整排空并原子发布最终目录。</summary>
        public bool complete;

        /// <summary>固定为 left。</summary>
        public string image_eye = "left";

        /// <summary>固定为 jpeg。</summary>
        public string image_format = "jpeg";

        /// <summary>图像像素原点。</summary>
        public string image_origin = "top_left";

        /// <summary>图像是否需要额外垂直翻转。</summary>
        public bool vertical_flip;

        /// <summary>图像时间戳的诚实语义。</summary>
        public string image_time_semantics = "delayed_image_time_proxy";

        /// <summary>Python 侧目标 mesh 相对路径。</summary>
        public string model_mesh_path = string.Empty;

        /// <summary>Python 加载 mesh 后应用的尺度。</summary>
        public float model_apply_scale = 1f;

        /// <summary>model/camera OpenCV 到 Unity 的轴符号，当前为 [1,-1,1]。</summary>
        public int[] model_cv_to_unity_axis_signs = { 1, -1, 1 };

        /// <summary>固定方法顺序。</summary>
        public string[] variant_ids = Array.Empty<string>();

        /// <summary>与方法顺序对应的论文颜色。</summary>
        public string[] variant_colors_hex = Array.Empty<string>();

        /// <summary>收到已编码 stereo 回调的次数。</summary>
        public int capture_attempts;

        /// <summary>成功进入后台 writer 的样本数。</summary>
        public int samples_enqueued;

        /// <summary>成功原子写出 JPEG 和 JSONL 的样本数。</summary>
        public int samples_written;

        /// <summary>writer 队列满时丢弃的整条样本数。</summary>
        public int queue_dropped;

        /// <summary>缺少 image-time 四路 pose 历史的样本数。</summary>
        public int pose_history_missing;

        /// <summary>缺少 frame-aligned 左目相机 pose 的样本数。</summary>
        public int camera_pose_missing;

        /// <summary>缺少相机标定的样本数。</summary>
        public int calibration_missing;

        /// <summary>平台参考尚未获得有效位姿的已写样本数。</summary>
        public int reference_invalid_samples;

        /// <summary>平台参考使用保持位姿的已写样本数。</summary>
        public int reference_held_samples;

        /// <summary>后台写入失败数。</summary>
        public int write_failures;

        /// <summary>writer 队列峰值。</summary>
        public int peak_queue_depth;

        /// <summary>成功写出的 JPEG 总字节数。</summary>
        public long image_bytes_written;

        /// <summary>首个后台写入异常；无异常时为空。</summary>
        public string writer_error = string.Empty;
    }
}
