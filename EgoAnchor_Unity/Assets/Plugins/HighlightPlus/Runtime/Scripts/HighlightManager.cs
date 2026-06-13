using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.EventSystems;

namespace HighlightPlus {

    [RequireComponent(typeof(HighlightEffect))]
    [DefaultExecutionOrder(100)]
    [HelpURL("https://kronnect.com/docs/highlight-plus/")]
    public class HighlightManager : MonoBehaviour {

        [Tooltip("Enables highlight when pointer is over this object.")]
        [SerializeField]
        bool _highlightOnHover = true;

        public bool highlightOnHover {
            get { return _highlightOnHover; }
            set {
                if (_highlightOnHover != value) {
                    _highlightOnHover = value;
                    if (!_highlightOnHover) {
                        if (currentEffect != null) {
                            Highlight(false);
                        }
                    }

                }
            }
        }

        public LayerMask layerMask = -1;
        public Camera raycastCamera;
        public RayCastSource raycastSource = RayCastSource.MousePosition;
        [Tooltip("Objects in this layer mask will block the highlight if they are between the camera and the target.")]
        public LayerMask blockingLayerMask = -1;
        [Tooltip("Minimum distance for target.")]
        public float minDistance;
        [Tooltip("Maximum distance for target. 0 = infinity")]
        public float maxDistance;
        [Tooltip("Blocks interaction if pointer is over an UI element")]
        public bool respectUI = true;
        [Tooltip("Unhighlights the object when the pointer is over a UI element")]
        public bool unhighlightOnUI;

        [Tooltip("If the object will be selected by clicking with mouse or tapping on it.")]
        public bool selectOnClick;
        [Tooltip("Optional profile for objects selected by clicking on them")]
        public HighlightProfile selectedProfile;
        [Tooltip("Profile to use when object is selected and highlighted.")]
        public HighlightProfile selectedAndHighlightedProfile;
        [Tooltip("Automatically deselects other previously selected objects")]
        public bool singleSelection;
        [Tooltip("Toggles selection on/off when clicking object")]
        public bool toggle;
        [Tooltip("Keeps current selection when clicking outside of any selectable object")]
        public bool keepSelection = true;

        HighlightEffect baseEffect, currentEffect;
        Transform currentObject;
        RaycastHit2D[] hitInfo2D;
        static RaycastHit blockingHit;
        readonly List<RaycastResult> cachedRaycastResults = new List<RaycastResult>();
        PointerEventData cachedPointerEventData;
        EventSystem cachedEventSystem;

        public readonly static List<HighlightEffect> selectedObjects = new List<HighlightEffect>();
        public event OnObjectSelectionEvent OnObjectSelected;
        public event OnObjectSelectionEvent OnObjectUnSelected;
        public event OnObjectHighlightEvent OnObjectHighlightStart;
        public event OnObjectHighlightEvent OnObjectHighlightStay;
        public event OnObjectHighlightEvent OnObjectHighlightEnd;
        public event OnObjectClickEvent OnObjectClicked;
        public static int lastTriggerFrame;

        static HighlightManager _instance;
        public static HighlightManager instance {
            get {
                if (_instance == null) {
                    _instance = Misc.FindObjectOfType<HighlightManager>();
                }
                return _instance;
            }
        }

        [RuntimeInitializeOnLoadMethod]
        static void DomainReloadDisabledSupport () {
            selectedObjects.Clear();
            lastTriggerFrame = 0;
            _instance = null;
        }

        void OnEnable () {
            currentObject = null;
            currentEffect = null;
            if (baseEffect == null) {
                if (!TryGetComponent(out baseEffect)) {
                    baseEffect = gameObject.AddComponent<HighlightEffect>();
                }
            }
            if (raycastCamera == null) {
                raycastCamera = GetCamera();
                if (raycastCamera == null) {
                    Debug.LogError("Highlight Manager: no camera found!");
                }
            }
            hitInfo2D = new RaycastHit2D[1];
            InputProxy.Init();
        }


        void OnDisable () {
            SwitchesObject(null);
            internal_DeselectAll();
        }

