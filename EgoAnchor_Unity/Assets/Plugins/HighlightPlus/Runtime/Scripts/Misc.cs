
using UnityEngine;
using System;

namespace HighlightPlus {
        
    public class Misc {

        public static Vector2 vector2Zero = new Vector2(0, 0);
        public static Vector2 vector2One = new Vector2(1, 1);
        public static Vector3 vector3Zero = new Vector3(0, 0, 0);
        public static Vector3 vector3Max = new Vector3(float.MaxValue, float.MaxValue, float.MaxValue);
        public static Vector3 vector3Min = new Vector3(float.MinValue, float.MinValue, float.MinValue);
        
        public static T FindObjectOfType<T>(bool includeInactive = false) where T : UnityEngine.Object {
#if UNITY_2023_1_OR_NEWER
            return UnityEngine.Object.FindAnyObjectByType<T>(includeInactive ? FindObjectsInactive.Include : FindObjectsInactive.Exclude);
#else
        return UnityEngine.Object.FindObjectOfType<T>(includeInactive);
#endif
        }

        public static UnityEngine.Object[] FindObjectsOfType(Type type, bool includeInactive = false) {
#if UNITY_2023_1_OR_NEWER
            return UnityEngine.Object.FindObjectsByType(type, includeInactive ? FindObjectsInactive.Include : FindObjectsInactive.Exclude, FindObjectsSortMode.None);
#else
        return UnityEngine.Object.FindObjectsOfType(type, includeInactive);
#endif
        }


        public static T[] FindObjectsOfType<T>(bool includeInactive = false) where T : UnityEngine.Object {
#if UNITY_2023_1_OR_NEWER
            return UnityEngine.Object.FindObjectsByType<T>(includeInactive ? FindObjectsInactive.Include : FindObjectsInactive.Exclude, FindObjectsSortMode.None);
#else
        return UnityEngine.Object.FindObjectsOfType<T>(includeInactive);
#endif
        }
    }

}