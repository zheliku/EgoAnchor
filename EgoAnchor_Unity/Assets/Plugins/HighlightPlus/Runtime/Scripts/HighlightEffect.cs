/// <summary>
/// Highlight Plus - (c) Kronnect Technologies SL
/// </summary>

using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Serialization;

namespace HighlightPlus {

    public delegate bool OnObjectHighlightEvent (GameObject obj);
    public delegate bool OnObjectHighlightStateEvent (GameObject obj, bool state);
    public delegate bool OnObjectSelectionEvent (GameObject obj);
    public delegate bool OnRendererHighlightEvent (Renderer renderer);
    public delegate void OnObjectClickEvent (GameObject obj, Vector3 position, Vector3 normal);

    /// <summary>
    /// Triggers when target effect animation occurs
    /// </summary>
    /// <param name="t">A value from 0 to 1 that represent the animation time from start to end, based on target duration and start time</param>
    public delegate void OnAnimateEvent (ref Vector3 center, ref Quaternion rotation, ref Vector3 scale, float t);

    public enum NormalsOption {
        Smooth = 0,
        PreserveOriginal = 1,
        Reorient = 2
    }

    public enum SeeThroughMode {
        WhenHighlighted = 0,
        AlwaysWhenOccluded = 1,
        Never = 2
    }

    public enum SeeThroughSortingMode {
        Default = 0,
        SortByMaterialsRenderQueue = 1,
        SortByMaterialsRenderQueueInverted = 2
    }

    public enum OverlayMode {
        WhenHighlighted = 0,
        Always = 10
    }

    public enum OverlayPattern {
        None,
        Polkadots,
        Grid,
        StaggeredLines,
        ZigZag
    }

    public enum TextureUVSpace {
        Triplanar = 0,
        ObjectSpace = 1,
        ScreenSpace = 2
    }

    public enum QualityLevel {
        Fastest = 0,
        High = 1,
        Highest = 2,
        Medium = 3
    }

    public enum TargetOptions {
        Children,
        OnlyThisObject,
        RootToChildren,
        LayerInScene,
        LayerInChildren,
        Scripting
    }

    public enum Visibility {
        Normal,
        AlwaysOnTop,
        OnlyWhenOccluded
    }

    public enum ColorStyle {
        SingleColor,
        Gradient
    }

    public enum OutlineEdgeMode {
        Exterior,
        Any
    }

    public enum ContourStyle {
        AroundVisibleParts,
        AroundObjectShape
    }

    public enum GlowBlendMode {
        Additive,
        AlphaBlending
    }

    public enum GlowDitheringStyle {
        Pattern,
        Noise
    }

    public enum InnerGlowBlendMode {
        Additive,
        AlphaBlending
    }

    public enum BlurMethod {
        Gaussian,
        Kawase
    }

    public enum IconAssetType {
        Mesh,
        Prefab
    }

    public enum IconAnimationOption {
        None,
        VerticalBounce = 10
    }


    public enum MaskMode {
        Stencil,
        IgnoreMask,
        StencilAndCutout,
        CutoutOnly
    }

    public enum TargetFXStyle {
        Texture = 0,
        Frame = 10,
        InwardCorners = 20,
        Cross = 30
    }

    public enum LabelMode {
        WhenHighlighted = 0,
        Always = 10
    }

    public enum LabelAlignment {
        Auto,
        Left,
        Right
    }



    public static class QualityLevelExtensions {
        public static bool UsesMultipleOffsets (this QualityLevel qualityLevel) {
            return qualityLevel == QualityLevel.Medium || qualityLevel == QualityLevel.High;
        }
    }

    [Serializable]
    public struct GlowPassData {
        public float offset;
        public float alpha;
        [ColorUsage(showAlpha: true, hdr: true)]
        public Color color;
    }

    [ExecuteAlways]
    [HelpURL("https://kronnect.com/docs/highlight-plus/")]
    public partial class HighlightEffect : MonoBehaviour {

        static int GetObjectId(UnityEngine.Object obj) {
#if UNITY_6000_4_OR_NEWER
            return obj.GetEntityId().GetHashCode();
#else
            return obj.GetInstanceID();
#endif
        }

        /// <summary>
        /// Gets or sets the current profile. To load a profile and apply its settings at runtime, please use ProfileLoad() method.
        /// </summary>
        [Tooltip("The current profile (optional). A profile let you store Highlight Plus settings and apply those settings easily to many objects. You can also load a profile and apply its settings at runtime, using the ProfileLoad() method of the Highlight Effect component.")]
        public HighlightProfile profile;

        /// <summary>
        /// Sets if changes to the original profile should propagate to this effect.
        /// </summary>
        [Tooltip("If enabled, settings from the profile will be applied to this component automatically when game starts or when any profile setting is updated.")]
        public bool profileSync;

        /// <summary>
        /// Which cameras can render the effects
        /// </summary>
        [Tooltip("Which cameras can render the effect.")]
        public LayerMask camerasLayerMask = -1;

        /// <summary>
        /// Specifies which objects are affected by this effect.
        /// </summary>
        [Tooltip("Different options to specify which objects are affected by this Highlight Effect component.")]
        public TargetOptions effectGroup = TargetOptions.Children;

        /// <summary>
        /// The target object where the include option applies
        /// </summary>
        [Tooltip("The target object to highlight.")]
        public Transform effectTarget;

        /// <summary>
        /// The layer that contains the affected objects by this effect when effectGroup is set to LayerMask.
        /// </summary>
        [Tooltip("The layer that contains the affected objects by this effect when effectGroup is set to LayerMask.")]
        public LayerMask effectGroupLayer = -1;

        /// <summary>
        /// Optional object name filter
        /// </summary>
        [Tooltip("Only include objects whose names contains this text.")]
        public string effectNameFilter;

        /// <summary>
        /// Optional object name exclusion filter
        /// </summary>
        [Tooltip("Use RegEx to determine if an object name matches the effectNameFilter.")]
        public bool effectNameUseRegEx;

        /// <summary>
        /// Exclude objects that already have a highlight effect component
        /// </summary>
        [Tooltip("Exclude objects that already have a Highlight Effect component when using Include options.")]
        public bool excludeObjectsWithHighlightEffect;

        /// <summary>
        /// Combine objects into a single mesh
        /// </summary>
        [Tooltip("Combine meshes of all objects in this group affected by Highlight Effect reducing draw calls.")]
        public bool combineMeshes;

        /// <summary>
        /// The alpha threshold for transparent cutout objects. Pixels with alpha below this value will be discarded.
        /// </summary>
        [Tooltip("The alpha threshold for transparent cutout objects. Pixels with alpha below this value will be discarded.")]
        [Range(0, 1)]
        public float alphaCutOff;
        [Tooltip("Optional custom texture property name used for alpha clipping; if not found, falls back to _BaseMap or _MainTex.")]
        public string alphaCutOffTextureName;

        /// <summary>
        /// If back facing triangles are ignored. Backfaces triangles are not visible but you may set this property to false to force highlight effects to act on those triangles as well.
        /// </summary>
        [Tooltip("If back facing triangles are ignored.Backfaces triangles are not visible but you may set this property to false to force highlight effects to act on those triangles as well.")]
        public bool cullBackFaces = true;

        /// <summary>
        /// Show highlight effects even if the object is currently not visible. This option is useful if the affected objects are rendered using GPU instancing tools which render directly to the GPU without creating real game object geometry in CPU.
        /// </summary>
        [Tooltip("Show highlight effects even if the object is not visible. If this object or its children use GPU Instancing tools, the MeshRenderer can be disabled although the object is visible. In this case, this option is useful to enable highlighting.")]
        public bool ignoreObjectVisibility;

        /// <summary>
        /// Enable to support reflection probes
        /// </summary>
        [Tooltip("Support reflection probes. Enable only if you want the effects to be visible in reflections.")]
        public bool reflectionProbes;

        /// <summary>
        /// Enable to support reflection probes
        /// </summary>
        [Tooltip("Enables GPU instancing. Reduces draw calls in outline and outer glow effects on platforms that support GPU instancing. Should be enabled by default.")]
        public bool GPUInstancing = true;

        [Tooltip("Custom sorting priority for the highlight effect (useful to control which effects render on top of others")]
        public int sortingPriority;

        /// <summary>
        /// Enable to support reflection probes
        /// </summary>
        [Tooltip("Bakes skinned mesh to leverage GPU instancing when using outline/outer glow with mesh-based rendering. Reduces draw calls significantly on skinned meshes.")]
        public bool optimizeSkinnedMesh = true;

        /// <summary>
        /// Enabled depth buffer flip in HQ
        /// </summary>
        [Tooltip("Enables depth buffer clipping. Only applies to outline or outer glow in High Quality mode.")]
        public bool depthClip;

        [Tooltip("Fades out effects based on distance to camera")]
        public bool cameraDistanceFade;

        [Tooltip("The closest distance particles can get to the camera before they fade from the camera's view.")]
        public float cameraDistanceFadeNear;

        [Tooltip("The farthest distance particles can get away from the camera before they fade from the camera's view.")]
        public float cameraDistanceFadeFar = 1000;

        [Tooltip("If enabled, the highlight effect will use a pass from the original object's shader to render the silhouette.")]
        public bool useOriginalShader;

        [Tooltip("The pass name from the original shader to use for rendering the silhouette.")]
        public string customPassName;

        [Tooltip("Normals handling option:\nPreserve original: use original mesh normals.\nSmooth: average normals to produce a smoother outline/glow mesh based effect.\nReorient: recomputes normals based on vertex direction to centroid.")]
        public NormalsOption normalsOption;

        /// <summary>
        /// Ignores highlight effects on this object.
        /// </summary>
        [Tooltip("Ignore highlighting on this object.")]
        public bool ignore;

        [SerializeField]
        bool _highlighted;

        public bool highlighted { get { return _highlighted; } set { SetHighlighted(value); } }

        public float fadeInDuration;
        public float fadeOutDuration;

        public bool flipY;

        [Tooltip("Keeps the outline/glow size unaffected by object distance.")]
        public bool constantWidth = true;

        [Tooltip("Increases the screen coverage for the outline/glow to avoid cuts when using cloth or vertex shader that transform mesh vertices")]
        public int extraCoveragePixels;

        [Tooltip("Minimum width when the constant width option is not used")]
        [Range(0, 1)]
        public float minimumWidth;

        [Tooltip("Mask to include or exclude certain submeshes. By default, all submeshes are included.")]
        public int subMeshMask = -1;

        [Tooltip("Selects which custom vertex transformation to use in CustomVertexTransform.cginc (0 = default).")]
        public int vertexTransformMode;

        [Range(0, 1)]
        [Tooltip("Intensity of the overlay effect. A value of 0 disables the overlay completely.")]
        public float overlay;
        public OverlayMode overlayMode = OverlayMode.WhenHighlighted;
        public OverlayPattern overlayPattern = OverlayPattern.None;
        public Vector2 overlayPatternScrolling;
        [ColorUsage(showAlpha: false, hdr: true)] public Color overlayColor = Color.yellow;
        public float overlayAnimationSpeed = 1f;
        [Range(0, 1)]
        public float overlayMinIntensity = 0.5f;
        [Range(0, 1)]
        [Tooltip("Controls the blending or mix of the overlay color with the natural colors of the object.")]
        public float overlayBlending = 1.0f;
        [Tooltip("Optional overlay texture.")]
        public Texture2D overlayTexture;
        public TextureUVSpace overlayTextureUVSpace = TextureUVSpace.ObjectSpace;
        public float overlayTextureScale = 1f;
        public Vector2 overlayTextureScrolling;
        public Visibility overlayVisibility = Visibility.Normal;

        [Tooltip("Scale of the overlay pattern")]
        [Range(1f, 100f)]
        public float overlayPatternScale = 10f;
        [Tooltip("Size/Thickness of the overlay pattern")]
        [Range(0.01f, 1f)]
        public float overlayPatternSize = 0.15f;
        [Tooltip("Softness of the overlay pattern")]
        [Range(0.01f, 0.5f)]
        public float overlayPatternSoftness = 0.02f;
        [Tooltip("Rotation angle for the overlay pattern in degrees")]
        [Range(-180f, 180f)]
        public float overlayPatternRotation;

        [Range(0, 1)]
        [Tooltip("Intensity of the outline. A value of 0 disables the outline completely.")]
        public float outline = 1f;
        [ColorUsage(true, true)] public Color outlineColor = Color.black;
        public ColorStyle outlineColorStyle = ColorStyle.SingleColor;
        [GradientUsage(hdr: true, ColorSpace.Linear)] public Gradient outlineGradient;
        public bool outlineGradientInLocalSpace;
        public float outlineWidth = 0.45f;
        [Range(1, 3)]
        public int outlineBlurPasses = 2;
        public QualityLevel outlineQuality = QualityLevel.Medium;
        public OutlineEdgeMode outlineEdgeMode = OutlineEdgeMode.Exterior;
        public float outlineEdgeThreshold = 0.995f;
        [Tooltip("Controls how quickly the outline effect scales down with distance when constant width is disabled. Lower values make the effect fade faster with distance.")]
        public float outlineDistanceScaleBias = 25f;
        public float outlineSharpness = 1f;
        [Range(1, 8)]
        [Tooltip("Reduces the quality of the outline but improves performance a bit.")]
        public int outlineDownsampling = 1;
        public Visibility outlineVisibility = Visibility.Normal;
        public GlowBlendMode glowBlendMode = GlowBlendMode.Additive;
        public bool outlineBlitDebug;
        [Tooltip("If enabled, this object won't combine the outline with other objects.")]
        public bool outlineIndependent;
        public ContourStyle outlineContourStyle = ContourStyle.AroundVisibleParts;
        [Tooltip("Select the mask mode used with this effect.")]
        public MaskMode outlineMaskMode = MaskMode.Stencil;
        public float outlineGradientKnee = 0.4f;
        public float outlineGradientPower = 8f;
        [Tooltip("Adds a empty margin between the outline mesh and the effects")]
        [Range(0, 1)]
        public float padding;

        [Tooltip("Makes the outline pixelated. A value of 0 disables pixelation. Higher values produce bigger pixels.")]
        [Range(0, 32)]
        public int outlinePixelation;

        [Tooltip("Enables stylized outline effect.")]
        public bool outlineStylized;
        [Tooltip("Pattern texture used for the stylized outline effect.")]
        public Texture2D outlinePattern;
        [Tooltip("Scale of the pattern texture.")]
        public float outlinePatternScale = 0.3f;
        [Tooltip("Threshold for the pattern texture.")]
        [Range(0, 1)]
        public float outlinePatternThreshold = 0.3f;
        [Tooltip("Distortion amount for the pattern texture.")]
        [Range(0, 1.5f)]
        public float outlinePatternDistortionAmount = 0.5f;
        [Tooltip("Pattern texture used for the distortion effect.")]
        public Texture2D outlinePatternDistortionTexture;
        [Tooltip("Stop motion scale for the distortion effect.")]
        public float outlinePatternStopMotionScale = 5f;

        [Tooltip("Enables dashed outline effect.")]
        public bool outlineDashed;
        [Tooltip("Width of the dashed outline.")]
        [Range(0, 1)]
        public float outlineDashWidth = 0.5f;
        [Tooltip("Gap of the dashed outline.")]
        [Range(0, 1)]
        public float outlineDashGap = 0.3f;
        [Tooltip("Speed of the dashed outline.")]
        public float outlineDashSpeed = 2f;

        [Range(0, 5)]
        [Tooltip("The intensity of the outer glow effect. A value of 0 disables the glow completely.")]
        public float glow;
        public float glowWidth = 0.4f;
        public QualityLevel glowQuality = QualityLevel.Medium;
        public BlurMethod glowBlurMethod = BlurMethod.Gaussian;
        public bool glowHighPrecision = true;
        [Tooltip("Controls how quickly the glow effect scales down with distance when constant width is disabled. Lower values make the effect fade faster with distance.")]
        public float glowDistanceScaleBias = 25f;
        [Range(1, 8)]
        [Tooltip("Reduces the quality of the glow but improves performance a bit.")]
        public int glowDownsampling = 2;
        [ColorUsage(true, true)] public Color glowHQColor = new Color(0.64f, 1f, 0f, 1f);
        [Tooltip("When enabled, outer glow renders with dithering. When disabled, glow appears as a solid color.")]
        [Range(0, 1)]
        public float glowDithering = 1f;
        public GlowDitheringStyle glowDitheringStyle = GlowDitheringStyle.Pattern;
        [Tooltip("Seed for the dithering effect")]
        public float glowMagicNumber1 = 0.75f;
        [Tooltip("Another seed for the dithering effect that combines with first seed to create different patterns")]
        public float glowMagicNumber2 = 0.5f;
        public float glowAnimationSpeed = 1f;
        public Visibility glowVisibility = Visibility.Normal;
        public bool glowBlitDebug;
        [Tooltip("Blends glow passes one after another. If this option is disabled, glow passes won't overlap (in this case, make sure the glow pass 1 has a smaller offset than pass 2, etc.)")]
        public bool glowBlendPasses = true;
#if UNITY_2020_2_OR_NEWER
        [NonReorderable]
#endif
        public GlowPassData[] glowPasses;
        [Tooltip("Select the mask mode used with this effect.")]
        public MaskMode glowMaskMode = MaskMode.Stencil;
        [Tooltip("Makes the glow pixelated. A value of 0 disables pixelation. Higher values produce bigger pixels.")]
        [Range(0, 32)]
        public int glowPixelation;

        [Range(0, 5f)]
        [Tooltip("The intensity of the inner glow effect. A value of 0 disables the glow completely.")]
        public float innerGlow;
        [Range(0, 2)]
        public float innerGlowWidth = 1f;
        public float innerGlowPower = 1f;
        [ColorUsage(true, true)] public Color innerGlowColor = Color.white;
        public InnerGlowBlendMode innerGlowBlendMode = InnerGlowBlendMode.Additive;
        public Visibility innerGlowVisibility = Visibility.Normal;

        [Range(0, 1)]
        [Tooltip("Intensity of the focus effect. A value of 0 disables the focus effect completely.")]
        public float focus;
        [Tooltip("Color and transparency of the focus dim overlay.")]
        public Color focusColor = new Color(0, 0, 0, 0.9412f);
        [Range(0, 1)]
        [Tooltip("Optional background blur intensity for the focus effect.")]
        public float focusBlur;
        [Range(1, 8)]
        [Tooltip("Downsampling factor for the focus blur. Higher values improve performance at the cost of quality.")]
        public int focusBlurDownsampling = 2;
        [Range(0, 1)]
        [Tooltip("Desaturation intensity for the focus background. A value of 1 makes the background fully grayscale.")]
        public float focusDesaturation;

        [Tooltip("Enables the targetFX effect. This effect draws an animated sprite over the object.")]
        public bool targetFX;
        [Tooltip("Style of the target FX effect.")]
        public TargetFXStyle targetFXStyle = TargetFXStyle.Texture;
        [Tooltip("Width of the frame when using Frame style")]
        [Range(0.001f, 0.5f)]
        public float targetFXFrameWidth = 0.1f;
        [Tooltip("Length of the frame corners when using Frame style")]
        [Range(0, 0.5f)]
        public float targetFXCornerLength = 0.25f;
        [Tooltip("Minimum opacity of the frame when using Frame style")]
        [Range(0, 1)]
        public float targetFXFrameMinOpacity;
        [Tooltip("If the ground is transparent, the effect won't work. You can set this property to the altitude of the transparent ground to force the effect to render at this altitude.")]
        public float targetFXGroundMinAltitude = -1000;
        public Texture2D targetFXTexture;
        [ColorUsage(true, true)] public Color targetFXColor = Color.white;
        public Transform targetFXCenter;
        public float targetFXRotationSpeed = 50f;
        [Tooltip("Initial rotation angle for the Target FX effect")]
        public float targetFXRotationAngle;
        public float targetFXInitialScale = 4f;
        public float targetFXEndScale = 1.5f;
        [Tooltip("Makes target scale relative to object renderer bounds")]
        public bool targetFXScaleToRenderBounds = true;
        [Tooltip("Enable to render a single target FX effect at the center of the enclosing bounds")]
        public bool targetFXUseEnclosingBounds;
        [Tooltip("Makes target FX effect square")]
        public bool targetFXSquare = true;
        [Tooltip("Places target FX sprite at the bottom of the highlighted object")]
        public bool targetFXAlignToGround;
        [Tooltip("Optional worlds space offset for the position of the targetFX effect")]
        public Vector3 targetFXOffset;
        [Tooltip("If enabled, the target FX effect will be centered on the hit position")]
        public bool targetFxCenterOnHitPosition;
        [Tooltip("If enabled, the target FX effect will align to the hit normal")]
        public bool targetFxAlignToNormal;
        [Tooltip("Fade out effect with altitude")]
        public float targetFXFadePower = 32;
        public float targetFXGroundMaxDistance = 10f;
        public LayerMask targetFXGroundLayerMask = -1;
        public float targetFXTransitionDuration = 0.5f;
        [Tooltip("The duration of the effect. A value of 0 will keep the target sprite on screen while object is highlighted.")]
        public float targetFXStayDuration = 1.5f;
        public Visibility targetFXVisibility = Visibility.AlwaysOnTop;

        [Tooltip("Enables the iconFX effect. This effect draws an animated object over the object.")]
        public bool iconFX;
        public IconAssetType iconFXAssetType;
        public GameObject iconFXPrefab;
        public Mesh iconFXMesh;
        [ColorUsage(true, true)] public Color iconFXLightColor = Color.white;
        [ColorUsage(true, true)] public Color iconFXDarkColor = Color.gray;
        public Transform iconFXCenter;
        public float iconFXRotationSpeed = 50f;
        public IconAnimationOption iconFXAnimationOption = IconAnimationOption.None;
        public float iconFXAnimationAmount = 0.1f;
        public float iconFXAnimationSpeed = 3f;
        public float iconFXScale = 1f;
        [Tooltip("Makes target scale relative to object renderer bounds.")]
        public bool iconFXScaleToRenderBounds;
        [Tooltip("Optional world space offset for the position of the iconFX effect")]
        public Vector3 iconFXOffset = new Vector3(0, 1, 0);
        public float iconFXTransitionDuration = 0.5f;
        public float iconFXStayDuration = 1.5f;

        [Tooltip("Enables the label effect. This effect shows a text label over the object.")]
        public bool labelEnabled;
        [Tooltip("The text to display in the label")]
        public string labelText = "Label";
        [Tooltip("The size of the label text")]
        public float labelTextSize = 14;
        [ColorUsage(true, true)] public Color labelColor = Color.white;
        [Tooltip("The prefab to use for the label. Must contain a Canvas and TextMeshProUGUI component.")]
        public GameObject labelPrefab;
        public Vector2 labelViewportOffset;
        public float labelVerticalOffset;
        [Tooltip("The horizontal offset of the label with respect to the object center")]
        [FormerlySerializedAs("lineLength")]
        public float labelLineLength = 200;
        [Tooltip("The target transform for the label")]
        public Transform labelTarget;
        [Tooltip("If enabled, the label will follow the cursor when hovering the object")]
        public bool labelFollowCursor = true;
        public LabelMode labelMode = LabelMode.WhenHighlighted;
        [Tooltip("If enabled, the label will be shown in editor mode (non playing)")]
        public bool labelShowInEditorMode = true;
        [Tooltip("Controls the alignment of the label relative to the target object on screen.")]
        public LabelAlignment labelAlignment = LabelAlignment.Auto;
        [Tooltip("Enables relative alignment based on the forward direction of the alignment transform.")]
        public bool labelRelativeAlignment;
        [Tooltip("The transform used for relative alignment direction.")]
        public Transform labelAlignmentTransform;

