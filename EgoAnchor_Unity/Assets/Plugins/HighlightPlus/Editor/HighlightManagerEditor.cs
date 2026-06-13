using System.Collections;
using System.Collections.Generic;
using UnityEditor;
using UnityEngine;

namespace HighlightPlus {
    [CustomEditor(typeof(HighlightManager))]
    public class HighlightManagerEditor : UnityEditor.Editor {

        SerializedProperty highlightOnHover, layerMask, raycastCamera, raycastSource, blockingLayerMask, minDistance, maxDistance, respectUI, unhighlightOnUI;
        SerializedProperty selectOnClick, selectedProfile, selectedAndHighlightedProfile, singleSelection, toggleOnClick, keepSelection;

        void OnEnable() {
            highlightOnHover = serializedObject.FindProperty("_highlightOnHover");
            layerMask = serializedObject.FindProperty("layerMask");
            raycastCamera = serializedObject.FindProperty("raycastCamera");
            raycastSource = serializedObject.FindProperty("raycastSource");
            blockingLayerMask = serializedObject.FindProperty("blockingLayerMask");
            minDistance = serializedObject.FindProperty("minDistance");
            maxDistance = serializedObject.FindProperty("maxDistance");
            respectUI = serializedObject.FindProperty("respectUI");
            selectOnClick = serializedObject.FindProperty("selectOnClick");
            selectedProfile = serializedObject.FindProperty("selectedProfile");
            selectedAndHighlightedProfile = serializedObject.FindProperty("selectedAndHighlightedProfile");
            singleSelection = serializedObject.FindProperty("singleSelection");
            toggleOnClick = serializedObject.FindProperty("toggle");
            keepSelection = serializedObject.FindProperty("keepSelection");
            unhighlightOnUI = serializedObject.FindProperty("unhighlightOnUI");
        }

        public override void OnInspectorGUI() {
            EditorGUILayout.Separator();
            EditorGUILayout.HelpBox("Only objects with a collider can be highlighted automatically.", MessageType.Info);

            serializedObject.Update();

            EditorGUILayout.PropertyField(layerMask);
            EditorGUILayout.PropertyField(raycastCamera);
            EditorGUILayout.PropertyField(raycastSource);
            EditorGUILayout.PropertyField(blockingLayerMask);
            EditorGUILayout.PropertyField(minDistance);
            EditorGUILayout.PropertyField(maxDistance);
            EditorGUILayout.PropertyField(respectUI);
            if (respectUI.boolValue) {
                EditorGUI.indentLevel++;
                EditorGUILayout.PropertyField(unhighlightOnUI);
                EditorGUI.indentLevel--;
            }
            EditorGUILayout.PropertyField(highlightOnHover);
            EditorGUILayout.PropertyField(selectOnClick);
            if (selectOnClick.boolValue) {
                EditorGUI.indentLevel++;
                EditorGUILayout.PropertyField(selectedProfile);
                EditorGUILayout.PropertyField(selectedAndHighlightedProfile);
                EditorGUILayout.PropertyField(singleSelection);
                EditorGUILayout.PropertyField(toggleOnClick);
                EditorGUILayout.PropertyField(keepSelection);
                EditorGUI.indentLevel--;
            }

            serializedObject.ApplyModifiedProperties();
        }


        [MenuItem("GameObject/Effects/Highlight Plus/Create Highlight Manager", false, 10)]
		static void CreateManager (MenuCommand menuCommand) {
			HighlightManager manager = Misc.FindObjectOfType<HighlightManager> ();
			if (manager == null) {
				GameObject managerGO = new GameObject ("HighlightPlusManager");
				manager = managerGO.AddComponent<HighlightManager> ();
				// Register root object for undo.
				Undo.RegisterCreatedObjectUndo (manager, "Create Highlight Plus Manager");
			}
			Selection.activeObject = manager;
		}

    }

}
