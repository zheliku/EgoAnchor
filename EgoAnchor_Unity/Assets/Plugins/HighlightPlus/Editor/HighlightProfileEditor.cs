using UnityEditor;
using UnityEngine;

namespace HighlightPlus {

    [CustomEditor(typeof(HighlightProfile))]
    [CanEditMultipleObjects]
    public class HighlightProfileEditor : UnityEditor.Editor {

        SerializedProperty effectGroup, effectGroupLayer, effectNameFilter, effectNameUseRegEx, excludeObjectsWithHighlightEffect, combineMeshes, alphaCutOff, alphaCutOffTextureName, cullBackFaces;
        SerializedProperty overlay, overlayMode, overlayColor, overlayAnimationSpeed, overlayMinIntensity, overlayTexture, overlayTextureScale, overlayTextureScrolling, overlayTextureUVSpace, overlayBlending, overlayVisibility;
        SerializedProperty overlayPattern, overlayPatternScrolling, overlayPatternScale, overlayPatternSize, overlayPatternSoftness, overlayPatternRotation;
        SerializedProperty fadeInDuration, fadeOutDuration, constantWidth, normalsOption, minimumWidth, extraCoveragePixels;
        SerializedProperty outline, outlineColor, outlineColorStyle, outlineGradient, outlineGradientInLocalSpace, outlineGradientKnee, outlineGradientPower;
        SerializedProperty outlineWidth, outlineBlurPasses, outlineQuality, outlineEdgeMode, outlineEdgeThreshold, outlineSharpness, padding;
        SerializedProperty outlineDownsampling, outlineVisibility, outlineIndependent, outlineContourStyle, outlineMaskMode;
        SerializedProperty outlineStylized, outlinePattern, outlinePatternScale, outlinePatternThreshold, outlinePatternDistortionAmount, outlinePatternStopMotionScale;
        SerializedProperty outlinePatternDistortionTexture;
        SerializedProperty outlineDashed, outlineDashWidth, outlineDashGap, outlineDashSpeed;
        SerializedProperty outlineDistanceScaleBias;
        SerializedProperty outlinePixelation;
        SerializedProperty glow, glowWidth, glowQuality, glowBlurMethod, glowDownsampling, glowHQColor, glowDithering, glowDitheringStyle, glowMagicNumber1, glowMagicNumber2, glowAnimationSpeed, glowDistanceScaleBias;
        SerializedProperty glowBlendPasses, glowVisibility, glowBlendMode, glowPasses, glowMaskMode, glowHighPrecision;
        SerializedProperty glowPixelation;
        SerializedProperty innerGlow, innerGlowWidth, innerGlowColor, innerGlowBlendMode, innerGlowVisibility, innerGlowPower;
        SerializedProperty focus, focusColor, focusBlur, focusBlurDownsampling, focusDesaturation;
        SerializedProperty targetFX, targetFXTexture, targetFXColor, targetFXRotationSpeed, targetFXInitialScale, targetFXEndScale, targetFXScaleToRenderBounds, targetFXUseEnclosingBounds, targetFXSquare, targetFXOffset;
        SerializedProperty targetFXAlignToGround, targetFXFadePower, targetFXGroundMaxDistance, targetFXGroundLayerMask, targetFXTransitionDuration, targetFXStayDuration, targetFXVisibility;
        SerializedProperty targetFXStyle, targetFXFrameWidth, targetFXCornerLength, targetFXFrameMinOpacity, targetFXGroundMinAltitude;
        SerializedProperty targetFXRotationAngle, targetFxCenterOnHitPosition, targetFxAlignToNormal;
        SerializedProperty iconFX, iconFXAssetType, iconFXPrefab, iconFXMesh, iconFXLightColor, iconFXDarkColor, iconFXRotationSpeed, iconFXAnimationOption, iconFXAnimationAmount, iconFXAnimationSpeed, iconFXScale, iconFXScaleToRenderBounds, iconFXOffset, iconFXTransitionDuration, iconFXStayDuration;
        SerializedProperty seeThrough, seeThroughOccluderMask, seeThroughOccluderMaskAccurate, seeThroughOccluderThreshold, seeThroughOccluderCheckInterval, seeThroughOccluderCheckIndividualObjects, seeThroughDepthOffset, seeThroughMaxDepth, seeThroughFadeRange;
        SerializedProperty seeThroughIntensity, seeThroughTintAlpha, seeThroughTintColor, seeThroughNoise, seeThroughBorder, seeThroughBorderWidth, seeThroughBorderColor, seeThroughOrdered, seeThroughBorderOnly, seeThroughTexture, seeThroughTextureUVSpace, seeThroughTextureScale, seeThroughChildrenSortingMode;
        SerializedProperty hitFxInitialIntensity, hitFxMode, hitFxFadeOutDuration, hitFxColor, hitFxRadius, hitFXTriggerMode;
        SerializedProperty cameraDistanceFade, cameraDistanceFadeNear, cameraDistanceFadeFar;
        SerializedProperty labelEnabled, labelText, labelColor, labelPrefab, labelVerticalOffset, labelViewportOffset, labelLineLength, labelFollowCursor;
        SerializedProperty labelTextSize, labelMode, labelAlignment, labelShowInEditorMode, labelMaxDistance, labelFadeStartDistance, labelScaleByDistance, labelScaleMin, labelScaleMax;
        SerializedProperty labelRelativeAlignment, labelAlignmentTransform;

        static GUIStyle sectionHeaderStyle;
        static GUIStyle sectionHeaderStatusStyle;
        static readonly GUIContent sectionHeaderActiveLabel = new GUIContent("\u2713");
        const string HP_PREF_PREFIX = "HighlightPlus.HPProfileEditor.";
        const string HP_HIGHLIGHT_OPTIONS = HP_PREF_PREFIX + "HighlightOptions";
        const string HP_OUTLINE = HP_PREF_PREFIX + "Outline";
        const string HP_GLOW = HP_PREF_PREFIX + "Glow";
        const string HP_INNER_GLOW = HP_PREF_PREFIX + "InnerGlow";
        const string HP_FOCUS = HP_PREF_PREFIX + "Focus";
        const string HP_OVERLAY = HP_PREF_PREFIX + "Overlay";
        const string HP_TARGET = HP_PREF_PREFIX + "Target";
        const string HP_ICON = HP_PREF_PREFIX + "Icon";
        const string HP_LABEL = HP_PREF_PREFIX + "Label";
        const string HP_SEE_THROUGH = HP_PREF_PREFIX + "SeeThrough";
        const string HP_HIT_FX = HP_PREF_PREFIX + "HitFX";

        bool expandHighlightOptions, expandOutline, expandGlow, expandInnerGlow, expandFocus, expandOverlay, expandTarget, expandIcon, expandLabel, expandSeeThrough, expandHitFX;

