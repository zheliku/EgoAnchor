using EgoAnchor.Policy;
using UnityEngine;
using UnityEngine.Rendering;

namespace EgoAnchor.Runtime
{
    /// <summary>
    /// 管理 anchor 的轨迹段，并将每一段交给仓库 LineRenderer3D 的圆管生成器。
    /// 轨迹段作为本节点的子物体创建，圆管网格由该子物体上的 LineRenderer3D 生成。
    /// </summary>
    [DefaultExecutionOrder(100)]
    public sealed class AnchorTrajectoryRenderer : MonoBehaviour
    {
        /// <summary>轨迹采样间隔，单位秒。</summary>
        [SerializeField, Min(0.001f)] private float sampleIntervalSeconds = 0.0222222f;

        /// <summary>圆管外径，单位米。</summary>
        [SerializeField, Min(0.0001f)] private float lineWidth = 0.002f;

        /// <summary>圆管截面的分段数。</summary>
        [SerializeField, Range(6, 24)] private int radialSegments = 8;

        /// <summary>轨迹材质；为空时创建支持置顶渲染的内置材质。</summary>
        [SerializeField] private Material lineMaterial;

        /// <summary>轨迹颜色，场景中配置为对应 anchor 的高亮颜色。</summary>
        [SerializeField] private Color lineColor = new Color(0.64f, 1f, 0f, 1f);

        /// <summary>当前 anchor 的 pose runtime。</summary>
        [SerializeField] private PoseToAnchorRuntime runtime;

        /// <summary>当前正在接收采样点的轨迹段。</summary>
        private GameObject activeSegment;

        /// <summary>当前轨迹段的仓库三维圆管生成器。</summary>
        private LineRenderer3D activeLine;

        /// <summary>运行时创建并复用的材质实例。</summary>
        private Material runtimeMaterial;

        /// <summary>anchor 的显示姿态来源。</summary>
        private DynamicObjectAnchor dynamicAnchor;

        /// <summary>下一次允许采样的实时钟时间戳。</summary>
        private double nextSampleTimeSeconds;

        /// <summary>组件启用时停用历史轨迹，等待 Tracking 后开始新的轨迹段。</summary>
        private void OnEnable()
        {
            DisconnectActiveSegment();
            nextSampleTimeSeconds = 0.0;

            MeshRenderer[] oldMeshSegments = GetComponentsInChildren<MeshRenderer>(true);
            foreach (MeshRenderer oldRenderer in oldMeshSegments)
            {
                if (oldRenderer != null)
                {
                    oldRenderer.gameObject.SetActive(false);
                }
            }

            LineRenderer[] oldLineSegments = GetComponentsInChildren<LineRenderer>(true);
            foreach (LineRenderer oldRenderer in oldLineSegments)
            {
                if (oldRenderer != null)
                {
                    oldRenderer.gameObject.SetActive(false);
                }
            }
        }

        /// <summary>组件停用时断开当前轨迹，已经完成的历史段保持可见。</summary>
        private void OnDisable()
        {
            DisconnectActiveSegment();
        }

        /// <summary>补齐 runtime 和显示姿态来源引用。</summary>
        private void Awake()
        {
            if (runtime == null)
            {
                runtime = GetComponent<PoseToAnchorRuntime>();
                if (runtime == null)
                {
                    runtime = GetComponentInParent<PoseToAnchorRuntime>();
                }
            }

            dynamicAnchor = GetComponent<DynamicObjectAnchor>();
            if (dynamicAnchor == null)
            {
                dynamicAnchor = GetComponentInParent<DynamicObjectAnchor>();
            }
        }

        /// <summary>每帧在 anchor 输出更新后，按时间采样当前 Tracking 位姿。</summary>
        private void LateUpdate()
        {
            KeepSegmentsAtWorldOrigin();

            if (runtime == null)
            {
                return;
            }

            AnchorState state = runtime.CurrentAnchorState;
            bool hasPose = runtime.TryGetOutputPose(out Pose pose);
            bool visible = dynamicAnchor == null || dynamicAnchor.HasDisplayPose;
            bool tracking = state == AnchorState.Tracking && hasPose && visible;
            if (!tracking)
            {
                if (!visible || state == AnchorState.Lost || state == AnchorState.Searching)
                {
                    DisconnectActiveSegment();
                }

                return;
            }

            if (activeSegment == null)
            {
                BeginSegment();
            }

            double now = Time.realtimeSinceStartupAsDouble;
            if (now >= nextSampleTimeSeconds || activeLine.Count() == 0)
            {
                AddPoint(pose.position);
                nextSampleTimeSeconds = now + Mathf.Max(sampleIntervalSeconds, 0.001f);
            }
        }

