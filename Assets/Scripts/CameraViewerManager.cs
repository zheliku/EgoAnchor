using System.Collections;
using Meta.XR;
using UnityEngine;
using UnityEngine.UI;

/// <summary>
/// Quest 相机纹理显示管理器。
///
/// 用途：
/// - 等待左右 Passthrough 相机可用。
/// - 将左右纹理绑定到 UI RawImage，便于本地可视化联调。
/// </summary>
public class CameraViewerManager : MonoBehaviour
{
    [SerializeField]
    private PassthroughCameraAccess _leftCameraAccess;
    [SerializeField]
    private PassthroughCameraAccess _rightCameraAccess;

    [SerializeField]
    private RawImage _leftImage;
    [SerializeField]
    private RawImage _rightImage;

    private Texture _leftCameraTexture;
    private Texture _rightCameraTexture;

    IEnumerator Start()
    {
        while (!_leftCameraAccess || !_rightCameraAccess ||
               !_leftCameraAccess.IsPlaying || !_rightCameraAccess.IsPlaying)
        {
            yield return null;
        }

        _leftCameraTexture = _leftCameraAccess.GetTexture();
        _rightCameraTexture = _rightCameraAccess.GetTexture();
        while (_leftCameraTexture == null || _rightCameraTexture == null)
        {
            yield return null;
            _leftCameraTexture = _leftCameraAccess.GetTexture();
            _rightCameraTexture = _rightCameraAccess.GetTexture();
        }

        if (_leftImage != null)
        {
            _leftImage.texture = _leftCameraTexture;
        }
        if (_rightImage != null)
        {
            _rightImage.texture = _rightCameraTexture;
        }
    }
}
