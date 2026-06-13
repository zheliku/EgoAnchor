using UnityEngine;

namespace HighlightPlus.Demos {

    public class SimpleCharacterController : MonoBehaviour {
        public float moveSpeed = 5f;
        public float mouseSensitivity = 2f;
        public Transform playerCamera;
        private float rotationX = 0f;

        void Start () {
            Cursor.lockState = CursorLockMode.Locked; // Locks cursor to center
            Cursor.visible = true; // Keeps cursor visible
        }

        void Update () {
            // Movement input using WASD
            float moveX = 0f, moveZ = 0f;
            if (Input.GetKey(KeyCode.W)) moveZ = 1f;
            if (Input.GetKey(KeyCode.S)) moveZ = -1f;
            if (Input.GetKey(KeyCode.A)) moveX = -1f;
            if (Input.GetKey(KeyCode.D)) moveX = 1f;

            Vector3 moveDirection = transform.right * moveX + transform.forward * moveZ;
            transform.position += moveDirection * moveSpeed * Time.deltaTime;

            // Mouse look input
            float mouseX = Input.GetAxis("Mouse X") * mouseSensitivity;
            float mouseY = Input.GetAxis("Mouse Y") * mouseSensitivity;

            rotationX -= mouseY;
            rotationX = Mathf.Clamp(rotationX, -90f, 90f); // Prevents flipping

            playerCamera.localRotation = Quaternion.Euler(rotationX, 0f, 0f);
            transform.Rotate(Vector3.up * mouseX);

            // Keep cursor locked in center
            Cursor.lockState = CursorLockMode.Locked;
            Cursor.visible = true;
        }
    }
}