        [Tooltip("Maximum distance from camera where the label is visible (units). Default 250.")]
        public float labelMaxDistance = 250f;
        [Tooltip("Distance at which label starts fading out (units). 0 disables fading.")]
        public float labelFadeStartDistance = 200f;
        [Tooltip("Enable distance-based scaling of label Canvas.")]
        public bool labelScaleByDistance;
        [Tooltip("Minimum scale when at max distance (0..1 typically). Default 1.")]
        public float labelScaleMin = 1f;
        [Tooltip("Maximum scale when near camera. Default 1.")]
        public float labelScaleMax = 1f;

        [Tooltip("See-through mode for this Highlight Effect component.")]
        public SeeThroughMode seeThrough = SeeThroughMode.Never;
        [Tooltip("This mask setting let you specify which objects will be considered as occluders and cause the see-through effect for this Highlight Effect component. For example, you assign your walls to a different layer and specify that layer here, so only walls and not other objects, like ground or ceiling, will trigger the see-through effect.")]
        public LayerMask seeThroughOccluderMask = -1;
        [Tooltip("A multiplier for the occluder volume size which can be used to reduce the actual size of occluders when Highlight Effect checks if they're occluding this object.")]
        [Range(0.01f, 0.6f)] public float seeThroughOccluderThreshold = 0.3f;
        [Tooltip("Uses stencil buffers to ensure pixel-accurate occlusion test. If this option is disabled, only physics raycasting is used to test for occlusion.")]
        public bool seeThroughOccluderMaskAccurate;
        [Tooltip("The interval of time between occlusion tests.")]
        public float seeThroughOccluderCheckInterval = 1f;
        [Tooltip("If enabled, occlusion test is performed for each children element. If disabled, the bounds of all children is combined and a single occlusion test is performed for the combined bounds.")]
        public bool seeThroughOccluderCheckIndividualObjects;
        [Tooltip("Shows the see-through effect only if the occluder if at this 'offset' distance from the object.")]
        public float seeThroughDepthOffset;
        [Tooltip("Hides the see-through effect if the occluder is further than this distance from the object (0 = infinite)")]
        public float seeThroughMaxDepth;
		[Tooltip("Fade-out width near Max Depth (0 keeps hard clip)")]
		public float seeThroughFadeRange;
        [Range(0, 5f)] public float seeThroughIntensity = 0.8f;
        [Range(0, 1)] public float seeThroughTintAlpha = 0.5f;
        [ColorUsage(true, true)] public Color seeThroughTintColor = Color.red;
        [Range(0, 1)] public float seeThroughNoise = 1f;
        [Range(0, 1)] public float seeThroughBorder;
        public Color seeThroughBorderColor = Color.black;
        [Tooltip("Only display the border instead of the full see-through effect.")]
        public bool seeThroughBorderOnly;
        public float seeThroughBorderWidth = 0.45f;
        [Tooltip("This option clears the stencil buffer after rendering the see-through effect which results in correct rendering order and supports other stencil-based effects that render afterwards.")]
        public bool seeThroughOrdered;
        [Tooltip("Optional see-through mask effect texture.")]
        public Texture2D seeThroughTexture;
        public TextureUVSpace seeThroughTextureUVSpace;
        public float seeThroughTextureScale = 1f;
        [Tooltip("The order by which children objects are rendered by the see-through effect")]
        public SeeThroughSortingMode seeThroughChildrenSortingMode = SeeThroughSortingMode.Default;

        /// <summary>
        /// Highlight/selection events specific to this object. If you're using Highlight Manager or Trigger, those components expose similar events. Use them instead of these.
        /// </summary>
        public event OnObjectSelectionEvent OnObjectSelected;
        public event OnObjectSelectionEvent OnObjectUnSelected;
        public event OnObjectHighlightEvent OnObjectHighlightStart;
        public event OnObjectHighlightEvent OnObjectHighlightEnd;

        /// <summary>
        /// Events that are triggered when the highlight state of the object changes.
        /// </summary>
        public event OnObjectHighlightStateEvent OnObjectHighlightStateChange;
        public event OnRendererHighlightEvent OnRendererHighlightStart;
        public event OnAnimateEvent OnTargetAnimates;
        public event OnAnimateEvent OnIconAnimates;

        struct ModelMaterials {
            public bool render; // if this object can render this frame
            public Transform transform;
            public bool renderWasVisibleDuringSetup;
            public Mesh mesh, originalMesh, bakedSkinnedMesh;
            public Renderer renderer;
            public bool isSkinnedMesh;
            public bool isParticleSystem;
            public int subMeshCount;
            public NormalsOption normalsOption;
            public Material[] fxMatMask, fxMatOutline, fxMatGlow, fxMatSolidColor, fxMatSeeThroughInner, fxMatSeeThroughBorder, fxMatOverlay, fxMatInnerGlow;
            public Matrix4x4 renderingMatrix;
            public int[] customPassIds;

            public bool isCombined;
            public bool preserveOriginalMesh => !isCombined && normalsOption == NormalsOption.PreserveOriginal;

            public void Init () {
                render = false;
                transform = null;
                mesh = originalMesh = null;
                if (bakedSkinnedMesh != null) DestroyImmediate(bakedSkinnedMesh);
                renderer = null;
                isSkinnedMesh = false;
                isParticleSystem = false;
                subMeshCount = 0;
                normalsOption = NormalsOption.Smooth;
                isCombined = false;
                customPassIds = null;
            }
        }

        public enum FadingState {
            FadingOut = -1,
            NoFading = 0,
            FadingIn = 1
        }

        [SerializeField, HideInInspector]
        ModelMaterials[] rms;
        [SerializeField, HideInInspector]
        int rmsCount;

        /// <summary>
        /// Number of objects affected by this highlight effect script
        /// </summary>
        public int includedObjectsCount => rmsCount;

        [NonSerialized]
        public bool alignToGroundTried, alignToGroundHitGood;

#if UNITY_EDITOR
        /// <summary>
        /// True if there's some static children
        /// </summary>
        [NonSerialized]
        public bool staticChildren;
#endif

        /// <summary>
        /// Returns true if the renderer for this gameobject is visible by any camera
        /// </summary>
        [NonSerialized]
        public bool isVisible;

        [NonSerialized]
        Transform _target;

        public Transform target {
            get => _target;
            set {
                if (value == null) {
                    _target = null;
                    return;
                }
                SetTarget(value);
            }
        }

        public Transform currentTarget => effectTarget != null ? effectTarget : transform;

        /// <summary>
        /// Time in which the highlight started
        /// </summary>
        [NonSerialized]
        public float highlightStartTime;

        /// <summary>
        /// Time in which the target fx started
        /// </summary>
        [NonSerialized]
        public float targetFXStartTime;

        /// <summary>
        /// Time in which the icon fx started
        /// </summary>
        [NonSerialized]
        public float iconFXStartTime;

        GameObject instantiatedIconPrefab;
        List<Material> instantiatedIconMaterials;

        bool _isSelected;
        /// <summary>
        /// True if this object is selected (if selectOnClick is used)
        /// </summary>
        public bool isSelected {
            get { return _isSelected; }
            set {
                if (_isSelected != value) {
                    if (value) {
                        if (OnObjectSelected != null && !OnObjectSelected(gameObject)) return;
                    }
                    else {
                        if (OnObjectUnSelected != null && !OnObjectUnSelected(gameObject)) return;
                    }
                    _isSelected = value;
                    if (_isSelected) lastSelected = this;
                }
            }
        }

        /// <summary>
        /// If a sprite is used with this script, spriteMode = true. Certain mesh-only options will be disabled.
        /// </summary>
        [NonSerialized]
        public bool spriteMode;

        /// <summary>
        /// If a particle system is used with this script, particleMode = true. Certain mesh-only options will be disabled.
        /// </summary>
        [NonSerialized]
        public bool particleMode;

        [NonSerialized]
        public HighlightProfile previousSettings;

        public void RestorePreviousHighlightEffectSettings () {
            if (previousSettings != null) {
                previousSettings.Load(this);
            }
        }


        /// <summary>
        /// Returns a reference to the last highlighted object
        /// </summary>
        public static HighlightEffect lastHighlighted;

        /// <summary>
        /// Returns a reference to the last selected object (when selection is managed by Highlight Manager or Trigger)
        /// </summary>
        public static HighlightEffect lastSelected;

        [NonSerialized]
        public string lastRegExError;


        #region Internal fields
        const float TAU = 0.70711f;

        // Reference materials. These are instanced per object (rms).
        static Material fxMatMask, fxMatSolidColor, fxMatSeeThrough, fxMatSeeThroughBorder, fxMatOverlay, fxMatClearStencil;
        static Material fxMatSeeThroughMask;
        static Material fxMatFocus, fxMatFocusBlur;

        // Shared template materials
        static Material fxMatGlowTemplate, fxMatInnerGlow, fxMatOutlineTemplate;
        static int sharedTemplateMaterialsRefCount;

        // Cached shaders
        static Shader shaderMask, shaderGlow, shaderInnerGlow, shaderOutline, shaderOverlay;
        static Shader shaderSeeThrough, shaderSeeThroughBorder, shaderSeeThroughMask;
        static Shader shaderTarget, shaderComposeGlow, shaderComposeOutline;
        static Shader shaderSolidColor, shaderBlurGlow, shaderBlurOutline, shaderClearStencil;
        static Shader shaderSeeThroughOccluder, shaderDepthWrite, shaderFocus;
        static Texture2D cachedNoiseTex;

        // Per-object materials
        Material fxMatTarget;
        Material fxMatComposeGlow, fxMatComposeOutline, fxMatBlurGlow, fxMatBlurOutline;
        Material fxMatIcon;

        static Vector4[] offsets;

        float fadeStartTime;
        [NonSerialized]
        public FadingState fading = FadingState.NoFading;
        CommandBuffer cbHighlight;
        bool cbHighlightEmpty;
        int[] mipGlowBuffers, mipOutlineBuffers;
        static Mesh quadMesh, cubeMesh;
        int sourceRT;
        Matrix4x4 quadGlowMatrix, quadOutlineMatrix;
        Vector4[] corners;
        RenderTextureDescriptor sourceDesc;
        Color debugColor, blackColor;
        Visibility lastOutlineVisibility;
        bool requireUpdateMaterial;
        Bounds enclosingBounds;

        [NonSerialized]
        public static List<HighlightEffect> effects = new List<HighlightEffect>();

        public static bool customSorting;
        public static bool focusRendered;
        [NonSerialized]
        public float sortingOffset; // used to avoid two objects with same distance to camera during sorting

        bool useSmoothGlow, useSmoothOutline, useSmoothBlend;
        bool useGPUInstancing;
        bool usesReversedZBuffer;
        bool usesSeeThrough;
        bool maskRequired;
        bool shouldBakeSkinnedMesh;
        bool renderMaskOnTop;

        class PerCameraOcclusionData {
            public float checkLastTime = -10000;
            public int occlusionRenderFrame;
            public bool lastOcclusionTestResult;
            public readonly List<Renderer> cachedOccluders = new List<Renderer>();
            public Collider cachedOccluderCollider;
        }
        readonly Dictionary<Camera, PerCameraOcclusionData> perCameraOcclusionData = new Dictionary<Camera, PerCameraOcclusionData>();
        MaterialPropertyBlock glowPropertyBlock, outlinePropertyBlock;
        static readonly List<Vector4> matDataDirection = new List<Vector4>();
        static readonly List<Vector4> matDataGlow = new List<Vector4>();
        static readonly List<Vector4> matDataColor = new List<Vector4>();
        static Matrix4x4[] matrices;

        int outlineOffsetsMin, outlineOffsetsMax;
        int glowOffsetsMin, glowOffsetsMax;

        Texture2D outlineGradientTex;
        Color[] outlineGradientColors;

        bool isInitialized;
        float realOutlineWidth;
        [NonSerialized]
        bool sharedTemplateMaterialsAcquired;

        #endregion



        [RuntimeInitializeOnLoadMethod]
        static void DomainReloadDisabledSupport () {
            lastHighlighted = lastSelected = null;
            effects.RemoveAll(i => i == null);
            sharedTemplateMaterialsRefCount = 0;
        }

        void OnEnable () {
            InitIfNeeded();
            CheckLabel(false);
        }

        void InitIfNeeded () {
            if (rms == null || !isInitialized || fxMatOutlineTemplate == null) {
                Init();
            }
            HighlightPlusRenderPassFeature.sortFrameCount = 0;
            if (!effects.Contains(this)) {
                effects.Add(this);
            }
            UpdateVisibilityState();
        }

        void Init () {
            lastOutlineVisibility = outlineVisibility;
            debugColor = new Color(1f, 0f, 0f, 0.5f);
            blackColor = new Color(0, 0, 0, 0);
            if (offsets == null || offsets.Length != 8) {
                offsets = new Vector4[] {
                    new Vector4(0,1),
                    new Vector4(1,0),
                    new Vector4(0,-1),
                    new Vector4(-1,0),
                    new Vector4 (-TAU, TAU),
                    new Vector4 (TAU, TAU),
                    new Vector4 (TAU, -TAU),
                    new Vector4 (-TAU, -TAU)
                };
            }
            if (corners == null || corners.Length != 8) {
                corners = new Vector4[8];
            }
            InitCommandBuffer();
            if (quadMesh == null) {
                BuildQuad();
            }
            if (cubeMesh == null) {
                BuildCube();
            }
            if (_target == null) {
                _target = currentTarget;
            }
            if (glowPasses == null || glowPasses.Length == 0) {
                glowPasses = new GlowPassData[4];
                glowPasses[0] = new GlowPassData() { offset = 4, alpha = 0.1f, color = new Color(0.64f, 1f, 0f, 1f) };
                glowPasses[1] = new GlowPassData() { offset = 3, alpha = 0.2f, color = new Color(0.64f, 1f, 0f, 1f) };
                glowPasses[2] = new GlowPassData() { offset = 2, alpha = 0.3f, color = new Color(0.64f, 1f, 0f, 1f) };
                glowPasses[3] = new GlowPassData() { offset = 1, alpha = 0.4f, color = new Color(0.64f, 1f, 0f, 1f) };
            }
            sourceRT = Shader.PropertyToID("_HPSourceRT");
            useGPUInstancing = GPUInstancing && SystemInfo.supportsInstancing;
            usesReversedZBuffer = SystemInfo.usesReversedZBuffer;

            if (useGPUInstancing) {
                if (glowPropertyBlock == null) {
                    glowPropertyBlock = new MaterialPropertyBlock();
                }
                if (outlinePropertyBlock == null) {
                    outlinePropertyBlock = new MaterialPropertyBlock();
                }
            }

            InitTemplateMaterials();

            if (profileSync && profile != null) {
                profile.Load(this);
            }

            isInitialized = true;
        }

        private void Start () {
            SetupMaterial();
        }

        public void OnDidApplyAnimationProperties () {   // support for animating property based fields
            UpdateMaterialProperties();
        }

        void OnDisable () {
            UpdateMaterialProperties(true);
            if (label != null) {
                label.Hide();
            }
            RemoveEffect();
        }

        void Reset () {
            SetupMaterial();
        }

        void OnValidate () {
            outlineGradientKnee = Mathf.Max(0f, outlineGradientKnee);
            outlineGradientPower = Mathf.Max(0f, outlineGradientPower);
            extraCoveragePixels = Mathf.Max(0, extraCoveragePixels);
            outlinePatternScale = Mathf.Max(0, outlinePatternScale);
            outlineWidth = Mathf.Max(0, outlineWidth);
            outlineDistanceScaleBias = Mathf.Max(1, outlineDistanceScaleBias);
            glowWidth = Mathf.Max(0, glowWidth);
            glowAnimationSpeed = Mathf.Max(0, glowAnimationSpeed);
            glowDistanceScaleBias = Mathf.Max(1, glowDistanceScaleBias);
            outlineDistanceScaleBias = Mathf.Max(1, outlineDistanceScaleBias);
            innerGlowPower = Mathf.Max(1f, innerGlowPower);
            overlayAnimationSpeed = Mathf.Max(0, overlayAnimationSpeed);
            targetFXTransitionDuration = Mathf.Max(0.0001f, targetFXTransitionDuration);
            targetFXStayDuration = Mathf.Max(0, targetFXStayDuration);
            targetFXFadePower = Mathf.Max(0, targetFXFadePower);
            iconFXTransitionDuration = Mathf.Max(0.0001f, iconFXTransitionDuration);
            iconFXAnimationAmount = Mathf.Max(0, iconFXAnimationAmount);
            iconFXAnimationSpeed = Mathf.Max(0, iconFXAnimationSpeed);
            iconFXStayDuration = Mathf.Max(0, iconFXStayDuration);
            iconFXScale = Mathf.Max(0, iconFXScale);
            seeThroughDepthOffset = Mathf.Max(0, seeThroughDepthOffset);
            seeThroughMaxDepth = Mathf.Max(0, seeThroughMaxDepth);
            seeThroughBorderWidth = Mathf.Max(0, seeThroughBorderWidth);
            outlineSharpness = Mathf.Max(1f, outlineSharpness);
            outlinePatternScale = Mathf.Max(0, outlinePatternScale);
            outlinePatternDistortionAmount = Mathf.Max(0, outlinePatternDistortionAmount);
            outlinePatternThreshold = Mathf.Max(0, outlinePatternThreshold);
            outlinePatternStopMotionScale = Mathf.Max(1, outlinePatternStopMotionScale);
            outlineDashSpeed = Mathf.Max(0, outlineDashSpeed);
            labelLineLength = Mathf.Max(0, labelLineLength);
            if (labelPrefab == null) {
                labelPrefab = Resources.Load<GameObject>("HighlightPlus/Label");
            }

            if (label != null) {
                // Update label position data
                label.SetPosition(labelTarget == null ? transform : labelTarget,
                                Misc.vector3Zero,
                                new Vector3(0, labelVerticalOffset, 0),
                                labelViewportOffset);
            }
        }

        void DestroyMaterial (Material mat) {
            if (mat != null) DestroyImmediate(mat);
        }

        void DestroyMaterialArray (Material[] mm) {
            if (mm == null) return;
            for (int k = 0; k < mm.Length; k++) {
                DestroyMaterial(mm[k]);
            }
        }

        void DisposeModelMaterials () {
            if (rms == null) return;
            for (int k = 0; k < rms.Length; k++) {
                if (rms[k].bakedSkinnedMesh != null) {
                    DestroyImmediate(rms[k].bakedSkinnedMesh);
                }
                DestroyMaterialArray(rms[k].fxMatMask);
                DestroyMaterialArray(rms[k].fxMatOutline);
                DestroyMaterialArray(rms[k].fxMatGlow);
                DestroyMaterialArray(rms[k].fxMatSolidColor);
                DestroyMaterialArray(rms[k].fxMatSeeThroughInner);
                DestroyMaterialArray(rms[k].fxMatSeeThroughBorder);
                DestroyMaterialArray(rms[k].fxMatOverlay);
                DestroyMaterialArray(rms[k].fxMatInnerGlow);
            }
        }

        void RemoveEffect () {
            effects.Remove(this);
        }

        void OnDestroy () {

            RemoveEffect();

            ReleaseInstantiatedIconPrefab();
            ReleaseLabel();

            DisposeModelMaterials();

            // Release shared template materials (ref-counted)
            ReleaseSharedTemplateMaterials();

            // Destroy per-instance materials
            DestroyMaterial(fxMatTarget);
            DestroyMaterial(fxMatComposeGlow);
            DestroyMaterial(fxMatComposeOutline);
            DestroyMaterial(fxMatBlurGlow);
            DestroyMaterial(fxMatBlurOutline);
            DestroyMaterial(fxMatIcon);

            if (outlineGradientTex != null) {
                DestroyImmediate(outlineGradientTex);
                outlineGradientTex = null;
            }

            combinedMeshes.Remove(combinedMeshesHashId);

            bool cleaning = true;
            while (cleaning) {
                cleaning = false;
                foreach (Mesh instancedMesh in sharedMeshUsage.Keys) {
                    if (instancedMesh == null) continue;
                    sharedMeshUsage.TryGetValue(instancedMesh, out HashSet<HighlightEffect> usageSet);
                    if (usageSet != null) usageSet.Remove(this);
                    if (usageSet == null || usageSet.Count == 0) {
                        sharedMeshUsage.Remove(instancedMesh);
                        DestroyImmediate(instancedMesh);
                        cleaning = true;
                        break;
                    }
                }
            }
        }

        private void OnBecameVisible () {
            isVisible = true;
        }

        private void OnBecameInvisible () {
            if (rms == null || rms.Length != 1 || rms[0].transform != transform) {
                // if effect group doesn't include exactly one object and this object is this same gameobject
                // ignore this optimization
                isVisible = true;
            }
            else {
                isVisible = false;
            }
        }

        /// <summary>
        /// Loads a profile into this effect
        /// </summary>
        public void ProfileLoad (HighlightProfile profile) {
            if (profile != null) {
                this.profile = profile;
                profile.Load(this);
            }
        }

        /// <summary>
        /// Reloads currently assigned profile
        /// </summary>
        public void ProfileReload () {
            if (profile != null) {
                profile.Load(this);
            }
        }


        /// <summary>
        /// Save current settings into given profile
        /// </summary>
        public void ProfileSaveChanges (HighlightProfile profile) {
            if (profile != null) {
                profile.Save(this);
            }
        }

        /// <summary>
        /// Save current settings into current profile
        /// </summary>
        public void ProfileSaveChanges () {
            if (profile != null) {
                profile.Save(this);
            }
        }

        public void GetRenderers (List<Renderer> results) {
            results.Clear();
            if (rms == null) return;

            for (int k = 0; k < rmsCount; k++) {
                if (rms[k].renderer != null) {
                    results.Add(rms[k].renderer);
                }
            }
        }

        public void Refresh (bool discardCachedMeshes = false) {
            if (discardCachedMeshes) {
                RefreshCachedMeshes();
            }
            InitIfNeeded();
            if (enabled) {
                SetupMaterial();
            }
        }

        public void ResetHighlightStartTime () {
            highlightStartTime = targetFXStartTime = iconFXStartTime = GetTime();
        }


        RenderTargetIdentifier colorAttachmentBuffer, depthAttachmentBuffer;

        public void SetCommandBuffer (CommandBuffer cmd) {
            cbHighlight = cmd;
            cbHighlightEmpty = false;
        }