        void Update () {
            if (raycastCamera == null)
                return;

#if ENABLE_INPUT_SYSTEM && !ENABLE_LEGACY_INPUT_MANAGER
            if (respectUI) {
                EventSystem es = EventSystem.current;
                if (es == null) {
                    es = CreateEventSystem();
                }
                cachedRaycastResults.Clear();
                if (cachedPointerEventData == null || cachedEventSystem != es) {
                    cachedPointerEventData = new PointerEventData(es);
                    cachedEventSystem = es;
                }
                Vector3 cameraPos = raycastCamera.transform.position;
                if (raycastSource == RayCastSource.MousePosition) {
                    cachedPointerEventData.position = InputProxy.mousePosition;
                } else {
                    cachedPointerEventData.position = new Vector2(raycastCamera.pixelWidth * 0.5f, raycastCamera.pixelHeight * 0.5f);
                }
                es.RaycastAll(cachedPointerEventData, cachedRaycastResults);
                int hitCount = cachedRaycastResults.Count;
                // check UI blocker
                bool blocked = false;
                for (int k = 0; k < hitCount; k++) {
                    RaycastResult rr = cachedRaycastResults[k];
                    if (rr.module is UnityEngine.UI.GraphicRaycaster) {
                        blocked = true;
                        break;
                    }
                }
                if (blocked) {
                    if (unhighlightOnUI && currentEffect != null && currentEffect.highlighted) {
                        currentEffect.SetHighlighted(false);
                    }
                    return;
                }

                // compute blocking ray for distance checks
                Ray blockingRay;
                if (raycastSource == RayCastSource.MousePosition) {
                    blockingRay = raycastCamera.ScreenPointToRay(InputProxy.mousePosition);
                } else {
                    blockingRay = new Ray(raycastCamera.transform.position, raycastCamera.transform.forward);
                }
                float uiBlockingDistance = GetBlockingDistance(blockingRay, maxDistance > 0 ? maxDistance : raycastCamera.farClipPlane);

                // look for our gameobject
                for (int k = 0; k < hitCount; k++) {
                    RaycastResult rr = cachedRaycastResults[k];
                    float distance = Vector3.Distance(rr.worldPosition, cameraPos);
                    if (distance < minDistance || (maxDistance > 0 && distance > maxDistance) || distance > uiBlockingDistance) continue;

                    GameObject theGameObject = rr.gameObject;
                    if ((layerMask & (1 << rr.gameObject.layer)) == 0) continue;

                    // is this object state controller by Highlight Trigger?
                    HighlightTrigger trigger = theGameObject.GetComponent<HighlightTrigger>();
                    if (trigger != null) return;

                    UpdateHitPosition(theGameObject.transform, rr.worldPosition, Misc.vector3Zero);

                    // Toggles selection
                    Transform t = theGameObject.transform;
                    if (InputProxy.GetMouseButtonDown(0)) {
                        if (selectOnClick) {
                            ToggleSelection(t, !toggle);
                        }
                    } else 
                        // Check if the object has a Highlight Effect
                        if (t != currentObject) {
                            SwitchesObject(t);
                        }
                }
            }

            // if not blocked by UI and no hit found, fallback to raycast (required if no PhysicsRaycaster is present on the camera)
#endif

            Ray ray;
            {
#if !(ENABLE_INPUT_SYSTEM && !ENABLE_LEGACY_INPUT_MANAGER)
                Vector2 screenPos = raycastSource == RayCastSource.MousePosition ? (Vector2)InputProxy.mousePosition : new Vector2(raycastCamera.pixelWidth * 0.5f, raycastCamera.pixelHeight * 0.5f);
                if (!CanInteractAt(screenPos)) {
                    if (unhighlightOnUI && currentEffect != null && currentEffect.highlighted) {
                        currentEffect.SetHighlighted(false);
                    }
                    return;
                }
#endif
                if (raycastSource == RayCastSource.MousePosition) {
                    ray = raycastCamera.ScreenPointToRay(InputProxy.mousePosition);
                }
                else {
                    ray = new Ray(raycastCamera.transform.position, raycastCamera.transform.forward);
                }
            }

            VerifyHighlightStay();

            float blockingDistance = GetBlockingDistance(ray, maxDistance > 0 ? maxDistance : raycastCamera.farClipPlane);
            RaycastHit hitInfo;
            if (Physics.Raycast(ray, out hitInfo, maxDistance > 0 ? maxDistance : raycastCamera.farClipPlane, layerMask) && Vector3.Distance(hitInfo.point, ray.origin) >= minDistance && hitInfo.distance <= blockingDistance) {
                Transform t = hitInfo.collider.transform;
                // is this object state controller by Highlight Trigger?
                if (t.TryGetComponent(out HighlightTrigger _)) {
                    return;
                }

                // Toggles selection
                if (InputProxy.GetMouseButtonDown(0)) {
                    if (selectOnClick) {
                        ToggleSelection(t, !toggle);
                    }
                }
                else
                    // Check if the object has a Highlight Effect
                    if (t != currentObject) {
                    SwitchesObject(t);
                }
                UpdateHitPosition(t, hitInfo.point, hitInfo.normal);
                return;
            }
            else // check sprites
            if (Physics2D.GetRayIntersectionNonAlloc(ray, hitInfo2D, maxDistance > 0 ? maxDistance : raycastCamera.farClipPlane, layerMask) > 0 && Vector3.Distance(hitInfo2D[0].point, ray.origin) >= minDistance && Vector3.Distance(hitInfo2D[0].point, ray.origin) <= blockingDistance) {
                Transform t = hitInfo2D[0].collider.transform;
                // is this object state controller by Highlight Trigger?
                if (t.TryGetComponent(out HighlightTrigger _)) {
                    return;
                }

                // Toggles selection
                if (InputProxy.GetMouseButtonDown(0)) {
                    if (selectOnClick) {
                        ToggleSelection(t, !toggle);
                    }
                }
                else
                    // Check if the object has a Highlight Effect
                    if (t != currentObject) {
                    SwitchesObject(t);
                }
                UpdateHitPosition(t, hitInfo2D[0].point, Misc.vector3Zero);
                return;
            }

            // no hit
            if (selectOnClick && !keepSelection && InputProxy.GetMouseButtonDown(0) && lastTriggerFrame < Time.frameCount) {
                internal_DeselectAll();
            }
            SwitchesObject(null);
        }


#if ENABLE_INPUT_SYSTEM && !ENABLE_LEGACY_INPUT_MANAGER
        EventSystem CreateEventSystem() {
            GameObject eo = new GameObject("Event System created by Highlight Plus", typeof(EventSystem), typeof(UnityEngine.InputSystem.UI.InputSystemUIInputModule));
            return eo.GetComponent<EventSystem>();
        }
#endif
        void VerifyHighlightStay () {
            if (currentObject == null || currentEffect == null || !currentEffect.highlighted) return;
            if (OnObjectHighlightStay != null && !OnObjectHighlightStay(currentObject.gameObject)) {
                SwitchesObject(null);
            }
        }

