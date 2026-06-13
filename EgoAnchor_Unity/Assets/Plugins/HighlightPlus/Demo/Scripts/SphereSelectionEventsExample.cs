using UnityEngine;
using HighlightPlus;

namespace HighlightPlus.Demos {
	
	public class SphereSelectionEventsExample : MonoBehaviour {

		public HighlightManager manager;
			
		void Start() {
			manager.OnObjectSelected += OnObjectSelected;
			manager.OnObjectUnSelected += OnObjectUnSelected;
		}

		bool OnObjectSelected(GameObject go) {
			Debug.Log(go.name + " selected!");
			return true;
        }

		bool OnObjectUnSelected(GameObject go) {
			Debug.Log(go.name + " un-selected!");
			return true;
		}


	}

}