        public CommandBuffer BuildCommandBuffer (Camera cam, RenderTargetIdentifier colorAttachmentBuffer, RenderTargetIdentifier depthAttachmentBuffer, bool clearStencil, ref RenderTextureDescriptor sourceDesc) {
            this.colorAttachmentBuffer = colorAttachmentBuffer;
            this.depthAttachmentBuffer = depthAttachmentBuffer;
            this.sourceDesc = sourceDesc;
            BuildCommandBuffer(cam, clearStencil);
            return cbHighlightEmpty ? null : cbHighlight;
        }

        void BuildCommandBuffer (Camera cam, bool clearStencil) {

            if (colorAttachmentBuffer == 0) {
                colorAttachmentBuffer = BuiltinRenderTextureType.CameraTarget;
            }
            if (depthAttachmentBuffer == 0) {
                depthAttachmentBuffer = BuiltinRenderTextureType.CameraTarget;
            }

            InitCommandBuffer();

            if (requireUpdateMaterial) {
                requireUpdateMaterial = false;
                UpdateMaterialProperties();
            }

            bool independentFullScreenNotExecuted = true;
            if (clearStencil) {
                ConfigureOutput();
                cbHighlight.DrawMesh(quadMesh, Matrix4x4.identity, fxMatClearStencil, 0, 0);
                HighlightPlusRenderPassFeature.RenderBlockers(cbHighlight);
                independentFullScreenNotExecuted = false;
            }

            bool seeThroughReal = usesSeeThrough;
            if (seeThroughReal) {
                ConfigureOutput();
                seeThroughReal = RenderSeeThroughOccluders(cbHighlight, cam);
                if (seeThroughReal && seeThroughOccluderMask != -1) {
                    if (seeThroughOccluderMaskAccurate) {
                        CheckOcclusionAccurate(cbHighlight, cam);
                    }
                    else {
                        seeThroughReal = CheckOcclusion(cam);
                    }
                }
            }

            bool showOverlay = hitActive || overlayMode == OverlayMode.Always;
            if (!_highlighted && !seeThroughReal && !showOverlay) {
                return;
            }

            ConfigureOutput();

            if (rms == null) {
                SetupMaterial();
                if (rms == null) return;
            }

            if (rmsCount == 0) return;

            // Check camera culling mask
            int cullingMask = cam.cullingMask;

            // Ensure renderers are valid and visible (in case LODgroup has changed active renderer)
            bool needsSetupMaterial = false;
            if (!ignoreObjectVisibility) {
                for (int k = 0; k < rmsCount; k++) {
                    if (rms[k].renderer == null || (rms[k].renderer != null && rms[k].renderer.isVisible != rms[k].renderWasVisibleDuringSetup)) {
                        needsSetupMaterial = true;
                        break;
                    }
                }
            }

            if (!needsSetupMaterial) {
                if (outline > 0 && rms[0].fxMatOutline == null) {
                    needsSetupMaterial = true;
                }
                else if (glow > 0 && rms[0].fxMatGlow == null) {
                    needsSetupMaterial = true;
                }
                else if (((outline > 0 && outlineQuality == QualityLevel.Highest) || (glow > 0 && glowQuality == QualityLevel.Highest)) && rms[0].fxMatSolidColor == null) {
                    needsSetupMaterial = true;
                }
                else if ((innerGlow > 0 || (hitFxInitialIntensity > 0 && hitFxMode == HitFxMode.InnerGlow)) && rms[0].fxMatInnerGlow == null) {
                    needsSetupMaterial = true;
                }
                else if (seeThrough != SeeThroughMode.Never && rms[0].fxMatSeeThroughInner == null) {
                    needsSetupMaterial = true;
                }
                else if (seeThrough != SeeThroughMode.Never && seeThroughBorder > 0 && rms[0].fxMatSeeThroughBorder == null) {
                    needsSetupMaterial = true;
                }
                else if ((overlay > 0 || (hitFxInitialIntensity > 0 && hitFxMode != HitFxMode.InnerGlow)) && rms[0].fxMatOverlay == null) {
                    needsSetupMaterial = true;
                }
                else if (focus > 0 && fxMatFocus == null) {
                    needsSetupMaterial = true;
                }
            }

            if (needsSetupMaterial) {
                SetupMaterial();
            }

            if (fxMatMask == null)
                return;

            // Apply effect
            cbHighlight.SetGlobalInt(ShaderParams.VertexTransformMode, vertexTransformMode);
            float glowReal = _highlighted ? this.glow : 0;
            float now = GetTime();

            // First create masks
            float aspect = cam.aspect;
            bool somePartVisible = false;

            for (int k = 0; k < rmsCount; k++) {
                rms[k].render = false;

                Transform t = rms[k].transform;
                if (t == null)
                    continue;

                if (shouldBakeSkinnedMesh && rms[k].isSkinnedMesh) {
                    SkinnedMeshRenderer smr = (SkinnedMeshRenderer)rms[k].renderer;
                    if (rms[k].bakedSkinnedMesh == null) {
                        rms[k].bakedSkinnedMesh = new Mesh();
                    }
                    smr.BakeMesh(rms[k].bakedSkinnedMesh, true);
                    rms[k].mesh = rms[k].bakedSkinnedMesh;
                    rms[k].normalsOption = NormalsOption.Smooth;
                }

                Mesh mesh = rms[k].mesh;
                if (mesh == null && !rms[k].isParticleSystem)
                    continue;

                if (!ignoreObjectVisibility) {
                    int layer = t.gameObject.layer;
                    if (((1 << layer) & cullingMask) == 0)
                        continue;
                    if (!rms[k].renderer.isVisible)
                        continue;
                }

                somePartVisible = true;
                rms[k].render = true;
                rms[k].renderingMatrix = t.localToWorldMatrix;

                if (outlineIndependent) {
                    if (useSmoothBlend) {
                        if (independentFullScreenNotExecuted) {
                            independentFullScreenNotExecuted = false;
                            cbHighlight.DrawMesh(quadMesh, Matrix4x4.identity, fxMatClearStencil, 0, 0);
                            HighlightPlusRenderPassFeature.RenderBlockers(cbHighlight);
                        }
                    }
                    else if (outline > 0 || glow > 0) {
                        bool allowGPUInstancing = useGPUInstancing && (shouldBakeSkinnedMesh || !rms[k].isSkinnedMesh) && !rms[k].isParticleSystem;

                        float width = realOutlineWidth;
                        if (glow > 0) {
                            width = Mathf.Max(width, glowWidth);
                        }
                        int subMeshCount = rms[k].subMeshCount;
                        for (int l = 0; l < subMeshCount; l++) {
                            if (((1 << l) & subMeshMask) == 0) continue;
                            if (outlineQuality.UsesMultipleOffsets()) {
                                matDataDirection.Clear();
                                for (int o = outlineOffsetsMin; o <= outlineOffsetsMax; o++) {
                                    Vector4 direction = offsets[o] * (width / 100f);
                                    direction.y *= aspect;

                                    if (allowGPUInstancing) {
                                        matDataDirection.Add(direction);
                                    }
                                    else {
                                        cbHighlight.SetGlobalVector(ShaderParams.OutlineDirection, direction);
                                        if (rms[k].isCombined) {
                                            cbHighlight.DrawMesh(rms[k].mesh, rms[k].renderingMatrix, rms[k].fxMatOutline[l], l, 1);
                                        }
                                        else {
                                            cbHighlight.DrawRenderer(rms[k].renderer, rms[k].fxMatOutline[l], l, 1);
                                        }
                                    }
                                }

                                if (allowGPUInstancing) {
                                    int instanceCount = matDataDirection.Count;
                                    if (instanceCount > 0) {
                                        outlinePropertyBlock.Clear();
                                        outlinePropertyBlock.SetVectorArray(ShaderParams.OutlineDirection, matDataDirection);
                                        if (matrices == null || matrices.Length < instanceCount) {
                                            matrices = new Matrix4x4[instanceCount];
                                        }
                                        if (rms[k].isCombined) {
                                            for (int m = 0; m < instanceCount; m++) {
                                                matrices[m] = rms[k].renderingMatrix;
                                            }
                                        }
                                        else {
                                            for (int m = 0; m < instanceCount; m++) {
                                                matrices[m] = rms[k].renderingMatrix;
                                            }
                                        }
                                        cbHighlight.DrawMeshInstanced(mesh, l, rms[k].fxMatOutline[l], 1, matrices, instanceCount, outlinePropertyBlock);
                                    }
                                }

                            }
                            else {
                                cbHighlight.SetGlobalVector(ShaderParams.OutlineDirection, Vector4.zero);
                                if (rms[k].isCombined) {
                                    cbHighlight.DrawMesh(rms[k].mesh, rms[k].renderingMatrix, rms[k].fxMatOutline[l], l, 1);
                                }
                                else {
                                    cbHighlight.DrawRenderer(rms[k].renderer, rms[k].fxMatOutline[l], l, 1);
                                }
                            }
                        }
                    }
                }

            }

            if (maskRequired) {
                if (focus > 0) {
                    cbHighlight.SetGlobalInt(ShaderParams.MaskStencilRef, 10); // 2|8: main mask bit + focus exclusion bit
                    cbHighlight.SetGlobalInt(ShaderParams.MaskWriteMask, 10);
                } else {
                    cbHighlight.SetGlobalInt(ShaderParams.MaskStencilRef, 2);
                    cbHighlight.SetGlobalInt(ShaderParams.MaskWriteMask, 2);
                }
                for (int k = 0; k < rmsCount; k++) {
                    if (rms[k].render) {
                        RenderMask(k, rms[k].mesh);
                    }
                }
            }

            // Compute tweening
            float fadeGroup = 1f;
            float fade = 1f;
            if (fading != FadingState.NoFading) {
                if (fading == FadingState.FadingIn) {
                    if (fadeInDuration > 0) {
                        fadeGroup = (now - fadeStartTime) / fadeInDuration;
                        if (fadeGroup > 1f) {
                            fadeGroup = 1f;
                            fading = FadingState.NoFading;
                        }
                    }
                }
                else if (fadeOutDuration > 0) {
                    fadeGroup = 1f - (now - fadeStartTime) / fadeOutDuration;
                    if (fadeGroup < 0f) {
                        fadeGroup = 0f;
                        fading = FadingState.NoFading;
                        _highlighted = false;
                        requireUpdateMaterial = true;
                        if (OnObjectHighlightEnd != null) {
                            OnObjectHighlightEnd(gameObject);
                        }
                        SendMessage("HighlightEnd", null, SendMessageOptions.DontRequireReceiver);
                    }
                }
            }

            if (glowQuality == QualityLevel.High) {
                glowReal *= 0.25f;
            }
            else if (glowQuality == QualityLevel.Medium) {
                glowReal *= 0.5f;
            }

            // Focus effect - fullscreen dim with optional blur/desaturation (rendered once per frame across all effects)
            float focusTintAlpha = focus * focusColor.a * fadeGroup;
            float effectiveBlur = focusBlur * focus * fadeGroup;
            float effectiveDesaturation = focusDesaturation * focus * fadeGroup;
            bool focusActive = focusTintAlpha > 0 || effectiveBlur > 0 || effectiveDesaturation > 0;
            if (focusActive && fxMatFocus != null && !focusRendered) {
                focusRendered = true;
                Color fc = focusColor;
                fc.a = focusTintAlpha;
                fxMatFocus.SetColor(ShaderParams.FocusColor, fc);

                bool needsScreenSampling = effectiveBlur > 0 || effectiveDesaturation > 0;
                if (needsScreenSampling && fxMatFocusBlur != null) {
                    fxMatFocus.SetFloat(ShaderParams.FocusDesaturation, effectiveDesaturation);

                    RenderTextureDescriptor focusBlurDesc = sourceDesc;
                    focusBlurDesc.msaaSamples = 1;
                    focusBlurDesc.depthBufferBits = 0;

                    if (effectiveBlur > 0) {
                        int ds = Mathf.Max(1, focusBlurDownsampling);
                        focusBlurDesc.width = Mathf.Max(1, focusBlurDesc.width / ds);
                        focusBlurDesc.height = Mathf.Max(1, focusBlurDesc.height / ds);
                    }

                    cbHighlight.GetTemporaryRT(ShaderParams.FocusBlurRT, focusBlurDesc, FilterMode.Bilinear);

                    if (effectiveBlur > 0) {
                        cbHighlight.GetTemporaryRT(ShaderParams.FocusBlurTempRT, focusBlurDesc, FilterMode.Bilinear);

                        float blurScale = effectiveBlur * 2f;
                        fxMatFocusBlur.SetFloat(ShaderParams.BlurScale, blurScale);

                        // H+V Gaussian blur pass 1 (camera color -> downscaled temp)
                        RenderingUtils.FullScreenBlit(cbHighlight, colorAttachmentBuffer, ShaderParams.FocusBlurTempRT, fxMatFocusBlur, 0);
                        RenderingUtils.FullScreenBlit(cbHighlight, ShaderParams.FocusBlurTempRT, ShaderParams.FocusBlurRT, fxMatFocusBlur, 1);

                        // H+V Gaussian blur pass 2 (at downscaled resolution)
                        RenderingUtils.FullScreenBlit(cbHighlight, ShaderParams.FocusBlurRT, ShaderParams.FocusBlurTempRT, fxMatFocusBlur, 0);
                        RenderingUtils.FullScreenBlit(cbHighlight, ShaderParams.FocusBlurTempRT, ShaderParams.FocusBlurRT, fxMatFocusBlur, 1);

                        cbHighlight.ReleaseTemporaryRT(ShaderParams.FocusBlurTempRT);
                    } else {
                        // Copy screen for desaturation only
                        cbHighlight.Blit(colorAttachmentBuffer, ShaderParams.FocusBlurRT);
                    }

                    // Restore render target with depth/stencil for the composite
                    cbHighlight.SetRenderTarget(colorAttachmentBuffer, depthAttachmentBuffer);

                    // Draw focus composite with blurred/desaturated background
                    cbHighlight.SetGlobalTexture(ShaderParams.FocusBlurTex, ShaderParams.FocusBlurRT);
                    cbHighlight.DrawMesh(quadMesh, Matrix4x4.identity, fxMatFocus, 0, 1);

                    cbHighlight.ReleaseTemporaryRT(ShaderParams.FocusBlurRT);
                } else if (focusTintAlpha > 0) {
                    // Simple dim without blur or desaturation
                    cbHighlight.DrawMesh(quadMesh, Matrix4x4.identity, fxMatFocus, 0, 0);
                }
            }

            bool targetEffectRendered = false;
            bool iconEffectRendered = false;
            bool usesSeeThroughBorder = (seeThroughBorder * seeThroughBorderWidth) > 0;
            bool shouldUpdateLabel = _highlighted && labelEnabled && label != null && cam.cameraType == CameraType.Game;

            if (useSmoothBlend || (targetFX && targetFXUseEnclosingBounds) || iconFX) {
                ComputeEnclosingBounds();
            }

            // Add mesh effects
            for (int k = 0; k < rmsCount; k++) {
                if (!rms[k].render)
                    continue;
                Mesh mesh = rms[k].mesh;
                int subMeshCount = rms[k].subMeshCount;

                fade = fadeGroup;

                // Distance fade
                float fadeDistance = 1f;
                if (cameraDistanceFade) {
                    fadeDistance = ComputeCameraDistanceFade(rms[k].transform.position, cam.transform);
                }
                fade *= fadeDistance;
                cbHighlight.SetGlobalFloat(ShaderParams.FadeFactor, fade);

                // Update label
                if (shouldUpdateLabel) {
                    shouldUpdateLabel = false;
                    label.alpha = labelMode == LabelMode.Always ? fadeDistance : fade;
                }

                if (_highlighted || showOverlay) {
                    // Hit FX
                    Color overlayColor = this.overlayColor;
                    float overlayMinIntensity = this.overlayMinIntensity;
                    float overlayBlending = this.overlayBlending;

                    Color innerGlowColorA = this.innerGlowColor;
                    float innerGlow = this.innerGlow;

                    if (hitActive) {
                        overlayColor.a = _highlighted ? overlay : 0;
                        innerGlowColorA.a = _highlighted ? innerGlow : 0;
                        float t = hitFadeOutDuration > 0 ? (now - hitStartTime) / hitFadeOutDuration : 1f;
                        if (t >= 1f) {
                            hitActive = false;
                        }
                        else {
                            if (hitFxMode == HitFxMode.InnerGlow) {
                                bool lerpToCurrentInnerGlow = _highlighted && innerGlow > 0;
                                innerGlowColorA = lerpToCurrentInnerGlow ? Color.Lerp(hitColor, innerGlowColor, t) : hitColor;
                                innerGlowColorA.a = lerpToCurrentInnerGlow ? Mathf.Lerp(1f - t, innerGlow, t) : 1f - t;
                                innerGlowColorA.a *= hitInitialIntensity;
                            }
                            else {
                                bool lerpToCurrentOverlay = _highlighted && overlay > 0;
                                overlayColor = lerpToCurrentOverlay ? Color.Lerp(hitColor, overlayColor, t) : hitColor;
                                overlayColor.a = lerpToCurrentOverlay ? Mathf.Lerp(1f - t, overlay, t) : 1f - t;
                                overlayColor.a *= hitInitialIntensity;
                                overlayMinIntensity = 1f;
                                overlayBlending = 0;
                            }
                        }
                    }
                    else {
                        overlayColor.a = overlay * fade;
                        innerGlowColorA.a = innerGlow * fade;
                    }

                    bool usesOverlay = overlayColor.a > 0;
                    bool usesInnerGlow = innerGlowColorA.a > 0;

                    if (usesOverlay || usesInnerGlow) {
                        for (int l = 0; l < subMeshCount; l++) {
                            if (((1 << l) & subMeshMask) == 0) continue;

                            // Overlay
                            if (usesOverlay) {
                                Material fxMat = rms[k].fxMatOverlay[l];
                                fxMat.SetColor(ShaderParams.OverlayColor, overlayColor);
                                float animSpeed = overlayAnimationSpeed;
#if UNITY_EDITOR
                                if (!Application.isPlaying) {
                                    animSpeed = 0;
                                }
#endif
                                fxMat.SetVector(ShaderParams.OverlayData, new Vector4(animSpeed, overlayMinIntensity, overlayBlending, overlayTextureScale));
                                if (hitActive && hitFxMode == HitFxMode.LocalHit) {
                                    fxMat.SetVector(ShaderParams.OverlayHitPosData, new Vector4(hitPosition.x, hitPosition.y, hitPosition.z, hitRadius));
                                    fxMat.SetFloat(ShaderParams.OverlayHitStartTime, hitStartTime);
                                }
                                else {
                                    fxMat.SetVector(ShaderParams.OverlayHitPosData, Vector4.zero);
                                }
                                if (rms[k].isCombined) {
                                    cbHighlight.DrawMesh(mesh, rms[k].renderingMatrix, rms[k].fxMatOverlay[l], l);
                                }
                                else {
                                    cbHighlight.DrawRenderer(rms[k].renderer, rms[k].fxMatOverlay[l], l);
                                }
                            }


                            // Inner Glow
                            if (usesInnerGlow && rms[k].fxMatInnerGlow != null && rms[k].fxMatInnerGlow.Length > l) {
                                Material fxMat = rms[k].fxMatInnerGlow[l];
                                if (fxMat != null) {
                                    fxMat.SetColor(ShaderParams.InnerGlowColor, innerGlowColorA);
                                    if (rms[k].isCombined) {
                                        cbHighlight.DrawMesh(rms[k].mesh, rms[k].renderingMatrix, fxMat, l);
                                    }
                                    else {
                                        cbHighlight.DrawRenderer(rms[k].renderer, fxMat, l);
                                    }
                                }
                            }
                        }
                    }
                }

                if (!_highlighted)
                    continue;

                bool usesOutlineNonHQ = outline > 0 && outlineQuality != QualityLevel.Highest;
                bool usesGlowNonHQ = glow > 0 && glowQuality != QualityLevel.Highest;

                if (usesOutlineNonHQ || usesGlowNonHQ) {
                    bool allowGPUInstancing = useGPUInstancing && (shouldBakeSkinnedMesh || !rms[k].isSkinnedMesh);

                    for (int l = 0; l < subMeshCount; l++) {
                        if (((1 << l) & subMeshMask) == 0) continue;

                        // Glow
                        if (usesGlowNonHQ) {
                            matDataGlow.Clear();
                            matDataColor.Clear();
                            matDataDirection.Clear();
                            for (int glowPass = 0; glowPass < glowPasses.Length; glowPass++) {
                                if (glowQuality.UsesMultipleOffsets()) {
                                    for (int o = glowOffsetsMin; o <= glowOffsetsMax; o++) {
                                        Vector4 direction = offsets[o];
                                        direction.y *= aspect;
                                        Color dataColor = glowPasses[glowPass].color;
                                        Vector4 dataGlow = new Vector4(fade * glowReal * glowPasses[glowPass].alpha, glowPasses[glowPass].offset * glowWidth / 100f, glowMagicNumber1, glowMagicNumber2);
                                        if (allowGPUInstancing) {
                                            matDataDirection.Add(direction);
                                            matDataGlow.Add(dataGlow);
                                            matDataColor.Add(new Vector4(dataColor.r, dataColor.g, dataColor.b, dataColor.a));
                                        }
                                        else {
                                            cbHighlight.SetGlobalVector(ShaderParams.GlowDirection, direction);
                                            cbHighlight.SetGlobalColor(ShaderParams.GlowColor, dataColor);
                                            cbHighlight.SetGlobalVector(ShaderParams.Glow, dataGlow);
                                            if (rms[k].isCombined) {
                                                cbHighlight.DrawMesh(mesh, rms[k].renderingMatrix, rms[k].fxMatGlow[l], l);
                                            }
                                            else {
                                                cbHighlight.DrawRenderer(rms[k].renderer, rms[k].fxMatGlow[l], l);
                                            }
                                        }
                                    }
                                }
                                else {
                                    Vector4 dataGlow = new Vector4(fade * glowReal * glowPasses[glowPass].alpha, glowPasses[glowPass].offset * glowWidth / 100f, glowMagicNumber1, glowMagicNumber2);
                                    Color dataColor = glowPasses[glowPass].color;
                                    if (allowGPUInstancing) {
                                        matDataDirection.Add(Vector4.zero);
                                        matDataGlow.Add(dataGlow);
                                        matDataColor.Add(new Vector4(dataColor.r, dataColor.g, dataColor.b, dataColor.a));
                                    }
                                    else {
                                        int matIndex = glowPass * 8;
                                        cbHighlight.SetGlobalColor(ShaderParams.GlowColor, dataColor);
                                        cbHighlight.SetGlobalVector(ShaderParams.Glow, dataGlow);
                                        cbHighlight.SetGlobalVector(ShaderParams.GlowDirection, Vector4.zero);
                                        if (rms[k].isCombined) {
                                            cbHighlight.DrawMesh(mesh, rms[k].renderingMatrix, rms[k].fxMatGlow[l], l);
                                        }
                                        else {
                                            cbHighlight.DrawRenderer(rms[k].renderer, rms[k].fxMatGlow[l], l);
                                        }
                                    }
                                }
                            }
                            if (allowGPUInstancing) {
                                int instanceCount = matDataDirection.Count;
                                if (instanceCount > 0) {
                                    glowPropertyBlock.Clear();
                                    glowPropertyBlock.SetVectorArray(ShaderParams.GlowDirection, matDataDirection);
                                    glowPropertyBlock.SetVectorArray(ShaderParams.GlowColor, matDataColor);
                                    glowPropertyBlock.SetVectorArray(ShaderParams.Glow, matDataGlow);
                                    if (matrices == null || matrices.Length < instanceCount) {
                                        matrices = new Matrix4x4[instanceCount];
                                    }
                                    if (rms[k].isCombined) {
                                        for (int m = 0; m < instanceCount; m++) {
                                            matrices[m] = rms[k].renderingMatrix;
                                        }
                                    }
                                    else {
                                        for (int m = 0; m < instanceCount; m++) {
                                            matrices[m] = rms[k].renderingMatrix;
                                        }
                                    }
                                    cbHighlight.DrawMeshInstanced(mesh, l, rms[k].fxMatGlow[l], 0, matrices, instanceCount, glowPropertyBlock);
                                }
                            }
                        }

                        // Outline
                        if (usesOutlineNonHQ) {
                            Color outlineColor = this.outlineColor;
                            if (outlineColorStyle == ColorStyle.Gradient) {
                                outlineColor.a *= outline * fade;
                                Bounds bounds = outlineGradientInLocalSpace ? mesh.bounds : rms[k].renderer.bounds;
                                cbHighlight.SetGlobalVector(ShaderParams.OutlineVertexData, new Vector4(bounds.min.y, bounds.size.y + 0.0001f, 0, 0));
                            }
                            else {
                                outlineColor.a *= outline * fade;
                                cbHighlight.SetGlobalVector(ShaderParams.OutlineVertexData, new Vector4(-1e6f, 1f, 0, 0));
                            }
                            cbHighlight.SetGlobalColor(ShaderParams.OutlineColor, outlineColor);
                            if (outlineQuality.UsesMultipleOffsets()) {
                                matDataDirection.Clear();
                                for (int o = outlineOffsetsMin; o <= outlineOffsetsMax; o++) {
                                    Vector4 direction = offsets[o] * (realOutlineWidth / 100f);
                                    direction.y *= aspect;
                                    if (allowGPUInstancing) {
                                        matDataDirection.Add(direction);
                                    }
                                    else {
                                        cbHighlight.SetGlobalVector(ShaderParams.OutlineDirection, direction);
                                        if (rms[k].isCombined) {
                                            cbHighlight.DrawMesh(mesh, rms[k].renderingMatrix, rms[k].fxMatOutline[l], l, 0);
                                        }
                                        else {
                                            cbHighlight.DrawRenderer(rms[k].renderer, rms[k].fxMatOutline[l], l, 0);
                                        }
                                    }
                                }
                                if (allowGPUInstancing) {
                                    int instanceCount = matDataDirection.Count;
                                    if (instanceCount > 0) {
                                        outlinePropertyBlock.Clear();
                                        outlinePropertyBlock.SetVectorArray(ShaderParams.OutlineDirection, matDataDirection);
                                        if (matrices == null || matrices.Length < instanceCount) {
                                            matrices = new Matrix4x4[instanceCount];
                                        }
                                        for (int m = 0; m < instanceCount; m++) {
                                            matrices[m] = rms[k].renderingMatrix;
                                        }
                                        cbHighlight.DrawMeshInstanced(mesh, l, rms[k].fxMatOutline[l], 0, matrices, instanceCount, outlinePropertyBlock);
                                    }
                                }
                            }
                            else {
                                cbHighlight.SetGlobalColor(ShaderParams.OutlineColor, outlineColor);
                                cbHighlight.SetGlobalVector(ShaderParams.OutlineDirection, Vector4.zero);
                                if (rms[k].isSkinnedMesh) {
                                    cbHighlight.DrawRenderer(rms[k].renderer, rms[k].fxMatOutline[l], l, 0);
                                }
                                else {
                                    // keep this because normals may be reoriented / smoothed
                                    cbHighlight.DrawMesh(mesh, rms[k].renderingMatrix, rms[k].fxMatOutline[l], l, 0);
                                }
                            }
                        }

                    }
                }

                // Target
                if (targetFX) {
                    float fadeOut = 1f;
                    if (targetFXStayDuration > 0 && Application.isPlaying) {
                        fadeOut = now - targetFXStartTime;
                        if (fadeOut >= targetFXStayDuration) {
                            fadeOut -= targetFXStayDuration;
                            fadeOut = 1f - fadeOut;
                        }
                        if (fadeOut > 1f) {
                            fadeOut = 1f;
                        }
                    }
                    bool usesTarget = targetFXCenter != null;
                    if (fadeOut > 0 && !(targetEffectRendered && (usesTarget || targetFXUseEnclosingBounds))) {
                        targetEffectRendered = true;
                        float scaleT = 1f;
                        float time;
                        float normalizedTime = 1;
                        if (Application.isPlaying) {
                            normalizedTime = (now - targetFXStartTime) / targetFXTransitionDuration;
                            if (normalizedTime > 1f) {
                                normalizedTime = 1f;
                            }
                            scaleT = Mathf.Sin(normalizedTime * Mathf.PI * 0.5f);
                            time = now;
                        }
                        else {
                            time = (float)DateTime.Now.Subtract(DateTime.Today).TotalSeconds;
                        }
                        Bounds bounds = targetFXUseEnclosingBounds ? enclosingBounds : rms[k].renderer.bounds;
                        if (!targetFXScaleToRenderBounds) {
                            bounds.size = Vector3.one;
                        }
                        Vector3 scale = bounds.size;
                        if (targetFXSquare) {
                            float maxSize = scale.x;
                            if (scale.y > maxSize) {
                                maxSize = scale.y;
                            }
                            if (scale.z > maxSize) {
                                maxSize = scale.z;
                            }
                            scale.x = scale.y = scale.z = maxSize;
                        }
                        scale = Vector3.Lerp(scale * targetFXInitialScale, scale * targetFXEndScale, scaleT);
                        Vector3 center = usesTarget ? targetFXCenter.position : bounds.center;
                        if (targetFxCenterOnHitPosition && currentHitTarget != null) {
                            center = currentHitTarget.TransformPoint(currentHitLocalPosition);
                        }
                        center += targetFXOffset;
                        Quaternion rotation;
                        if (targetFXAlignToGround) {
                            rotation = Quaternion.Euler(90, 0, 0);
                            center.y += 0.5f; // a bit of offset in case it's in contact with ground
                            alignToGroundTried = true;
                            alignToGroundHitGood = Physics.Raycast(center, Vector3.down, out RaycastHit groundHitInfo, targetFXGroundMaxDistance, targetFXGroundLayerMask);
                            if (alignToGroundHitGood) {
                                center = groundHitInfo.point;
                                center.y += 0.01f;
                                Vector4 renderData = groundHitInfo.normal;
                                renderData.w = targetFXFadePower;
                                fxMatTarget.SetVector(ShaderParams.TargetFXRenderData, renderData);
                                rotation = Quaternion.Euler(0, targetFXRotationAngle + time * targetFXRotationSpeed, 0);
                                if (OnTargetAnimates != null) {
                                    OnTargetAnimates(ref center, ref rotation, ref scale, normalizedTime);
                                }
                                Matrix4x4 m = Matrix4x4.TRS(center, rotation, scale);
                                Color color = targetFXColor;
                                color.a *= fade * fadeOut * normalizedTime;
                                fxMatTarget.color = color;
                                cbHighlight.DrawMesh(cubeMesh, m, fxMatTarget, 0, 0);
                            }
                        }
                        else {
                            alignToGroundTried = false;
                            if (targetFxAlignToNormal && currentHitNormal != Vector3.zero) {
                                // Align to hit normal
                                rotation = Quaternion.LookRotation(currentHitNormal);
                                rotation *= Quaternion.Euler(0, 0, targetFXRotationAngle + time * targetFXRotationSpeed);
                            }
                            else {
                                // Default behavior: face camera
                                rotation = Quaternion.LookRotation(cam.transform.forward);
                                rotation *= Quaternion.Euler(0, 0, targetFXRotationAngle + time * targetFXRotationSpeed);
                            }
                            if (OnTargetAnimates != null) {
                                OnTargetAnimates(ref center, ref rotation, ref scale, normalizedTime);
                            }
                            Matrix4x4 m = Matrix4x4.TRS(center, rotation, scale);
                            Color color = targetFXColor;
                            color.a *= fade * fadeOut * normalizedTime;
                            fxMatTarget.color = color;
                            cbHighlight.DrawMesh(quadMesh, m, fxMatTarget, 0, 1);
                        }
                    }
                }


                // Icon 
                if (iconFX) {
                    float fadeOut = 1f;
                    if (iconFXStayDuration > 0 && Application.isPlaying) {
                        fadeOut = (now - iconFXStartTime);
                        if (fadeOut >= iconFXStayDuration) {
                            fadeOut -= iconFXStayDuration;
                            fadeOut = 1f - fadeOut;
                        }
                        if (fadeOut > 1f) {
                            fadeOut = 1f;
                        }
                    }
                    bool usesTarget = iconFXCenter != null;
                    if (fadeOut > 0 && !(iconEffectRendered && usesTarget)) {
                        iconEffectRendered = true;
                        float scaleT = 1f;
                        float time;
                        float normalizedTime = 0;
                        if (Application.isPlaying) {
                            time = now;
                            normalizedTime = (time - iconFXStartTime) / iconFXTransitionDuration;
                            if (normalizedTime > 1f) {
                                normalizedTime = 1f;
                            }
                            scaleT = Mathf.Sin(normalizedTime * Mathf.PI * 0.5f);
                        }
                        else {
                            time = (float)DateTime.Now.Subtract(DateTime.Today).TotalSeconds;
                        }
                        Bounds bounds = enclosingBounds;
                        if (!iconFXScaleToRenderBounds) {
                            bounds.size = Vector3.one;
                        }
                        Vector3 scale = bounds.size * iconFXScale;
                        Vector3 center = usesTarget ? iconFXCenter.position : bounds.center;
                        center += iconFXOffset;
                        switch (iconFXAnimationOption) {
                            case IconAnimationOption.VerticalBounce:
                                center.y += iconFXAnimationAmount * Mathf.Abs(Mathf.Sin((now - iconFXStartTime) * iconFXAnimationSpeed));
                                break;
                        }
                        Quaternion rotation = Quaternion.Euler(0, time * iconFXRotationSpeed, 0);
                        if (OnIconAnimates != null) {
                            OnIconAnimates(ref center, ref rotation, ref scale, normalizedTime);
                        }

                        if (iconFXAssetType == IconAssetType.Prefab) {
                            if (instantiatedIconPrefab != null && instantiatedIconMaterials != null) {
                                instantiatedIconPrefab.SetActive(true);
                                Transform t = instantiatedIconPrefab.transform;
                                t.position = center;
                                t.rotation = rotation;
                                Vector3 originalScale = iconFXPrefab.transform.localScale;
                                scale.x *= originalScale.x;
                                scale.y *= originalScale.y;
                                scale.z *= originalScale.z;
                                t.localScale = scale;
                                if (fadeOut < 1f) {
                                    foreach (Material m in instantiatedIconMaterials) {
                                        Color c = m.color;
                                        c.a *= fadeOut;
                                        m.color = c;
                                    }
                                }
                            }
                        }
                        else if (iconFXMesh != null) {
                            Matrix4x4 m = Matrix4x4.TRS(center, rotation, scale);
                            Material mat = fxMatIcon;
                            Color lightColor = iconFXLightColor;
                            lightColor.a *= fade * fadeOut;
                            mat.color = lightColor;
                            Color darkColor = iconFXDarkColor;
                            darkColor.a *= fade * fadeOut;
                            mat.SetColor(ShaderParams.IconFXDarkColor, darkColor);
                            cbHighlight.DrawMesh(iconFXMesh, m, mat);
                        }
                    }
                    else if (fadeOut <= 0) {
                        HideIconPrefab();
                    }
                }
                else {
                    HideIconPrefab();
                }
            }


            if (useSmoothBlend && _highlighted && somePartVisible) {

                // Prepare smooth outer glow / outline target
                sourceDesc.colorFormat = useSmoothOutline && outlineEdgeMode == OutlineEdgeMode.Any ? RenderTextureFormat.ARGB32 : RenderTextureFormat.R8;
                sourceDesc.msaaSamples = 1;
                sourceDesc.useMipMap = false;
                sourceDesc.depthBufferBits = 0;

                // avoid using excessively large buffers
                const int maxSourceRTWidth = 1920;
                if (sourceDesc.width > maxSourceRTWidth) {
                    float aspectRatio = (float)sourceDesc.height / sourceDesc.width;
                    sourceDesc.height = Mathf.RoundToInt(maxSourceRTWidth * aspectRatio);
                    sourceDesc.width = maxSourceRTWidth;
                }

                int smoothRTWidth = sourceDesc.width;
                int smoothRTHeight = sourceDesc.height;

                cbHighlight.GetTemporaryRT(sourceRT, sourceDesc, FilterMode.Bilinear);
                RenderTargetIdentifier sourceTarget = new RenderTargetIdentifier(sourceRT, 0, CubemapFace.Unknown, -1);
                cbHighlight.SetRenderTarget(sourceTarget);
                cbHighlight.ClearRenderTarget(false, true, new Color(0, 0, 0, 0));

                for (int k = 0; k < rmsCount; k++) {
                    if (!rms[k].render)
                        continue;

                    // Render object body for glow/outline highest quality
                    Mesh mesh = rms[k].mesh;
                    int subMeshCount = rms[k].subMeshCount;
                    for (int l = 0; l < subMeshCount; l++) {
                        if (((1 << l) & subMeshMask) == 0) continue;
                        if (useOriginalShader) {
                            Material[] originalMaterials = rms[k].renderer.sharedMaterials;
                            if (l < originalMaterials.Length) {
                                int passId = -1;
                                if (rms[k].customPassIds != null && l < rms[k].customPassIds.Length) {
                                    passId = rms[k].customPassIds[l];
                                }
                                if (passId >= 0) {
                                    cbHighlight.DrawRenderer(rms[k].renderer, originalMaterials[l], l, passId);
                                }
                            }
                        }
                        else {
                            if (l < rms[k].fxMatSolidColor.Length) {
                                if (rms[k].isCombined) {
                                    cbHighlight.DrawMesh(rms[k].mesh, rms[k].renderingMatrix, rms[k].fxMatSolidColor[l], l);
                                }
                                else {
                                    cbHighlight.DrawRenderer(rms[k].renderer, rms[k].fxMatSolidColor[l], l);
                                }
                            }
                        }
                    }
                }

                if (ComputeSmoothQuadMatrix(cam, enclosingBounds)) {

                    // Smooth Glow
                    if (useSmoothGlow) {
                        float intensity = glow * fade;
                        fxMatComposeGlow.color = new Color(glowHQColor.r * intensity, glowHQColor.g * intensity, glowHQColor.b * intensity, glowHQColor.a * intensity);
                        SmoothGlow(smoothRTWidth / glowDownsampling, smoothRTHeight / glowDownsampling);
                    }

                    // Smooth Outline
                    if (useSmoothOutline) {
                        float intensity = outline * fade;
                        fxMatComposeOutline.color = new Color(outlineColor.r, outlineColor.g, outlineColor.b, outlineColor.a * intensity * 10f);
                        SmoothOutline(smoothRTWidth / outlineDownsampling, smoothRTHeight / outlineDownsampling);
                    }

                    // Bit result
                    ComposeSmoothBlend(glowVisibility, outlineVisibility);
                }
            }

            // See-through
            if (seeThroughReal) {
                if (renderMaskOnTop) {
                    for (int k = 0; k < rmsCount; k++) {
                        if (!rms[k].render)
                            continue;
                        Mesh mesh = rms[k].mesh;
                        RenderSeeThroughClearStencil(k, mesh);
                    }
                    for (int k = 0; k < rmsCount; k++) {
                        if (!rms[k].render)
                            continue;
                        Mesh mesh = rms[k].mesh;
                        RenderSeeThroughMask(k, mesh);
                    }
                }
                for (int k = 0; k < rmsCount; k++) {
                    if (!rms[k].render)
                        continue;
                    Mesh mesh = rms[k].mesh;
                    int subMeshCount = rms[k].subMeshCount;
                    for (int l = 0; l < subMeshCount; l++) {
                        if (((1 << l) & subMeshMask) == 0) continue;
                        if (l < rms[k].fxMatSeeThroughInner.Length && rms[k].fxMatSeeThroughInner[l] != null) {
                            if (rms[k].isCombined) {
                                cbHighlight.DrawMesh(mesh, rms[k].renderingMatrix, rms[k].fxMatSeeThroughInner[l], l);
                            }
                            else {
                                cbHighlight.DrawRenderer(rms[k].renderer, rms[k].fxMatSeeThroughInner[l], l);
                            }
                        }
                    }
                }

                if (usesSeeThroughBorder) {
                    for (int k = 0; k < rmsCount; k++) {
                        if (!rms[k].render)
                            continue;
                        Mesh mesh = rms[k].mesh;
                        int subMeshCount = rms[k].subMeshCount;
                        for (int l = 0; l < subMeshCount; l++) {
                            if (((1 << l) & subMeshMask) == 0) continue;
                            if (rms[k].isCombined) {
                                cbHighlight.DrawMesh(mesh, rms[k].renderingMatrix, rms[k].fxMatSeeThroughBorder[l], l);
                            }
                            else {
                                cbHighlight.DrawRenderer(rms[k].renderer, rms[k].fxMatSeeThroughBorder[l], l);
                            }
                        }
                    }
                }

                if (seeThroughOrdered) { // Ordered for see-through
                    for (int k = 0; k < rmsCount; k++) {
                        if (!rms[k].render)
                            continue;
                        Mesh mesh = rms[k].mesh;
                        int subMeshCount = rms[k].subMeshCount;
                        for (int l = 0; l < subMeshCount; l++) {
                            if (((1 << l) & subMeshMask) == 0) continue;
                            if (rms[k].isCombined) {
                                cbHighlight.DrawMesh(mesh, rms[k].renderingMatrix, fxMatClearStencil, l, 1);
                            }
                            else {
                                cbHighlight.DrawRenderer(rms[k].renderer, fxMatClearStencil, l, 1);
                            }
                        }
                    }
                }
            }
        }



