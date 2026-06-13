using UnityEditor;
using UnityEngine;

namespace HighlightPlus {

    [CustomEditor(typeof(HighlightEffectBlocker))]
    public class HighlightEffectBlockerEditor : Editor {

        SerializedProperty include, layerMask, blockOutlineAndGlow, blockOverlay, nameFilter, useRegEx;
        HighlightEffectBlocker hb;

        void OnEnable() {
            include = serializedObject.FindProperty("include");
            layerMask = serializedObject.FindProperty("layerMask");
            nameFilter = serializedObject.FindProperty("nameFilter");
            useRegEx = serializedObject.FindProperty("useRegEx");
            blockOutlineAndGlow = serializedObject.FindProperty("blockOutlineAndGlow");
            blockOverlay = serializedObject.FindProperty("blockOverlay");
            hb = (HighlightEffectBlocker)target;
        }

        public override void OnInspectorGUI() {

            serializedObject.Update();

            EditorGUILayout.PropertyField(include);
            if (include.intValue == (int)BlockerTargetOptions.LayerInChildren) {
                EditorGUI.indentLevel++;
                EditorGUILayout.PropertyField(layerMask);
                EditorGUI.indentLevel--;
            }
            if (include.intValue != (int)BlockerTargetOptions.OnlyThisObject) {
                EditorGUI.indentLevel++;
                EditorGUILayout.PropertyField(nameFilter, new GUIContent("Object Name Filter"));
                EditorGUILayout.PropertyField(useRegEx, new GUIContent("Use Regular Expressions"));
                EditorGUI.indentLevel--;
            }
            EditorGUILayout.PropertyField(blockOutlineAndGlow);
            EditorGUILayout.PropertyField(blockOverlay);

            if (serializedObject.ApplyModifiedProperties()) {
                hb.Refresh();
            }
        }
    }
} 