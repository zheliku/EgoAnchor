
#if UNITY_EDITOR
using TMPro;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.UI;

namespace EgoAnchor.Eval.RQ1.Editor
{
    /// <summary>
    /// RQ1 场景一键构建器。
    /// 菜单：EgoAnchor → RQ1 → Build Status Panel
    /// </summary>
    public static class RQ1SceneBuilder
    {
        private const string MenuPath = "EgoAnchor/RQ1/Build Status Panel";

        [MenuItem(MenuPath)]
        public static void BuildStatusPanel()
        {
            // ── 1. 找/创建 Canvas ──────────────────────────────────────────
            Canvas canvas = Object.FindFirstObjectByType<Canvas>();
            if (canvas == null)
            {
                var go = new GameObject("Canvas");
                canvas = go.AddComponent<Canvas>();
                canvas.renderMode = RenderMode.WorldSpace;
                go.AddComponent<CanvasScaler>();
                go.AddComponent<GraphicRaycaster>();

                var rt = go.GetComponent<RectTransform>();
                rt.sizeDelta    = new Vector2(800, 600);
                rt.localScale   = Vector3.one * 0.001f;
                rt.localPosition = new Vector3(0, 0, 0.4f);
            }

            // ── 2. 找/创建 RQ1_StatusPanel ────────────────────────────────
            Transform existingPanel = canvas.transform.Find("RQ1_StatusPanel");
            if (existingPanel != null)
            {
                bool replace = EditorUtility.DisplayDialog(
                    "RQ1 Scene Builder",
                    "RQ1_StatusPanel 已存在，是否重建？",
                    "重建", "取消");
                if (!replace) return;
                Object.DestroyImmediate(existingPanel.gameObject);
            }

            var panel = CreatePanel(canvas.transform);

            // ── 3. 找/创建 RQ1Controller ──────────────────────────────────
            var controllerGo = GameObject.Find("RQ1Controller")
                            ?? new GameObject("RQ1Controller");

            var metricRecorder = EnsureComponent<RQ1MetricRecorder>(controllerGo);
            var inputHandler   = EnsureComponent<RQ1InputHandler>(controllerGo);
            var statusUI       = EnsureComponent<RQ1StatusUI>(controllerGo);

            // ── 4. 找 EvalSession ─────────────────────────────────────────
            var evalSession = Object.FindFirstObjectByType<EvalSession>();
            if (evalSession == null)
                Debug.LogWarning("[RQ1SceneBuilder] 未找到 EvalSession，请手动绑定。");

            // ── 5. 绑定 RQ1InputHandler 引用 ──────────────────────────────
            var ihSo = new SerializedObject(inputHandler);
            SetRef(ihSo, "recorder",   metricRecorder);
            SetRef(ihSo, "evalSession", evalSession);
            ihSo.ApplyModifiedProperties();

            // ── 6. 绑定 RQ1StatusUI 引用 ──────────────────────────────────
            var uiSo = new SerializedObject(statusUI);
            SetRef(uiSo, "recorder",              metricRecorder);
            SetRef(uiSo, "evalSession",            evalSession);
            SetRef(uiSo, "recordingStatusText",   panel.recordingStatus);
            SetRef(uiSo, "sessionIdText",          panel.sessionId);
            SetRef(uiSo, "durationText",           panel.duration);
            SetRef(uiSo, "currentMetricText",      panel.currentMetric);
            SetRef(uiSo, "suggestedDurationText",  panel.suggestedDuration);
            SetRef(uiSo, "markedDurationText",     panel.markedDuration);
            SetRef(uiSo, "keyBindingsText",        panel.keyBindings);
            uiSo.ApplyModifiedProperties();

            // ── 7. 绑定 EvalRecorder 里的 rq1MetricRecorder ───────────────
            var evalRecorder = Object.FindFirstObjectByType<EvalRecorder>();
            if (evalRecorder != null)
            {
                var erSo = new SerializedObject(evalRecorder);
                SetRef(erSo, "rq1MetricRecorder", metricRecorder);
                erSo.ApplyModifiedProperties();
            }
            else
            {
                Debug.LogWarning("[RQ1SceneBuilder] 未找到 EvalRecorder，请手动绑定。");
            }

            // ── 8. 保存场景 ───────────────────────────────────────────────
            EditorSceneManager.MarkSceneDirty(
                UnityEngine.SceneManagement.SceneManager.GetActiveScene());

            Debug.Log("[RQ1SceneBuilder] ✅ RQ1 状态面板构建完成！请保存场景（Ctrl+S）。");
            Selection.activeGameObject = controllerGo;
            EditorGUIUtility.PingObject(controllerGo);
        }

        // ── 内部辅助 ──────────────────────────────────────────────────────

        private struct PanelRefs
        {
            public TextMeshProUGUI recordingStatus;
            public TextMeshProUGUI sessionId;
            public TextMeshProUGUI duration;
            public TextMeshProUGUI currentMetric;
            public TextMeshProUGUI suggestedDuration;
            public TextMeshProUGUI markedDuration;
            public TextMeshProUGUI keyBindings;
        }

