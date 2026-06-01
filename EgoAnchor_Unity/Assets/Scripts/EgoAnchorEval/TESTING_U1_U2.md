# U1/U2 Manual Test Guide

This file is the required test script and checklist for Stage U1/U2.

## Automated Checks

Run from repository root:

```powershell
dotnet run --project EgoAnchor_Tools\eval_writer_smoke\EvalWriterSmoke.csproj
dotnet build EgoAnchor_Unity\EgoAnchorEval.csproj --no-restore
dotnet build EgoAnchor_Unity\Assembly-CSharp.csproj --no-restore
```

Expected result: all three commands exit 0. The smoke command writes a temporary JSONL row and checks exact JSON bytes plus capture/output JSON fields.

## Scene Setup

1. In the Unity evaluation scene, create or select `EvalRig`.
2. Add these components to `EvalRig`:
   - `ControllerGroundTruthProvider`
   - `AnchorEvalRecorder`
   - `EvalManualSmokeDriver`
3. Bind `ControllerGroundTruthProvider.cameraRig` to the scene `OVRCameraRig`.
4. Set `ControllerGroundTruthProvider.controller` to the controller under test.
5. Bind `AnchorEvalRecorder.gt` to the provider on `EvalRig`.
6. Bind `AnchorEvalRecorder.headAnchor` to `OVRCameraRig/TrackingSpace/CenterEyeAnchor`.
7. Set `AnchorEvalRecorder.alignmentReference` to `Left`.
8. Bind `AnchorEvalRecorder.stereoSource` and `framePoseHistory` to the same scene instances used by runtime streaming.
9. Add at least two `recordedRuntimes`:
   - primary stable runtime, label `kalman` or current stable label, `isPrimary=true`
   - raw runtime, label `raw`, `isPrimary=false`
10. Bind `EvalManualSmokeDriver.gt` and `recorder` to the same components.

## U1 GT Test

1. Enter Play Mode with Quest Link active.
2. Press `F6` to toggle GT logging, or use the component context menu `EgoAnchor Eval/Log Ground Truth Once`.
3. Move the selected controller.
4. Confirm Console logs look like:

```text
[EgoAnchorEval][U1] controller=RTouch has_pose=True tracked=True pos=(...) rot_xyzw=(...)
```

Expected result: position changes with the controller. `tracked` is true when visible and becomes false when tracking is lost.

## U2 Recorder Test

1. In Play Mode, press `F7`, or use context menu `EgoAnchor Eval/Begin U1 U2 Smoke Recording`.
2. Move head/controller for 5-10 seconds.
3. Press `F8`, or use context menu `EgoAnchor Eval/Stop U1 U2 Smoke Recording`.
4. Check the logged session directory printed in Console. Default root:

```text
EgoAnchor_Python/data/eval/manual_smoke/<session_id>/
```

Expected files:

```text
<session_id>_unity_capture.jsonl
<session_id>_unity_output.jsonl
```

Expected content:

- capture rows contain increasing `frame_id`, `capture_mono_ms`, `head_pos`, `cam_pos`, `gt_pos`, and `gt_tracked`.
- output rows contain `render_mono_ms`, `source_frame_id`, `gt_pos`, and a `variants` array.
- the primary variant contains `aligned_raw_pos`, `aligned_raw_rot`, and `reliability_score`.
- output row count should be higher than capture row count.