        void OnEnable () {
            expandHighlightOptions = EditorPrefs.GetBool(HP_HIGHLIGHT_OPTIONS, true);
            expandOutline = EditorPrefs.GetBool(HP_OUTLINE, true);
            expandGlow = EditorPrefs.GetBool(HP_GLOW, true);
            expandInnerGlow = EditorPrefs.GetBool(HP_INNER_GLOW, true);
            expandFocus = EditorPrefs.GetBool(HP_FOCUS, true);
            expandOverlay = EditorPrefs.GetBool(HP_OVERLAY, true);
            expandTarget = EditorPrefs.GetBool(HP_TARGET, true);
            expandIcon = EditorPrefs.GetBool(HP_ICON, true);
            expandLabel = EditorPrefs.GetBool(HP_LABEL, true);
            expandSeeThrough = EditorPrefs.GetBool(HP_SEE_THROUGH, true);
            expandHitFX = EditorPrefs.GetBool(HP_HIT_FX, true);

            effectGroup = serializedObject.FindProperty("effectGroup");
            effectGroupLayer = serializedObject.FindProperty("effectGroupLayer");
            effectNameFilter = serializedObject.FindProperty("effectNameFilter");
            effectNameUseRegEx = serializedObject.FindProperty("effectNameUseRegEx");
            excludeObjectsWithHighlightEffect = serializedObject.FindProperty("excludeObjectsWithHighlightEffect");
            combineMeshes = serializedObject.FindProperty("combineMeshes");
            alphaCutOff = serializedObject.FindProperty("alphaCutOff");
            alphaCutOffTextureName = serializedObject.FindProperty("alphaCutOffTextureName");
            cullBackFaces = serializedObject.FindProperty("cullBackFaces");
            normalsOption = serializedObject.FindProperty("normalsOption");
            fadeInDuration = serializedObject.FindProperty("fadeInDuration");
            fadeOutDuration = serializedObject.FindProperty("fadeOutDuration");
            constantWidth = serializedObject.FindProperty("constantWidth");
            extraCoveragePixels = serializedObject.FindProperty("extraCoveragePixels");
            minimumWidth = serializedObject.FindProperty("minimumWidth");
            padding = serializedObject.FindProperty("padding");

            overlay = serializedObject.FindProperty("overlay");
            overlayMode = serializedObject.FindProperty("overlayMode");
            overlayColor = serializedObject.FindProperty("overlayColor");
            overlayAnimationSpeed = serializedObject.FindProperty("overlayAnimationSpeed");
            overlayMinIntensity = serializedObject.FindProperty("overlayMinIntensity");
            overlayBlending = serializedObject.FindProperty("overlayBlending");
            overlayVisibility = serializedObject.FindProperty("overlayVisibility");
            overlayTexture = serializedObject.FindProperty("overlayTexture");
            overlayTextureUVSpace = serializedObject.FindProperty("overlayTextureUVSpace");
            overlayTextureScale = serializedObject.FindProperty("overlayTextureScale");
            overlayTextureScrolling = serializedObject.FindProperty("overlayTextureScrolling");
            overlayPattern = serializedObject.FindProperty("overlayPattern");
            overlayPatternScrolling = serializedObject.FindProperty("overlayPatternScrolling");
            overlayPatternScale = serializedObject.FindProperty("overlayPatternScale");
            overlayPatternSize = serializedObject.FindProperty("overlayPatternSize");
            overlayPatternSoftness = serializedObject.FindProperty("overlayPatternSoftness");
            overlayPatternRotation = serializedObject.FindProperty("overlayPatternRotation");

            outline = serializedObject.FindProperty("outline");
            outlineColor = serializedObject.FindProperty("outlineColor");
            outlineColorStyle = serializedObject.FindProperty("outlineColorStyle");
            outlineGradient = serializedObject.FindProperty("outlineGradient");
            outlineGradientInLocalSpace = serializedObject.FindProperty("outlineGradientInLocalSpace");
            outlineGradientKnee = serializedObject.FindProperty("outlineGradientKnee");
            outlineGradientPower = serializedObject.FindProperty("outlineGradientPower");
            outlineWidth = serializedObject.FindProperty("outlineWidth");
            outlineBlurPasses = serializedObject.FindProperty("outlineBlurPasses");
            outlineQuality = serializedObject.FindProperty("outlineQuality");
            outlineEdgeMode = serializedObject.FindProperty("outlineEdgeMode");
            outlineEdgeThreshold = serializedObject.FindProperty("outlineEdgeThreshold");
            outlineSharpness = serializedObject.FindProperty("outlineSharpness");
            outlineDownsampling = serializedObject.FindProperty("outlineDownsampling");
            outlineVisibility = serializedObject.FindProperty("outlineVisibility");
            outlineIndependent = serializedObject.FindProperty("outlineIndependent");
            outlineContourStyle = serializedObject.FindProperty("outlineContourStyle");
            outlineMaskMode = serializedObject.FindProperty("outlineMaskMode");
            outlineStylized = serializedObject.FindProperty("outlineStylized");
            outlinePattern = serializedObject.FindProperty("outlinePattern");
            outlinePatternScale = serializedObject.FindProperty("outlinePatternScale");
            outlinePatternThreshold = serializedObject.FindProperty("outlinePatternThreshold");
            outlinePatternDistortionAmount = serializedObject.FindProperty("outlinePatternDistortionAmount");
            outlinePatternStopMotionScale = serializedObject.FindProperty("outlinePatternStopMotionScale");
            outlinePatternDistortionTexture = serializedObject.FindProperty("outlinePatternDistortionTexture");
            outlineDashed = serializedObject.FindProperty("outlineDashed");
            outlineDashWidth = serializedObject.FindProperty("outlineDashWidth");
            outlineDashGap = serializedObject.FindProperty("outlineDashGap");
            outlineDashSpeed = serializedObject.FindProperty("outlineDashSpeed");
            outlineDistanceScaleBias = serializedObject.FindProperty("outlineDistanceScaleBias");
            outlinePixelation = serializedObject.FindProperty("outlinePixelation");

            glow = serializedObject.FindProperty("glow");
            glowWidth = serializedObject.FindProperty("glowWidth");
            glowQuality = serializedObject.FindProperty("glowQuality");
            glowHighPrecision = serializedObject.FindProperty("glowHighPrecision");
            glowBlurMethod = serializedObject.FindProperty("glowBlurMethod");
            glowDownsampling = serializedObject.FindProperty("glowDownsampling");
            glowHQColor = serializedObject.FindProperty("glowHQColor");
            glowAnimationSpeed = serializedObject.FindProperty("glowAnimationSpeed");
            glowDistanceScaleBias = serializedObject.FindProperty("glowDistanceScaleBias");
            glowDithering = serializedObject.FindProperty("glowDithering");
            glowDitheringStyle = serializedObject.FindProperty("glowDitheringStyle");
            glowMagicNumber1 = serializedObject.FindProperty("glowMagicNumber1");
            glowMagicNumber2 = serializedObject.FindProperty("glowMagicNumber2");
            glowBlendPasses = serializedObject.FindProperty("glowBlendPasses");
            glowVisibility = serializedObject.FindProperty("glowVisibility");
            glowBlendMode = serializedObject.FindProperty("glowBlendMode");
            glowPasses = serializedObject.FindProperty("glowPasses");
            glowMaskMode = serializedObject.FindProperty("glowMaskMode");
            glowPixelation = serializedObject.FindProperty("glowPixelation");

            innerGlow = serializedObject.FindProperty("innerGlow");
            innerGlowColor = serializedObject.FindProperty("innerGlowColor");
            innerGlowWidth = serializedObject.FindProperty("innerGlowWidth");
            innerGlowPower = serializedObject.FindProperty("innerGlowPower");
            innerGlowBlendMode = serializedObject.FindProperty("innerGlowBlendMode");
            innerGlowVisibility = serializedObject.FindProperty("innerGlowVisibility");

            focus = serializedObject.FindProperty("focus");
            focusColor = serializedObject.FindProperty("focusColor");
            focusBlur = serializedObject.FindProperty("focusBlur");
            focusBlurDownsampling = serializedObject.FindProperty("focusBlurDownsampling");
            focusDesaturation = serializedObject.FindProperty("focusDesaturation");

            targetFX = serializedObject.FindProperty("targetFX");
            targetFXTexture = serializedObject.FindProperty("targetFXTexture");
            targetFXRotationSpeed = serializedObject.FindProperty("targetFXRotationSpeed");
            targetFXInitialScale = serializedObject.FindProperty("targetFXInitialScale");
            targetFXEndScale = serializedObject.FindProperty("targetFXEndScale");
            targetFXScaleToRenderBounds = serializedObject.FindProperty("targetFXScaleToRenderBounds");
            targetFXUseEnclosingBounds = serializedObject.FindProperty("targetFXUseEnclosingBounds");
            targetFXSquare = serializedObject.FindProperty("targetFXSquare");
            targetFXOffset = serializedObject.FindProperty("targetFXOffset");
            targetFxCenterOnHitPosition = serializedObject.FindProperty("targetFxCenterOnHitPosition");
            targetFxAlignToNormal = serializedObject.FindProperty("targetFxAlignToNormal");
            targetFXAlignToGround = serializedObject.FindProperty("targetFXAlignToGround");
            targetFXFadePower = serializedObject.FindProperty("targetFXFadePower");
            targetFXColor = serializedObject.FindProperty("targetFXColor");
            targetFXTransitionDuration = serializedObject.FindProperty("targetFXTransitionDuration");
            targetFXStayDuration = serializedObject.FindProperty("targetFXStayDuration");
            targetFXVisibility = serializedObject.FindProperty("targetFXVisibility");
            targetFXStyle = serializedObject.FindProperty("targetFXStyle");
            targetFXFrameWidth = serializedObject.FindProperty("targetFXFrameWidth");
            targetFXCornerLength = serializedObject.FindProperty("targetFXCornerLength");
            targetFXFrameMinOpacity = serializedObject.FindProperty("targetFXFrameMinOpacity");
            targetFXRotationAngle = serializedObject.FindProperty("targetFXRotationAngle");
            targetFXGroundMinAltitude = serializedObject.FindProperty("targetFXGroundMinAltitude");
            targetFXGroundMaxDistance = serializedObject.FindProperty("targetFXGroundMaxDistance");
            targetFXGroundLayerMask = serializedObject.FindProperty("targetFXGroundLayerMask");

            iconFX = serializedObject.FindProperty("iconFX");
            iconFXAssetType = serializedObject.FindProperty("iconFXAssetType");
            iconFXPrefab = serializedObject.FindProperty("iconFXPrefab");
            iconFXMesh = serializedObject.FindProperty("iconFXMesh");
            iconFXLightColor = serializedObject.FindProperty("iconFXLightColor");
            iconFXDarkColor = serializedObject.FindProperty("iconFXDarkColor");
            iconFXRotationSpeed = serializedObject.FindProperty("iconFXRotationSpeed");
            iconFXAnimationOption = serializedObject.FindProperty("iconFXAnimationOption");
            iconFXAnimationAmount = serializedObject.FindProperty("iconFXAnimationAmount");
            iconFXAnimationSpeed = serializedObject.FindProperty("iconFXAnimationSpeed");
            iconFXScale = serializedObject.FindProperty("iconFXScale");
            iconFXScaleToRenderBounds = serializedObject.FindProperty("iconFXScaleToRenderBounds");
            iconFXOffset = serializedObject.FindProperty("iconFXOffset");
            iconFXTransitionDuration = serializedObject.FindProperty("iconFXTransitionDuration");
            iconFXStayDuration = serializedObject.FindProperty("iconFXStayDuration");

            seeThrough = serializedObject.FindProperty("seeThrough");
            seeThroughOccluderMask = serializedObject.FindProperty("seeThroughOccluderMask");
            seeThroughOccluderMaskAccurate = serializedObject.FindProperty("seeThroughOccluderMaskAccurate");
            seeThroughOccluderThreshold = serializedObject.FindProperty("seeThroughOccluderThreshold");
            seeThroughOccluderCheckInterval = serializedObject.FindProperty("seeThroughOccluderCheckInterval");
            seeThroughOccluderCheckIndividualObjects = serializedObject.FindProperty("seeThroughOccluderCheckIndividualObjects");
            seeThroughDepthOffset = serializedObject.FindProperty("seeThroughDepthOffset");
            seeThroughMaxDepth = serializedObject.FindProperty("seeThroughMaxDepth");
            seeThroughFadeRange = serializedObject.FindProperty("seeThroughFadeRange");
            seeThroughIntensity = serializedObject.FindProperty("seeThroughIntensity");
            seeThroughTintAlpha = serializedObject.FindProperty("seeThroughTintAlpha");
            seeThroughTintColor = serializedObject.FindProperty("seeThroughTintColor");
            seeThroughNoise = serializedObject.FindProperty("seeThroughNoise");
            seeThroughBorder = serializedObject.FindProperty("seeThroughBorder");
            seeThroughBorderWidth = serializedObject.FindProperty("seeThroughBorderWidth");
            seeThroughBorderColor = serializedObject.FindProperty("seeThroughBorderColor");
            seeThroughBorderOnly = serializedObject.FindProperty("seeThroughBorderOnly");
            seeThroughOrdered = serializedObject.FindProperty("seeThroughOrdered");
            seeThroughTexture = serializedObject.FindProperty("seeThroughTexture");
            seeThroughTextureScale = serializedObject.FindProperty("seeThroughTextureScale");
            seeThroughTextureUVSpace = serializedObject.FindProperty("seeThroughTextureUVSpace");
            seeThroughChildrenSortingMode = serializedObject.FindProperty("seeThroughChildrenSortingMode");

            hitFxInitialIntensity = serializedObject.FindProperty("hitFxInitialIntensity");
            hitFxMode = serializedObject.FindProperty("hitFxMode");
            hitFxFadeOutDuration = serializedObject.FindProperty("hitFxFadeOutDuration");
            hitFxColor = serializedObject.FindProperty("hitFxColor");
            hitFxRadius = serializedObject.FindProperty("hitFxRadius");
            hitFXTriggerMode = serializedObject.FindProperty("hitFXTriggerMode");

            cameraDistanceFade = serializedObject.FindProperty("cameraDistanceFade");
            cameraDistanceFadeNear = serializedObject.FindProperty("cameraDistanceFadeNear");
            cameraDistanceFadeFar = serializedObject.FindProperty("cameraDistanceFadeFar");

            labelEnabled = serializedObject.FindProperty("labelEnabled");
            labelText = serializedObject.FindProperty("labelText");
            labelTextSize = serializedObject.FindProperty("labelTextSize");
            labelColor = serializedObject.FindProperty("labelColor");
            labelPrefab = serializedObject.FindProperty("labelPrefab");
            labelVerticalOffset = serializedObject.FindProperty("labelVerticalOffset");
            labelViewportOffset = serializedObject.FindProperty("labelViewportOffset");
            labelLineLength = serializedObject.FindProperty("labelLineLength");
            labelFollowCursor = serializedObject.FindProperty("labelFollowCursor");
            labelMode = serializedObject.FindProperty("labelMode");
            labelShowInEditorMode = serializedObject.FindProperty("labelShowInEditorMode");
            labelAlignment = serializedObject.FindProperty("labelAlignment");
            labelRelativeAlignment = serializedObject.FindProperty("labelRelativeAlignment");
            labelAlignmentTransform = serializedObject.FindProperty("labelAlignmentTransform");
            
            labelMaxDistance = serializedObject.FindProperty("labelMaxDistance");
            labelFadeStartDistance = serializedObject.FindProperty("labelFadeStartDistance");
            labelScaleByDistance = serializedObject.FindProperty("labelScaleByDistance");
            labelScaleMin = serializedObject.FindProperty("labelScaleMin");
            labelScaleMax = serializedObject.FindProperty("labelScaleMax");
        }