        void RenderMask (int k, Mesh mesh) {
            int subMeshCount = rms[k].subMeshCount;
            for (int l = 0; l < subMeshCount; l++) {
                if (((1 << l) & subMeshMask) == 0) continue;
                if (rms[k].isCombined) {
                    cbHighlight.DrawMesh(rms[k].mesh, rms[k].renderingMatrix, rms[k].fxMatMask[l], l, 0);
                }
                else {
                    cbHighlight.DrawRenderer(rms[k].renderer, rms[k].fxMatMask[l], l, 0);
                }
            }
        }

        void RenderSeeThroughClearStencil (int k, Mesh mesh) {
            int subMeshCount = rms[k].subMeshCount;
            if (rms[k].isCombined) {
                for (int l = 0; l < subMeshCount; l++) {
                    if (((1 << l) & subMeshMask) == 0) continue;
                    cbHighlight.DrawMesh(mesh, rms[k].renderingMatrix, fxMatClearStencil, l, 1);
                }
            }
            else {
                for (int l = 0; l < subMeshCount; l++) {
                    if (((1 << l) & subMeshMask) == 0) continue;
                    cbHighlight.DrawRenderer(rms[k].renderer, fxMatClearStencil, l, 1);
                }
            }
        }

        void RenderSeeThroughMask (int k, Mesh mesh) {
            int subMeshCount = rms[k].subMeshCount;
            if (rms[k].isCombined) {
                for (int l = 0; l < subMeshCount; l++) {
                    if (((1 << l) & subMeshMask) == 0) continue;
                    cbHighlight.DrawMesh(mesh, rms[k].renderingMatrix, rms[k].fxMatMask[l], l, 1);
                }
            }
            else {
                for (int l = 0; l < subMeshCount; l++) {
                    if (((1 << l) & subMeshMask) == 0) continue;
                    cbHighlight.DrawRenderer(rms[k].renderer, rms[k].fxMatMask[l], l, 1);
                }
            }
        }


        void WorldToViewportPoint (ref Matrix4x4 m, ref Vector4 p, bool perspectiveProjection, float zBufferParamsZ, float zBufferParamsW) {
            p = m * p;
            p.x = (p.x / p.w + 1f) * 0.5f;
            p.y = (p.y / p.w + 1f) * 0.5f;

            if (perspectiveProjection) {
                p.z /= p.w;
                p.z = 1.0f / (zBufferParamsZ * p.z + zBufferParamsW);
            }
            else {
                if (usesReversedZBuffer) {
                    p.z = 1f - p.z;
                }
                p.z = (zBufferParamsW - zBufferParamsZ) * p.z + zBufferParamsZ;
            }
        }

        void ComputeEnclosingBounds () {

            if (rmsCount == 0 || rms == null) {
                enclosingBounds.SetMinMax(Misc.vector3Zero, Misc.vector3Zero);
                return;
            }

            Vector3 min = Misc.vector3Max, max = Misc.vector3Min;
            Vector3 boundsMin, boundsMax;

            for (int k = 0; k < rmsCount; k++) {
                if (!rms[k].render && rms[k].isCombined)
                    continue;
                if (rms[k].renderer == null) continue;

                Bounds bounds = rms[k].renderer.bounds;
                Vector3 center = bounds.center;
                Vector3 extents = bounds.extents;
                boundsMin.x = center.x - extents.x;
                boundsMin.y = center.y - extents.y;
                boundsMin.z = center.z - extents.z;
                boundsMax.x = center.x + extents.x;
                boundsMax.y = center.y + extents.y;
                boundsMax.z = center.z + extents.z;
                if (k == 0) {
                    min = boundsMin;
                    max = boundsMax;
                }
                else {
                    if (boundsMin.x < min.x) {
                        min.x = boundsMin.x;
                    }
                    if (boundsMin.y < min.y) {
                        min.y = boundsMin.y;
                    }
                    if (boundsMin.z < min.z) {
                        min.z = boundsMin.z;
                    }
                    if (boundsMax.x > max.x) {
                        max.x = boundsMax.x;
                    }
                    if (boundsMax.y > max.y) {
                        max.y = boundsMax.y;
                    }
                    if (boundsMax.z > max.z) {
                        max.z = boundsMax.z;
                    }
                }
            }
            enclosingBounds.SetMinMax(min, max);
        }



        float smoothEffectDistance; // Store distance for use in SmoothGlow/SmoothOutline

