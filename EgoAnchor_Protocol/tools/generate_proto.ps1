param(
    [string]$ProtocolRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$PythonOut = (Resolve-Path (Join-Path $PSScriptRoot "..\..\EgoAnchor_Python\src_v2")).Path,
    [string]$CSharpOut = (Resolve-Path (Join-Path $PSScriptRoot "..\..\EgoAnchor_Unity\Assets\Scripts_v2\EgoAnchor\Protocol\Generated")).Path,
    [string]$UnityProtocolOut = (Resolve-Path (Join-Path $PSScriptRoot "..\..\EgoAnchor_Unity\Assets\Scripts_v2\EgoAnchor\Protocol")).Path
)

$ProtoRoot = Join-Path $ProtocolRoot "proto"
New-Item -ItemType Directory -Force -Path $PythonOut | Out-Null
New-Item -ItemType Directory -Force -Path $CSharpOut | Out-Null
New-Item -ItemType Directory -Force -Path $UnityProtocolOut | Out-Null

$ProtoFiles = @(
    (Join-Path $ProtoRoot "protocol\v1\common.proto"),
    (Join-Path $ProtoRoot "protocol\v1\quest.proto"),
    (Join-Path $ProtoRoot "protocol\v1\anchor.proto")
)

protoc --proto_path=$ProtoRoot --python_out=$PythonOut $ProtoFiles
New-Item -ItemType Directory -Force -Path (Join-Path $PythonOut "egoanchor") | Out-Null
if (Test-Path (Join-Path $PythonOut "egoanchor\protocol")) {
    Remove-Item -Recurse -Force (Join-Path $PythonOut "egoanchor\protocol")
}
Move-Item (Join-Path $PythonOut "protocol") (Join-Path $PythonOut "egoanchor\protocol")

# protoc 34.1 emits Python gencode with a 7.34.1 runtime guard, while the
# current pixi environment can resolve protobuf 7.34.0. The generated wire code
# is compatible for these messages, so strip only the guard block to keep local
# tests and runtime imports stable until the environment moves to a matching
# protobuf runtime.
Get-ChildItem -Path (Join-Path $PythonOut "egoanchor\protocol\v1") -Filter "*_pb2.py" | ForEach-Object {
    $content = Get-Content -Raw -Path $_.FullName
    $content = $content -replace "from google\.protobuf import runtime_version as _runtime_version\r?\n", ""
    $content = $content -replace "_runtime_version\.ValidateProtobufRuntimeVersion\([\s\S]*?\)\r?\n# @@protoc_insertion_point\(imports\)", "# @@protoc_insertion_point(imports)"
    $content = $content -replace "from protocol\.v1 import", "from egoanchor.protocol.v1 import"
    $content = $content -replace "'protocol\.v1\.", "'egoanchor.protocol.v1."
    Set-Content -Path $_.FullName -Value $content -Encoding UTF8
}

protoc --proto_path=$ProtoRoot --csharp_out=$CSharpOut $ProtoFiles

$subjectsPath = Join-Path $ProtocolRoot "subjects.v1.json"
$subjectsJson = Get-Content -Raw -Path $subjectsPath | ConvertFrom-Json -AsHashtable
$subjectNamesPath = Join-Path $UnityProtocolOut "SubjectNames.cs"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("namespace EgoAnchor.V2.Protocol")
$lines.Add("{")
$lines.Add("    /// <summary>")
$lines.Add("    /// Unity 侧 v2 subject 名称常量。")
$lines.Add("    /// 本文件由 EgoAnchor_Protocol/tools/generate_proto.ps1 从 subjects.v1.json 生成。")
$lines.Add("    /// 不要手动修改；subject 变更请改 subjects.v1.json 后重新运行生成脚本。")
$lines.Add("    /// </summary>")
$lines.Add("    public static class SubjectNames")
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
foreach ($subject in $subjectsJson.Keys) {
    $constName = $nameMap[$subject]
    if ([string]::IsNullOrWhiteSpace($constName)) {
        $constName = ($subject -replace "^egoanchor\.v1\.", "" -replace "[^A-Za-z0-9]+", " ").Split(" ") | ForEach-Object { if ($_) { $_.Substring(0,1).ToUpperInvariant() + $_.Substring(1) } }
        $constName = ($constName -join "")
    }
    $lines.Add("        public const string $constName = `"$subject`";")
}
$lines.Add("    }")
$lines.Add("}")
Set-Content -Path $subjectNamesPath -Value ($lines -join "`r`n") -Encoding UTF8
