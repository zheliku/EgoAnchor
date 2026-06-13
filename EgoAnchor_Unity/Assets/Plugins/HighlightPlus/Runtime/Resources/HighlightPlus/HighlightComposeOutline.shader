Shader "HighlightPlus/Geometry/ComposeOutline" {
Properties {
    _MainTex ("Texture", Any) = "black" {}
	_Color("Color", Color) = (1,1,1)
	_Cull("Cull Mode", Int) = 2
	_ZTest("ZTest Mode", Int) = 0
	_Flip("Flip", Vector) = (0, 1, 0)
	_Debug("Debug Color", Color) = (0,0,0,0)
	_OutlineStencilComp("Stencil Comp", Int) = 6
	_OutlineSharpness("Outline Sharpness", Float) = 1.0
	_PatternTex("Pattern Texture", 2D) = "black" {}
	_PatternData("Pattern Data", Vector) = (1.0, 0.5, 0.1, 0)
	_DistortionTex("Distortion Texture", 2D) = "white" {}
	_DashData("Dash Data", Vector) = (0.1, 0.1, 1.0, 0.1)
	_OutlineGradientTex("Outline Gradient Texture", 2D) = "white" {}
	_OutlineGradientData("Outline Gradient Data", Vector) = (0.5, 1.0, 0, 0)
	_Padding("Padding", Float) = 0
	_Pixelation("Pixelation", Float) = 0
}
SubShader
	{
		Tags { "Queue" = "Transparent+120" "RenderType" = "Transparent" "DisableBatching" = "True" }
		Blend SrcAlpha OneMinusSrcAlpha

		// Compose effect on camera target (optimal quad blit)
		Pass
		{
			Name "Composte Outline"
			ZWrite Off
			ZTest Always // [_ZTest]
			Cull Off // [_Cull]
			Stencil {
				Ref 2
				Comp [_OutlineStencilComp]
				Pass keep
				ReadMask 2
				WriteMask 2
			}
			
			CGPROGRAM
			#pragma vertex vert
			#pragma fragment frag
			#pragma multi_compile_local _ HP_ALL_EDGES
			#pragma multi_compile_local _ HP_MASK_CUTOUT
			#pragma multi_compile_local _ HP_STYLIZED
			#pragma multi_compile_local _ HP_DASHED
			#pragma multi_compile_local _ HP_OUTLINE_GRADIENT_WS
			#include "UnityCG.cginc"

			UNITY_DECLARE_SCREENSPACE_TEXTURE(_HPComposeOutlineFinal);
			UNITY_DECLARE_SCREENSPACE_TEXTURE(_HPSourceRT);
			float4 _HPSourceRT_TexelSize;

			sampler2D _PatternTex;
			float4 _PatternData;
			#define PATTERN_SCALE _PatternData.x
			#define PATTERN_THRESHOLD _PatternData.y
			#define PATTERN_DISTORTION_AMOUNT _PatternData.z
			#define PATTERN_STOP_MOTION_SCALE _PatternData.w
			sampler2D _DistortionTex;

            fixed4 _Color;
			float3 _Flip;
			fixed4 _Debug;
			half _OutlineSharpness;
			half _Padding;
			int _Pixelation;

			half4 _DashData;
			#define DASH_WIDTH _DashData.x
			#define DASH_GAP _DashData.y
			#define DASH_SPEED _DashData.z

			#if HP_ALL_EDGES
				#define OUTLINE_SOURCE outline.g
			#else
				#define OUTLINE_SOURCE outline.r
			#endif

            sampler2D _OutlineGradientTex;
			float2 _OutlineGradientData;
			#define OUTLINE_GRADIENT_KNEE _OutlineGradientData.x
			#define OUTLINE_GRADIENT_POWER _OutlineGradientData.y

            struct appdata
            {
                float4 vertex : POSITION;
				UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct v2f
            {
				float4 pos: SV_POSITION;
				float4 scrPos: TEXCOORD0;
				UNITY_VERTEX_INPUT_INSTANCE_ID
				UNITY_VERTEX_OUTPUT_STEREO
            };

            v2f vert (appdata v)
            {
				v2f o;
				UNITY_SETUP_INSTANCE_ID(v);
				UNITY_INITIALIZE_OUTPUT(v2f, o);
				UNITY_TRANSFER_INSTANCE_ID(v, o);
				UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
				o.pos = UnityObjectToClipPos(v.vertex);
				o.scrPos = ComputeScreenPos(o.pos);
				o.scrPos.y = o.scrPos.w * _Flip.x + o.scrPos.y * _Flip.y;
				return o;
            }
            
            fixed4 frag (v2f i) : SV_Target
            {
				UNITY_SETUP_INSTANCE_ID(i);
				UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i);
				float2 uv = i.scrPos.xy/i.scrPos.w;

				if (_Pixelation > 1) {
					float2 pixel_uv = uv * _HPSourceRT_TexelSize.zw;
					pixel_uv = (floor(pixel_uv / _Pixelation) + 0.5) * _Pixelation;
					uv = pixel_uv * _HPSourceRT_TexelSize.xy;
				}

				#if HP_STYLIZED
					// Apply pattern texture with distortion
					float2 patternUV = uv * PATTERN_SCALE + floor(_Time.y * PATTERN_STOP_MOTION_SCALE) / PATTERN_STOP_MOTION_SCALE;
					fixed pattern = tex2D(_DistortionTex, patternUV).x;
					uv.x += (pattern - 0.5) * PATTERN_DISTORTION_AMOUNT;

					#if !HP_MASK_CUTOUT
						fixed mask = UNITY_SAMPLE_SCREENSPACE_TEXTURE(_HPSourceRT, uv).r;
						if (mask > 0.5) return 0;
					#endif
				#endif
				
				fixed4 outline = UNITY_SAMPLE_SCREENSPACE_TEXTURE(_HPComposeOutlineFinal, uv);
            	fixed4 color = _Color;
				OUTLINE_SOURCE = step(OUTLINE_SOURCE, _Padding) * OUTLINE_SOURCE / _Padding;
            	color.a *= OUTLINE_SOURCE;

				#if HP_OUTLINE_GRADIENT_WS
					half gradientT = pow(color.a * OUTLINE_GRADIENT_KNEE, OUTLINE_GRADIENT_POWER);
					half4 gradientC = tex2D(_OutlineGradientTex, float2(gradientT, 0));
					color.rgb = gradientC.rgb;
					color.a *= gradientC.a;
				#endif

				#if HP_DASHED
					float dashPattern = sin(( dot(float2(uv.x, uv.y), float2(uv.x, uv.y)) * _HPSourceRT_TexelSize.z * DASH_WIDTH + _Time.w * DASH_SPEED)) + DASH_GAP;
					clip(dashPattern);
				#endif

				#if HP_STYLIZED
					fixed patternCutout = tex2D(_PatternTex, patternUV * 4.0).x;
					color.a = saturate(color.a - patternCutout * PATTERN_THRESHOLD * 10);
				#endif

				#if HP_MASK_CUTOUT
					fixed4 maskN = UNITY_SAMPLE_SCREENSPACE_TEXTURE(_HPSourceRT, uv + float2(0, 1) * _HPSourceRT_TexelSize.xy);
					fixed4 maskS = UNITY_SAMPLE_SCREENSPACE_TEXTURE(_HPSourceRT, uv + float2(0, -1) * _HPSourceRT_TexelSize.xy);
					fixed4 maskW = UNITY_SAMPLE_SCREENSPACE_TEXTURE(_HPSourceRT, uv + float2(-1, 0) * _HPSourceRT_TexelSize.xy);
					fixed4 maskE = UNITY_SAMPLE_SCREENSPACE_TEXTURE(_HPSourceRT, uv + float2(1, 0) * _HPSourceRT_TexelSize.xy);
					color.a *= all(maskN.rgb==0) || all(maskS.rgb == 0) || all(maskW.rgb == 0) || all(maskE.rgb == 0);
				#endif

            	color.a = saturate(color.a);
				color.a = pow(color.a, _OutlineSharpness);

				color = lerp(color, _Debug, 1.0 - color.a);

            	return color;
			}
				ENDCG
	}

    }
}