        bool ComputeSmoothQuadMatrix (Camera cam, Bounds bounds) {
            // Compute bounds in screen space and enlarge for glow space
            bool res;
            if (VRCheck.isVrRunning) {
                Vector3 shift = Vector3.zero;
                res = ComputeSmoothQuadMatrixOriginShifted(cam, ref bounds, ref shift);
            }
            else {
                Transform camTransform = cam.transform;
                Vector3 shift = camTransform.position;
                camTransform.position = Vector3.zero;
                cam.ResetWorldToCameraMatrix();
                bounds.center -= shift;
                res = ComputeSmoothQuadMatrixOriginShifted(cam, ref bounds, ref shift);
                camTransform.position = shift;
            }
            return res;
        }

        bool ComputeSmoothQuadMatrixOriginShifted (Camera cam, ref Bounds bounds, ref Vector3 shift) {
            // Compute bounds in screen space and enlarge for glow space

            Matrix4x4 wcm = cam.worldToCameraMatrix;

            Matrix4x4 mat = GL.GetGPUProjectionMatrix(cam.projectionMatrix, false) * wcm;
            Vector3 min = bounds.min;
            Vector3 max = bounds.max;
            corners[0] = new Vector4(min.x, min.y, min.z, 1f);
            corners[1] = new Vector4(min.x, min.y, max.z, 1f);
            corners[2] = new Vector4(max.x, min.y, min.z, 1f);
            corners[3] = new Vector4(max.x, min.y, max.z, 1f);
            corners[4] = new Vector4(min.x, max.y, min.z, 1f);
            corners[5] = new Vector4(min.x, max.y, max.z, 1f);
            corners[6] = new Vector4(max.x, max.y, min.z, 1f);
            corners[7] = new Vector4(max.x, max.y, max.z, 1f);
            Vector3 scrMin = new Vector3(float.MaxValue, float.MaxValue, 0);
            Vector3 scrMax = new Vector3(float.MinValue, float.MinValue, 0);
            float distanceMin = float.MaxValue;
            float distanceMax = float.MinValue;
            float nearClipPlane = cam.nearClipPlane;
            float farClipPlane = cam.farClipPlane;

            float x, y, z, w;
            bool isPerspectiveCamera = !cam.orthographic;
            if (isPerspectiveCamera) {
                if (usesReversedZBuffer) {
                    x = -1f + farClipPlane / nearClipPlane;
                    y = 1f;
                    z = x / farClipPlane;
                    w = 1f / farClipPlane;
                }
                else {
                    x = 1f - farClipPlane / nearClipPlane;
                    y = farClipPlane / nearClipPlane;
                    z = x / farClipPlane;
                    w = y / farClipPlane;
                }
            }
            else {
                z = nearClipPlane;
                w = farClipPlane;
            }

            for (int k = 0; k < 8; k++) {
                WorldToViewportPoint(ref mat, ref corners[k], isPerspectiveCamera, z, w);
                if (corners[k].x < scrMin.x) {
                    scrMin.x = corners[k].x;
                }
                if (corners[k].y < scrMin.y) {
                    scrMin.y = corners[k].y;
                }
                if (corners[k].x > scrMax.x) {
                    scrMax.x = corners[k].x;
                }
                if (corners[k].y > scrMax.y) {
                    scrMax.y = corners[k].y;
                }
                if (corners[k].z < distanceMin) {
                    distanceMin = corners[k].z;
                    if (distanceMin < nearClipPlane) {
                        distanceMin = distanceMax = 0.01f + nearClipPlane;
                        scrMin.x = scrMin.y = 0;
                        scrMax.x = 1f;
                        scrMax.y = 1f;
                        break;
                    }
                }
                if (corners[k].z > distanceMax) {
                    distanceMax = corners[k].z;
                }
            }
            if (scrMax.y == scrMin.y)
                return false;

            int pixelWidth = cam.pixelWidth;
            int pixelHeight = cam.pixelHeight;
            Rect pixelRect = cam.pixelRect;
            scrMin.x *= pixelWidth;
            scrMax.x *= pixelWidth;
            scrMin.y *= pixelHeight;
            scrMax.y *= pixelHeight;
            scrMin.x += pixelRect.xMin;
            scrMax.x += pixelRect.xMin;
            scrMin.y += pixelRect.yMin;
            scrMax.y += pixelRect.yMin;

            // Store the average distance for use in blur effects
            smoothEffectDistance = (distanceMin + distanceMax) * 0.5f;

            if (spriteMode || particleMode) {
                scrMin.z = scrMax.z = smoothEffectDistance + nearClipPlane;
            }
            else {
                scrMin.z = scrMax.z = VRCheck.isVrRunning ? distanceMin : 0.05f + nearClipPlane; // small shift to avoid origin far issues
            }

            if (outline > 0) {
                BuildMatrix(cam, scrMin, scrMax, (int)(10 + 20 * realOutlineWidth + 5 * outlineDownsampling), ref quadOutlineMatrix, ref shift);
            }
            if (glow > 0) {
                BuildMatrix(cam, scrMin, scrMax, (int)(20 + 30 * glowWidth + 10 * glowDownsampling), ref quadGlowMatrix, ref shift);
            }
            return true;
        }

        void BuildMatrix (Camera cam, Vector3 scrMin, Vector3 scrMax, int border, ref Matrix4x4 quadMatrix, ref Vector3 shift) {

            // Insert padding to make room for effects
            border += extraCoveragePixels;
            scrMin.x -= border;
            scrMin.y -= border;
            scrMax.x += border;
            scrMax.y += border;

            // Back to world space
            Vector3 third = new Vector3(scrMax.x, scrMin.y, scrMin.z);
            scrMin = cam.ScreenToWorldPoint(scrMin);
            scrMax = cam.ScreenToWorldPoint(scrMax);
            third = cam.ScreenToWorldPoint(third);

            float width = Vector3.Distance(scrMin, third);
            float height = Vector3.Distance(scrMax, third);

            quadMatrix = Matrix4x4.TRS((scrMin + scrMax) * 0.5f + shift, cam.transform.rotation, new Vector3(width, height, 1f));
        }

        void SmoothGlow (int rtWidth, int rtHeight) {

            RenderTextureDescriptor glowDesc = sourceDesc;

            float widthScale = 1f;
            if (!constantWidth) {
                widthScale = Mathf.Max(minimumWidth, 1f - Mathf.Log(1 + smoothEffectDistance / glowDistanceScaleBias));
            }

            // Apply distance-based scale for blur width
            float blurScale = glowWidth * widthScale;

            glowDesc.colorFormat = glowHighPrecision ? RenderTextureFormat.RHalf : RenderTextureFormat.R8;
            glowDesc.depthBufferBits = 0;

            if (glowBlurMethod == BlurMethod.Gaussian) {

                // Adjust number of blur passes based on distance
                int blurPasses = 4;
                if (!constantWidth && blurScale < 1f) {
                    blurPasses = Mathf.Max(1, Mathf.RoundToInt(4 * blurScale));
                    blurScale *= 4f / blurPasses;
                }

                fxMatBlurGlow.SetFloat(ShaderParams.BlurScale, blurScale / glowDownsampling);

                // Blur buffers
                int bufferCount = blurPasses * 2;
                if (mipGlowBuffers == null || mipGlowBuffers.Length != bufferCount) {
                    mipGlowBuffers = new int[bufferCount];
                    for (int k = 0; k < bufferCount; k++) {
                        mipGlowBuffers[k] = Shader.PropertyToID("_HPSmoothGlowTemp" + k);
                    }
                }
                mipGlowBuffers[bufferCount - 2] = ShaderParams.GlowRT;

                for (int k = 0; k < bufferCount; k++) {
                    float reduction = k / 2 + 2;
                    int reducedWidth = (int)(rtWidth / reduction);
                    int reducedHeight = (int)(rtHeight / reduction);
                    if (reducedWidth <= 0) {
                        reducedWidth = 1;
                    }
                    if (reducedHeight <= 0) {
                        reducedHeight = 1;
                    }
                    glowDesc.width = reducedWidth;
                    glowDesc.height = reducedHeight;
                    cbHighlight.GetTemporaryRT(mipGlowBuffers[k], glowDesc, FilterMode.Bilinear);
                }

                if (useOriginalShader) {
                    cbHighlight.EnableShaderKeyword(ShaderParams.SKW_SOURCE_SOLID_COLOR);
                }

                for (int k = 0; k < bufferCount - 1; k += 2) {
                    if (k == 0) {
                        RenderingUtils.FullScreenBlit(cbHighlight, sourceRT, mipGlowBuffers[k + 1], fxMatBlurGlow, 0);
                        cbHighlight.DisableShaderKeyword(ShaderParams.SKW_SOURCE_SOLID_COLOR);
                    }
                    else {
                        RenderingUtils.FullScreenBlit(cbHighlight, mipGlowBuffers[k], mipGlowBuffers[k + 1], fxMatBlurGlow, 0);
                    }
                    RenderingUtils.FullScreenBlit(cbHighlight, mipGlowBuffers[k + 1], mipGlowBuffers[k], fxMatBlurGlow, 1);

                    if (k < bufferCount - 2) {
                        RenderingUtils.FullScreenBlit(cbHighlight, mipGlowBuffers[k], mipGlowBuffers[k + 2], fxMatBlurGlow, 2);
                    }
                }
            }
            else {
                // Adjust number of blur passes based on distance (Kawase method)
                int blurPasses = 4;
                if (!constantWidth && blurScale < 1f) {
                    blurPasses = Mathf.Max(1, Mathf.RoundToInt(4 * blurScale));
                    blurScale *= 4f / blurPasses;
                }
                fxMatBlurGlow.SetFloat(ShaderParams.BlurScale, blurScale / glowDownsampling);

                int bufferCount = blurPasses;
                if (mipGlowBuffers == null || mipGlowBuffers.Length != bufferCount) {
                    mipGlowBuffers = new int[bufferCount];
                    for (int k = 0; k < bufferCount - 1; k++) {
                        mipGlowBuffers[k] = Shader.PropertyToID("_HPSmoothGlowTemp" + k);
                    }
                    mipGlowBuffers[bufferCount - 1] = ShaderParams.GlowRT;
                }

                for (int k = 0; k < bufferCount; k++) {
                    float reduction = k + 2;
                    int reducedWidth = (int)(rtWidth / reduction);
                    int reducedHeight = (int)(rtHeight / reduction);
                    if (reducedWidth <= 0) {
                        reducedWidth = 1;
                    }
                    if (reducedHeight <= 0) {
                        reducedHeight = 1;
                    }
                    glowDesc.width = reducedWidth;
                    glowDesc.height = reducedHeight;
                    cbHighlight.GetTemporaryRT(mipGlowBuffers[k], glowDesc, FilterMode.Bilinear);
                }
                if (useOriginalShader) {
                    cbHighlight.EnableShaderKeyword(ShaderParams.SKW_SOURCE_SOLID_COLOR);
                }
                RenderingUtils.FullScreenBlit(cbHighlight, sourceRT, mipGlowBuffers[0], fxMatBlurGlow, 3);
                cbHighlight.DisableShaderKeyword(ShaderParams.SKW_SOURCE_SOLID_COLOR);
                for (int k = 0; k < bufferCount - 1; k++) {
                    cbHighlight.SetGlobalFloat(ShaderParams.ResampleScale, k + 0.5f);
                    RenderingUtils.FullScreenBlit(cbHighlight, mipGlowBuffers[k], mipGlowBuffers[k + 1], fxMatBlurGlow, 3);
                }
            }
        }

        void SmoothOutline (int rtWidth, int rtHeight) {

            // Apply edge width clamping if needed
            float edgeWidth = realOutlineWidth;
            if (outlineEdgeMode == OutlineEdgeMode.Any) {
                edgeWidth = Mathf.Clamp(edgeWidth, outlineBlurPasses / 5f, outlineBlurPasses);
            }

            // Apply distance-based scale for blur width
            float blurScale = edgeWidth;
            float widthScale = 1f;
            if (!constantWidth) {
                widthScale = Mathf.Max(minimumWidth, 1f - Mathf.Log(1 + smoothEffectDistance / outlineDistanceScaleBias));
                blurScale *= widthScale;
            }

            // Adjust blur passes based on distance
            int adjustedBlurPasses = outlineBlurPasses;
            if (!constantWidth && blurScale < 1f) {
                // Reduce blur passes as object gets farther
                adjustedBlurPasses = Mathf.Max(1, Mathf.RoundToInt(outlineBlurPasses * blurScale));
                blurScale *= (float)outlineBlurPasses / adjustedBlurPasses;
            }

            // Set the blur scale with distance adjustment
            fxMatBlurOutline.SetFloat(ShaderParams.BlurScale, blurScale / outlineDownsampling);
            fxMatBlurOutline.SetFloat(ShaderParams.BlurScaleFirstHoriz, blurScale * 2f);

            // Blur buffers
            int bufferCount = adjustedBlurPasses * 2;
            if (mipOutlineBuffers == null || mipOutlineBuffers.Length != bufferCount) {
                mipOutlineBuffers = new int[bufferCount];
                for (int k = 0; k < bufferCount; k++) {
                    mipOutlineBuffers[k] = Shader.PropertyToID("_HPSmoothOutlineTemp" + k);
                }
            }
            mipOutlineBuffers[bufferCount - 2] = ShaderParams.OutlineRT;

            RenderTextureDescriptor outlineDesc = sourceDesc;
            outlineDesc.depthBufferBits = 0;

            for (int k = 0; k < bufferCount; k++) {
                float reduction = k / 2 + 2;
                int reducedWidth = (int)(rtWidth / reduction);
                int reducedHeight = (int)(rtHeight / reduction);
                if (reducedWidth <= 0) {
                    reducedWidth = 1;
                }
                if (reducedHeight <= 0) {
                    reducedHeight = 1;
                }
                outlineDesc.width = reducedWidth;
                outlineDesc.height = reducedHeight;
                cbHighlight.GetTemporaryRT(mipOutlineBuffers[k], outlineDesc, FilterMode.Bilinear);
            }

            for (int k = 0; k < bufferCount - 1; k += 2) {
                if (k == 0) {
                    RenderingUtils.FullScreenBlit(cbHighlight, sourceRT, mipOutlineBuffers[k + 1], fxMatBlurOutline, 3);
                }
                else {
                    RenderingUtils.FullScreenBlit(cbHighlight, mipOutlineBuffers[k], mipOutlineBuffers[k + 1], fxMatBlurOutline, 0);
                }
                RenderingUtils.FullScreenBlit(cbHighlight, mipOutlineBuffers[k + 1], mipOutlineBuffers[k], fxMatBlurOutline, 1);

                if (k < bufferCount - 2) {
                    RenderingUtils.FullScreenBlit(cbHighlight, mipOutlineBuffers[k], mipOutlineBuffers[k + 2], fxMatBlurOutline, 2);
                }
            }
        }


        void ComposeSmoothBlend (Visibility smoothGlowVisibility, Visibility smoothOutlineVisibility) {

            // Render mask on target surface
            var useDepthRenderBuffer = colorAttachmentBuffer != BuiltinRenderTextureType.CameraTarget && depthAttachmentBuffer == BuiltinRenderTextureType.CameraTarget;
            cbHighlight.SetRenderTarget(colorAttachmentBuffer, useDepthRenderBuffer ? colorAttachmentBuffer : depthAttachmentBuffer);
            //            cbHighlight.SetRenderTarget(colorAttachmentBuffer, depthAttachmentBuffer);

            bool renderSmoothGlow = glow > 0 && glowWidth > 0 && glowQuality == QualityLevel.Highest;
            if (renderSmoothGlow) {
                fxMatComposeGlow.SetVector(ShaderParams.Flip, (VRCheck.isVrRunning && flipY) ? new Vector4(1, -1) : new Vector4(0, 1));
                fxMatComposeGlow.SetInt(ShaderParams.ZTest, GetZTestValue(smoothGlowVisibility));
                cbHighlight.DrawMesh(quadMesh, quadGlowMatrix, fxMatComposeGlow, 0, 0);
            }
            bool renderSmoothOutline = outline > 0 && realOutlineWidth > 0 && outlineQuality == QualityLevel.Highest;
            if (renderSmoothOutline) {
                fxMatComposeOutline.SetVector(ShaderParams.Flip, (VRCheck.isVrRunning && flipY) ? new Vector4(1, -1) : new Vector4(0, 1));
                fxMatComposeOutline.SetInt(ShaderParams.ZTest, GetZTestValue(smoothOutlineVisibility));
                cbHighlight.DrawMesh(quadMesh, quadOutlineMatrix, fxMatComposeOutline, 0, 0);
            }
            // Release render textures
            if (renderSmoothGlow) {
                for (int k = 0; k < mipGlowBuffers.Length; k++) {
                    cbHighlight.ReleaseTemporaryRT(mipGlowBuffers[k]);
                }
            }
            if (renderSmoothOutline) {
                for (int k = 0; k < mipOutlineBuffers.Length; k++) {
                    cbHighlight.ReleaseTemporaryRT(mipOutlineBuffers[k]);
                }
            }

            cbHighlight.ReleaseTemporaryRT(sourceRT);
        }

        void InitMaterial (ref Material material, ref Shader cachedShader, string shaderName) {
            if (material != null) return;
            if (cachedShader == null) {
                cachedShader = Shader.Find(shaderName);
                if (cachedShader == null) {
                    Debug.LogError("Shader " + shaderName + " not found.");
                    return;
                }
            }
            material = new Material(cachedShader);
        }

        void Fork (Material material, ref Material[] array, int count) {
            if (array == null || array.Length < count) {
                DestroyMaterialArray(array);
                array = new Material[count];
            }
            for (int k = 0; k < count; k++) {
                if (array[k] == null) {
                    array[k] = Instantiate(material);
                }
            }
        }

        /// <summary>
        /// Sets target for highlight effects
        /// </summary>
        public void SetTarget (Transform transform) {
            if (transform == null) return;
            InitIfNeeded();
            if (transform != _target) {
                if (_highlighted) {
                    ImmediateFadeOut();
                }
                _target = transform;
                SetupMaterial();
            }
            else {
                UpdateVisibilityState();
            }
        }

        /// <summary>
        /// Sets target for highlight effects and also specify a list of renderers to be included as well
        /// </summary>
        public void SetTargets (Transform transform, Renderer[] renderers) {
            if (transform == null)
                return;

            InitIfNeeded();
            if (_highlighted) {
                ImmediateFadeOut();
            }

            effectGroup = TargetOptions.Scripting;
            _target = transform;
            SetupMaterial(renderers);
        }


        /// <summary>
        /// Start or finish highlight on the object
        /// </summary>
        public void SetHighlighted (bool state) {

            if (state != _highlighted && OnObjectHighlightStateChange != null) {
                if (!OnObjectHighlightStateChange(gameObject, state)) return;
            }

            if (state) lastHighlighted = this;

            if (!Application.isPlaying) {
                _highlighted = state;
                return;
            }

            float now = GetTime();

            if (fading == FadingState.NoFading) {
                fadeStartTime = now;
            }

            if (state && !ignore) {
                if (_highlighted && fading == FadingState.NoFading) {
                    return;
                }
                if (OnObjectHighlightStart != null) {
                    if (!OnObjectHighlightStart(gameObject)) {
                        return;
                    }
                }
                SendMessage("HighlightStart", null, SendMessageOptions.DontRequireReceiver);
                highlightStartTime = targetFXStartTime = iconFXStartTime = now;
                if (fadeInDuration > 0) {
                    if (fading == FadingState.FadingOut) {
                        float remaining = fadeOutDuration - (now - fadeStartTime);
                        fadeStartTime = now - remaining;
                        fadeStartTime = Mathf.Min(fadeStartTime, now);
                    }
                    fading = FadingState.FadingIn;
                }
                else {
                    fading = FadingState.NoFading;
                }
                _highlighted = true;
                requireUpdateMaterial = true;
                if (hitFXTriggerMode == HitFXTriggerMode.WhenHighlighted) {
                    HitFX();
                }
            }
            else if (_highlighted) {
                if (fadeOutDuration > 0) {
                    if (fading == FadingState.FadingIn) {
                        float elapsed = now - fadeStartTime;
                        fadeStartTime = now + elapsed - fadeInDuration;
                        fadeStartTime = Mathf.Min(fadeStartTime, now);
                    }
                    fading = FadingState.FadingOut; // when fade out ends, highlighted will be set to false in OnRenderObject
                }
                else {
                    fading = FadingState.NoFading;
                    ImmediateFadeOut();
                    requireUpdateMaterial = true;
                }
            }
        }

        void ImmediateFadeOut () {
            fading = FadingState.NoFading;
            _highlighted = false;
            HideIconPrefab();
            if (OnObjectHighlightEnd != null) {
                OnObjectHighlightEnd(gameObject);
            }
            SendMessage("HighlightEnd", null, SendMessageOptions.DontRequireReceiver);
        }

        void SetupMaterial () {

#if UNITY_EDITOR
            staticChildren = false;
#endif

            if (target == null || fxMatMask == null)
                return;

            IList<Renderer> rr = null;
            switch (effectGroup) {
                case TargetOptions.OnlyThisObject:
                    if (target.TryGetComponent(out Renderer renderer) && ValidRenderer(renderer)) {
                        tempRR.Clear();
                        tempRR.Add(renderer);
                        rr = tempRR;
                    }
                    break;
                case TargetOptions.RootToChildren:
                    HighlightRoot hroot = target.GetComponentInParent<HighlightRoot>(true);
                    if (hroot == null) {
                        rr = FindRenderersInChildren(target.root);
                    }
                    else {
                        rr = FindRenderersInChildren(hroot.transform);
                    }
                    break;
                case TargetOptions.LayerInScene: {
                        HighlightEffect eg = this;
                        if (target != transform) {
                            if (target.TryGetComponent(out HighlightEffect targetEffect)) {
                                eg = targetEffect;
                            }
                        }
                        rr = FindRenderersWithLayerInScene(eg.effectGroupLayer);
                    }
                    break;
                case TargetOptions.LayerInChildren: {
                        HighlightEffect eg = this;
                        if (target != transform) {
                            if (target.TryGetComponent(out HighlightEffect targetEffect)) {
                                eg = targetEffect;
                            }
                        }
                        rr = FindRenderersWithLayerInChildren(eg.effectGroupLayer);
                    }
                    break;
                case TargetOptions.Children:
                    rr = FindRenderersInChildren(target);
                    break;
                case TargetOptions.Scripting:
                    UpdateMaterialProperties();
                    return;
            }

            SetupMaterial(rr);
        }

