using UnityEngine;
using HighlightPlus;

namespace HighlightPlus.Demos {

    public class ManualSelectionDemo : MonoBehaviour {

        public HighlightManager manager;
        public Transform objectToSelect;

        public Transform[] objectsToSelect;

        void Update () {
            if (InputProxy.GetKeyDown("1")) {
                manager.SelectObject(objectToSelect);
            }
            if (InputProxy.GetKeyDown("2")) {
                manager.ToggleObject(objectToSelect);
            }
            if (InputProxy.GetKeyDown("3")) {
                manager.UnselectObject(objectToSelect);
            }
            if (InputProxy.GetKeyDown("4")) {
                manager.SelectObjects(objectsToSelect);
            }
            if (InputProxy.GetKeyDown("5")) {
                manager.UnselectObjects();
            }

        }
    }
}