        void SwitchesObject (Transform newObject) {
            if (currentEffect != null) {
                if (highlightOnHover) {
                    Highlight(false);
                }
                currentEffect = null;
            }
            currentObject = newObject;
            if (newObject == null) return;
            if (newObject.TryGetComponent(out HighlightTrigger ht) && ht.enabled) {
                return;
            }

            if (!newObject.TryGetComponent(out HighlightEffect otherEffect)) {
                // Check if there's a parent highlight effect that includes this object
                HighlightEffect parentEffect = newObject.GetComponentInParent<HighlightEffect>();
                if (parentEffect != null && parentEffect.Includes(newObject)) {
                    currentEffect = parentEffect;
                    if (highlightOnHover) {
                        Highlight(true);
                    }
                    return;
                }
            }
            currentEffect = otherEffect != null ? otherEffect : baseEffect;
            baseEffect.enabled = currentEffect == baseEffect;
            currentEffect.SetTarget(currentObject);

            if (highlightOnHover) {
                Highlight(true);
            }
        }

        void UpdateHitPosition (Transform target, Vector3 positionWS, Vector3 normalWS) {
            if (currentEffect == null) return;
            Vector3 localPosition = target.InverseTransformPoint(positionWS);
            currentEffect.SetHitPosition(target, localPosition, Misc.vector3Zero, normalWS);

            if (InputProxy.GetMouseButtonDown(0) && OnObjectClicked != null) {
                OnObjectClicked(target.gameObject, positionWS, normalWS);
            }
        }

#if !(ENABLE_INPUT_SYSTEM && !ENABLE_LEGACY_INPUT_MANAGER)
        bool CanInteractAt (Vector2 screenPosition) {
            if (!respectUI) return true;
            EventSystem es = EventSystem.current;
            if (es == null) return true;
            if (Application.isMobilePlatform && InputProxy.touchCount > 0) {
                if (es.IsPointerOverGameObject(InputProxy.GetFingerIdFromTouch(0))) {
                    return false;
                }
                if (raycastSource == RayCastSource.CameraDirection) {
                    return !IsUIAtScreenPosition(es, screenPosition);
                }
                return true;
            }
            if (raycastSource == RayCastSource.MousePosition) {
                return !es.IsPointerOverGameObject(-1);
            }
            return !IsUIAtScreenPosition(es, screenPosition);
        }

