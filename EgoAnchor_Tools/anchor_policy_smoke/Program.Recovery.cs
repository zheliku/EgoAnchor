using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Threading.Tasks;
using EgoAnchor.Client;
using EgoAnchor.Policy;
using EgoAnchor.Protocol.Generated;
using EgoAnchor.Runtime;
using UnityEngine;

static partial class Program
{
    private static void AssertRecoveryControllerDoesNothingWhenDisabled()
    {
        PoseToAnchorRuntime runtime = CreatePoseRuntimeForSmoke();
        SetRuntimeStateForSmoke(runtime, inputReady: true, state: AnchorState.Lost);
        FakeAnchorCommandSender sender = new FakeAnchorCommandSender();
        AnchorRecoveryController controller = CreateRecoveryController(runtime, sender);
        SetRecoveryField(controller, "enableAutoReacquire", false);

        bool triggered = controller.Tick(1.0);

        Assert(!triggered, "disabled recovery controller should not trigger");
        Assert(sender.Calls == 0, "disabled recovery controller should not send command");
        Assert(controller.LatestReason == "auto_reacquire_disabled", "disabled recovery should expose a clear reason");
    }

    private static void AssertRecoveryControllerTriggersOnLostWhenEnabled()
    {
        PoseToAnchorRuntime runtime = CreatePoseRuntimeForSmoke();
        SetRuntimeStateForSmoke(runtime, inputReady: true, state: AnchorState.Lost);
        FakeAnchorCommandSender sender = new FakeAnchorCommandSender();
        AnchorRecoveryController controller = CreateRecoveryController(runtime, sender);
        SetRecoveryField(controller, "lostSeconds", 0.3f);

        Assert(!controller.Tick(2.0), "lost trigger should wait for configured duration");
        Assert(controller.Tick(2.31), "lost trigger should fire after configured duration");

        Assert(sender.Calls == 1, "lost trigger should send one reacquire command");
        Assert(sender.Reasons[0] == AnchorRecoveryController.ReasonLost, "lost trigger should use fixed reason");
        Assert(sender.ClearTrackingFirst[0], "lost trigger should pass clearTrackingFirst");
    }

    private static void AssertRecoveryControllerTriggersOnLowScoreOnlyWhenEnabled()
    {
        PoseToAnchorRuntime runtime = CreatePoseRuntimeForSmoke();
        SetRuntimeStateForSmoke(runtime, inputReady: true, state: AnchorState.Tracking, frameId: 7, score: 0.1f);

        FakeAnchorCommandSender disabledSender = new FakeAnchorCommandSender();
        AnchorRecoveryController disabled = CreateRecoveryController(runtime, disabledSender);
        SetRecoveryField(disabled, "enableLowScoreReacquire", false);
        SetRecoveryField(disabled, "lowScoreSeconds", 0.0f);
        Assert(!disabled.Tick(3.0), "low-score trigger should stay off when enableLowScoreReacquire=false");
        Assert(disabledSender.Calls == 0, "disabled low-score trigger should not send command");

        FakeAnchorCommandSender enabledSender = new FakeAnchorCommandSender();
        AnchorRecoveryController enabled = CreateRecoveryController(runtime, enabledSender);
        SetRecoveryField(enabled, "enableLowScoreReacquire", true);
        SetRecoveryField(enabled, "lowScoreSeconds", 0.0f);
        Assert(enabled.Tick(3.0), "low-score trigger should fire when explicitly enabled");
        Assert(enabledSender.Calls == 1, "enabled low-score trigger should send command");
        Assert(enabledSender.Reasons[0] == AnchorRecoveryController.ReasonLowScore, "low-score trigger should use fixed reason");
    }

    private static void AssertRecoveryControllerHonorsCooldownAndInFlight()
    {
        PoseToAnchorRuntime runtime = CreatePoseRuntimeForSmoke();
        SetRuntimeStateForSmoke(runtime, inputReady: true, state: AnchorState.Lost);

        FakeAnchorCommandSender pendingSender = new FakeAnchorCommandSender();
        pendingSender.Pending = new TaskCompletionSource<CommandAck>(TaskCreationOptions.RunContinuationsAsynchronously);
        AnchorRecoveryController inFlightController = CreateRecoveryController(runtime, pendingSender);
        SetRecoveryField(inFlightController, "lostSeconds", 0.0f);
        Assert(inFlightController.Tick(4.0), "first lost tick should send a pending command");
        Assert(inFlightController.InFlight, "controller should expose in-flight command state");
        Assert(!inFlightController.Tick(14.0), "in-flight guard should suppress repeated commands");
        Assert(pendingSender.Calls == 1, "in-flight guard should keep command count at one");

        FakeAnchorCommandSender cooldownSender = new FakeAnchorCommandSender();
        AnchorRecoveryController cooldownController = CreateRecoveryController(runtime, cooldownSender);
        SetRecoveryField(cooldownController, "lostSeconds", 0.0f);
        SetRecoveryField(cooldownController, "cooldownSeconds", 3.0f);
        Assert(cooldownController.Tick(10.0), "first lost tick should send command before cooldown");
        Assert(!cooldownController.Tick(11.0), "cooldown guard should suppress early second command");
        Assert(cooldownController.Tick(13.1), "cooldown guard should release after configured interval");
        Assert(cooldownSender.Calls == 2, "cooldown controller should send exactly two commands after release");
    }

