using UnityEngine;

namespace EgoAnchor.Eval
{
    /// <summary>
    /// 评估 session 热键驱动：F7 开始录制，F8 停止录制。
    /// 使用内置 Input 系统，不依赖 Unity.InputSystem 包。
    /// </summary>
    public sealed class EvalHotkeys : MonoBehaviour
    {
        [Header("References")]
        [Tooltip("被热键控制的 EvalSession。")]
        [SerializeField] private EvalSession session;

        [Header("Keys")]
        [Tooltip("开始录制热键，默认 F7。")]
        [SerializeField] private KeyCode startKey = KeyCode.F7;

        [Tooltip("停止录制热键，默认 F8。")]
        [SerializeField] private KeyCode stopKey = KeyCode.F8;

        private void Update()
        {
            if (session == null) return;
            if (Input.GetKeyDown(startKey)) session.StartSession();
            if (Input.GetKeyDown(stopKey))  session.StopSession();
        }

        [ContextMenu("EgoAnchor Eval/Start Session")]
        public void StartSession() => session?.StartSession();

        [ContextMenu("EgoAnchor Eval/Stop Session")]
        public void StopSession() => session?.StopSession();
    }
}