        void SetupMaterial (IList<Renderer> rr) {

            if (rr == null) {
                rr = Array.Empty<Renderer>();
            }
            if (rms == null || rms.Length < rr.Count) {
                DisposeModelMaterials();
                rms = new ModelMaterials[rr.Count];
            }
            InitCommandBuffer();

            spriteMode = false;
            particleMode = false;
            rmsCount = 0;

            // Load noise texture once before loop if glow is enabled
            if (glow > 0 && fxMatGlowTemplate != null) {
                if (cachedNoiseTex == null) {
                    cachedNoiseTex = Resources.Load<Texture2D>("HighlightPlus/blueNoiseVL");
                }
                fxMatGlowTemplate.SetTexture(ShaderParams.NoiseTex, cachedNoiseTex);
            }

            // Precompute invariant filter conditions
            bool useNameFilter = effectGroup != TargetOptions.OnlyThisObject && !string.IsNullOrEmpty(effectNameFilter);
            Regex filterRegex = null;
            if (useNameFilter && effectNameUseRegEx) {
                try {
                    filterRegex = new Regex(effectNameFilter);
                    lastRegExError = "";
                }
                catch (Exception ex) {
                    lastRegExError = ex.Message;
                    useNameFilter = false;
                }
            }

            int rrCount = rr.Count;
            for (int k = 0; k < rrCount; k++) {
                rms[rmsCount].Init();
                Renderer renderer = rr[k];
                if (renderer == null) continue;
                if (useNameFilter) {
                    if (filterRegex != null) {
                        if (!filterRegex.IsMatch(renderer.name)) continue;
                    }
                    else {
                        if (!renderer.name.Contains(effectNameFilter)) continue;
                    }
                }
                rms[rmsCount].renderer = renderer;
                rms[rmsCount].renderWasVisibleDuringSetup = renderer.isVisible;
                sortingOffset = GetObjectId(renderer.gameObject) % 0.0001f;

                if (renderer.transform != target) {
                    if (renderer.TryGetComponent(out HighlightEffect otherEffect) && otherEffect.enabled && (otherEffect.ignore || excludeObjectsWithHighlightEffect)) {
                        continue; // ignore this object
                    }
                }

                if (OnRendererHighlightStart != null) {
                    if (!OnRendererHighlightStart(renderer)) {
                        rmsCount++;
                        continue;
                    }
                }

                rms[rmsCount].isCombined = false;
                bool isSkinnedMesh = renderer is SkinnedMeshRenderer;
                rms[rmsCount].isSkinnedMesh = isSkinnedMesh;
                bool isSpriteRenderer = renderer is SpriteRenderer;
                bool isParticleRenderer = renderer is ParticleSystemRenderer;
                rms[rmsCount].isParticleSystem = isParticleRenderer;
                rms[rmsCount].normalsOption = isSkinnedMesh ? NormalsOption.PreserveOriginal : normalsOption;
                if (isSpriteRenderer) {
                    rms[rmsCount].mesh = quadMesh;
                    spriteMode = renderer.gameObject.activeInHierarchy;
                }
                else if (isParticleRenderer) {
                    rms[rmsCount].mesh = null;
                    particleMode = renderer.gameObject.activeInHierarchy;
                }
                else if (isSkinnedMesh) {
                    // ignore cloth skinned renderers
                    rms[rmsCount].mesh = ((SkinnedMeshRenderer)renderer).sharedMesh;
                }
                else if (Application.isPlaying && renderer.isPartOfStaticBatch) {
                    // static batched objects need to have a mesh collider in order to use its original mesh
                    if (renderer.TryGetComponent(out MeshCollider mc)) {
                        rms[rmsCount].mesh = mc.sharedMesh;
                    }
                }
                else {
                    if (renderer.TryGetComponent(out MeshFilter mf)) {
                        rms[rmsCount].mesh = mf.sharedMesh;

#if UNITY_EDITOR
                        if (renderer.gameObject.isStatic && renderer.GetComponent<MeshCollider>() == null) {
                            staticChildren = true;
                        }
#endif

                    }
                }

                if (rms[rmsCount].mesh == null && !isParticleRenderer) {
                    continue;
                }

                rms[rmsCount].transform = renderer.transform;

                int subMeshCount;
                if (isParticleRenderer) {
                    renderer.GetSharedMaterials(rendererSharedMaterials);
                    subMeshCount = rendererSharedMaterials.Count;
                } else {
                    subMeshCount = rms[rmsCount].mesh.subMeshCount;
                }
                rms[rmsCount].subMeshCount = subMeshCount;
                Fork(fxMatMask, ref rms[rmsCount].fxMatMask, subMeshCount);
                if (outline > 0 || outlineIndependent) {
                    Fork(fxMatOutlineTemplate, ref rms[rmsCount].fxMatOutline, subMeshCount);
                }
                if (glow > 0) {
                    Fork(fxMatGlowTemplate, ref rms[rmsCount].fxMatGlow, subMeshCount);
                }
                if (seeThrough != SeeThroughMode.Never) {
                    Fork(fxMatSeeThrough, ref rms[rmsCount].fxMatSeeThroughInner, subMeshCount);
                    if (seeThroughBorder > 0) {
                        Fork(fxMatSeeThroughBorder, ref rms[rmsCount].fxMatSeeThroughBorder, subMeshCount);
                    }
                }
                if (overlay > 0 || (hitFxInitialIntensity > 0 && hitFxMode != HitFxMode.InnerGlow)) {
                    Fork(fxMatOverlay, ref rms[rmsCount].fxMatOverlay, subMeshCount);
                }
                if (innerGlow > 0 || (hitFxInitialIntensity > 0 && hitFxMode == HitFxMode.InnerGlow)) {
                    Fork(fxMatInnerGlow, ref rms[rmsCount].fxMatInnerGlow, subMeshCount);
                }
                if (outlineQuality == QualityLevel.Highest || glowQuality == QualityLevel.Highest) {
                    Fork(fxMatSolidColor, ref rms[rmsCount].fxMatSolidColor, subMeshCount);
                }
                rms[rmsCount].originalMesh = rms[rmsCount].mesh;
                if (!isParticleRenderer && !rms[rmsCount].preserveOriginalMesh) {
                    if (innerGlow > 0 || (glow > 0 && glowQuality != QualityLevel.Highest) || (outline > 0 && outlineQuality != QualityLevel.Highest)) {
                        if (normalsOption == NormalsOption.Reorient) {
                            ReorientNormals(rmsCount);
                        }
                        else {
                            AverageNormals(rmsCount);
                        }
                    }
                }
                rmsCount++;
            }

#if UNITY_EDITOR
            // Avoids command buffer issue when refreshing asset inside the Editor
            if (!Application.isPlaying) {
                mipGlowBuffers = null;
                mipOutlineBuffers = null;
            }
#endif

            if (spriteMode) {
                outlineIndependent = false;
                cullBackFaces = false;
                seeThrough = SeeThroughMode.Never;
                if (alphaCutOff <= 0) {
                    alphaCutOff = 0.5f;
                }
                bool recheckMaterials = false;
                if (outline > 0 && outlineQuality != QualityLevel.Highest) {
                    outlineQuality = QualityLevel.Highest;
                    recheckMaterials = true;
                }
                if (glow > 0 && glowQuality != QualityLevel.Highest) {
                    glowQuality = QualityLevel.Highest;
                    recheckMaterials = true;
                }
                if (innerGlow > 0) {
                    innerGlow = 0;
                    recheckMaterials = true;
                }
                if (recheckMaterials) {
                    // settings have changed, need to ensure materials are forked correctly
                    SetupMaterial(rr);
                    return;
                }
            }
            else if (particleMode) {
                outlineIndependent = false;
                cullBackFaces = false;
                seeThrough = SeeThroughMode.Never;
                if (alphaCutOff <= 0) {
                    alphaCutOff = 0.5f;
                }
                bool recheckMaterials = false;
                if (outline > 0 && outlineQuality != QualityLevel.Highest) {
                    outlineQuality = QualityLevel.Highest;
                    recheckMaterials = true;
                }
                if (glow > 0 && glowQuality != QualityLevel.Highest) {
                    glowQuality = QualityLevel.Highest;
                    recheckMaterials = true;
                }
                if (innerGlow > 0) {
                    innerGlow = 0;
                    recheckMaterials = true;
                }
                if (recheckMaterials) {
                    // settings have changed, need to ensure materials are forked correctly
                    SetupMaterial(rr);
                    return;
                }
            }
            else {
                if (combineMeshes) {
                    CombineMeshes();
                }
            }

            UpdateMaterialProperties();
        }

        readonly List<Renderer> tempRR = new List<Renderer>();

        bool ValidRenderer (Renderer r) {
            return r is MeshRenderer || r is SpriteRenderer || r is SkinnedMeshRenderer || r is ParticleSystemRenderer;
        }

        IList<Renderer> FindRenderersWithLayerInScene (LayerMask layer) {
            Renderer[] rr = Misc.FindObjectsOfType<Renderer>();
            tempRR.Clear();
            int rrLen = rr.Length;
            for (var i = 0; i < rrLen; i++) {
                Renderer r = rr[i];
                if (((1 << r.gameObject.layer) & layer) != 0 && ValidRenderer(r)) {
                    tempRR.Add(r);
                }
            }
            return tempRR;
        }

        IList<Renderer> FindRenderersWithLayerInChildren (LayerMask layer) {
            tempRR.Clear();
            target.GetComponentsInChildren(true, tempRR);
            int write = 0;
            int tempRRCount = tempRR.Count;
            for (var i = 0; i < tempRRCount; i++) {
                Renderer r = tempRR[i];
                if (((1 << r.gameObject.layer) & layer) != 0 && ValidRenderer(r)) {
                    tempRR[write++] = r;
                }
            }
            if (write < tempRRCount) {
                tempRR.RemoveRange(write, tempRRCount - write);
            }
            return tempRR;
        }

        IList<Renderer> FindRenderersInChildren (Transform parent) {
            tempRR.Clear();
            parent.GetComponentsInChildren(true, tempRR);
            int write = 0;
            int tempRRCount = tempRR.Count;
            for (var i = 0; i < tempRRCount; i++) {
                Renderer r = tempRR[i];
                if (ValidRenderer(r)) {
                    tempRR[write++] = r;
                }
            }
            if (write < tempRRCount) {
                tempRR.RemoveRange(write, tempRRCount - write);
            }
            return tempRR;
        }

        void InitTemplateMaterials () {
            // Track ref count for shared template materials
            if (!sharedTemplateMaterialsAcquired) {
                sharedTemplateMaterialsAcquired = true;
                sharedTemplateMaterialsRefCount++;
            }

            // Static shared materials
            InitMaterial(ref fxMatMask, ref shaderMask, "HighlightPlus/Geometry/Mask");
            InitMaterial(ref fxMatOverlay, ref shaderOverlay, "HighlightPlus/Geometry/Overlay");
            InitMaterial(ref fxMatSeeThrough, ref shaderSeeThrough, "HighlightPlus/Geometry/SeeThrough");
            InitMaterial(ref fxMatSeeThroughBorder, ref shaderSeeThroughBorder, "HighlightPlus/Geometry/SeeThroughBorder");
            InitMaterial(ref fxMatSeeThroughMask, ref shaderSeeThroughMask, "HighlightPlus/Geometry/SeeThroughMask");
            InitMaterial(ref fxMatSolidColor, ref shaderSolidColor, "HighlightPlus/Geometry/SolidColor");
            InitMaterial(ref fxMatClearStencil, ref shaderClearStencil, "HighlightPlus/ClearStencil");
            if (focus > 0) {
                InitMaterial(ref fxMatFocus, ref shaderFocus, "HighlightPlus/Geometry/Focus");
                InitMaterial(ref fxMatFocusBlur, ref shaderBlurGlow, "HighlightPlus/Geometry/BlurGlow");
                if (fxMatFocusBlur != null) {
                    fxMatFocusBlur.SetFloat(ShaderParams.Speed, 0);
                }
            }

            // Shared template materials (used only as source for Fork)
            InitMaterial(ref fxMatGlowTemplate, ref shaderGlow, "HighlightPlus/Geometry/Glow");
            if (fxMatGlowTemplate != null && useGPUInstancing && !fxMatGlowTemplate.enableInstancing) {
                fxMatGlowTemplate.enableInstancing = true;
            }
            InitMaterial(ref fxMatInnerGlow, ref shaderInnerGlow, "HighlightPlus/Geometry/InnerGlow");
            InitMaterial(ref fxMatOutlineTemplate, ref shaderOutline, "HighlightPlus/Geometry/Outline");
            if (fxMatOutlineTemplate != null && useGPUInstancing && !fxMatOutlineTemplate.enableInstancing) {
                fxMatOutlineTemplate.enableInstancing = true;
            }

            // Per-instance materials (conditional based on settings)
            if (targetFX) {
                InitMaterial(ref fxMatTarget, ref shaderTarget, "HighlightPlus/Geometry/Target");
            }
            if (glow > 0 && glowQuality == QualityLevel.Highest) {
                InitMaterial(ref fxMatComposeGlow, ref shaderComposeGlow, "HighlightPlus/Geometry/ComposeGlow");
                InitMaterial(ref fxMatBlurGlow, ref shaderBlurGlow, "HighlightPlus/Geometry/BlurGlow");
            }
            if (outline > 0 && outlineQuality == QualityLevel.Highest) {
                InitMaterial(ref fxMatComposeOutline, ref shaderComposeOutline, "HighlightPlus/Geometry/ComposeOutline");
                InitMaterial(ref fxMatBlurOutline, ref shaderBlurOutline, "HighlightPlus/Geometry/BlurOutline");
            }
        }

        void ReleaseSharedTemplateMaterials () {
            if (!sharedTemplateMaterialsAcquired) return;
            sharedTemplateMaterialsAcquired = false;
            if (sharedTemplateMaterialsRefCount <= 0) return;
            sharedTemplateMaterialsRefCount--;
            if (sharedTemplateMaterialsRefCount > 0) return;
            DestroyMaterial(fxMatGlowTemplate);
            DestroyMaterial(fxMatInnerGlow);
            DestroyMaterial(fxMatOutlineTemplate);
            fxMatGlowTemplate = null;
            fxMatInnerGlow = null;
            fxMatOutlineTemplate = null;
        }

        void InitCommandBuffer () {
            if (cbHighlight == null) {
                cbHighlight = new CommandBuffer();
                cbHighlight.name = name;
            }
            cbHighlightEmpty = true;
        }


        void ConfigureOutput () {
            if (!cbHighlightEmpty) return;
            cbHighlightEmpty = false;

#if UNITY_2022_1_OR_NEWER
            // depth priming might have changed depth render target so we ensure it's set to normal
            colorAttachmentBuffer = new RenderTargetIdentifier(colorAttachmentBuffer, 0, CubemapFace.Unknown, -1);
            depthAttachmentBuffer = new RenderTargetIdentifier(depthAttachmentBuffer, 0, CubemapFace.Unknown, -1);
#if UNITY_2023_1_OR_NEWER // used as workaround for render graph - a bug sets depth load buffer action to don't care instead of load. This redundant setRenderTarget call fixes it
            cbHighlight.SetRenderTarget(colorAttachmentBuffer, RenderBufferLoadAction.Load, RenderBufferStoreAction.Store, depthAttachmentBuffer, RenderBufferLoadAction.Load, RenderBufferStoreAction.Store);
#endif
            cbHighlight.SetRenderTarget(colorAttachmentBuffer, depthAttachmentBuffer);
#elif UNITY_2021_2_OR_NEWER
            var useDepthRenderBuffer = colorAttachmentBuffer != BuiltinRenderTextureType.CameraTarget && depthAttachmentBuffer == BuiltinRenderTextureType.CameraTarget;
            cbHighlight.SetRenderTarget(colorAttachmentBuffer, useDepthRenderBuffer ? colorAttachmentBuffer : depthAttachmentBuffer);
#endif
        }

        public void UpdateVisibilityState () {
            // isVisible only accounts for cases where there's a single object managed by the highlight effect
            // and that object can receive OnBecameVisible/OnBecameInvisible. Otherwise we can't use this optimization
            if (rms == null || rms.Length != 1 || rms[0].transform != transform || rms[0].renderer == null) {
                isVisible = true;
            }
            else if (rms[0].renderer != null) {
                isVisible = rms[0].renderer.isVisible;
            }
        }


