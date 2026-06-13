#ifndef CUSTOM_VERTEX_TRANSFORM_INCLUDED
#define CUSTOM_VERTEX_TRANSFORM_INCLUDED

int _HP_VertexTransformMode;

float4 ComputeVertexPosition(float4 vertex) {
    // Add custom vertex transforms here based on _HP_VertexTransformMode
    // Mode 0: default transform
    // Mode 1+: add your custom transforms below
    UNITY_BRANCH
    switch (_HP_VertexTransformMode) {
        case 1:
            // Example: custom transform 1
            // vertex.xyz += ...
            break;
        case 2:
            // Example: custom transform 2
            // vertex.xyz += ...
            break;
        default:
            // Default transform
            break;
    }
    return UnityObjectToClipPos(vertex);
}
		
#endif