        bool IsUIAtScreenPosition (EventSystem es, Vector2 screenPosition) {
            cachedRaycastResults.Clear();
            if (cachedPointerEventData == null || cachedEventSystem != es) {
                cachedPointerEventData = new PointerEventData(es);
                cachedEventSystem = es;
            }
            cachedPointerEventData.position = screenPosition;
            es.RaycastAll(cachedPointerEventData, cachedRaycastResults);
            int hitCount = cachedRaycastResults.Count;
            for (int k = 0; k < hitCount; k++) {
                RaycastResult rr = cachedRaycastResults[k];
                if (rr.module is UnityEngine.UI.GraphicRaycaster) {
                    return true;
                }
            }
            return false;
        }
#endif

        float GetBlockingDistance (Ray ray, float maxRayDistance) {
            if (blockingLayerMask == 0) return float.MaxValue;
            if (Physics.Raycast(ray, out blockingHit, maxRayDistance, blockingLayerMask)) {
                return blockingHit.distance + 0.01f;
            }
            return float.MaxValue;
        }

        void ToggleSelection (Transform t, bool forceSelection) {

            if (t == null) return;
            // We need a highlight effect on each selected object
            HighlightEffect hb = t.GetComponent<HighlightEffect>();
            if (hb == null) {
                HighlightEffect parentEffect = t.GetComponentInParent<HighlightEffect>();
                if (parentEffect != null && parentEffect.Includes(t)) {
                    hb = parentEffect;
                    if (hb.previousSettings == null) {
                        hb.previousSettings = ScriptableObject.CreateInstance<HighlightProfile>();
                    }
                    hb.previousSettings.Save(hb);
                }
                else {
                    hb = t.gameObject.AddComponent<HighlightEffect>();
                    hb.camerasLayerMask = baseEffect.camerasLayerMask;
                    hb.ignoreObjectVisibility = baseEffect.ignoreObjectVisibility;
                    hb.reflectionProbes = baseEffect.reflectionProbes;
                    hb.normalsOption = baseEffect.normalsOption;
                    hb.optimizeSkinnedMesh = baseEffect.optimizeSkinnedMesh;
                    hb.GPUInstancing = baseEffect.GPUInstancing;
                    
                    hb.previousSettings = ScriptableObject.CreateInstance<HighlightProfile>();
                    // copy default highlight effect settings from this manager into this highlight plus component
                    hb.previousSettings.Save(baseEffect);
                    hb.previousSettings.Load(hb);
                }
            }

            bool currentState = hb.isSelected;
            bool newState = forceSelection ? true : !currentState;
            if (newState == currentState) return;

            if (newState) {
                if (OnObjectSelected != null && !OnObjectSelected(t.gameObject)) return;
            }
            else {
                if (OnObjectUnSelected != null && !OnObjectUnSelected(t.gameObject)) return;
            }

            if (singleSelection) {
                internal_DeselectAll();
            }

            currentEffect = hb;
            currentEffect.isSelected = newState;
            baseEffect.enabled = false;

            if (currentEffect.isSelected) {
                if (currentEffect.previousSettings == null) {
                    currentEffect.previousSettings = ScriptableObject.CreateInstance<HighlightProfile>();
                }
                hb.previousSettings.Save(hb);

                if (!selectedObjects.Contains(currentEffect)) {
                    selectedObjects.Add(currentEffect);
                }
            }
            else {
                if (currentEffect.previousSettings != null) {
                    currentEffect.previousSettings.Load(hb);
                }
                if (selectedObjects.Contains(currentEffect)) {
                    selectedObjects.Remove(currentEffect);
                }
            }

            Highlight(newState);
        }