        public void UpdateMaterialProperties (bool disabling = false) {

            if (rms == null)
                return;

            if (ignore) {
                _highlighted = false;
            }

            UpdateVisibilityState();

            CheckLabel(disabling);

            usesSeeThrough = seeThroughIntensity > 0 && (seeThrough == SeeThroughMode.AlwaysWhenOccluded || (seeThrough == SeeThroughMode.WhenHighlighted && _highlighted));
            bool outlineWantsMask = _highlighted && outline > 0 && outlineMaskMode != MaskMode.IgnoreMask;
            bool glowWantsMask = _highlighted && glow > 0 && glowMaskMode != MaskMode.IgnoreMask;

            MaskMode a_outlineMaskMode = useOriginalShader ? MaskMode.CutoutOnly : outlineMaskMode;
            MaskMode a_glowMaskMode = useOriginalShader ? MaskMode.CutoutOnly : glowMaskMode;

            bool outlineNeedsStencil = outlineWantsMask && (outlineQuality != QualityLevel.Highest || a_outlineMaskMode != MaskMode.CutoutOnly);
            bool glowNeedsStencil = glowWantsMask && (glowQuality != QualityLevel.Highest || a_glowMaskMode != MaskMode.CutoutOnly);

            maskRequired = usesSeeThrough || outlineNeedsStencil || glowNeedsStencil || (_highlighted && focus > 0);

            // Resort materials if needed
            if (usesSeeThrough && seeThroughChildrenSortingMode != SeeThroughSortingMode.Default && rms.Length > 0) {
                if (seeThroughChildrenSortingMode == SeeThroughSortingMode.SortByMaterialsRenderQueue) {
                    Array.Sort(rms, MaterialsRenderQueueComparer);
                }
                else {
                    Array.Sort(rms, MaterialsRenderQueueInvertedComparer);
                }
            }

            Color seeThroughTintColor = this.seeThroughTintColor;
            seeThroughTintColor.a = this.seeThroughTintAlpha;

            if (lastOutlineVisibility != outlineVisibility) {
                // change by scripting?
                if (glowQuality == QualityLevel.Highest && outlineQuality == QualityLevel.Highest) {
                    glowVisibility = outlineVisibility;
                }
                lastOutlineVisibility = outlineVisibility;
            }
            if (outlineQuality == QualityLevel.Medium) {
                outlineOffsetsMin = 4; outlineOffsetsMax = 7;
            }
            else if (outlineQuality == QualityLevel.High) {
                outlineOffsetsMin = 0; outlineOffsetsMax = 7;
            }
            else {
                outlineOffsetsMin = outlineOffsetsMax = 0;
            }
            realOutlineWidth = outlineWidth + (outlineQuality != QualityLevel.Highest ? padding : 0);

            if (glowQuality == QualityLevel.Medium) {
                glowOffsetsMin = 4; glowOffsetsMax = 7;
            }
            else if (glowQuality == QualityLevel.High) {
                glowOffsetsMin = 0; glowOffsetsMax = 7;
            }
            else {
                glowOffsetsMin = glowOffsetsMax = 0;
            }

            shouldBakeSkinnedMesh = optimizeSkinnedMesh && ((outline > 0 && outlineQuality != QualityLevel.Highest) || (glow > 0 && glowQuality != QualityLevel.Highest));
            useSmoothGlow = glow > 0 && glowWidth > 0 && glowQuality == QualityLevel.Highest;
            useSmoothOutline = outline > 0 && realOutlineWidth > 0 && outlineQuality == QualityLevel.Highest;
            useSmoothBlend = useSmoothGlow || useSmoothOutline;

            // Create materials on-demand if settings changed at runtime
            if (useSmoothGlow && fxMatComposeGlow == null) {
                InitMaterial(ref fxMatComposeGlow, ref shaderComposeGlow, "HighlightPlus/Geometry/ComposeGlow");
                InitMaterial(ref fxMatBlurGlow, ref shaderBlurGlow, "HighlightPlus/Geometry/BlurGlow");
            }
            if (useSmoothOutline && fxMatComposeOutline == null) {
                InitMaterial(ref fxMatComposeOutline, ref shaderComposeOutline, "HighlightPlus/Geometry/ComposeOutline");
                InitMaterial(ref fxMatBlurOutline, ref shaderBlurOutline, "HighlightPlus/Geometry/BlurOutline");
            }
            if (focus > 0 && fxMatFocus == null) {
                InitMaterial(ref fxMatFocus, ref shaderFocus, "HighlightPlus/Geometry/Focus");
                InitMaterial(ref fxMatFocusBlur, ref shaderBlurGlow, "HighlightPlus/Geometry/BlurGlow");
                if (fxMatFocusBlur != null) {
                    fxMatFocusBlur.SetFloat(ShaderParams.Speed, 0);
                }
            }
            if (useSmoothBlend) {
                if (useSmoothGlow && useSmoothOutline) {
                    outlineVisibility = glowVisibility;
                }
                outlineEdgeThreshold = Mathf.Clamp01(outlineEdgeThreshold);
            }

            renderMaskOnTop = _highlighted && ((outline > 0 && outlineVisibility != Visibility.Normal) || (glow > 0 && glowVisibility != Visibility.Normal) || (innerGlow > 0 && innerGlowVisibility != Visibility.Normal));
            renderMaskOnTop = renderMaskOnTop | (useSmoothBlend && outlineContourStyle == ContourStyle.AroundObjectShape);

            if (useSmoothGlow) {
                fxMatComposeGlow.SetInt(ShaderParams.Cull, cullBackFaces ? (int)CullMode.Back : (int)CullMode.Off);
                fxMatComposeGlow.SetFloat(ShaderParams.Padding, Mathf.Max(0.001f, 1f - padding));
                fxMatComposeGlow.SetInt(ShaderParams.Pixelation, glowPixelation);
                if (glowBlendMode == GlowBlendMode.Additive) {
                    fxMatComposeGlow.SetInt(ShaderParams.BlendSrc, (int)BlendMode.One);
                    fxMatComposeGlow.SetInt(ShaderParams.BlendDst, (int)BlendMode.One);
                }
                else {
                    fxMatComposeGlow.SetInt(ShaderParams.BlendSrc, (int)BlendMode.SrcAlpha);
                    fxMatComposeGlow.SetInt(ShaderParams.BlendDst, (int)BlendMode.OneMinusSrcAlpha);
                }
                fxMatComposeGlow.SetColor(ShaderParams.Debug, glowBlitDebug ? debugColor : blackColor);
                fxMatComposeGlow.SetInt(ShaderParams.GlowStencilComp, (a_glowMaskMode == MaskMode.IgnoreMask || a_glowMaskMode == MaskMode.CutoutOnly) ? (int)CompareFunction.Always : (int)CompareFunction.NotEqual);
                if (a_glowMaskMode == MaskMode.StencilAndCutout || a_glowMaskMode == MaskMode.CutoutOnly) {
                    fxMatComposeGlow.EnableKeyword(ShaderParams.SKW_MASK_CUTOUT);
                }
                else {
                    fxMatComposeGlow.DisableKeyword(ShaderParams.SKW_MASK_CUTOUT);
                }
                if (outlineEdgeMode == OutlineEdgeMode.Exterior) {
                    fxMatComposeGlow.DisableKeyword(ShaderParams.SKW_ALL_EDGES);
                }
                else {
                    fxMatComposeGlow.EnableKeyword(ShaderParams.SKW_ALL_EDGES);
                }
                float animSpeed = glowAnimationSpeed;
#if UNITY_EDITOR
                if (!Application.isPlaying) {
                    animSpeed = 0;
                }
#endif
                fxMatBlurGlow.SetFloat(ShaderParams.Speed, animSpeed);
            }

            // Configure blur outline material for custom shader usage
            if (useSmoothOutline && fxMatBlurOutline != null) {
                if (useOriginalShader) {
                    fxMatBlurOutline.EnableKeyword(ShaderParams.SKW_SOURCE_SOLID_COLOR);
                }
                else {
                    fxMatBlurOutline.DisableKeyword(ShaderParams.SKW_SOURCE_SOLID_COLOR);
                }
            }

            if (outline > 0 && outlineColorStyle == ColorStyle.Gradient && outlineGradient != null) {
                const int OUTLINE_GRADIENT_TEX_SIZE = 32;
                bool requiresUpdate = false;
                if (outlineGradientTex == null) {
                    outlineGradientTex = new Texture2D(OUTLINE_GRADIENT_TEX_SIZE, 1, TextureFormat.RGBA32, mipChain: false, linear: true);
                    outlineGradientTex.wrapMode = TextureWrapMode.Clamp;
                    requiresUpdate = true;
                }
                if (outlineGradientColors == null || outlineGradientColors.Length != OUTLINE_GRADIENT_TEX_SIZE) {
                    outlineGradientColors = new Color[OUTLINE_GRADIENT_TEX_SIZE];
                    requiresUpdate = true;
                }
                for (int k = 0; k < OUTLINE_GRADIENT_TEX_SIZE; k++) {
                    float t = (float)k / OUTLINE_GRADIENT_TEX_SIZE;
                    Color color = outlineGradient.Evaluate(t);
                    if (color != outlineGradientColors[k]) {
                        outlineGradientColors[k] = color;
                        requiresUpdate = true;
                    }
                }
                if (requiresUpdate) {
                    outlineGradientTex.SetPixels(outlineGradientColors);
                    outlineGradientTex.Apply();
                }
            }

            // Outline hq
            if (useSmoothOutline) {
                fxMatComposeOutline.SetInt(ShaderParams.Cull, cullBackFaces ? (int)CullMode.Back : (int)CullMode.Off);
                fxMatComposeOutline.SetColor(ShaderParams.Debug, outlineBlitDebug ? debugColor : blackColor);
                fxMatComposeOutline.SetFloat(ShaderParams.OutlineSharpness, outlineSharpness);
                fxMatComposeOutline.SetFloat(ShaderParams.Padding, Mathf.Max(0.001f, 1f - padding));
                fxMatComposeOutline.SetInt(ShaderParams.Pixelation, outlinePixelation);

                // Pass pattern properties
                if (outlineStylized) {
                    fxMatComposeOutline.EnableKeyword(ShaderParams.SKW_OUTLINE_STYLIZED);
                    fxMatComposeOutline.SetTexture(ShaderParams.PatternTex, outlinePattern);
                    if (outlinePatternDistortionTexture == null) {
                        outlinePatternDistortionTexture = Resources.Load<Texture2D>("HighlightPlus/charcoal");
                    }
                    fxMatComposeOutline.SetTexture(ShaderParams.DistortionTex, outlinePatternDistortionTexture);
                    fxMatComposeOutline.SetVector(ShaderParams.PatternData, new Vector4(outlinePatternScale, outlinePatternThreshold, outlinePatternDistortionAmount * 0.01f, outlinePatternStopMotionScale));
                }
                else {
                    fxMatComposeOutline.DisableKeyword(ShaderParams.SKW_OUTLINE_STYLIZED);
                }

                if (outlineDashed) {
                    fxMatComposeOutline.EnableKeyword(ShaderParams.SKW_OUTLINE_DASHED);
                    fxMatComposeOutline.SetVector(ShaderParams.DashData, new Vector4(1.001f - outlineDashWidth, 1f - outlineDashGap * 2f, outlineDashSpeed, 0));
                }
                else {
                    fxMatComposeOutline.DisableKeyword(ShaderParams.SKW_OUTLINE_DASHED);
                }

                if (outlineEdgeMode == OutlineEdgeMode.Exterior) {
                    fxMatComposeOutline.DisableKeyword(ShaderParams.SKW_ALL_EDGES);
                }
                else {
                    fxMatComposeOutline.EnableKeyword(ShaderParams.SKW_ALL_EDGES);
                    outlineDownsampling = 1;
                }
                if (outlineEdgeMode != OutlineEdgeMode.Exterior || a_outlineMaskMode == MaskMode.IgnoreMask || a_outlineMaskMode == MaskMode.CutoutOnly || (outlineQuality == QualityLevel.Highest && outlineStylized)) {
                    fxMatComposeOutline.SetInt(ShaderParams.OutlineStencilComp, (int)CompareFunction.Always);
                }
                else {
                    fxMatComposeOutline.SetInt(ShaderParams.OutlineStencilComp, (int)CompareFunction.NotEqual);
                }
                if (a_outlineMaskMode == MaskMode.StencilAndCutout || a_outlineMaskMode == MaskMode.CutoutOnly) {
                    fxMatComposeOutline.EnableKeyword(ShaderParams.SKW_MASK_CUTOUT);
                }
                else {
                    fxMatComposeOutline.DisableKeyword(ShaderParams.SKW_MASK_CUTOUT);
                }

                if (outlineColorStyle == ColorStyle.Gradient) {
                    fxMatComposeOutline.SetTexture(ShaderParams.OutlineGradientTex, outlineGradientTex);
                    fxMatComposeOutline.SetVector(ShaderParams.OutlineGradientData, new Vector4(outlineGradientKnee, outlineGradientPower, 0, 0));
                    fxMatComposeOutline.EnableKeyword(ShaderParams.SKW_OUTLINE_GRADIENT_WS);
                }
                else {
                    fxMatComposeOutline.DisableKeyword(ShaderParams.SKW_OUTLINE_GRADIENT_WS);
                }
            }

            // Setup materials

            // Target
            if (targetFX) {
                if (fxMatTarget == null) {
                    InitMaterial(ref fxMatTarget, ref shaderTarget, "HighlightPlus/Geometry/Target");
                }
                if (targetFXTexture == null) {
                    targetFXTexture = Resources.Load<Texture2D>("HighlightPlus/target");
                }
                fxMatTarget.mainTexture = targetFXTexture;
                fxMatTarget.SetInt(ShaderParams.ZTest, GetZTestValue(targetFXVisibility));
                fxMatTarget.DisableKeyword(ShaderParams.SKW_TARGET_FRAME);
                fxMatTarget.DisableKeyword(ShaderParams.SKW_TARGET_INWARD_CORNERS);
                fxMatTarget.DisableKeyword(ShaderParams.SKW_TARGET_CROSS);
                fxMatTarget.SetVector(ShaderParams.TargetFXFrameData, new Vector4(targetFXFrameWidth, targetFXCornerLength, targetFXFrameMinOpacity, targetFXGroundMinAltitude));
                switch (targetFXStyle) {
                    case TargetFXStyle.Frame:
                        fxMatTarget.EnableKeyword(ShaderParams.SKW_TARGET_FRAME);
                        break;
                    case TargetFXStyle.InwardCorners:
                        fxMatTarget.EnableKeyword(ShaderParams.SKW_TARGET_INWARD_CORNERS);
                        break;
                    case TargetFXStyle.Cross:
                        fxMatTarget.EnableKeyword(ShaderParams.SKW_TARGET_CROSS);
                        break;
                    default:
                        break;
                }
            }

            // Icon
            if (iconFX && _highlighted) {
                if (iconFXAssetType == IconAssetType.Prefab) {
                    if (_highlighted && iconFXPrefab != null) {
                        if (instantiatedIconPrefab == null) {
                            instantiatedIconPrefab = Instantiate(iconFXPrefab);
                            instantiatedIconPrefab.hideFlags = HideFlags.DontSave;
                        }
                        if (instantiatedIconMaterials == null) {
                            // Cache all materials from all renderers
                            instantiatedIconMaterials = new List<Material>();
                            var renderers = instantiatedIconPrefab.GetComponentsInChildren<Renderer>(true);
                            foreach (var renderer in renderers) {
                                Material mat = renderer.sharedMaterial;
                                if (mat != null) {
                                    mat = Instantiate(mat);
                                    renderer.material = mat;
                                    instantiatedIconMaterials.Add(mat);
                                }
                            }
                        }
                    }
                }
                else {
                    ReleaseInstantiatedIconPrefab();
                    if (iconFXMesh == null) {
                        iconFXMesh = Resources.Load<Mesh>("HighlightPlus/IconMesh");
                    }
                    if (fxMatIcon == null) {
                        fxMatIcon = new Material(Shader.Find("HighlightPlus/Geometry/IconFX"));
                    }
                }
            }
            else {
                HideIconPrefab();
            }

            // Per object
            float scaledOutlineWidth = outlineQuality.UsesMultipleOffsets() ? 0f : realOutlineWidth / 100f;

            for (int k = 0; k < rmsCount; k++) {
                if (rms[k].mesh != null || rms[k].isParticleSystem) {

                    Renderer renderer = rms[k].renderer;
                    if (renderer == null)
                        continue;

                    renderer.GetSharedMaterials(rendererSharedMaterials);

                    // Per submesh
                    int subMeshCount = rms[k].subMeshCount;

                    if (useOriginalShader && !string.IsNullOrEmpty(customPassName)) {
                        if (rms[k].customPassIds == null || rms[k].customPassIds.Length != subMeshCount) {
                            rms[k].customPassIds = new int[subMeshCount];
                        }
                    }

                    for (int l = 0; l < subMeshCount; l++) {
                        if (((1 << l) & subMeshMask) == 0) continue;

                        Material mat = null;
                        if (l < rendererSharedMaterials.Count) {
                            mat = rendererSharedMaterials[l];
                        }

                        if (useOriginalShader && !string.IsNullOrEmpty(customPassName)) {
                            if (mat != null) {
                                rms[k].customPassIds[l] = mat.FindPass(customPassName);
                            }
                            else {
                                rms[k].customPassIds[l] = -1;
                            }
                        }

                        if (mat == null)
                            continue;

                        bool hasTexture = false;
                        Texture matTexture = null;
                        Vector2 matTextureOffset = Misc.vector2Zero;
                        Vector2 matTextureScale = Misc.vector2One;
                        // Try custom texture name first if provided
                        if (!string.IsNullOrEmpty(alphaCutOffTextureName) && mat.HasProperty(alphaCutOffTextureName)) {
                            matTexture = mat.GetTexture(alphaCutOffTextureName);
                            hasTexture = matTexture != null;
                            if (hasTexture) {
                                string stPropertyName = alphaCutOffTextureName + "_ST";
                                if (mat.HasProperty(stPropertyName)) {
                                    Vector4 st = mat.GetVector(stPropertyName);
                                    matTextureScale.x = st.x;
                                    matTextureScale.y = st.y;
                                    matTextureOffset.x = st.z;
                                    matTextureOffset.y = st.w;
                                }
                            }
                        }
                        else if (mat.HasProperty(ShaderParams.BaseMap)) {
                            matTexture = mat.GetTexture(ShaderParams.BaseMap); // we don't use mainTexture because ShaderGraph doesn't inform that generic property correctly
                            hasTexture = true;
                            if (mat.HasProperty(ShaderParams.BaseMapST)) {
                                Vector4 baseMapST = mat.GetVector(ShaderParams.BaseMapST);
                                matTextureScale.x = baseMapST.x;
                                matTextureScale.y = baseMapST.y;
                                matTextureOffset.x = baseMapST.z;
                                matTextureOffset.y = baseMapST.w;
                            }
                        }
                        else if (mat.HasProperty(ShaderParams.MainTex)) {
                            matTexture = mat.GetTexture(ShaderParams.MainTex);
                            hasTexture = matTexture != null;
                            if (hasTexture) {
                                matTextureOffset = mat.mainTextureOffset;
                                matTextureScale = mat.mainTextureScale;
                            }
                        }
                        else {
                            Shader shader = mat.shader;
                            int texturePropertyCount = shader.GetPropertyCount();
                            for (int i = 0; i < texturePropertyCount; i++) {
                                if ((shader.GetPropertyFlags(i) & ShaderPropertyFlags.MainTexture) != 0) {
                                    string mainTextureName = shader.GetPropertyName(i);
                                    matTexture = mat.GetTexture(mainTextureName);
                                    hasTexture = matTexture != null;
                                    if (hasTexture) {
                                        string stPropertyName = mainTextureName + "_ST";
                                        if (mat.HasProperty(stPropertyName)) {
                                            Vector4 st = mat.GetVector(stPropertyName);
                                            matTextureScale.x = st.x;
                                            matTextureScale.y = st.y;
                                            matTextureOffset.x = st.z;
                                            matTextureOffset.y = st.w;
                                        }
                                    }
                                    break;
                                }
                            }
                        }

                        bool useAlphaTest = alphaCutOff > 0 && hasTexture;

                        // Mask
                        if (rms[k].fxMatMask != null && rms[k].fxMatMask.Length > l) {
                            Material fxMat = rms[k].fxMatMask[l];
                            if (fxMat != null) {
                                fxMat.mainTexture = matTexture;
                                fxMat.mainTextureOffset = matTextureOffset;
                                fxMat.mainTextureScale = matTextureScale;
                                if (useAlphaTest) {
                                    fxMat.SetFloat(ShaderParams.CutOff, alphaCutOff);
                                    fxMat.EnableKeyword(ShaderParams.SKW_ALPHACLIP);
                                }
                                else {
                                    fxMat.DisableKeyword(ShaderParams.SKW_ALPHACLIP);
                                }
                                fxMat.SetInt(ShaderParams.Cull, cullBackFaces ? (int)CullMode.Back : (int)CullMode.Off);
                                fxMat.SetFloat(ShaderParams.Padding, outlineQuality != QualityLevel.Highest ? padding * 0.01f : 0);
                                if (renderMaskOnTop) {
                                    fxMat.SetInt(ShaderParams.ZTest, (int)CompareFunction.Always);
                                }
                                else {
                                    fxMat.SetInt(ShaderParams.ZTest, (int)CompareFunction.LessEqual);
                                }
                            }
                        }

                        // Outline
                        if (rms[k].fxMatOutline != null && rms[k].fxMatOutline.Length > l) {
                            Material fxMat = rms[k].fxMatOutline[l];
                            if (fxMat != null) {
                                fxMat.SetFloat(ShaderParams.OutlineWidth, scaledOutlineWidth);
                                fxMat.SetInt(ShaderParams.OutlineZTest, GetZTestValue(outlineVisibility));
                                fxMat.SetInt(ShaderParams.Cull, cullBackFaces ? (int)CullMode.Back : (int)CullMode.Off);
                                fxMat.SetFloat(ShaderParams.ConstantWidth, constantWidth ? 1.0f : 0);
                                fxMat.SetFloat(ShaderParams.MinimumWidth, minimumWidth);
                                fxMat.SetInt(ShaderParams.OutlineStencilComp, outlineMaskMode == MaskMode.IgnoreMask ? (int)CompareFunction.Always : (int)CompareFunction.NotEqual);
                                if (useAlphaTest) {
                                    fxMat.mainTexture = matTexture;
                                    fxMat.mainTextureOffset = matTextureOffset;
                                    fxMat.mainTextureScale = matTextureScale;
                                    fxMat.SetFloat(ShaderParams.CutOff, alphaCutOff);
                                    fxMat.EnableKeyword(ShaderParams.SKW_ALPHACLIP);
                                }
                                else {
                                    fxMat.DisableKeyword(ShaderParams.SKW_ALPHACLIP);
                                }
                                fxMat.DisableKeyword(ShaderParams.SKW_OUTLINE_GRADIENT_LS);
                                fxMat.DisableKeyword(ShaderParams.SKW_OUTLINE_GRADIENT_WS);
                                if (outlineColorStyle == ColorStyle.Gradient) {
                                    fxMat.SetTexture(ShaderParams.OutlineGradientTex, outlineGradientTex);
                                    fxMat.EnableKeyword(outlineGradientInLocalSpace ? ShaderParams.SKW_OUTLINE_GRADIENT_LS : ShaderParams.SKW_OUTLINE_GRADIENT_WS);
                                }
                            }
                        }

                        // Outer Glow
                        if (rms[k].fxMatGlow != null && rms[k].fxMatGlow.Length > l) {
                            Material fxMat = rms[k].fxMatGlow[l];
                            if (fxMat != null) {
                                float animSpeed = glowAnimationSpeed;
#if UNITY_EDITOR
                                if (!Application.isPlaying) {
                                    animSpeed = 0;
                                }
#endif
                                fxMat.SetVector(ShaderParams.Glow2, new Vector4(outline > 0 ? realOutlineWidth / 100f : 0, animSpeed, glowDithering));
                                if (glowDitheringStyle == GlowDitheringStyle.Noise) {
                                    fxMat.EnableKeyword(ShaderParams.SKW_DITHER_BLUENOISE);
                                }
                                else {
                                    fxMat.DisableKeyword(ShaderParams.SKW_DITHER_BLUENOISE);
                                }
                                fxMat.SetInt(ShaderParams.GlowZTest, GetZTestValue(glowVisibility));
                                fxMat.SetInt(ShaderParams.Cull, cullBackFaces ? (int)CullMode.Back : (int)CullMode.Off);
                                fxMat.SetFloat(ShaderParams.ConstantWidth, constantWidth ? 1.0f : 0);
                                fxMat.SetFloat(ShaderParams.MinimumWidth, minimumWidth);
                                fxMat.SetInt(ShaderParams.GlowStencilOp, glowBlendPasses ? (int)StencilOp.Keep : (int)StencilOp.Replace);
                                fxMat.SetInt(ShaderParams.GlowStencilComp, glowMaskMode == MaskMode.IgnoreMask ? (int)CompareFunction.Always : (int)CompareFunction.NotEqual);

                                if (useAlphaTest) {
                                    fxMat.mainTexture = matTexture;
                                    fxMat.mainTextureOffset = matTextureOffset;
                                    fxMat.mainTextureScale = matTextureScale;
                                    fxMat.SetFloat(ShaderParams.CutOff, alphaCutOff);
                                    fxMat.EnableKeyword(ShaderParams.SKW_ALPHACLIP);
                                }
                                else {
                                    fxMat.DisableKeyword(ShaderParams.SKW_ALPHACLIP);
                                }
                            }
                        }

                        // See-through
                        bool usesSeeThroughBorder = rms[k].fxMatSeeThroughBorder != null && rms[k].fxMatSeeThroughBorder.Length > l && (seeThroughBorder * seeThroughBorderWidth > 0);
                        if (rms[k].fxMatSeeThroughInner != null && rms[k].fxMatSeeThroughInner.Length > l) {
                            Material fxMat = rms[k].fxMatSeeThroughInner[l];
                            if (fxMat != null) {
                                fxMat.SetFloat(ShaderParams.SeeThrough, seeThroughIntensity);
                                fxMat.SetFloat(ShaderParams.SeeThroughNoise, seeThroughNoise);
                                fxMat.SetColor(ShaderParams.SeeThroughTintColor, seeThroughTintColor);
                                fxMat.SetInt(ShaderParams.Cull, cullBackFaces ? (int)CullMode.Back : (int)CullMode.Off);
                                if (seeThroughOccluderMaskAccurate && seeThroughOccluderMask != -1) {
                                    fxMat.SetInt(ShaderParams.SeeThroughStencilRef, 1);
                                    fxMat.SetInt(ShaderParams.SeeThroughStencilComp, (int)CompareFunction.Equal);
                                    fxMat.SetInt(ShaderParams.SeeThroughStencilPassOp, (int)StencilOp.Zero);
                                }
                                else {
                                    fxMat.SetInt(ShaderParams.SeeThroughStencilRef, 2);
                                    fxMat.SetInt(ShaderParams.SeeThroughStencilComp, (int)CompareFunction.Greater);
                                    fxMat.SetInt(ShaderParams.SeeThroughStencilPassOp, (int)StencilOp.Replace);
                                }
                                //if (hasTexture) {
                                fxMat.mainTexture = matTexture;
                                fxMat.mainTextureOffset = matTextureOffset;
                                fxMat.mainTextureScale = matTextureScale;
                                //}
                                if (useAlphaTest) {
                                    fxMat.SetFloat(ShaderParams.CutOff, alphaCutOff);
                                    fxMat.EnableKeyword(ShaderParams.SKW_ALPHACLIP);
                                }
                                else {
                                    fxMat.DisableKeyword(ShaderParams.SKW_ALPHACLIP);
                                }
                                if (seeThroughDepthOffset > 0 || seeThroughMaxDepth > 0) {
                                    fxMat.SetFloat(ShaderParams.SeeThroughDepthOffset, seeThroughDepthOffset > 0 ? seeThroughDepthOffset : -1);
                                    fxMat.SetFloat(ShaderParams.SeeThroughMaxDepth, seeThroughMaxDepth > 0 ? seeThroughMaxDepth : 999999);
									fxMat.SetFloat(ShaderParams.SeeThroughFadeRange, seeThroughFadeRange > 0 ? seeThroughFadeRange : 0);
                                    fxMat.EnableKeyword(ShaderParams.SKW_DEPTH_OFFSET);
                                }
                                else {
                                    fxMat.DisableKeyword(ShaderParams.SKW_DEPTH_OFFSET);
                                }
                                if (seeThroughBorderOnly) {
                                    fxMat.EnableKeyword(ShaderParams.SKW_SEETHROUGH_ONLY_BORDER);
                                }
                                else {
                                    fxMat.DisableKeyword(ShaderParams.SKW_SEETHROUGH_ONLY_BORDER);
                                }

                                fxMat.DisableKeyword(ShaderParams.SKW_TEXTURE_TRIPLANAR);
                                fxMat.DisableKeyword(ShaderParams.SKW_TEXTURE_OBJECTSPACE);
                                fxMat.DisableKeyword(ShaderParams.SKW_TEXTURE_SCREENSPACE);
                                if (seeThroughTexture != null) {
                                    fxMat.SetTexture(ShaderParams.SeeThroughTexture, seeThroughTexture);
                                    fxMat.SetFloat(ShaderParams.SeeThroughTextureScale, seeThroughTextureScale);
                                    switch (seeThroughTextureUVSpace) {
                                        case TextureUVSpace.ScreenSpace:
                                            fxMat.EnableKeyword(ShaderParams.SKW_TEXTURE_SCREENSPACE);
                                            break;
                                        case TextureUVSpace.ObjectSpace:
                                            fxMat.EnableKeyword(ShaderParams.SKW_TEXTURE_OBJECTSPACE);
                                            break;
                                        default:
                                            fxMat.EnableKeyword(ShaderParams.SKW_TEXTURE_TRIPLANAR);
                                            break;
                                    }
                                }

                            }
                        }

                        // See-through border
                        if (usesSeeThroughBorder) {
                            Material fxMat = rms[k].fxMatSeeThroughBorder[l];
                            if (fxMat != null) {
                                fxMat.SetColor(ShaderParams.SeeThroughBorderColor, new Color(seeThroughBorderColor.r, seeThroughBorderColor.g, seeThroughBorderColor.b, seeThroughBorder));
                                fxMat.SetFloat(ShaderParams.SeeThroughBorderWidth, (seeThroughBorder * seeThroughBorderWidth) > 0 ? seeThroughBorderWidth / 100f : 0);
                                fxMat.SetFloat(ShaderParams.SeeThroughBorderConstantWidth, constantWidth ? 1.0f : 0);
                                fxMat.SetInt(ShaderParams.Cull, cullBackFaces ? (int)CullMode.Back : (int)CullMode.Off);
                                if (seeThroughOccluderMaskAccurate && seeThroughOccluderMask != -1) {
                                    fxMat.SetInt(ShaderParams.SeeThroughStencilRef, 1);
                                    fxMat.SetInt(ShaderParams.SeeThroughStencilComp, (int)CompareFunction.Equal);
                                    fxMat.SetInt(ShaderParams.SeeThroughStencilPassOp, (int)StencilOp.Zero);
                                }
                                else {
                                    fxMat.SetInt(ShaderParams.SeeThroughStencilRef, 2);
                                    fxMat.SetInt(ShaderParams.SeeThroughStencilComp, (int)CompareFunction.Greater);
                                    fxMat.SetInt(ShaderParams.SeeThroughStencilPassOp, (int)StencilOp.Keep);
                                }
                                //if (hasTexture) {
                                fxMat.mainTexture = matTexture;
                                fxMat.mainTextureOffset = matTextureOffset;
                                fxMat.mainTextureScale = matTextureScale;
                                //}
                                if (useAlphaTest) {
                                    fxMat.SetFloat(ShaderParams.CutOff, alphaCutOff);
                                    fxMat.EnableKeyword(ShaderParams.SKW_ALPHACLIP);
                                }
                                else {
                                    fxMat.DisableKeyword(ShaderParams.SKW_ALPHACLIP);
                                }
                                if (seeThroughDepthOffset > 0 || seeThroughMaxDepth > 0) {
                                    fxMat.SetFloat(ShaderParams.SeeThroughDepthOffset, seeThroughDepthOffset > 0 ? seeThroughDepthOffset : -1);
                                    fxMat.SetFloat(ShaderParams.SeeThroughMaxDepth, seeThroughMaxDepth > 0 ? seeThroughMaxDepth : 999999);
									fxMat.SetFloat(ShaderParams.SeeThroughFadeRange, seeThroughFadeRange > 0 ? seeThroughFadeRange : 0);
                                    fxMat.EnableKeyword(ShaderParams.SKW_DEPTH_OFFSET);
                                }
                                else {
                                    fxMat.DisableKeyword(ShaderParams.SKW_DEPTH_OFFSET);
                                }
                            }
                        }

                        // Overlay
                        if (rms[k].fxMatOverlay != null && rms[k].fxMatOverlay.Length > l) {
                            Material fxMat = rms[k].fxMatOverlay[l];
                            if (fxMat != null) {
                                //if (hasTexture) {
                                fxMat.mainTexture = matTexture;
                                fxMat.mainTextureOffset = matTextureOffset;
                                fxMat.mainTextureScale = matTextureScale;
                                //}
                                if (mat.HasProperty(ShaderParams.Color)) {
                                    fxMat.SetColor(ShaderParams.OverlayBackColor, mat.GetColor(ShaderParams.Color));
                                }
                                fxMat.SetInt(ShaderParams.Cull, cullBackFaces ? (int)CullMode.Back : (int)CullMode.Off);
                                fxMat.SetInt(ShaderParams.OverlayZTest, GetZTestValue(overlayVisibility));
                                fxMat.DisableKeyword(ShaderParams.SKW_TEXTURE_TRIPLANAR);
                                fxMat.DisableKeyword(ShaderParams.SKW_TEXTURE_OBJECTSPACE);
                                fxMat.DisableKeyword(ShaderParams.SKW_TEXTURE_SCREENSPACE);
                                fxMat.SetTexture(ShaderParams.OverlayTexture, overlayTexture);
                                fxMat.SetVector(ShaderParams.OverlayTextureScrolling, overlayTextureScrolling);

                                // Set overlay pattern keyword
                                fxMat.DisableKeyword(ShaderParams.SKW_PATTERN_GRID);
                                fxMat.DisableKeyword(ShaderParams.SKW_PATTERN_POLKADOTS);
                                fxMat.DisableKeyword(ShaderParams.SKW_PATTERN_STAGGERED_LINES);
                                fxMat.DisableKeyword(ShaderParams.SKW_PATTERN_ZIGZAG);
                                if (overlayPattern == OverlayPattern.Polkadots) {
                                    fxMat.EnableKeyword(ShaderParams.SKW_PATTERN_POLKADOTS);
                                }
                                else if (overlayPattern == OverlayPattern.Grid) {
                                    fxMat.EnableKeyword(ShaderParams.SKW_PATTERN_GRID);
                                }
                                else if (overlayPattern == OverlayPattern.StaggeredLines) {
                                    fxMat.EnableKeyword(ShaderParams.SKW_PATTERN_STAGGERED_LINES);
                                }
                                else if (overlayPattern == OverlayPattern.ZigZag) {
                                    fxMat.EnableKeyword(ShaderParams.SKW_PATTERN_ZIGZAG);
                                }
                                fxMat.SetVector(ShaderParams.OverlayPatternData, new Vector4(overlayPatternScale, overlayPatternSize, overlayPatternSoftness, overlayPatternRotation));
                                fxMat.SetVector(ShaderParams.OverlayPatternScrolling, overlayPatternScrolling);

                                switch (overlayTextureUVSpace) {
                                    case TextureUVSpace.ScreenSpace:
                                        fxMat.EnableKeyword(ShaderParams.SKW_TEXTURE_SCREENSPACE);
                                        break;
                                    case TextureUVSpace.ObjectSpace:
                                        fxMat.EnableKeyword(ShaderParams.SKW_TEXTURE_OBJECTSPACE);
                                        break;
                                    default:
                                        fxMat.EnableKeyword(ShaderParams.SKW_TEXTURE_TRIPLANAR);
                                        break;
                                }

                                if (useAlphaTest) {
                                    fxMat.SetFloat(ShaderParams.CutOff, alphaCutOff);
                                    fxMat.EnableKeyword(ShaderParams.SKW_ALPHACLIP);
                                }
                                else {
                                    fxMat.DisableKeyword(ShaderParams.SKW_ALPHACLIP);
                                }
                            }
                        }

                        // Inner Glow
                        if (rms[k].fxMatInnerGlow != null && rms[k].fxMatInnerGlow.Length > l) {
                            Material fxMat = rms[k].fxMatInnerGlow[l];
                            if (fxMat != null) {
                                fxMat.mainTexture = matTexture;
                                fxMat.mainTextureOffset = matTextureOffset;
                                fxMat.mainTextureScale = matTextureScale;
                                fxMat.SetVector(ShaderParams.InnerGlowData, new Vector4(innerGlowWidth, innerGlowPower, 0, 0));
                                fxMat.SetInt(ShaderParams.InnerGlowZTest, GetZTestValue(innerGlowVisibility));
                                fxMat.SetInt(ShaderParams.Cull, cullBackFaces ? (int)CullMode.Back : (int)CullMode.Off);
                                fxMat.SetInt(ShaderParams.InnerGlowBlendMode, innerGlowBlendMode == InnerGlowBlendMode.Additive ? 1 : 10);
                                if (useAlphaTest) {
                                    fxMat.SetFloat(ShaderParams.CutOff, alphaCutOff);
                                    fxMat.EnableKeyword(ShaderParams.SKW_ALPHACLIP);
                                }
                                else {
                                    fxMat.DisableKeyword(ShaderParams.SKW_ALPHACLIP);
                                }
                            }
                        }

                        // Solid Color for smooth glow
                        if (rms[k].fxMatSolidColor != null && rms[k].fxMatSolidColor.Length > l) {
                            Material fxMat = rms[k].fxMatSolidColor[l];
                            if (fxMat != null) {
                                fxMat.color = glowHQColor;
                                fxMat.SetInt(ShaderParams.Cull, cullBackFaces ? (int)CullMode.Back : (int)CullMode.Off);
                                fxMat.SetFloat(ShaderParams.OutlineEdgeThreshold, outlineEdgeThreshold);
                                fxMat.mainTexture = matTexture;
                                fxMat.mainTextureOffset = matTextureOffset;
                                fxMat.mainTextureScale = matTextureScale;

                                if ((glow > 0 && glowQuality == QualityLevel.Highest && glowVisibility == Visibility.Normal) || (outline > 0 && outlineQuality == QualityLevel.Highest && outlineVisibility == Visibility.Normal)) {
                                    fxMat.DisableKeyword(ShaderParams.SKW_DEPTHCLIP_INV);
                                    fxMat.EnableKeyword(ShaderParams.SKW_DEPTHCLIP);
                                }
                                else if ((glow > 0 && glowQuality == QualityLevel.Highest && glowVisibility == Visibility.OnlyWhenOccluded) || (outline > 0 && outlineQuality == QualityLevel.Highest && outlineVisibility == Visibility.OnlyWhenOccluded)) {
                                    fxMat.DisableKeyword(ShaderParams.SKW_DEPTHCLIP);
                                    fxMat.EnableKeyword(ShaderParams.SKW_DEPTHCLIP_INV);
                                }
                                else {
                                    fxMat.DisableKeyword(ShaderParams.SKW_DEPTHCLIP);
                                    fxMat.DisableKeyword(ShaderParams.SKW_DEPTHCLIP_INV);
                                }
                                //}
                                if (useAlphaTest) {
                                    fxMat.SetFloat(ShaderParams.CutOff, alphaCutOff);
                                    fxMat.EnableKeyword(ShaderParams.SKW_ALPHACLIP);
                                }
                                else {
                                    fxMat.DisableKeyword(ShaderParams.SKW_ALPHACLIP);
                                }
                                if (outlineEdgeMode == OutlineEdgeMode.Any) {
                                    fxMat.EnableKeyword(ShaderParams.SKW_ALL_EDGES);
                                }
                                else {
                                    fxMat.DisableKeyword(ShaderParams.SKW_ALL_EDGES);
                                }
                            }
                        }
                    }
                }
            }
        }