    private static void AssertRecoveryControllerWaitsWhenInputNotReady()
    {
        PoseToAnchorRuntime runtime = CreatePoseRuntimeForSmoke();
        SetRuntimeStateForSmoke(runtime, inputReady: false, state: AnchorState.Lost);
        FakeAnchorCommandSender sender = new FakeAnchorCommandSender();
        AnchorRecoveryController controller = CreateRecoveryController(runtime, sender);
        SetRecoveryField(controller, "lostSeconds", 0.0f);

        Assert(!controller.Tick(5.0), "input-not-ready guard should suppress recovery");
        Assert(sender.Calls == 0, "input-not-ready guard should not send command");
        Assert(controller.LatestReason == AnchorRecoveryController.ReasonInputNotReady, "input-not-ready guard should expose fixed reason");

        SetRuntimeStateForSmoke(runtime, inputReady: true);
        Assert(controller.Tick(5.1), "controller should resume trigger evaluation when input becomes ready");
        Assert(sender.Calls == 1, "ready input should allow command");
    }

    private static AnchorRecoveryController CreateRecoveryController(PoseToAnchorRuntime runtime, IAnchorCommandSender sender)
    {
        AnchorRecoveryController controller = (AnchorRecoveryController)RuntimeHelpers.GetUninitializedObject(typeof(AnchorRecoveryController));
        MakeUnityObjectNonNull(controller);
        SetRecoveryField(controller, "runtime", runtime);
        controller.SetCommandSenderForTesting(sender);
        SetRecoveryField(controller, "enableAutoReacquire", true);
        SetRecoveryField(controller, "enableLowScoreReacquire", false);
        SetRecoveryField(controller, "enableLostReacquire", true);
        SetRecoveryField(controller, "enableNoPoseReacquire", true);
        SetRecoveryField(controller, "lowScoreThreshold", 0.25f);
        SetRecoveryField(controller, "lowScoreSeconds", 0.8f);
        SetRecoveryField(controller, "lostSeconds", 0.3f);
        SetRecoveryField(controller, "noPoseSeconds", 1.0f);
        SetRecoveryField(controller, "cooldownSeconds", 3.0f);
        SetRecoveryField(controller, "clearTrackingFirst", true);
        SetRecoveryField(controller, "lowScoreStartSeconds", -1.0);
        SetRecoveryField(controller, "lostStartSeconds", -1.0);
        SetRecoveryField(controller, "noPoseStartSeconds", -1.0);
        SetRecoveryField(controller, "lastCommandSeconds", double.NegativeInfinity);
        SetRecoveryField(controller, "latestReason", "");
        return controller;
    }

    private static void SetRecoveryField(AnchorRecoveryController controller, string fieldName, object value)
    {
        typeof(AnchorRecoveryController)
            .GetField(fieldName, BindingFlags.Instance | BindingFlags.NonPublic)
            .SetValue(controller, value);
    }

    private sealed class FakeAnchorCommandSender : IAnchorCommandSender
    {
        public int Calls;
        public readonly List<string> Reasons = new List<string>();
        public readonly List<bool> ClearTrackingFirst = new List<bool>();
        public TaskCompletionSource<CommandAck> Pending;

        public Task<CommandAck> ReacquireAsync(
            ReacquireAnchorRequest.Types.ReacquireMode mode,
            bool clearTrackingFirst,
            string promptOverride = "",
            double timeoutMs = 0.0,
            string reason = "unity_api",
            CancellationToken token = default)
        {
            Calls++;
            Reasons.Add(reason);
            ClearTrackingFirst.Add(clearTrackingFirst);
            return Pending != null
                ? Pending.Task
                : Task.FromResult(new CommandAck { Accepted = true, Status = "accepted" });
        }
    }
}
