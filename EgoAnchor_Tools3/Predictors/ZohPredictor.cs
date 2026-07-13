using EgoAnchor.Tools3.Core;
using EgoAnchor.Tools3.Data;
using EgoAnchor.Tools3.Sim;

namespace EgoAnchor.Tools3.Predictors
{
    /// <summary>
    /// 零阶保持基线：收到观测后保持最近位姿，直到下一帧到达。
    /// </summary>
    public sealed class ZohPredictor : IPredictor
    {
        private Pose lastPose = Pose.Identity;
        private bool hasPose;

        public string Label => "zoh";

        public bool HasEstimate => hasPose;

        public void Reset()
        {
            lastPose = Pose.Identity;
            hasPose = false;
        }

        public void OnObservation(in Observation observation)
        {
            lastPose = observation.Pose;
            hasPose = true;
        }

        public Pose PredictAt(double renderTimeSeconds)
        {
            // 零阶保持与渲染时刻无关，始终返回最近一帧观测。
            return lastPose;
        }
    }
}