        private static PanelRefs CreatePanel(Transform canvasTransform)
        {
            // 外层面板（深色背景）
            var panelGo = new GameObject("RQ1_StatusPanel");
            panelGo.transform.SetParent(canvasTransform, false);

            var panelRt = panelGo.AddComponent<RectTransform>();
            panelRt.anchorMin  = new Vector2(0.55f, 0.02f);
            panelRt.anchorMax  = new Vector2(0.99f, 0.98f);
            panelRt.offsetMin  = Vector2.zero;
            panelRt.offsetMax  = Vector2.zero;

            var bg = panelGo.AddComponent<Image>();
            bg.color = new Color(0.08f, 0.08f, 0.12f, 0.92f);

            // 竖直布局
            var layout = panelGo.AddComponent<VerticalLayoutGroup>();
            layout.padding        = new RectOffset(16, 16, 14, 14);
            layout.spacing        = 6f;
            layout.childAlignment = TextAnchor.UpperLeft;
            layout.childControlHeight  = false;
            layout.childControlWidth   = true;
            layout.childForceExpandHeight = false;
            layout.childForceExpandWidth  = true;

            // ── 标题 ──
            var title = CreateTMP(panelGo.transform, "Title", "── RQ1 采集状态 ──", 22, Color.cyan, FontStyles.Bold);

            // ── 分隔线 ──
            CreateDivider(panelGo.transform);

            // ── 状态行 ──
            var recStatus   = CreateTMP(panelGo.transform, "RecordingStatus", "○ 未录制",        20, Color.gray);
            var sessionId   = CreateTMP(panelGo.transform, "SessionId",       "Session: 未开始", 16, new Color(0.8f, 0.8f, 0.8f));
            var duration    = CreateTMP(panelGo.transform, "Duration",        "时长: 00:00",      18, Color.white);

            // ── 分隔线 ──
            CreateDivider(panelGo.transform);

            // ── 当前指标 ──
            var curMetric   = CreateTMP(panelGo.transform, "CurrentMetric",    "当前指标: 无标记",    20, Color.yellow, FontStyles.Bold);
            var sugDuration = CreateTMP(panelGo.transform, "SuggestedDuration","建议时长: -",         16, new Color(0.7f, 0.9f, 0.7f));
            var markDuration= CreateTMP(panelGo.transform, "MarkedDuration",   "已标记: 00:00",        16, new Color(0.9f, 0.7f, 0.4f));

            // ── 分隔线 ──
            CreateDivider(panelGo.transform);

            // ── 按键对照表 ──
            var keyBindings = CreateTMP(panelGo.transform, "KeyBindings",
                "[1] 长时静止  60s\n[2] 慢速平移  20s\n[3] 快速挥动  20s\n[4] 旋转运动  20s\n[5] 遮挡恢复  单次\n[0] 清除标记\n[F7] 开始  [F8] 停止",
                15, new Color(0.75f, 0.85f, 1.0f));

            return new PanelRefs
            {
                recordingStatus = recStatus,
                sessionId       = sessionId,
                duration        = duration,
                currentMetric   = curMetric,
                suggestedDuration = sugDuration,
                markedDuration  = markDuration,
                keyBindings     = keyBindings,
            };
        }

        private static TextMeshProUGUI CreateTMP(
            Transform parent, string goName, string defaultText,
            float fontSize, Color color,
            FontStyles style = FontStyles.Normal)
        {
            var go = new GameObject(goName);
            go.transform.SetParent(parent, false);

            var rt = go.AddComponent<RectTransform>();
            rt.sizeDelta = new Vector2(0, fontSize * 1.6f);

            var tmp = go.AddComponent<TextMeshProUGUI>();
            tmp.text      = defaultText;
            tmp.fontSize  = fontSize;
            tmp.color     = color;
            tmp.fontStyle = style;

            var le = go.AddComponent<LayoutElement>();
            le.preferredHeight = fontSize * 1.6f;

            return tmp;
        }

        private static void CreateDivider(Transform parent)
        {
            var go = new GameObject("Divider");
            go.transform.SetParent(parent, false);

            var rt = go.AddComponent<RectTransform>();
            rt.sizeDelta = new Vector2(0, 2f);

            var img = go.AddComponent<Image>();
            img.color = new Color(0.4f, 0.4f, 0.5f, 0.6f);

            var le = go.AddComponent<LayoutElement>();
            le.preferredHeight = 2f;
        }

        private static T EnsureComponent<T>(GameObject go) where T : Component
        {
            var comp = go.GetComponent<T>();
            return comp != null ? comp : go.AddComponent<T>();
        }

        private static void SetRef(SerializedObject so, string propName, Object value)
        {
            var prop = so.FindProperty(propName);
            if (prop == null)
            {
                Debug.LogWarning($"[RQ1SceneBuilder] 属性未找到：{so.targetObject.GetType().Name}.{propName}");
                return;
            }
            prop.objectReferenceValue = value;
        }
    }
}
#endif