        void OnDisable() {
            EditorPrefs.SetBool(HP_HIGHLIGHT_OPTIONS, expandHighlightOptions);
            EditorPrefs.SetBool(HP_OUTLINE, expandOutline);
            EditorPrefs.SetBool(HP_GLOW, expandGlow);
            EditorPrefs.SetBool(HP_INNER_GLOW, expandInnerGlow);
            EditorPrefs.SetBool(HP_FOCUS, expandFocus);
            EditorPrefs.SetBool(HP_OVERLAY, expandOverlay);
            EditorPrefs.SetBool(HP_TARGET, expandTarget);
            EditorPrefs.SetBool(HP_ICON, expandIcon);
            EditorPrefs.SetBool(HP_LABEL, expandLabel);
            EditorPrefs.SetBool(HP_SEE_THROUGH, expandSeeThrough);
            EditorPrefs.SetBool(HP_HIT_FX, expandHitFX);
        }

        bool DrawSectionHeader(string title, string prefKey, bool expanded, bool isActive = false) {
            if (sectionHeaderStyle == null) {
                sectionHeaderStyle = new GUIStyle("ShurikenModuleTitle") {
                    fontStyle = FontStyle.Bold,
                    fixedHeight = 22f,
                    contentOffset = new Vector2(20f, -2f)
                };
            }
            if (sectionHeaderStatusStyle == null) {
                sectionHeaderStatusStyle = new GUIStyle(EditorStyles.miniLabel) {
                    alignment = TextAnchor.MiddleRight,
                    fontStyle = FontStyle.Bold
                };
                sectionHeaderStatusStyle.normal.textColor = new Color(0.2f, 0.8f, 0.2f);
            }

            Rect rect = GUILayoutUtility.GetRect(16f, 22f, sectionHeaderStyle);
            GUI.Box(rect, title, sectionHeaderStyle);

            Rect toggleRect = new Rect(rect.x + 4f, rect.y + 2f, 13f, 13f);
            if (Event.current.type == EventType.Repaint) {
                EditorStyles.foldout.Draw(toggleRect, false, false, expanded, false);
            }

            if (isActive) {
                Rect statusRect = new Rect(rect.xMax - 26f, rect.y - 2f, 22f, rect.height);
                GUI.Label(statusRect, sectionHeaderActiveLabel, sectionHeaderStatusStyle);
            }

            if (Event.current.type == EventType.MouseDown && rect.Contains(Event.current.mousePosition)) {
                expanded = !expanded;
                EditorPrefs.SetBool(prefKey, expanded);
                Event.current.Use();
            }

            return expanded;
        }

