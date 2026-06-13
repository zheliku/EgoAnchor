Shader "HighlightPlus/Geometry/Overlay" {
Properties {
    _MainTex ("Texture", Any) = "white" {}
    _Color ("Color", Color) = (1,1,1) // not used; dummy property to avoid inspector warning "material has no _Color property"
    _OverlayColor ("Overlay Color", Color) = (1,1,1,1)
    _OverlayBackColor ("Overlay Back Color", Color) = (1,1,1,1)
    _OverlayData("Overlay Data", Vector) = (1,0.5,1,1)
    _OverlayHitPosData("Overlay Hit Pos Data", Vector) = (0,0,0,0)
    _OverlayHitStartTime("Overlay Hit Start Time", Float) = 0
    _OverlayTexture("Overlay Texture", 2D) = "white" {}
    _CutOff("CutOff", Float ) = 0.5
    _Cull ("Cull Mode", Int) = 2
    _OverlayZTest("ZTest", Int) = 4
    _OverlayPatternScrolling("Pattern Scrolling", Vector) = (0,0,0,0)
    _OverlayPatternData("Pattern Data", Vector) = (0,0,0,0)
}
    SubShader
    {
        Tags { "Queue"="Transparent+121" "RenderType"="Transparent" "DisableBatching"="True" }
    
        // Overlay
        Pass
        {
            Name "Overlay"
        	Stencil {
                Ref 4
                ReadMask 4
                Comp NotEqual
                Pass keep
            }
            Blend SrcAlpha OneMinusSrcAlpha
            ZWrite Off
            Cull [_Cull]
            Offset -1, -1   // avoid issues on Quest 2 standalone when using with other render features (ie. Liquid Volume Pro 2 irregular topology)
            ZTest [_OverlayZTest]

            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_local _ HP_ALPHACLIP
            #pragma multi_compile_local _ HP_TEXTURE_TRIPLANAR HP_TEXTURE_SCREENSPACE HP_TEXTURE_OBJECTSPACE
            #pragma multi_compile_local _ HP_PATTERN_POLKADOTS HP_PATTERN_GRID HP_PATTERN_STAGGERED_LINES HP_PATTERN_ZIGZAG

            #include "UnityCG.cginc"
            #include "CustomVertexTransform.cginc"

            struct appdata
            {
                float4 vertex : POSITION;
                float2 uv     : TEXCOORD0;
                float3 norm   : NORMAL;
				UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct v2f
            {
                float4 pos    : SV_POSITION;
                float2 uv     : TEXCOORD0;
                float3 wpos   : TEXCOORD1;
                #if HP_TEXTURE_TRIPLANAR
                    float3 wnorm  : TEXCOORD2;
                #endif
                #if HP_TEXTURE_SCREENSPACE
                    float4 scrPos : TEXCOORD3;
                #endif
				UNITY_VERTEX_OUTPUT_STEREO
            };

      		fixed4 _OverlayColor;
      		sampler2D _MainTex;
      		float4 _MainTex_ST;
      		fixed4 _OverlayBackColor;
      		fixed4 _OverlayData; // x = speed, y = MinIntensity, z = blend, w = texture scale
            float4 _OverlayHitPosData;
            float _OverlayHitStartTime;
      		fixed _CutOff;
            sampler2D _OverlayTexture;
            float2 _OverlayTextureScrolling;

            float2 _OverlayPatternScrolling;
            float4 _OverlayPatternData;
            #define PATTERN_SCALE    (_OverlayPatternData.x)
            #define PATTERN_SIZE     (_OverlayPatternData.y)
            #define PATTERN_SOFTNESS (_OverlayPatternData.z)
            #define PATTERN_ROTATION (_OverlayPatternData.w)

            v2f vert (appdata v)
            {
                v2f o;
				UNITY_SETUP_INSTANCE_ID(v);
				UNITY_INITIALIZE_OUTPUT(v2f, o);
				UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.pos = ComputeVertexPosition(v.vertex);
                #if HP_TEXTURE_SCREENSPACE
                    o.scrPos = ComputeScreenPos(o.pos);
                    o.scrPos.x *= _ScreenParams.x / _ScreenParams.y;
                #endif
                o.wpos = mul(unity_ObjectToWorld, v.vertex).xyz;
                #if HP_TEXTURE_TRIPLANAR
                    o.wnorm = UnityObjectToWorldNormal(v.norm);
                #endif
                o.uv = TRANSFORM_TEX (v.uv, _MainTex);
                return o;
            }

            // Helper to rotate UVs by angle in degrees
            float2 rotateUV(float2 uv, float angleDeg) {
                float angleRad = radians(angleDeg);
                float s = sin(angleRad);
                float c = cos(angleRad);
                float2 center = float2(0.5, 0.5);
                uv -= center;
                float2 rotated = float2(
                    uv.x * c - uv.y * s,
                    uv.x * s + uv.y * c
                );
                return rotated + center;
            }

            // Function to create antialiased polka dot pattern
            float polkaDotPattern(float2 uv) {
                float2 scrolledUV = uv + _OverlayPatternScrolling * _Time.y;
                float2 rotatedUV = rotateUV(scrolledUV, PATTERN_ROTATION);
                float2 localUV = rotatedUV;
                // Offset every other row
                localUV.x += 0.5 / PATTERN_SCALE * (floor(rotatedUV.y * PATTERN_SCALE) % 2.0);
                float2 scaledUV = localUV * PATTERN_SCALE;
                float2 gridPos = frac(scaledUV) - 0.5;
                float dist = length(gridPos);
                float alpha = smoothstep(PATTERN_SIZE + PATTERN_SOFTNESS, PATTERN_SIZE - PATTERN_SOFTNESS, dist);
                return saturate(alpha);
            }

            // Function to create antialiased grid pattern
            float gridPattern(float2 uv) {
                float2 scrolledUV = uv + _OverlayPatternScrolling * _Time.y;
                float2 rotatedUV = rotateUV(scrolledUV, PATTERN_ROTATION);
                float2 scaledUV = rotatedUV * PATTERN_SCALE;
                float2 grid = abs(frac(scaledUV) - 0.5);
                float lin = min(grid.x, grid.y);
                float alpha = smoothstep(PATTERN_SIZE + PATTERN_SOFTNESS, PATTERN_SIZE - PATTERN_SOFTNESS, lin);
                return saturate(alpha);
            }

            // Function to create antialiased staggered horizontal dashed lines
            float staggeredLinePattern(float2 uv) {
                float2 scrolledUV = uv + _OverlayPatternScrolling * _Time.y;
                float2 rotatedUV = rotateUV(scrolledUV, PATTERN_ROTATION);
                float2 scaledUV = rotatedUV * PATTERN_SCALE;
                
                // Row index for staggering the dash pattern
                float row = floor(scaledUV.y);
                float dashOffset = (row % 2.0) * 0.5; // Stagger by half a pattern period along X
                float staggeredX = scaledUV.x + dashOffset;
                
                // Calculate visibility for the horizontal line itself.
                // Thickness is controlled by PATTERN_SIZE.
                // hline_alpha = 1 if on the line, 0 if in the gap between lines.
                float hline_alpha = smoothstep(PATTERN_SIZE + PATTERN_SOFTNESS, PATTERN_SIZE - PATTERN_SOFTNESS, abs(frac(scaledUV.y) - 0.5));
                
                // Calculate visibility for the dash segments along the X-axis.
                // Let's use a fixed 50% duty cycle for dashes (dash length = gap length).
                // For a 50% duty cycle, the effective "size" parameter for the dash segment is 0.25.
                // (because abs(frac(X)-0.5) goes from 0 to 0.5; visible for 0 to 0.25 means 0.25*2=0.5 of the period).
                float dash_segment_parameter = 0.25; 
                float dash_alpha = smoothstep(dash_segment_parameter + PATTERN_SOFTNESS, dash_segment_parameter - PATTERN_SOFTNESS, abs(frac(staggeredX) - 0.5));
                
                // Final alpha: The pixel is visible if it's on a horizontal line AND on a dash segment of that line.
                float final_alpha = hline_alpha * dash_alpha;
                return saturate(final_alpha);
            }

            // Function to create antialiased zigzag pattern
            float zigZagPattern(float2 uv) {
                float2 scrolledUV = uv + _OverlayPatternScrolling * _Time.y;
                float2 rotatedUV = rotateUV(scrolledUV, PATTERN_ROTATION);
                float2 scaledUV = rotatedUV * PATTERN_SCALE;

                // y_center_norm is a triangle wave ^ shape, ranging from 0 to 1, based on scaledUV.x
                // It represents the normalized y-coordinate of the zigzag centerline within a vertical cell.
                float y_center_norm = abs(frac(scaledUV.x) - 0.5) * 2.0;

                // y_pixel_norm is the normalized y-coordinate of the current pixel within a vertical cell.
                float y_pixel_norm = frac(scaledUV.y);

                // dist is the vertical distance from the pixel's normalized y to the zigzag centerline's normalized y.
                float dist = abs(y_pixel_norm - y_center_norm);

                // PATTERN_SIZE defines half the thickness of the line in normalized cell coordinates.
                // Alpha is 1 if dist is small (within PATTERN_SIZE), 0 if dist is large.
                float alpha = smoothstep(PATTERN_SIZE + PATTERN_SOFTNESS, PATTERN_SIZE - PATTERN_SOFTNESS, dist);
                return saturate(alpha);
            }

            fixed4 SampleOverlayTexture(float2 uv) {
                float2 uvOffset = _OverlayTextureScrolling * _Time.y;
                fixed4 tex = tex2D(_OverlayTexture, uv * _OverlayData.w + uvOffset);
                #if HP_PATTERN_POLKADOTS
                    tex.a *= polkaDotPattern(uv);
                #endif
                #if HP_PATTERN_GRID
                    tex.a *= gridPattern(uv);
                #endif
                #if HP_PATTERN_STAGGERED_LINES
                    tex.a *= staggeredLinePattern(uv);
                #endif
                #if HP_PATTERN_ZIGZAG
                    tex.a *= zigZagPattern(uv);
                #endif
                return tex;
            }

            fixed4 frag (v2f i) : SV_Target
            {
            	fixed4 color = tex2D(_MainTex, i.uv);
            	#if HP_ALPHACLIP
            	    clip(color.a - _CutOff);
            	#endif
                float time = _Time.y % 1000;
	    	    fixed t = _OverlayData.y + (1.0 - _OverlayData.y) * 2.0 * abs(0.5 - frac(time * _OverlayData.x));
                fixed4 col = lerp(_OverlayColor, color * _OverlayBackColor * _OverlayColor, _OverlayData.z);
                col.a *= t;

                if (_OverlayHitPosData.w>0) {
                    float elapsed = _Time.y - _OverlayHitStartTime;
                    float hitDist = distance(i.wpos, _OverlayHitPosData.xyz);
                    float atten = saturate( min(elapsed, _OverlayHitPosData.w) / hitDist );
                    col.a *= atten;
                }

                #if HP_TEXTURE_TRIPLANAR
                    half3 triblend = saturate(pow(i.wnorm, 4));
                    triblend /= max(dot(triblend, half3(1,1,1)), 0.0001);

                    // triplanar uvs
                    float3 tpos = i.wpos;
                    float2 uvX = tpos.zy;
                    float2 uvY = tpos.xz;
                    float2 uvZ = tpos.xy;

                    // albedo textures
                    fixed4 colX = SampleOverlayTexture(uvX);
                    fixed4 colY = SampleOverlayTexture(uvY);
                    fixed4 colZ = SampleOverlayTexture(uvZ);
                    fixed4 tex = colX * triblend.x + colY * triblend.y + colZ * triblend.z;
                    col *= tex;
                #elif HP_TEXTURE_SCREENSPACE
                    col *= SampleOverlayTexture(i.scrPos.xy / i.scrPos.w);
                #elif HP_TEXTURE_OBJECTSPACE
                    col *= SampleOverlayTexture(i.uv);
                #endif
                
                return col;
            }
            ENDCG
        }

    }
}