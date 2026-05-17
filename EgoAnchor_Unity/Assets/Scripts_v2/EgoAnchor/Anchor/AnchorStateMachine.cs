namespace EgoAnchor.V2.Anchor
{
    /// <summary>
    /// v2 anchor 生命周期状态。
    /// </summary>
    public enum AnchorState
    {
        Uninitialized,
        Searching,
        Tracking,
        Coasting,
        FrozenUncertain,
        Lost,
        Relocalizing,
        Paused,
    }

    /// <summary>
    /// v2 anchor 状态机占位。
    /// </summary>
    public sealed class AnchorStateMachine
    {
        public AnchorState State { get; private set; } = AnchorState.Uninitialized;

        public void Reset()
        {
            State = AnchorState.Searching;
        }
    }
}
