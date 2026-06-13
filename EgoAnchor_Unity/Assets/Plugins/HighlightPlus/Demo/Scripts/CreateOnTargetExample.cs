using UnityEngine;
using HighlightPlus;

namespace HighlightPlus.Demos {

	public class CreateOnTargetExample : MonoBehaviour {

		public HighlightManager manager;
		public GameObject prefab;

		void Start () {
			manager.OnObjectClicked += OnObjectClicked;
		}

		void OnObjectClicked (GameObject clickedGameObject, Vector3 clickPosition, Vector3 normal) {
			// Align capsule's up direction with the surface normal to make it stand upright
			Quaternion rotation = Quaternion.FromToRotation(Vector3.up, normal);
			GameObject newObject = Instantiate(prefab, clickPosition, rotation);
			newObject.name = "New Object";
		}



	}

}