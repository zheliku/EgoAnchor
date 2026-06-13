using System.Collections.Generic;
using UnityEngine;

namespace HighlightPlus {

    [ExecuteAlways]
    [DefaultExecutionOrder(-100)]
    public class HighlightLabelPoolManager : MonoBehaviour {

        private static HighlightLabelPoolManager instance;
        private static readonly Dictionary<GameObject, Queue<HighlightLabel>> labelPools = new Dictionary<GameObject, Queue<HighlightLabel>>();
        private static readonly HashSet<HighlightLabel> activeLabels = new HashSet<HighlightLabel>();
        private static readonly int initialPoolSize = 5;

        const string LABEL_INSTANCE_NAME = "Highlight Plus Label";
        const string LABEL_POOL_NAME = "Highlight Plus Label Pool Manager";

        [RuntimeInitializeOnLoadMethod]
        static void DomainReloadDisabledSupport () {
            DestroySceneLabels();
        }

        void OnEnable () {
            if (instance == null) {
                instance = this;
            } else if (instance != this) {
                DestroyImmediate(gameObject);
            }
            ClearPools();
        }

        void OnDestroy () {
            labelPools.Clear();
            activeLabels.Clear();
        }


        public static void DestroySceneLabels () {
            // Find and destroy any existing pool managers
            HighlightLabelPoolManager[] existingManagers = Misc.FindObjectsOfType<HighlightLabelPoolManager>(true);
            foreach (var manager in existingManagers) {
                if (manager != null) {
                    DestroyImmediate(manager.gameObject);
                }
            }
            ClearPools();
            instance = null;
        }

        static void ClearPools () {
            if (instance != null) {
                for (int i = instance.transform.childCount - 1; i >= 0; i--) {
                    Transform child = instance.transform.GetChild(i);
                    if (child != null) {
                        DestroyImmediate(child.gameObject);
                    }
                }
            }
            labelPools.Clear();
            activeLabels.Clear();
        }

        private static void InitializePool (GameObject prefab) {
            if (!labelPools.ContainsKey(prefab)) {
                labelPools[prefab] = new Queue<HighlightLabel>();
                for (int i = 0; i < initialPoolSize; i++) {
                    CreatePooledLabel(prefab);
                }
            }
        }

        private static HighlightLabel CreatePooledLabel (GameObject prefab) {
            GameObject labelInstanceGO = Instantiate(prefab);
            labelInstanceGO.name = LABEL_INSTANCE_NAME;
            labelInstanceGO.transform.SetParent(instance.transform, false);
            HighlightLabel labelInstance = labelInstanceGO.GetComponentInChildren<HighlightLabel>();
            labelInstance.labelPrefab = prefab;
            labelInstance.isPooled = true;
            labelInstanceGO.SetActive(false);
            labelPools[prefab].Enqueue(labelInstance);
            return labelInstance;
        }

        public static HighlightLabel GetLabelInstance (GameObject prefab) {
            if (instance == null) {
                GameObject go = new GameObject(LABEL_POOL_NAME);
                instance = go.AddComponent<HighlightLabelPoolManager>();
            }

            // Initialize pool if needed
            InitializePool(prefab);

            // Try to get from pool
            HighlightLabel labelInstance = null;
            while (labelInstance == null && labelPools[prefab].Count > 0) {
                labelInstance = labelPools[prefab].Dequeue();
            }
            if (labelInstance != null) {
                activeLabels.Add(labelInstance);
                return labelInstance;
            }

            // Create new instance if pool is empty
            HighlightLabel newLabel = CreatePooledLabel(prefab);
            activeLabels.Add(newLabel);
            return newLabel;
        }

        public static void ReturnToPool (HighlightLabel label) {
            if (label.labelPrefab != null && labelPools.ContainsKey(label.labelPrefab)) {
                labelPools[label.labelPrefab].Enqueue(label);
                activeLabels.Remove(label);
            }
        }

        public static void Refresh () {
            if (instance == null) return;
            instance.LateUpdate();
        }

        void LateUpdate () {
            foreach (var label in activeLabels) {
                if (label == null) continue;
                if (label.isVisible) {
                    label.UpdatePosition();
                    if (!label.gameObject.activeSelf) {
                        label.gameObject.SetActive(true);
                    }
                }
            }
        }

    }
}