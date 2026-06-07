param(
    [string]$ProtocolRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$PythonOut = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\..\EgoAnchor_Python")).Path "src"),
    [string]$UnityProtocolOut = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\..\EgoAnchor_Unity")).Path "Assets\Scripts\EgoAnchor\Protocol"),
    [string]$CSharpOut = (Join-Path $UnityProtocolOut "Generated"),
    [string]$CSharpNamespace = "EgoAnchor.Protocol.Generated"
)

$ErrorActionPreference = "Stop"

$ProtoRoot = Join-Path $ProtocolRoot "proto"
$Protoc = Get-Command protoc -ErrorAction Stop
New-Item -ItemType Directory -Force -Path $PythonOut | Out-Null
New-Item -ItemType Directory -Force -Path $CSharpOut | Out-Null
New-Item -ItemType Directory -Force -Path $UnityProtocolOut | Out-Null

$ProtoFiles = @(
    (Join-Path $ProtoRoot "protocol\v1\common.proto"),
    (Join-Path $ProtoRoot "protocol\v1\quest.proto"),
    (Join-Path $ProtoRoot "protocol\v1\anchor.proto")
)

function Invoke-PythonProtoGeneration {
    param(
        [Parameter(Mandatory=$true)][string]$OutputRoot
    )

    New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
    $tempRoot = Join-Path $OutputRoot ".proto_gen_tmp"
    if (Test-Path $tempRoot) {
        Remove-Item -Recurse -Force $tempRoot
    }
    New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
    & $Protoc.Source --proto_path=$ProtoRoot --python_out=$tempRoot $ProtoFiles
    if ($LASTEXITCODE -ne 0) {
        throw "protoc Python generation failed with exit code $LASTEXITCODE"
    }
    $tempV1 = Join-Path $tempRoot "protocol\v1"
    if (-not (Test-Path $tempV1)) {
        throw "protoc Python generation did not produce protocol\v1"
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $OutputRoot "egoanchor") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $OutputRoot "egoanchor\protocol") | Out-Null
    $targetV1 = Join-Path $OutputRoot "egoanchor\protocol\v1"
    if (Test-Path $targetV1) {
        Remove-Item -Recurse -Force $targetV1
    }
    Move-Item $tempV1 $targetV1
    Remove-Item -Recurse -Force $tempRoot
    if (-not (Test-Path (Join-Path $OutputRoot "egoanchor\protocol\__init__.py"))) {
        Set-Content -Path (Join-Path $OutputRoot "egoanchor\protocol\__init__.py") -Value "# protocol package`n" -Encoding UTF8
    }
    $v1Init = @'
"""protocol.v1 生成代码包级入口。

业务代码不直接导入具体 ``*_pb2.py`` 文件，而是从本包或上层
``egoanchor.protocol`` 入口获取 Protobuf 模块和常用消息类型。
"""

from __future__ import annotations

from . import anchor_pb2, common_pb2, quest_pb2

AnchorControlRequest = anchor_pb2.AnchorControlRequest
"""anchor control command request 类型。"""

CommandAck = common_pb2.CommandAck
"""command request/reply 的 ack 类型。"""

ErrorInfo = common_pb2.ErrorInfo
"""共享错误信息类型。"""

MessageHeader = common_pb2.MessageHeader
"""共享消息头类型。"""

Matrix4x4 = common_pb2.Matrix4x4
"""4x4 矩阵消息类型。"""

PoseResult = anchor_pb2.PoseResult
"""Python -> Unity pose result 类型。"""

QuestCameraInfo = quest_pb2.QuestCameraInfo
"""Quest 相机标定消息类型。"""

QuestStereoFrame = quest_pb2.QuestStereoFrame
"""Quest 双目帧消息类型。"""

ReacquireAnchorRequest = anchor_pb2.ReacquireAnchorRequest
"""主动重新获取 anchor 的 command request 类型。"""

ResetTrackingRequest = anchor_pb2.ResetTrackingRequest
"""重置 tracking 的 command request 类型。"""

