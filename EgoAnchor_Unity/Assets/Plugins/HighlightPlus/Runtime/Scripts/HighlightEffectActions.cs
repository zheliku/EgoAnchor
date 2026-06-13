using System;
using UnityEngine;

namespace HighlightPlus {

    public enum HitFxMode {
        Overlay = 0,
        InnerGlow = 1,
        LocalHit = 2
    }

    public enum HitFXTriggerMode {
        Scripting = 0,
        WhenHighlighted = 10
    }

    public partial class HighlightEffect : MonoBehaviour {

        public static bool useUnscaledTime;

        [NonSerialized]
        public Transform currentHitTarget;
        [NonSerialized]
        public Vector3 currentHitLocalPosition;
        [NonSerialized]
        public Vector3 currentHitNormal;

        public static float GetTime () {
            return useUnscaledTime ? Time.unscaledTime : Time.time;
        }

        #region Hit FX handling

        [Range(0, 1)] public float hitFxInitialIntensity;
        public HitFxMode hitFxMode = HitFxMode.Overlay;
        public HitFXTriggerMode hitFXTriggerMode = HitFXTriggerMode.Scripting;
        public float hitFxFadeOutDuration = 0.25f;
        [ColorUsage(true, true)] public Color hitFxColor = Color.white;
        public float hitFxRadius = 0.5f;

        float hitInitialIntensity;
        float hitStartTime;
        float hitFadeOutDuration;
        Color hitColor;
        bool hitActive;
        Vector3 hitPosition;
        float hitRadius;

        /// <summary>
        /// Performs a hit effect using default values
        /// </summary>
        public void HitFX () {
            HitFX(hitFxColor, hitFxFadeOutDuration, hitFxInitialIntensity);
        }

        /// <summary>
        /// Performs a hit effect localized at hit position and radius with default values
        /// </summary>
        public void HitFX (Vector3 position) {
            HitFX(hitFxColor, hitFxFadeOutDuration, hitFxInitialIntensity, position, hitFxRadius);

        }

        /// <summary>
        /// Performs a hit effect using desired color, fade out duration and optionally initial intensity (0-1)
        /// </summary>
        public void HitFX (Color color, float fadeOutDuration, float initialIntensity = 1f) {
            hitInitialIntensity = initialIntensity;
            hitFadeOutDuration = fadeOutDuration;
            hitColor = color;
            hitStartTime = GetTime();
            hitActive = true;
            if (overlay == 0) {
                UpdateMaterialProperties();
            }
        }


        /// <summary>
        /// Performs a hit effect using desired color, fade out duration, initial intensity (0-1), hit position and radius of effect
        /// </summary>
        public void HitFX (Color color, float fadeOutDuration, float initialIntensity, Vector3 position, float radius) {
            hitInitialIntensity = initialIntensity;
            hitFadeOutDuration = fadeOutDuration;
            hitColor = color;
            hitStartTime = GetTime();
            hitActive = true;
            hitPosition = position;
            hitRadius = radius;
            if (overlay == 0) {
                UpdateMaterialProperties();
            }
        }

        #endregion

        /// <summary>
        /// Initiates the target FX on demand using predefined configuration (see targetFX... properties)
        /// </summary>
        public void TargetFX () {
            targetFXStartTime = GetTime();
            if (!_highlighted) {
                highlighted = true;
            }
            if (!targetFX) {
                targetFX = true;
                UpdateMaterialProperties();
            }
        }


        /// <summary>
        /// Initiates the icon FX on demand using predefined configuration (see iconFX... properties)
        /// </summary>
        public void IconFX () {
            iconFXStartTime = GetTime();
            if (!_highlighted) {
                highlighted = true;
            }
            if (!iconFX) {
                iconFX = true;
                UpdateMaterialProperties();
            }
        }

        #region Label handling

        [NonSerialized]
        public HighlightLabel label;

        void ReleaseLabel () {
            label?.Release();
            label = null;
        }


        void CheckLabel (bool disabling) {
            // Enable label
            bool shouldShowLabel = labelMode == LabelMode.Always || (_highlighted && labelMode == LabelMode.WhenHighlighted) || (labelShowInEditorMode && !Application.isPlaying);
            shouldShowLabel = shouldShowLabel && !disabling && rmsCount != 0;
            if (shouldShowLabel && labelEnabled) {
                // Lazy initialization of label prefab
                if (label == null && labelPrefab != null) {
                    label = HighlightLabelPoolManager.GetLabelInstance(labelPrefab);
                }
                if (label != null) {
                    label.textLabel = labelText;
                    label.textColor = labelColor;
                    label.textSize = labelTextSize;
                    label.width = labelLineLength;
                    label.labelAlignment = labelAlignment;
                    label.labelRelativeAlignment = labelRelativeAlignment;
                    label.labelAlignmentTransform = labelAlignmentTransform;
                    label.labelMaxDistance = labelMaxDistance;
                    label.labelFadeStartDistance = labelFadeStartDistance;
                    label.labelScaleByDistance = labelScaleByDistance;
                    label.labelScaleMin = labelScaleMin;
                    label.labelScaleMax = labelScaleMax;
                    if (!label.isVisible) {
                        label.SetPosition(labelTarget == null ? target : labelTarget, Misc.vector3Zero, new Vector3(0, labelVerticalOffset, 0), labelViewportOffset);
                        label.Show();
                    }
                }
            }
            else if (!labelEnabled) {
                ReleaseLabel();
#if UNITY_EDITOR
                if (!Application.isPlaying) {
                    HighlightLabelPoolManager.DestroySceneLabels();
                }
#endif
            }
            else if (label != null) {
                label.Hide();
            }
        }

        public void SetHitPosition (Transform target, Vector3 localPosition, Vector3 offsetWS, Vector3 normalWS) {
            if (labelEnabled && labelFollowCursor && label != null) {
                label.SetPosition(target, localPosition, offsetWS);
            }
            currentHitTarget = target;
            currentHitLocalPosition = localPosition;
            currentHitNormal = normalWS;
        }

        /// <summary>
        /// Recreates label
        /// </summary>
        public void RefreshLabel () {
            HighlightLabelPoolManager.DestroySceneLabels();
            CheckLabel(false);
        }

        #endregion


    }
}