        int MaterialsRenderQueueComparer (ModelMaterials m1, ModelMaterials m2) {
            Material mat1 = m1.renderer != null ? m1.renderer.sharedMaterial : null;
            Material mat2 = m2.renderer != null ? m2.renderer.sharedMaterial : null;
            int mq1 = mat1 != null ? mat1.renderQueue : 0;
            int mq2 = mat2 != null ? mat2.renderQueue : 0;
            return mq1.CompareTo(mq2);
        }

        int MaterialsRenderQueueInvertedComparer (ModelMaterials m1, ModelMaterials m2) {
            Material mat1 = m1.renderer != null ? m1.renderer.sharedMaterial : null;
            Material mat2 = m2.renderer != null ? m2.renderer.sharedMaterial : null;
            int mq1 = mat1 != null ? mat1.renderQueue : 0;
            int mq2 = mat2 != null ? mat2.renderQueue : 0;
            return mq2.CompareTo(mq1);
        }

        float ComputeCameraDistanceFade (Vector3 position, Transform cameraTransform) {
            Vector3 heading = position - cameraTransform.position;
            float distance = Vector3.Dot(heading, cameraTransform.forward);
            if (distance < cameraDistanceFadeNear) {
                return 1f - Mathf.Min(1f, cameraDistanceFadeNear - distance);
            }
            if (distance > cameraDistanceFadeFar) {
                return 1f - Mathf.Min(1f, distance - cameraDistanceFadeFar);
            }
            return 1f;
        }

        int GetZTestValue (Visibility param) {
            switch (param) {
                case Visibility.AlwaysOnTop:
                    return (int)CompareFunction.Always;
                case Visibility.OnlyWhenOccluded:
                    return (int)CompareFunction.Greater;
                default:
                    return (int)CompareFunction.LessEqual;
            }
        }

        void BuildQuad () {
            quadMesh = new Mesh();

            // Setup vertices
            Vector3[] newVertices = new Vector3[4];
            float halfHeight = 0.5f;
            float halfWidth = 0.5f;
            newVertices[0] = new Vector3(-halfWidth, -halfHeight, 0);
            newVertices[1] = new Vector3(-halfWidth, halfHeight, 0);
            newVertices[2] = new Vector3(halfWidth, -halfHeight, 0);
            newVertices[3] = new Vector3(halfWidth, halfHeight, 0);

            // Setup UVs
            Vector2[] newUVs = new Vector2[newVertices.Length];
            newUVs[0] = new Vector2(0, 0);
            newUVs[1] = new Vector2(0, 1);
            newUVs[2] = new Vector2(1, 0);
            newUVs[3] = new Vector2(1, 1);

            // Setup triangles
            int[] newTriangles = { 0, 1, 2, 3, 2, 1 };

            // Setup normals
            Vector3[] newNormals = new Vector3[newVertices.Length];
            for (int i = 0; i < newNormals.Length; i++) {
                newNormals[i] = Vector3.forward;
            }

            // Create quad
            quadMesh.vertices = newVertices;
            quadMesh.uv = newUVs;
            quadMesh.triangles = newTriangles;
            quadMesh.normals = newNormals;

            quadMesh.RecalculateBounds();
        }

        void BuildCube () {
            cubeMesh = Resources.GetBuiltinResource<Mesh>("Cube.fbx");
        }


        #region Icon Prefab support

        void ReleaseInstantiatedIconPrefab () {
            if (instantiatedIconPrefab != null) {
                DestroyImmediate(instantiatedIconPrefab);
                instantiatedIconPrefab = null;
            }
            if (instantiatedIconMaterials != null) {
                foreach (Material m in instantiatedIconMaterials) {
                    DestroyMaterial(m);
                }
                instantiatedIconMaterials = null;
            }
        }

        void HideIconPrefab () {
            if (instantiatedIconPrefab != null) {
                instantiatedIconPrefab.SetActive(false);
            }
        }

        #endregion

        /// <summary>
        /// Returns true if a given transform is included in this effect
        /// </summary>
        public bool Includes (Transform transform) {
            for (int k = 0; k < rmsCount; k++) {
                if (rms[k].transform == transform) return true;
            }
            return false;
        }

        /// <summary>
        /// Updates profile glow color
        /// </summary>
        public void SetGlowColor (Color color) {
            if (glowPasses != null) {
                for (int k = 0; k < glowPasses.Length; k++) {
                    glowPasses[k].color = color;
                }
            }
            glowHQColor = color;
            UpdateMaterialProperties();
        }


        #region Normals handling

        static List<Vector3> vertices;
        static List<Vector3> normals;
        static Vector3[] newNormals;
        static int[] matches;
        static readonly Dictionary<Vector3, int> vv = new Dictionary<Vector3, int>();
        static readonly List<Material> rendererSharedMaterials = new List<Material>();

        // cached meshes
        static readonly Dictionary<int, Mesh> smoothMeshes = new Dictionary<int, Mesh>();
        static readonly Dictionary<int, Mesh> reorientedMeshes = new Dictionary<int, Mesh>();

        // annotate usage count of the instanced meshes due to normals or combine mesh option
        // when highlighte effect is destroyed and the usage count is zero, we destroy the cached mesh
        static readonly Dictionary<Mesh, HashSet<HighlightEffect>> sharedMeshUsage = new Dictionary<Mesh, HashSet<HighlightEffect>>();

        void AverageNormals (int objIndex) {
            if (rms == null || objIndex >= rms.Length) return;
            Mesh mesh = rms[objIndex].mesh;

            int hashCode = mesh.GetHashCode();
            if (!smoothMeshes.TryGetValue(hashCode, out Mesh newMesh) || newMesh == null) {
                if (!mesh.isReadable) return;
                if (normals == null) {
                    normals = new List<Vector3>();
                }
                else {
                    normals.Clear();
                }
                mesh.GetNormals(normals);
                int normalsCount = normals.Count;
                if (normalsCount == 0)
                    return;
                if (vertices == null) {
                    vertices = new List<Vector3>();
                }
                else {
                    vertices.Clear();
                }
                mesh.GetVertices(vertices);
                int vertexCount = vertices.Count;
                if (normalsCount < vertexCount) {
                    vertexCount = normalsCount;
                }
                if (newNormals == null || newNormals.Length < vertexCount) {
                    newNormals = new Vector3[vertexCount];
                }
                else {
                    Vector3 zero = Vector3.zero;
                    for (int k = 0; k < vertexCount; k++) {
                        newNormals[k] = zero;
                    }
                }
                if (matches == null || matches.Length < vertexCount) {
                    matches = new int[vertexCount];
                }
                // Locate overlapping vertices
                vv.Clear();
                for (int k = 0; k < vertexCount; k++) {
                    Vector3 v = vertices[k];
                    if (!vv.TryGetValue(v, out int i)) {
                        vv[v] = i = k;
                    }
                    matches[k] = i;
                }
                // Average normals
                for (int k = 0; k < vertexCount; k++) {
                    int match = matches[k];
                    newNormals[match] += normals[k];
                }
                for (int k = 0; k < vertexCount; k++) {
                    int match = matches[k];
                    normals[k] = newNormals[match].normalized;
                }
                // Reassign normals
                newMesh = Instantiate(mesh);
                newMesh.SetNormals(normals);
                smoothMeshes[hashCode] = newMesh;
            }
            IncrementMeshUsage(newMesh);
            rms[objIndex].mesh = newMesh;
        }


        void ReorientNormals (int objIndex) {
            if (rms == null || objIndex >= rms.Length) return;
            Mesh mesh = rms[objIndex].mesh;

            int hashCode = mesh.GetHashCode();
            if (!reorientedMeshes.TryGetValue(hashCode, out Mesh newMesh) || newMesh == null) {
                if (!mesh.isReadable) return;
                if (normals == null) {
                    normals = new List<Vector3>();
                }
                else {
                    normals.Clear();
                }
                if (vertices == null) {
                    vertices = new List<Vector3>();
                }
                else {
                    vertices.Clear();
                }
                mesh.GetVertices(vertices);
                int vertexCount = vertices.Count;
                if (vertexCount == 0) return;

                Vector3 mid = Vector3.zero;
                for (int k = 0; k < vertexCount; k++) {
                    mid += vertices[k];
                }
                mid /= vertexCount;
                // Average normals
                for (int k = 0; k < vertexCount; k++) {
                    normals.Add((vertices[k] - mid).normalized);
                }
                // Reassign normals
                newMesh = Instantiate(mesh);
                newMesh.SetNormals(normals);
                reorientedMeshes[hashCode] = newMesh;
            }
            IncrementMeshUsage(newMesh);
            rms[objIndex].mesh = newMesh;
        }

        #endregion

        #region Combine Meshes

        const int MAX_VERTEX_COUNT = 65535;
        static CombineInstance[] combineInstances;
        static readonly Dictionary<int, Mesh> combinedMeshes = new Dictionary<int, Mesh>();
        int combinedMeshesHashId;

        void CombineMeshes () {

            if (rmsCount <= 1) return;

            // Combine meshes of group into the first mesh in rms
            if (combineInstances == null || combineInstances.Length != rmsCount) {
                combineInstances = new CombineInstance[rmsCount];
            }
            int first = -1;
            int count = 0;
            combinedMeshesHashId = 17;
            int vertexCount = 0;
            Matrix4x4 im = Matrix4x4.identity;

            for (int k = 0; k < rmsCount; k++) {
                combineInstances[k].mesh = null;

                // Skip object if disabled
                Transform t = rms[k].transform;
                if (!t.gameObject.activeSelf) continue;
                if (rms[k].isSkinnedMesh) continue;

                Mesh mesh = rms[k].mesh;
                if (mesh == null || !mesh.isReadable) continue;

                vertexCount += mesh.vertexCount;
                combineInstances[count].mesh = mesh;
                int instanceId = GetObjectId(rms[k].renderer.gameObject);
                if (first < 0) {
                    first = k;
                    im = t.worldToLocalMatrix;
                }
                else {
                    rms[k].mesh = null;
                }
                unchecked {
                    combinedMeshesHashId = (combinedMeshesHashId * 31) + instanceId;
                }
                combineInstances[count].transform = im * t.localToWorldMatrix;
                count++;
            }
            if (count < 2) return;

            if (count != rmsCount) {
                Array.Resize(ref combineInstances, count);
            }

            if (!combinedMeshes.TryGetValue(combinedMeshesHashId, out Mesh combinedMesh) || combinedMesh == null) {
                combinedMesh = new Mesh();
                if (vertexCount > MAX_VERTEX_COUNT) {
                    combinedMesh.indexFormat = IndexFormat.UInt32;
                }
                combinedMesh.CombineMeshes(combineInstances, true, true);
                combinedMeshes[combinedMeshesHashId] = combinedMesh;
            }
            IncrementMeshUsage(combinedMesh);

            rms[first].mesh = combinedMesh;
            rms[first].isCombined = true;
        }


        public string ValidateCombineMeshes () {
            if (rms == null) return "No objects to combine.";
            foreach (var rm in rms) {
                if (!rm.isSkinnedMesh && rm.mesh != null && !rm.mesh.isReadable) return $"The mesh of object {rm.renderer.name} is not readable and can't be combined (check mesh's import settings).";
            }
            return null;
        }


        void IncrementMeshUsage (Mesh mesh) {
            if (sharedMeshUsage.TryGetValue(mesh, out HashSet<HighlightEffect> usageSet)) {
                usageSet.Add(this);
                return;
            }
            usageSet = new HashSet<HighlightEffect>();
            usageSet.Add(this);
            sharedMeshUsage[mesh] = usageSet;
        }

        /// <summary>
        /// Destroys any cached mesh
        /// </summary>
        public static void ClearMeshCache () {
            foreach (Mesh mesh in combinedMeshes.Values) {
                if (mesh != null) DestroyImmediate(mesh);
            }
            combinedMeshes.Clear();
            foreach (Mesh mesh in smoothMeshes.Values) {
                if (mesh != null) DestroyImmediate(mesh);
            }
            smoothMeshes.Clear();
            foreach (Mesh mesh in reorientedMeshes.Values) {
                if (mesh != null) DestroyImmediate(mesh);
            }
            reorientedMeshes.Clear();
            foreach (Mesh mesh in sharedMeshUsage.Keys) {
                if (mesh != null) DestroyImmediate(mesh);
            }
            sharedMeshUsage.Clear();
        }

        /// <summary>
        /// Clears cached mesh only for the highlighted object
        /// </summary>
        void RefreshCachedMeshes () {
            if (combinedMeshes.TryGetValue(combinedMeshesHashId, out Mesh combinedMesh)) {
                DestroyImmediate(combinedMesh);
                combinedMeshes.Remove(combinedMeshesHashId);
            }
            if (rms == null) return;
            for (int k = 0; k < rms.Length; k++) {
                Mesh mesh = rms[k].mesh;
                if (mesh != null) {
                    if (smoothMeshes.ContainsValue(mesh) || reorientedMeshes.ContainsValue(mesh)) {
                        DestroyImmediate(mesh);
                    }
                }

            }
        }
        #endregion
    }
}