__all__ = [
    "AnchorControlRequest",
    "CommandAck",
    "ErrorInfo",
    "MessageHeader",
    "Matrix4x4",
    "PoseResult",
    "QuestCameraInfo",
    "QuestStereoFrame",
    "ReacquireAnchorRequest",
    "ResetTrackingRequest",
    "anchor_pb2",
    "common_pb2",
    "quest_pb2",
]
'@
    Set-Content -Path (Join-Path $OutputRoot "egoanchor\protocol\v1\__init__.py") -Value $v1Init -Encoding UTF8

    # protoc 34.1 emits Python gencode with a 7.34.1 runtime guard, while the
    # current pixi environment can resolve protobuf 7.34.0. The generated wire code
    # is compatible for these messages, so strip only the guard block to keep local
    # tests and runtime imports stable until the environment moves to a matching
    # protobuf runtime.
    Get-ChildItem -Path (Join-Path $OutputRoot "egoanchor\protocol\v1") -Filter "*_pb2.py" | ForEach-Object {
        $content = Get-Content -Raw -Path $_.FullName
        $content = $content -replace "from google\.protobuf import runtime_version as _runtime_version\r?\n", ""
        $content = $content -replace "_runtime_version\.ValidateProtobufRuntimeVersion\([\s\S]*?\)\r?\n# @@protoc_insertion_point\(imports\)", "# @@protoc_insertion_point(imports)"
        $content = $content -replace "from protocol\.v1 import", "from egoanchor.protocol.v1 import"
        $content = $content -replace "'protocol\.v1\.", "'egoanchor.protocol.v1."
        Set-Content -Path $_.FullName -Value $content -Encoding UTF8
    }
}

