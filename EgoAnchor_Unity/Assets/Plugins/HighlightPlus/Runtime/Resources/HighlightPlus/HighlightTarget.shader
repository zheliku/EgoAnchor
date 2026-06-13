Shader "HighlightPlus/Geometry/Target" {
Properties {
    _MainTex ("Texture", 2D) = "white" {}
    _Color ("Color", Color) = (1,1,1,1)
    _ZTest ("ZTest", Int) = 0
    _TargetFXFrameData ("Frame Data (Width, Length, ShowCornersOnly)", Vector) = (0.1, 0.3, 0, 0)
    _TargetFXRenderData ("Render Data (Normal, FadePower, CustomAltitude)", Vector) = (0, 1, 0, 0)
}

    SubShader
    {
        Tags { "RenderType" = "Transparent" "Queue" = "Transparent-1" "DisableBatching" = "True" }

        Pass
        {
            Name "Target FX Decal"
            Blend SrcAlpha OneMinusSrcAlpha
            ZWrite Off
            ZTest [_ZTest]
            Cull Off
            
            HLSLPROGRAM

            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_local _ HP_TARGET_FRAME HP_TARGET_INWARD_CORNERS HP_TARGET_CROSS

            #pragma target 3.0

            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/DeclareDepthTexture.hlsl"

            struct appdata
            {
                float3 positionOS : POSITION;
				UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct v2f
            {
                float4 positionCS : SV_POSITION;
                float4 screenPos  : TEXCOORD0;
                float4 rayVS      : TEXCOORD1;
                float3 camPosVS   : TEXCOORD2;
        		UNITY_VERTEX_INPUT_INSTANCE_ID
		        UNITY_VERTEX_OUTPUT_STEREO
            };

            sampler2D _MainTex;
            CBUFFER_START(UnityPerMaterial)               
                float4 _MainTex_ST;
                half4 _Color;
                float4 _TargetFXRenderData;
                float4 _TargetFXFrameData;
            CBUFFER_END

            #define GROUND_NORMAL _TargetFXRenderData.xyz
            #define FADE_POWER _TargetFXRenderData.w
            #define FRAME_WIDTH _TargetFXFrameData.x
            #define CORNER_LENGTH _TargetFXFrameData.y
            #define FRAME_MIN_OPACITY _TargetFXFrameData.z
            #define GROUND_MIN_ALTITUDE _TargetFXFrameData.w

            v2f vert(appdata input)
            {
                v2f o;
		        UNITY_SETUP_INSTANCE_ID(input);
		        UNITY_TRANSFER_INSTANCE_ID(input, o);
		        UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);

                VertexPositionInputs vertexPositionInput = GetVertexPositionInputs(input.positionOS);
                o.positionCS = vertexPositionInput.positionCS;
                o.screenPos = ComputeScreenPos(o.positionCS);

                float3 viewRay = vertexPositionInput.positionVS;
                o.rayVS.w = viewRay.z;
                float4x4 viewToObject = mul(UNITY_MATRIX_I_M, UNITY_MATRIX_I_V);
                o.rayVS.xyz = mul((float3x3)viewToObject, -viewRay);
                o.camPosVS = mul(viewToObject, float4(0,0,0,1)).xyz;
                return o;
            }

            half4 frag(v2f i) : SV_Target
            {
        		UNITY_SETUP_INSTANCE_ID(i);
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i);

                float depth = SampleSceneDepth(i.screenPos.xy / i.screenPos.w);
                float3 decalPos;
                if(unity_OrthoParams.w) {
                    #if defined(UNITY_REVERSED_Z)
                        depth = 1.0 - depth;
                    #endif
                    float sceneDepthVS = lerp(_ProjectionParams.y, _ProjectionParams.z, depth);
				    float2 rayVSEnd = float2(unity_OrthoParams.xy * (i.screenPos.xy - 0.5) * 2.0);
                    
                    // Calculate correct ray origin on near plane for orthographic
                    float3 rayOrigin = float3(rayVSEnd, -_ProjectionParams.y);
                    float3 rayDirWS = mul((float3x3)UNITY_MATRIX_I_V, float3(0, 0, 1)); // Camera forward in world space
                    float3 rayOriginWS = mul(UNITY_MATRIX_I_V, float4(rayOrigin, 1)).xyz;

                    // Ground plane intersection
                    float t = (GROUND_MIN_ALTITUDE - rayOriginWS.y) / rayDirWS.y;
                    float3 hitPosWS = rayOriginWS + rayDirWS * t;
                    float3 hitPosVS = mul(UNITY_MATRIX_V, float4(hitPosWS, 1)).xyz;
                    sceneDepthVS = min(-hitPosVS.z, sceneDepthVS);

				    float4 posVS = float4(rayVSEnd, -sceneDepthVS, 1);       
				    float3 wpos = mul(UNITY_MATRIX_I_V, posVS).xyz;
                    decalPos = mul(GetWorldToObjectMatrix(), float4(wpos, 1)).xyz;
                } else {
                    float depthEye = LinearEyeDepth(depth, _ZBufferParams);
                    float3 rayDir = i.rayVS.xyz / i.rayVS.w;
                    float3 rayOrigin = i.camPosVS;
                    float t = (GROUND_MIN_ALTITUDE - rayOrigin.y) / rayDir.y;
                    depthEye = min(t, depthEye);
                    decalPos = rayOrigin + rayDir * depthEye;
                }
                clip(0.5 - abs(decalPos));

                // check normal
                float3 normal = normalize(cross(ddx(decalPos), -ddy(decalPos)));
                float slope = dot(normal, GROUND_NORMAL);
                clip(slope - 0.01);
            
                float2 uv = decalPos.xz + 0.5;
                half4 col;

                #if HP_TARGET_FRAME
                    float2 d = abs(uv - 0.5);
                    float dist = max(d.x, d.y);
                    float fw = fwidth(dist);
                    float frame = smoothstep(0.5 - FRAME_WIDTH - fw, 0.5 - FRAME_WIDTH, dist) * 
                                smoothstep(0.5 + fw, 0.5, dist);
                    
                    float cornerMask = step(0.5 - CORNER_LENGTH, d.x) * step(0.5 - CORNER_LENGTH, d.y);
                    frame *= cornerMask;
                    
                    col = _Color;
                    col.a *= frame;
                    col.a += FRAME_MIN_OPACITY;
                    col.a = saturate(col.a);
                #elif HP_TARGET_CROSS
                    uv = abs(0.5 - uv);
                    float2 d = abs(uv - 0.5);
                    float dist = max(d.x, d.y);
                    float fw = fwidth(dist);
                    float frame = smoothstep(0.5 - FRAME_WIDTH - fw, 0.5 - FRAME_WIDTH, dist) * 
                            smoothstep(0.5 + fw, 0.5, dist);
            
                    float cornerMask = step(0.5 - CORNER_LENGTH, d.x) * step(0.5 - CORNER_LENGTH, d.y);
                    frame *= cornerMask;
            
                    col = _Color;
                    col.a *= frame;
                    col.a += FRAME_MIN_OPACITY;
                    col.a = saturate(col.a);
                #elif HP_TARGET_INWARD_CORNERS
                    float2 d = abs(uv - 0.5);
                    d = (1 - CORNER_LENGTH) - d;
                    float dist = max(d.x, d.y);
                    float fw = fwidth(dist);
                    float frame = smoothstep(0.5 - FRAME_WIDTH - fw, 0.5 - FRAME_WIDTH, dist) * 
                            smoothstep(0.5 + fw, 0.5, dist);
            
                    float cornerMask = step(0.5 - CORNER_LENGTH, d.x) * step(0.5 - CORNER_LENGTH, d.y);
                    frame *= cornerMask;
            
                    col = _Color;
                    col.a *= frame;
                    col.a += FRAME_MIN_OPACITY;
                    col.a = saturate(col.a);
                #else
                    col = tex2D(_MainTex, uv) * _Color;
                #endif

                // atten with elevation
                col.a /= 1.0 + pow(1.0 + max(0, decalPos.y - 0.1), FADE_POWER);

                return col;
            }
            ENDHLSL
        }
    
        Pass
        {
            Name "Target FX"
            Blend SrcAlpha OneMinusSrcAlpha
            ZWrite Off
            ZTest [_ZTest]
            Cull Off
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_local _ HP_TARGET_FRAME HP_TARGET_INWARD_CORNERS HP_TARGET_CROSS

            #include "UnityCG.cginc"

            struct appdata
            {
                float4 vertex : POSITION;
                float2 uv     : TEXCOORD0;
				UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct v2f
            {
                float4 pos    : SV_POSITION;
                float2 uv     : TEXCOORD0;
				UNITY_VERTEX_OUTPUT_STEREO
            };

            sampler2D _MainTex;
      		fixed4 _Color;
            float4 _TargetFXFrameData;

            #define FRAME_WIDTH _TargetFXFrameData.x
            #define CORNER_LENGTH _TargetFXFrameData.y
            #define FRAME_MIN_OPACITY _TargetFXFrameData.z

            v2f vert (appdata v)
            {
                v2f o;
				UNITY_SETUP_INSTANCE_ID(v);
				UNITY_INITIALIZE_OUTPUT(v2f, o);
				UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.pos = UnityObjectToClipPos(v.vertex);
                o.uv = v.uv;
                return o;
            }
            
            fixed4 frag (v2f i) : SV_Target
            {

                float2 uv = i.uv;
                #if HP_TARGET_FRAME
                    float2 d = abs(uv - 0.5);
                    float dist = max(d.x, d.y);
                    float fw = fwidth(dist);
                    float frame = smoothstep(0.5 - FRAME_WIDTH - fw, 0.5 - FRAME_WIDTH, dist) * 
                                smoothstep(0.5 + fw, 0.5, dist);
                    
                    float cornerMask = step(0.5 - CORNER_LENGTH, d.x) * step(0.5 - CORNER_LENGTH, d.y);
                    frame *= cornerMask;
                    
                    fixed4 col = _Color;
                    col.a *= frame;
                    col.a += FRAME_MIN_OPACITY;
                    col.a = saturate(col.a);
                    return col;
                #elif HP_TARGET_CROSS
                    uv = abs(0.5 - uv);
                    float2 d = abs(uv - 0.5);
                    float dist = max(d.x, d.y);
                    float fw = fwidth(dist);
                    float frame = smoothstep(0.5 - FRAME_WIDTH - fw, 0.5 - FRAME_WIDTH, dist) * 
                                smoothstep(0.5 + fw, 0.5, dist);
                
                    float cornerMask = step(0.5 - CORNER_LENGTH, d.x) * step(0.5 - CORNER_LENGTH, d.y);
                    frame *= cornerMask;
                
                    fixed4 col = _Color;
                    col.a *= frame;
                    col.a += FRAME_MIN_OPACITY;
                    col.a = saturate(col.a);
                    return col;
                #elif HP_TARGET_INWARD_CORNERS
                    float2 d = abs(uv - 0.5);
                    d = (1 - CORNER_LENGTH) - d;
                    float dist = max(d.x, d.y);
                    float fw = fwidth(dist);
                    float frame = smoothstep(0.5 - FRAME_WIDTH - fw, 0.5 - FRAME_WIDTH, dist) * 
                                smoothstep(0.5 + fw, 0.5, dist);
                
                    float cornerMask = step(0.5 - CORNER_LENGTH, d.x) * step(0.5 - CORNER_LENGTH, d.y);
                    frame *= cornerMask;
                
                    fixed4 col = _Color;
                    col.a *= frame;
                    col.a += FRAME_MIN_OPACITY;
                    col.a = saturate(col.a);
                    return col;
                #else
                    return tex2D(_MainTex, uv) * _Color;
                #endif
            }
            ENDCG
        }

    }
}