        public override void OnInspectorGUI () {

            serializedObject.Update();

            EditorGUILayout.Separator();
            expandHighlightOptions = DrawSectionHeader("Highlight Options", HP_HIGHLIGHT_OPTIONS, expandHighlightOptions);
            if (expandHighlightOptions) {
                EditorGUI.indentLevel++;
                EditorGUILayout.PropertyField(effectGroup, new GUIContent("Include"));
                if (effectGroup.intValue == (int)TargetOptions.LayerInScene || effectGroup.intValue == (int)TargetOptions.LayerInChildren) {
                    EditorGUI.indentLevel++;
                    EditorGUILayout.PropertyField(effectGroupLayer, new GUIContent("Layer"));
                    EditorGUI.indentLevel--;
                }
                if (effectGroup.intValue != (int)TargetOptions.OnlyThisObject && effectGroup.intValue != (int)TargetOptions.Scripting) {
                    EditorGUI.indentLevel++;
                    EditorGUILayout.PropertyField(effectNameFilter, new GUIContent("Object Name Filter"));
                    EditorGUILayout.PropertyField(effectNameUseRegEx, new GUIContent("Use Regular Expressions"));
                    EditorGUILayout.PropertyField(excludeObjectsWithHighlightEffect, new GUIContent("Exclude Highlight Effect Objects", "If enabled, objects that already have a Highlight Effect component are excluded from this include list."));
                    EditorGUILayout.PropertyField(combineMeshes);
                    EditorGUI.indentLevel--;
                }
                EditorGUILayout.PropertyField(alphaCutOff);
                if (alphaCutOff.floatValue > 0f) {
                    EditorGUI.indentLevel++;
                    EditorGUILayout.PropertyField(alphaCutOffTextureName, new GUIContent("Custom Texture Name"));
                    EditorGUI.indentLevel--;
                }
                EditorGUILayout.PropertyField(padding, new GUIContent("Padding"));
                EditorGUILayout.PropertyField(cullBackFaces);
                EditorGUILayout.PropertyField(normalsOption);
                EditorGUILayout.PropertyField(fadeInDuration);
                EditorGUILayout.PropertyField(fadeOutDuration);
                EditorGUILayout.PropertyField(cameraDistanceFade);
                if (cameraDistanceFade.boolValue) {
                    EditorGUI.indentLevel++;
                    EditorGUILayout.PropertyField(cameraDistanceFadeNear, new GUIContent("Near Distance"));
                    EditorGUILayout.PropertyField(cameraDistanceFadeFar, new GUIContent("Far Distance"));
                    EditorGUI.indentLevel--;
                }
                EditorGUILayout.PropertyField(constantWidth);
                if (!constantWidth.boolValue) {
                    EditorGUI.indentLevel++;
                    EditorGUILayout.PropertyField(minimumWidth);
                    EditorGUI.indentLevel--;
                }
                EditorGUILayout.PropertyField(outlineIndependent, new GUIContent("Independent", "Do not combine outline with other highlighted objects."));
                EditorGUI.indentLevel--;
            }

            EditorGUILayout.Separator();

            expandOutline = DrawSectionHeader("Outline", HP_OUTLINE, expandOutline, outline.floatValue > 0);
            if (expandOutline) {
                EditorGUI.indentLevel++;
                EditorGUILayout.PropertyField(outline, new GUIContent("Intensity"));
                if (outline.floatValue > 0) {
                HighlightEffectEditor.QualityPropertyField(outlineQuality);
                if (outlineQuality.intValue == (int)QualityLevel.Highest) {
                    EditorGUILayout.PropertyField(outlineEdgeMode, new GUIContent("Edges"));
                    if (outlineEdgeMode.intValue == (int)OutlineEdgeMode.Any) {
                        EditorGUILayout.PropertyField(outlineEdgeThreshold, new GUIContent("Edge Detection Threshold"));
                    }
                    EditorGUILayout.PropertyField(outlineContourStyle, new GUIContent("Contour Style"));
                    EditorGUILayout.PropertyField(outlineWidth, new GUIContent("Width"));
                    EditorGUILayout.PropertyField(outlineBlurPasses, new GUIContent("Blur Passes"));
                    EditorGUILayout.PropertyField(outlineSharpness, new GUIContent("Sharpness"));
                    EditorGUILayout.PropertyField(outlineColorStyle, new GUIContent("Color Style"));
                    switch ((ColorStyle)outlineColorStyle.intValue) {
                        case ColorStyle.SingleColor:
                            EditorGUILayout.PropertyField(outlineColor, new GUIContent("Color"));
                            break;
                        case ColorStyle.Gradient:
                            EditorGUI.indentLevel++;
                            EditorGUILayout.PropertyField(outlineGradient, new GUIContent("Gradient"));
                            EditorGUILayout.PropertyField(outlineGradientKnee, new GUIContent("Knee"));
                            EditorGUILayout.PropertyField(outlineGradientPower, new GUIContent("Power"));
                            EditorGUI.indentLevel--;
                            break;
                    }
                }
                else {
                    EditorGUILayout.PropertyField(outlineWidth, new GUIContent("Width"));
                    EditorGUILayout.PropertyField(outlineColorStyle, new GUIContent("Color Style"));
                    switch ((ColorStyle)outlineColorStyle.intValue) {
                        case ColorStyle.SingleColor:
                            EditorGUILayout.PropertyField(outlineColor, new GUIContent("Color"));
                            break;
                        case ColorStyle.Gradient:
                            EditorGUI.indentLevel++;
                            EditorGUILayout.PropertyField(outlineGradient, new GUIContent("Gradient"));
                            EditorGUILayout.PropertyField(outlineGradientInLocalSpace, new GUIContent("In Local Space"));
                            EditorGUI.indentLevel--;
                            break;
                    }
                }
                if (outlineQuality.intValue == (int)QualityLevel.Highest && outlineEdgeMode.intValue != (int)OutlineEdgeMode.Any) {
                    EditorGUILayout.PropertyField(outlineDownsampling, new GUIContent("Downsampling"));
                }
                if (outlineQuality.intValue == (int)QualityLevel.Highest && glowQuality.intValue == (int)QualityLevel.Highest) {
                    EditorGUILayout.PropertyField(glowVisibility, new GUIContent("Visibility"));
                }
                else {
                    EditorGUILayout.PropertyField(outlineVisibility, new GUIContent("Visibility"));
                }
                EditorGUILayout.PropertyField(outlineMaskMode, new GUIContent("Mask Mode"));
                if (outlineQuality.intValue == (int)QualityLevel.Highest) {
                    EditorGUILayout.PropertyField(outlinePixelation, new GUIContent("Pixelation"));
                    EditorGUILayout.PropertyField(outlineStylized, new GUIContent("Stylized Effect"));
                    if (outlineStylized.boolValue) {
                        EditorGUI.indentLevel++;
                        EditorGUILayout.PropertyField(outlinePatternDistortionTexture, new GUIContent("Distortion Texture (R)", "Distortion texture for the stylized effect. Only red channel is used."));
                        if (outlinePatternDistortionTexture.objectReferenceValue != null) {
                            EditorGUI.indentLevel++;
                            EditorGUILayout.PropertyField(outlinePatternDistortionAmount, new GUIContent("Distortion Amount"));
                            EditorGUILayout.PropertyField(outlinePatternScale, new GUIContent("Scale"));
                            EditorGUILayout.PropertyField(outlinePatternStopMotionScale, new GUIContent("Stop Motion Speed"));
                        }
                        EditorGUILayout.PropertyField(outlinePattern, new GUIContent("Pattern (R)", "Pattern for the stylized effect. Only red channel is used."));
                        if (outlinePattern.objectReferenceValue != null) {
                            EditorGUI.indentLevel++;
                            EditorGUILayout.PropertyField(outlinePatternThreshold, new GUIContent("Threshold"));
                        }
                        EditorGUI.indentLevel--;
                    }
                    EditorGUILayout.PropertyField(outlineDashed, new GUIContent("Dashed Effect"));
                    if (outlineDashed.boolValue) {
                        EditorGUI.indentLevel++;
                        EditorGUILayout.PropertyField(outlineDashWidth, new GUIContent("Width"));
                        EditorGUILayout.PropertyField(outlineDashGap, new GUIContent("Gap"));
                        EditorGUILayout.PropertyField(outlineDashSpeed, new GUIContent("Speed"));
                        EditorGUI.indentLevel--;
                    }
                    if (!constantWidth.boolValue) {
                        EditorGUILayout.PropertyField(outlineDistanceScaleBias, new GUIContent("Distance Scale Bias", "Controls how quickly the outline effect scales down with distance. Lower values make the effect fade faster with distance."));
                    }
                    EditorGUILayout.PropertyField(extraCoveragePixels);
                    }
                }
                EditorGUI.indentLevel--;
            }

            expandGlow = DrawSectionHeader("Outer Glow", HP_GLOW, expandGlow, glow.floatValue > 0);
            if (expandGlow) {
                EditorGUI.indentLevel++;
                EditorGUILayout.PropertyField(glow, new GUIContent("Intensity"));
                if (glow.floatValue > 0) {
                HighlightEffectEditor.QualityPropertyField(glowQuality);
                if (glowQuality.intValue == (int)QualityLevel.Highest) {
                    EditorGUILayout.PropertyField(glowHighPrecision, new GUIContent("High Precision"));
                    EditorGUILayout.PropertyField(outlineContourStyle, new GUIContent("Contour Style"));
                    EditorGUILayout.PropertyField(glowWidth, new GUIContent("Width"));
                    EditorGUILayout.PropertyField(glowHQColor, new GUIContent("Color"));
                    EditorGUILayout.PropertyField(glowBlurMethod, new GUIContent("Blur Method", "Gaussian: better quality. Kawase: faster."));
                    EditorGUILayout.PropertyField(glowDownsampling, new GUIContent("Downsampling"));
                    EditorGUILayout.PropertyField(glowPixelation, new GUIContent("Pixelation"));
                }
                else {
                    EditorGUILayout.PropertyField(glowWidth, new GUIContent("Width"));
                }
                EditorGUILayout.PropertyField(glowAnimationSpeed, new GUIContent("Animation Speed"));
                if (glowQuality.intValue == (int)QualityLevel.Highest && !constantWidth.boolValue) {
                    EditorGUILayout.PropertyField(glowDistanceScaleBias, new GUIContent("Distance Scale Bias", "Controls how quickly the glow effect scales down with distance. Lower values make the effect fade faster with distance."));
                }
                EditorGUILayout.PropertyField(glowVisibility, new GUIContent("Visibility"));
                EditorGUILayout.PropertyField(glowMaskMode, new GUIContent("Mask Mode"));
                EditorGUILayout.PropertyField(glowBlendMode, new GUIContent("Blend Mode"));
                if (glowQuality.intValue != (int)QualityLevel.Highest) {
                    EditorGUILayout.PropertyField(glowDithering, new GUIContent("Dithering"));
                    if (glowDithering.floatValue > 0) {
                        EditorGUI.indentLevel++;
                        EditorGUILayout.PropertyField(glowDitheringStyle, new GUIContent("Style"));
                        if (glowDitheringStyle.intValue == (int)GlowDitheringStyle.Pattern) {
                            EditorGUILayout.PropertyField(glowMagicNumber1, new GUIContent("Magic Number 1"));
                            EditorGUILayout.PropertyField(glowMagicNumber2, new GUIContent("Magic Number 2"));
                        }
                        EditorGUI.indentLevel--;
                    }
                    EditorGUILayout.PropertyField(glowBlendPasses, new GUIContent("Blend Passes"));
                    EditorGUILayout.PropertyField(glowPasses, true);
                }
                else {
                        EditorGUILayout.PropertyField(extraCoveragePixels);
                    }
                }
                EditorGUI.indentLevel--;
            }

            expandInnerGlow = DrawSectionHeader("Inner Glow", HP_INNER_GLOW, expandInnerGlow, innerGlow.floatValue > 0);
            if (expandInnerGlow) {
                EditorGUI.indentLevel++;
                EditorGUILayout.PropertyField(innerGlow, new GUIContent("Intensity"));
                if (innerGlow.floatValue > 0) {
                    EditorGUILayout.PropertyField(innerGlowColor, new GUIContent("Color"));
                    EditorGUILayout.PropertyField(innerGlowWidth, new GUIContent("Width"));
                    EditorGUILayout.PropertyField(innerGlowPower, new GUIContent("Power"));
                    EditorGUILayout.PropertyField(innerGlowBlendMode, new GUIContent("Blend Mode"));
                    EditorGUILayout.PropertyField(innerGlowVisibility, new GUIContent("Visibility"));
                }
                EditorGUI.indentLevel--;
            }

            expandFocus = DrawSectionHeader("Focus", HP_FOCUS, expandFocus, focus.floatValue > 0);
            if (expandFocus) {
                EditorGUI.indentLevel++;
                EditorGUILayout.PropertyField(focus, new GUIContent("Intensity"));
                if (focus.floatValue > 0) {
                    EditorGUILayout.PropertyField(focusColor, new GUIContent("Color"));
                    EditorGUILayout.PropertyField(focusBlur, new GUIContent("Blur"));
                    if (focusBlur.floatValue > 0) {
                        EditorGUI.indentLevel++;
                        EditorGUILayout.PropertyField(focusBlurDownsampling, new GUIContent("Downsampling"));
                        EditorGUI.indentLevel--;
                    }
                    EditorGUILayout.PropertyField(focusDesaturation, new GUIContent("Desaturate"));
                }
                EditorGUI.indentLevel--;
            }

            expandOverlay = DrawSectionHeader("Overlay", HP_OVERLAY, expandOverlay, overlay.floatValue > 0);
            if (expandOverlay) {
                EditorGUI.indentLevel++;
                EditorGUILayout.PropertyField(overlay, new GUIContent("Intensity"));
                if (overlay.floatValue > 0) {
                    EditorGUILayout.PropertyField(overlayMode, new GUIContent("Mode"));
                EditorGUILayout.PropertyField(overlayColor, new GUIContent("Color"));
                EditorGUILayout.PropertyField(overlayTexture, new GUIContent("Texture"));
                if (overlayTexture.objectReferenceValue != null) {
                    EditorGUI.indentLevel++;
                    EditorGUILayout.PropertyField(overlayTextureScale, new GUIContent("Scale"));
                    if ((TextureUVSpace)overlayTextureUVSpace.intValue != TextureUVSpace.Triplanar) {
                        EditorGUILayout.PropertyField(overlayTextureScrolling, new GUIContent("Scrolling"));
                    }
                    EditorGUI.indentLevel--;
                }
                EditorGUILayout.PropertyField(overlayTextureUVSpace, new GUIContent("UV Space"));
                EditorGUILayout.PropertyField(overlayPattern, new GUIContent("Pattern"));
                if ((HighlightPlus.OverlayPattern)overlayPattern.enumValueIndex != HighlightPlus.OverlayPattern.None) {
                    EditorGUI.indentLevel++;
                    EditorGUILayout.PropertyField(overlayPatternScrolling, new GUIContent("Scrolling"));
                    EditorGUILayout.PropertyField(overlayPatternScale, new GUIContent("Scale"));
                    EditorGUILayout.PropertyField(overlayPatternSize, new GUIContent("Size"));
                    EditorGUILayout.PropertyField(overlayPatternSoftness, new GUIContent("Softness"));
                    EditorGUILayout.PropertyField(overlayPatternRotation, new GUIContent("Rotation"));
                    EditorGUI.indentLevel--;
                }
                EditorGUILayout.PropertyField(overlayBlending, new GUIContent("Blending"));
                EditorGUILayout.PropertyField(overlayMinIntensity, new GUIContent("Min Intensity"));
                    EditorGUILayout.PropertyField(overlayAnimationSpeed, new GUIContent("Animation Speed"));
                    EditorGUILayout.PropertyField(overlayVisibility, new GUIContent("Visibility"));
                }
                EditorGUI.indentLevel--;
            }

            expandTarget = DrawSectionHeader("Target", HP_TARGET, expandTarget, targetFX.boolValue);
            if (expandTarget) {
                EditorGUI.indentLevel++;
                EditorGUILayout.PropertyField(targetFX, new GUIContent("Enabled"));
                if (targetFX.boolValue) {
                    EditorGUILayout.PropertyField(targetFXStyle, new GUIContent("Style"));
                if (targetFXStyle.intValue == (int)TargetFXStyle.Texture) {
                    EditorGUILayout.PropertyField(targetFXTexture, new GUIContent("Texture"));
                }
                else {
                    EditorGUILayout.PropertyField(targetFXFrameWidth, new GUIContent("Width"));
                    EditorGUILayout.PropertyField(targetFXCornerLength, new GUIContent("Length"));
                    EditorGUILayout.PropertyField(targetFXFrameMinOpacity, new GUIContent("Min Opacity"));
                }
                EditorGUILayout.PropertyField(targetFXColor, new GUIContent("Color"));
                EditorGUILayout.PropertyField(targetFXUseEnclosingBounds, new GUIContent("Use Enclosing Bounds"));
                EditorGUILayout.PropertyField(targetFXOffset, new GUIContent("Offset"));
                EditorGUILayout.PropertyField(targetFxCenterOnHitPosition, new GUIContent("Center On Hit Position"));
                EditorGUILayout.PropertyField(targetFxAlignToNormal, new GUIContent("Align To Hit Normal"));
                EditorGUILayout.PropertyField(targetFXRotationSpeed, new GUIContent("Rotation Speed"));
                EditorGUILayout.PropertyField(targetFXRotationAngle, new GUIContent("Rotation Angle"));
                EditorGUILayout.PropertyField(targetFXInitialScale, new GUIContent("Initial Scale"));
                EditorGUILayout.PropertyField(targetFXEndScale, new GUIContent("End Scale"));
                EditorGUILayout.PropertyField(targetFXScaleToRenderBounds, new GUIContent("Scale To Object Bounds"));
                if (targetFXScaleToRenderBounds.boolValue) {
                    EditorGUILayout.PropertyField(targetFXSquare, new GUIContent("Square"));
                }
                EditorGUILayout.PropertyField(targetFXAlignToGround, new GUIContent("Align To Ground"));
                if (targetFXAlignToGround.boolValue) {
                    EditorGUI.indentLevel++;
                    EditorGUILayout.PropertyField(targetFXGroundMaxDistance, new GUIContent("Ground Max Distance"));
                    EditorGUILayout.PropertyField(targetFXGroundLayerMask, new GUIContent("Ground Layer Mask"));
                    EditorGUILayout.PropertyField(targetFXFadePower, new GUIContent("Fade Power"));
                    EditorGUILayout.PropertyField(targetFXGroundMinAltitude, new GUIContent("Ground Min Altitude"));
                    EditorGUI.indentLevel--;
                }
                    EditorGUILayout.PropertyField(targetFXTransitionDuration, new GUIContent("Transition Duration"));
                    EditorGUILayout.PropertyField(targetFXStayDuration, new GUIContent("Stay Duration"));
                    EditorGUILayout.PropertyField(targetFXVisibility, new GUIContent("Visibility"));
                }
                EditorGUI.indentLevel--;
            }

            expandIcon = DrawSectionHeader("Icon", HP_ICON, expandIcon, iconFX.boolValue);
            if (expandIcon) {
                EditorGUI.indentLevel++;
                EditorGUILayout.PropertyField(iconFX, new GUIContent("Enabled"));
                if (iconFX.boolValue) {
                    EditorGUILayout.PropertyField(iconFXAssetType, new GUIContent("Asset Type"));
                    if (iconFXAssetType.intValue == (int)IconAssetType.Mesh) {
                        EditorGUILayout.PropertyField(iconFXMesh, new GUIContent("Mesh"));
                        EditorGUILayout.PropertyField(iconFXLightColor, new GUIContent("Light Color"));
                        EditorGUILayout.PropertyField(iconFXDarkColor, new GUIContent("Dark Color"));
                    }
                    else {
                        EditorGUILayout.PropertyField(iconFXPrefab, new GUIContent("Prefab"));
                    }
                    EditorGUILayout.PropertyField(iconFXOffset, new GUIContent("Offset"));
                    EditorGUILayout.PropertyField(iconFXRotationSpeed, new GUIContent("Rotation Speed"));
                    EditorGUILayout.PropertyField(iconFXAnimationOption, new GUIContent("Animation"));
                    if (iconFXAnimationOption.intValue != 0) {
                        EditorGUI.indentLevel++;
                        EditorGUILayout.PropertyField(iconFXAnimationAmount, new GUIContent("Amount"));
                        EditorGUILayout.PropertyField(iconFXAnimationSpeed, new GUIContent("Speed"));
                        EditorGUI.indentLevel--;
                    }
                    EditorGUILayout.PropertyField(iconFXScale, new GUIContent("Scale"));
                    EditorGUILayout.PropertyField(iconFXScaleToRenderBounds, new GUIContent("Scale To Object Bounds"));
                    EditorGUILayout.PropertyField(iconFXTransitionDuration, new GUIContent("Transition Duration"));
                    EditorGUILayout.PropertyField(iconFXStayDuration, new GUIContent("Stay Duration"));
                }
                EditorGUI.indentLevel--;
            }

            expandSeeThrough = DrawSectionHeader("See Through", HP_SEE_THROUGH, expandSeeThrough, seeThrough.intValue != (int)SeeThroughMode.Never);
            if (expandSeeThrough) {
                EditorGUI.indentLevel++;
                EditorGUILayout.PropertyField(seeThrough);
                if (seeThrough.intValue != (int)SeeThroughMode.Never) {
                    EditorGUILayout.PropertyField(seeThroughOccluderMask, new GUIContent("Occluder Layer"));
                    if (seeThroughOccluderMask.intValue > 0) {
                        EditorGUI.indentLevel++;
                        EditorGUILayout.PropertyField(seeThroughOccluderMaskAccurate, new GUIContent("Accurate"));
                        EditorGUILayout.PropertyField(seeThroughOccluderThreshold, new GUIContent("Radius Threshold", "Multiplier to the object bounds. Making the bounds smaller prevents false occlusion tests."));
                        EditorGUILayout.PropertyField(seeThroughOccluderCheckInterval, new GUIContent("Check Interval", "Interval in seconds between occlusion tests."));
                        EditorGUILayout.PropertyField(seeThroughOccluderCheckIndividualObjects, new GUIContent("Check Individual Objects", "Interval in seconds between occlusion tests."));
                        EditorGUI.indentLevel--;
                    }
                    EditorGUILayout.PropertyField(seeThroughDepthOffset, new GUIContent("Depth Offset" + ((seeThroughDepthOffset.floatValue > 0) ? " •" : "")));
                    EditorGUILayout.PropertyField(seeThroughMaxDepth, new GUIContent("Max Depth" + ((seeThroughMaxDepth.floatValue > 0) ? " •" : "")));
                    if (seeThroughMaxDepth.floatValue > 0f) {
                        EditorGUI.indentLevel++;
                        EditorGUILayout.PropertyField(seeThroughFadeRange, new GUIContent("Fade Range"));
                        EditorGUI.indentLevel--;
                    }
                    EditorGUILayout.PropertyField(seeThroughIntensity, new GUIContent("Intensity"));
                    EditorGUILayout.PropertyField(seeThroughTintColor, new GUIContent("Color"));
                    EditorGUILayout.PropertyField(seeThroughTintAlpha, new GUIContent("Color Blend"));
                    EditorGUILayout.PropertyField(seeThroughNoise, new GUIContent("Noise"));
                    EditorGUILayout.PropertyField(seeThroughTexture, new GUIContent("Texture"));
                    if (seeThroughTexture.objectReferenceValue != null) {
                        EditorGUILayout.PropertyField(seeThroughTextureUVSpace, new GUIContent("UV Space"));
                        EditorGUILayout.PropertyField(seeThroughTextureScale, new GUIContent("Texture Scale"));
                    }
                    EditorGUILayout.PropertyField(seeThroughBorder, new GUIContent("Border When Hidden"));
                    if (seeThroughBorder.floatValue > 0) {
                        EditorGUI.indentLevel++;
                        EditorGUILayout.PropertyField(seeThroughBorderWidth, new GUIContent("Width"));
                        EditorGUILayout.PropertyField(seeThroughBorderColor, new GUIContent("Color"));
                        EditorGUILayout.PropertyField(seeThroughBorderOnly, new GUIContent("Border Only"));
                        EditorGUI.indentLevel--;
                    }
                    EditorGUILayout.PropertyField(seeThroughChildrenSortingMode, new GUIContent("Children Sorting Mode"));
                    EditorGUILayout.PropertyField(seeThroughOrdered, new GUIContent("Ordered"));
                }
                EditorGUI.indentLevel--;
            }

            expandHitFX = DrawSectionHeader("Hit FX", HP_HIT_FX, expandHitFX, hitFxInitialIntensity.floatValue > 0);
            if (expandHitFX) {
                EditorGUI.indentLevel++;
                EditorGUILayout.PropertyField(hitFxInitialIntensity, new GUIContent("Intensity"));
                if (hitFxInitialIntensity.floatValue > 0) {
                    EditorGUILayout.PropertyField(hitFxMode, new GUIContent("Style"));
                    EditorGUILayout.PropertyField(hitFXTriggerMode, new GUIContent("Trigger Mode"));
                    EditorGUILayout.PropertyField(hitFxFadeOutDuration, new GUIContent("Fade Out Duration"));
                    EditorGUILayout.PropertyField(hitFxColor, new GUIContent("Color"));
                    if ((HitFxMode)hitFxMode.intValue == HitFxMode.LocalHit) {
                        EditorGUILayout.PropertyField(hitFxRadius, new GUIContent("Radius"));
                    }
                }
                EditorGUI.indentLevel--;
            }

            expandLabel = DrawSectionHeader("Label", HP_LABEL, expandLabel, labelEnabled.boolValue);
            if (expandLabel) {
                EditorGUI.indentLevel++;
                EditorGUILayout.PropertyField(labelEnabled, new GUIContent("Enabled"));
                if (labelEnabled.boolValue) {
                    EditorGUILayout.PropertyField(labelMode, new GUIContent("Mode"));
                EditorGUILayout.PropertyField(labelShowInEditorMode, new GUIContent("Always Show In Editor Mode"));
                EditorGUILayout.PropertyField(labelText, new GUIContent("Text"));
                EditorGUILayout.PropertyField(labelTextSize, new GUIContent("Text Size"));
                EditorGUILayout.PropertyField(labelColor, new GUIContent("Color"));
                EditorGUILayout.PropertyField(labelPrefab, new GUIContent("Prefab", "The prefab to use for the label. Must contain a Canvas and TextMeshProUGUI component."));
                EditorGUILayout.PropertyField(labelAlignment, new GUIContent("Alignment"));
                EditorGUILayout.PropertyField(labelRelativeAlignment, new GUIContent("Relative Alignment"));
                if (labelRelativeAlignment.boolValue) {
                    EditorGUI.indentLevel++;
                    EditorGUILayout.PropertyField(labelAlignmentTransform, new GUIContent("Alignment Transform"));
                    EditorGUI.indentLevel--;
                }
                EditorGUILayout.PropertyField(labelFollowCursor, new GUIContent("Follow Cursor"));
                EditorGUILayout.PropertyField(labelVerticalOffset, new GUIContent("World Vertical Offset"));
                EditorGUILayout.PropertyField(labelViewportOffset, new GUIContent("Viewport Offset", "The viewport offset of the label in screen space (X, Y) as normalized values -1 to 1"));
                EditorGUILayout.PropertyField(labelLineLength, new GUIContent("Line Length"));
                EditorGUILayout.Space();
                EditorGUILayout.LabelField("Label Distance & Scale", EditorStyles.boldLabel);
                EditorGUILayout.PropertyField(labelMaxDistance, new GUIContent("Max Distance"));
                EditorGUILayout.PropertyField(labelFadeStartDistance, new GUIContent("Fade Start Distance"));
                EditorGUILayout.PropertyField(labelScaleByDistance, new GUIContent("Scale By Distance"));
                    if (labelScaleByDistance.boolValue) {
                        EditorGUI.indentLevel++;
                        EditorGUILayout.PropertyField(labelScaleMin, new GUIContent("Scale Min"));
                        EditorGUILayout.PropertyField(labelScaleMax, new GUIContent("Scale Max"));
                        EditorGUI.indentLevel--;
                    }
                }
                EditorGUI.indentLevel--;
            }

            if (serializedObject.ApplyModifiedProperties() || (Event.current.type == EventType.ValidateCommand &&
                Event.current.commandName == "UndoRedoPerformed")) {

                // Triggers profile reload on all Highlight Effect scripts
                HighlightEffect[] effects = Misc.FindObjectsOfType<HighlightEffect>();
                for (int t = 0; t < targets.Length; t++) {
                    HighlightProfile profile = (HighlightProfile)targets[t];
                    for (int k = 0; k < effects.Length; k++) {
                        if (effects[k] != null && effects[k].profile == profile && effects[k].profileSync) {
                            profile.Load(effects[k]);
                            effects[k].Refresh();
                        }
                    }
                }
                EditorUtility.SetDirty(target);
            }

        }

    }

}