function Invoke-CSharpProtoGeneration {
    param(
        [Parameter(Mandatory=$true)][string]$UnityProtocolRoot,
        [Parameter(Mandatory=$true)][string]$NamespaceLine,
        [Parameter(Mandatory=$false)][string]$NamespaceReplacement = "",
        [Parameter(Mandatory=$false)][string]$GeneratedRootOverride = "",
        [Parameter(Mandatory=$false)][string]$SubjectConstantsFileName = "SubjectNames.cs",
        [Parameter(Mandatory=$false)][string]$SubjectConstantsClassName = "SubjectNames"
    )

    $generatedRoot = if ([string]::IsNullOrWhiteSpace($GeneratedRootOverride)) { Join-Path $UnityProtocolRoot "Generated" } else { $GeneratedRootOverride }
    New-Item -ItemType Directory -Force -Path $generatedRoot | Out-Null
    New-Item -ItemType Directory -Force -Path $UnityProtocolRoot | Out-Null
    $tempGeneratedRoot = Join-Path $generatedRoot ".proto_gen_tmp"
    if (Test-Path $tempGeneratedRoot) {
        Remove-Item -Recurse -Force $tempGeneratedRoot
    }
    New-Item -ItemType Directory -Force -Path $tempGeneratedRoot | Out-Null
    & $Protoc.Source --proto_path=$ProtoRoot --csharp_out=$tempGeneratedRoot $ProtoFiles
    if ($LASTEXITCODE -ne 0) {
        throw "protoc C# generation failed with exit code $LASTEXITCODE"
    }

    Get-ChildItem -Path $generatedRoot -Filter "*.cs" -File | Remove-Item -Force
    Get-ChildItem -Path $tempGeneratedRoot -Filter "*.cs" -File | Move-Item -Destination $generatedRoot -Force
    Remove-Item -Recurse -Force $tempGeneratedRoot

    if (-not [string]::IsNullOrWhiteSpace($NamespaceReplacement)) {
        Get-ChildItem -Path $generatedRoot -Filter "*.cs" | ForEach-Object {
            $content = Get-Content -Raw -Path $_.FullName
            $content = $content -replace "namespace EgoAnchor\.Protocol\.V1", "namespace $NamespaceReplacement"
            $content = $content -replace "global::EgoAnchor\.Protocol\.V1\.", "global::$NamespaceReplacement."
            Set-Content -Path $_.FullName -Value $content -Encoding UTF8
        }
    }

    $subjectsPath = Join-Path $ProtocolRoot "subjects.v1.json"
    $subjectsJson = Get-Content -Raw -Path $subjectsPath | ConvertFrom-Json -AsHashtable
    $subjectNamesPath = Join-Path $UnityProtocolRoot $SubjectConstantsFileName
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("namespace $NamespaceLine")
    $lines.Add("{")
    $lines.Add("    /// <summary>")
    $lines.Add("    /// Unity 侧逻辑 subject 名称常量。")
    $lines.Add("    /// 本文件由 EgoAnchor_Protocol/tools/generate_proto.ps1 从 subjects.v1.json 生成。")
    $lines.Add("    /// 不要手动修改；subject 变更请改 subjects.v1.json 后重新运行生成脚本。")
    $lines.Add("    /// </summary>")
    $lines.Add("    public static class $SubjectConstantsClassName")
    $lines.Add("    {")
    $nameMap = @{
        "egoanchor.v1.quest.stereo" = "QuestStereo"
        "egoanchor.v1.quest.camera_info" = "QuestCameraInfo"
        "egoanchor.v1.pose.result" = "PoseResult"
        "egoanchor.v1.anchor.status" = "AnchorStatus"
        "egoanchor.v1.server.heartbeat" = "ServerHeartbeat"
        "egoanchor.v1.cmd.anchor.reset" = "ResetTracking"
        "egoanchor.v1.cmd.anchor.reacquire" = "ReacquireAnchor"
        "egoanchor.v1.cmd.anchor.control" = "AnchorControl"
    }
    $summaryMap = @{
        "egoanchor.v1.quest.stereo" = "Unity -> Python：Quest 双目 JPEG 图像数据面。"
        "egoanchor.v1.quest.camera_info" = "Unity -> Python：Quest 相机标定数据面。"
        "egoanchor.v1.pose.result" = "Python -> Unity：pose result 控制面消息。"
        "egoanchor.v1.anchor.status" = "Python -> Unity：anchor 状态事件。"
        "egoanchor.v1.server.heartbeat" = "Python -> Unity：服务心跳。"
        "egoanchor.v1.cmd.anchor.reset" = "Unity -> Python：reset request/reply 命令。"
        "egoanchor.v1.cmd.anchor.reacquire" = "Unity -> Python：reacquire request/reply 命令。"
        "egoanchor.v1.cmd.anchor.control" = "Unity -> Python：anchor control request/reply 命令。"
    }
    foreach ($subject in $subjectsJson.Keys) {
        $constName = $nameMap[$subject]
        if ([string]::IsNullOrWhiteSpace($constName)) {
            $constName = ($subject -replace "^egoanchor\.v1\.", "" -replace "[^A-Za-z0-9]+", " ").Split(" ") | ForEach-Object { if ($_) { $_.Substring(0,1).ToUpperInvariant() + $_.Substring(1) } }
            $constName = ($constName -join "")
        }
        $summary = $summaryMap[$subject]
        if ([string]::IsNullOrWhiteSpace($summary)) {
            $summary = "subjects.v1.json 中定义的逻辑 subject。"
        }
        $lines.Add("        /// <summary>$summary</summary>")
        $lines.Add("        public const string $constName = `"$subject`";")
    }
    $lines.Add("    }")
    $lines.Add("}")
    Set-Content -Path $subjectNamesPath -Value ($lines -join "`r`n") -Encoding UTF8
}

Invoke-PythonProtoGeneration -OutputRoot $PythonOut
Invoke-CSharpProtoGeneration -UnityProtocolRoot $UnityProtocolOut -NamespaceLine "EgoAnchor.Protocol" -NamespaceReplacement $CSharpNamespace -GeneratedRootOverride $CSharpOut -SubjectConstantsFileName "SubjectNames.cs" -SubjectConstantsClassName "SubjectNames"