        void Highlight (bool state) {
            if (currentEffect == null) return;

            if (state) {
                if (!currentEffect.highlighted) {
                    if (OnObjectHighlightStart != null && currentEffect.target != null) {
                        if (!OnObjectHighlightStart(currentEffect.target.gameObject)) {
                            currentObject = null; // allows re-checking so it keeps checking with the event
                            return;
                        }
                    }
                }
            }
            else {
                if (currentEffect.highlighted) {
                    if (OnObjectHighlightEnd != null && currentEffect.target != null) {
                        OnObjectHighlightEnd(currentEffect.target.gameObject);
                    }
                }
            }
            if (selectOnClick || currentEffect.isSelected) {
                if (currentEffect.isSelected) {
                    if (state && selectedAndHighlightedProfile != null) {
                        selectedAndHighlightedProfile.Load(currentEffect);
                    }
                    else if (selectedProfile != null) {
                        selectedProfile.Load(currentEffect);
                    }
                    else {
                        currentEffect.previousSettings.Load(currentEffect);
                    }
                    if (currentEffect.highlighted && currentEffect.fading != HighlightEffect.FadingState.FadingOut) {
                        currentEffect.UpdateMaterialProperties();
                    }
                    else {
                        currentEffect.SetHighlighted(true);
                    }
                    return;
                }
                else if (!highlightOnHover) {
                    currentEffect.SetHighlighted(false);
                    return;
                }
            }
            currentEffect.SetHighlighted(state);
        }

        public static Camera GetCamera () {
            Camera raycastCamera = Camera.main;
            if (raycastCamera == null) {
                raycastCamera = Misc.FindObjectOfType<Camera>();
            }
            return raycastCamera;
        }

        void internal_DeselectAll () {
            int count = selectedObjects.Count;
            for (int k = 0; k < count; k++) {
                HighlightEffect hb = selectedObjects[k];
                if (hb != null && hb.gameObject != null) {
                    if (OnObjectUnSelected != null) {
                        if (!OnObjectUnSelected(hb.gameObject)) continue;
                    }
                    hb.RestorePreviousHighlightEffectSettings();
                    hb.isSelected = false;
                    hb.SetHighlighted(false);
                }
            }
            selectedObjects.Clear();
        }

        /// <summary>
        /// Deselects any selected object in the scene
        /// </summary>
        public static void DeselectAll () {
            if (instance != null) {
                _instance.internal_DeselectAll();
                return;
            }

            foreach (HighlightEffect hb in selectedObjects) {
                if (hb != null && hb.gameObject != null) {
                    hb.RestorePreviousHighlightEffectSettings();
                    hb.isSelected = false;
                    hb.SetHighlighted(false);
                }
            }
            selectedObjects.Clear();
        }

        /// <summary>
        /// Unselects all objects in the scene
        /// </summary>
        public void UnselectObjects () {
            DeselectAll();
        }


        /// <summary>
        /// Manually causes highlight manager to select an object
        /// </summary>
        public void SelectObject (Transform t) {
            ToggleSelection(t, true);
        }

        /// <summary>
        /// Manually causes highlight manager to select multiple objects
        /// </summary>
        /// <param name="objects">Array of objects to select</param>
        public void SelectObjects (Transform[] objects) {
            foreach (var obj in objects) {
                SelectObject(obj);
            }
        }

        public void SelectObjects (List<Transform> objects) {
            foreach (var obj in objects) {
                SelectObject(obj);
            }
        }

        /// <summary>
        /// Manually causes highlight manager to toggle selection on an object
        /// </summary>
        public void ToggleObject (Transform t) {
            ToggleSelection(t, false);
        }

        /// <summary>
        /// Manually causes highlight manager to unselect an object
        /// </summary>
        public void UnselectObject (Transform t) {
            if (t == null) return;
            HighlightEffect hb = t.GetComponent<HighlightEffect>();
            if (hb == null) return;

            if (hb.isSelected) {
                ToggleSelection(t, false);
            }
        }


    }

}