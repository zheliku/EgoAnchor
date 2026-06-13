Shader "HighlightPlus/Geometry/Focus"
{
	Properties
	{
		_FocusColor ("Focus Color", Color) = (0,0,0,0.5)
		_FocusDesaturation ("Focus Desaturation", Range(0,1)) = 0
	}
	SubShader
	{
		ZTest Always
		ZWrite Off
		Cull Off

		Pass // 0: Dim only (no blur)
		{
			Stencil {
				Ref 8
				Comp NotEqual
				ReadMask 8
			}
			Blend SrcAlpha OneMinusSrcAlpha

			CGPROGRAM
			#pragma vertex vert
			#pragma fragment frag

			#include "UnityCG.cginc"

			fixed4 _FocusColor;

			struct appdata
			{
				float4 vertex : POSITION;
				UNITY_VERTEX_INPUT_INSTANCE_ID
			};

			struct v2f
			{
				float4 pos : SV_POSITION;
				UNITY_VERTEX_OUTPUT_STEREO
			};

			v2f vert (appdata v)
			{
				v2f o;
				UNITY_SETUP_INSTANCE_ID(v);
				UNITY_INITIALIZE_OUTPUT(v2f, o);
				UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
				o.pos = float4(v.vertex.xy, 0, 0.5);
				return o;
			}

			fixed4 frag (v2f i) : SV_Target
			{
				return _FocusColor;
			}
			ENDCG
		}

		Pass // 1: Blur/desaturation composite
		{
			Stencil {
				Ref 8
				Comp NotEqual
				ReadMask 8
			}

			CGPROGRAM
			#pragma vertex vertBlur
			#pragma fragment fragBlur

			#include "UnityCG.cginc"

			fixed4 _FocusColor;
			fixed _FocusDesaturation;
			UNITY_DECLARE_SCREENSPACE_TEXTURE(_FocusBlurTex);

			struct appdata
			{
				float4 vertex : POSITION;
				UNITY_VERTEX_INPUT_INSTANCE_ID
			};

			struct v2f
			{
				float4 pos : SV_POSITION;
				UNITY_VERTEX_INPUT_INSTANCE_ID
				UNITY_VERTEX_OUTPUT_STEREO
			};

			v2f vertBlur (appdata v)
			{
				v2f o;
				UNITY_SETUP_INSTANCE_ID(v);
				UNITY_INITIALIZE_OUTPUT(v2f, o);
				UNITY_TRANSFER_INSTANCE_ID(v, o);
				UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
				o.pos = float4(v.vertex.xy, 0, 0.5);
				return o;
			}

			fixed4 fragBlur (v2f i) : SV_Target
			{
				UNITY_SETUP_INSTANCE_ID(i);
				UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i);
				float2 uv = i.pos.xy / _ScreenParams.xy;
				fixed4 blurred = UNITY_SAMPLE_SCREENSPACE_TEXTURE(_FocusBlurTex, uv);
				fixed luminance = dot(blurred.rgb, fixed3(0.299, 0.587, 0.114));
				blurred.rgb = lerp(blurred.rgb, luminance, _FocusDesaturation);
				fixed3 result = blurred.rgb * (1.0 - _FocusColor.a) + _FocusColor.rgb * _FocusColor.a;
				return fixed4(result, 1.0);
			}
			ENDCG
		}
	}
}
