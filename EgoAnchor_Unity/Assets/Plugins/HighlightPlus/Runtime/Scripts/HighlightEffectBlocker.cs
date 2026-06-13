using UnityEngine;
using UnityEngine.Rendering;
using System.Collections.Generic;

namespace HighlightPlus {


    public enum BlockerTargetOptions {
        OnlyThisObject,
        Children,
        LayerInChildren
    }

    [DefaultExecutionOrder(100)]
    [ExecuteInEditMode]
    public class HighlightEffectBlocker : MonoBehaviour {

        public BlockerTargetOptions include = BlockerTargetOptions.OnlyThisObject;
        public LayerMask layerMask = -1;
        public string nameFilter;
        public bool useRegEx;

        public bool blockOutlineAndGlow = true;
        public bool blockOverlay = true;

        List<Renderer> renderers;

        void OnEnable () {
            Refresh();
            HighlightPlusRenderPassFeature.RegisterBlocker(this);
        }

        void OnDisable () {
            HighlightPlusRenderPassFeature.UnregisterBlocker(this);
        }

        public void Refresh() {
            if (renderers == null) {
                renderers = new List<Renderer>();
            } else {
                renderers.Clear();
            }
            switch (include) {
                case BlockerTargetOptions.OnlyThisObject:
                    Renderer r = GetComponent<Renderer>();
                    if (r != null) renderers.Add(r);
                    return;
                case BlockerTargetOptions.Children:
                    GetComponentsInChildren<Renderer>(true, renderers);
                    break;
                case BlockerTargetOptions.LayerInChildren:
                    Renderer[] childRenderers = GetComponentsInChildren<Renderer>(true);
                    for (int k = 0; k < childRenderers.Length; k++) {
                        Renderer cr = childRenderers[k];
                        if (cr != null && ((1 << cr.gameObject.layer) & layerMask) != 0) {
                            renderers.Add(cr);
                        }
                    }
                    break;
            }
            if (!string.IsNullOrEmpty(nameFilter)) {
                for (int k = renderers.Count - 1; k >= 0; k--) {
                    string objName = renderers[k].name;
                    if (useRegEx) {
                        if (!System.Text.RegularExpressions.Regex.IsMatch(objName, nameFilter)) {
                            renderers.RemoveAt(k);
                        }
                    } else if (!objName.Contains(nameFilter)) {
                        renderers.RemoveAt(k);
                    }
                }
            }
        }


        public void BuildCommandBuffer (CommandBuffer cmd, Material mat) {
            if (renderers == null) return;
            int renderersCount = renderers.Count;
            for (int k=0;k<renderersCount;k++) {
                Renderer r = renderers[k];
                if (r == null || !r.enabled || !r.gameObject.activeInHierarchy) continue;
                int submeshCount = r.sharedMaterials.Length;
                for (int i = 0; i < submeshCount; i++) {
                    cmd.DrawRenderer(r, mat, i);
                }
            }
        }

    }
}