        /// <summary>将轨迹段保持在世界原点单位变换，使网格顶点直接使用世界坐标。</summary>
        private void KeepSegmentsAtWorldOrigin()
        {
            for (int i = 0; i < transform.childCount; i++)
            {
                Transform child = transform.GetChild(i);
                if (child.GetComponent<MeshFilter>() != null)
                {
                    child.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
                    child.localScale = Vector3.one;
                }
            }
        }

        /// <summary>断开当前轨迹段，使下次 Tracking 从新子物体开始。</summary>

        private void DisconnectActiveSegment()
        {
            if (activeLine != null)
            {
                activeLine.CompleteGeneration();
            }

            activeSegment = null;
            activeLine = null;
            nextSampleTimeSeconds = 0.0;
        }

        /// <summary>创建一条轨迹段，并在其上挂载仓库的三维圆管生成器。</summary>
        private void BeginSegment()
        {
            activeSegment = new GameObject($"Trajectory {transform.childCount:00}");
            activeSegment.transform.SetParent(transform, false);
            activeSegment.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
            activeSegment.transform.localScale = Vector3.one;

            activeLine = activeSegment.AddComponent<LineRenderer3D>();
            activeLine.autoUpdate = false;
            activeLine.resolution = Mathf.Clamp(radialSegments, 6, 24);
            activeLine.material = GetMaterial();
            activeLine.SetPositions(0);
            nextSampleTimeSeconds = 0.0;
        }

        /// <summary>向仓库生成器追加一个点，并在拥有至少两个点后生成圆管网格。</summary>
        private void AddPoint(Vector3 point)
        {
            if (activeLine == null)
            {
                return;
            }

            int pointCount = activeLine.Count();
            if (pointCount > 0)
            {
                Vector3 previous = activeLine.GetPoint(pointCount - 1).position;
                if ((point - previous).sqrMagnitude < 0.00000001f)
                {
                    return;
                }
            }

            activeLine.AddPoint(point, Mathf.Max(lineWidth, 0.0001f) * 0.5f);
            if (activeLine.Count() >= 2)
            {
                activeLine.BeginGenerationAutoComplete();
            }
        }

        /// <summary>获取支持颜色和始终置顶渲染的材质实例。</summary>
        private Material GetMaterial()
        {
            if (runtimeMaterial != null)
            {
                return runtimeMaterial;
            }

            if (lineMaterial != null)
            {
                runtimeMaterial = new Material(lineMaterial);
            }
            else
            {
                Shader shader = Shader.Find("Hidden/Internal-Colored");
                if (shader != null)
                {
                    runtimeMaterial = new Material(shader);
                }
            }

            if (runtimeMaterial != null)
            {
                runtimeMaterial.name = "AnchorTrajectoryRuntime";
                runtimeMaterial.color = lineColor;
                runtimeMaterial.SetColor("_Color", lineColor);
                runtimeMaterial.renderQueue = 4000;
                runtimeMaterial.SetInt("_SrcBlend", (int)BlendMode.SrcAlpha);
                runtimeMaterial.SetInt("_DstBlend", (int)BlendMode.OneMinusSrcAlpha);
                runtimeMaterial.SetInt("_ZWrite", 0);
                runtimeMaterial.SetInt("_ZTest", (int)CompareFunction.Always);
                runtimeMaterial.SetInt("_Cull", (int)CullMode.Off);
            }

            return runtimeMaterial;
        }

        /// <summary>销毁运行时创建的材质实例。</summary>
        private void OnDestroy()
        {
            if (runtimeMaterial != null)
            {
                Destroy(runtimeMaterial);
            }
        }
    }
}
