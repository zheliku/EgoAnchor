# EgoAnchor_Python 环境配置与构建说明

这份文档以当前主线代码为准，重点说明 `EgoAnchor_Python` 在 Windows 和 Linux 上怎么把环境装起来、怎么构建一次、以及哪些旧记录已经不再适用。

先说结论：

- `pixi install` 只负责把 Python、CUDA、PyTorch、TensorRT、Open3D 和大部分依赖装进 `.pixi` 环境。
- `pixi run build` 才会补齐需要即时编译的部分，包括 `nvdiffrast`、`FoundationPose/mycpp`，以及 Fast-FoundationStereo 的默认 ONNX 和 TensorRT engine。
- Windows 仍然需要系统级的 Visual Studio C++ Build Tools。`pixi.toml` 里的 `vs2026_win-64` 只是激活包，不会把 `cl.exe` 和 Windows SDK 打包进 pixi。
- Linux 不需要额外装 MSVC；编译器和 CUDA Toolkit 由 pixi 环境提供，但显卡驱动仍然要系统自己装。

## 1. 当前环境基线

当前 `pixi.toml` 的主线基线是：

- Python 3.14
- Windows 端 CUDA 13.2 conda 组件
- Linux 端 `cuda-toolkit = 13.2.*`
- PyTorch 2.12.1 + cu130
- torchvision 0.27.1 + cu130
- TensorRT 11（通过 `tensorrt-cu13` 安装）
- Open3D 0.19.0 的 Python 3.14 预编译 wheel
- Windows 原生构建工具链：Visual Studio 2026 / 18 系列 Build Tools

如果你后面升级 Python、CUDA、Torch、TensorRT 或 MSVC，通常都要重新跑一次：

```powershell
pixi run build
```

## 2. 通用前置条件

### 2.1 NVIDIA 驱动

pixi 环境里的 CUDA Toolkit 不等于系统显卡驱动。无论 Windows 还是 Linux，机器上的 NVIDIA 驱动都要足够新，至少要支持 CUDA 13.x。

检查方法：

```powershell
nvidia-smi
```

重点看两项：

- `Driver Version`
- `CUDA Version`

对这个项目来说，`CUDA Version` 最好是 13.x 或更新。

### 2.2 Pixi

如果机器上还没有 pixi，可以先安装：

```powershell
powershell -ExecutionPolicy Bypass -c "irm -useb https://pixi.sh/install.ps1 | iex"
```

安装后重新开一个终端，确认 `pixi` 已经在 `PATH` 里：

```powershell
pixi --version
```

### 2.3 NATS Server

默认配置下，Python 消息面会连：

```text
nats://127.0.0.1:4222
```

如果你要跑正常的 Unity <-> Python 联调，或者直接用默认配置启动 Python 服务，就需要先把 `nats-server` 跑起来。

Windows 下可以直接用 Scoop：

```powershell
scoop install main/nats-server
```

启动：

```powershell
nats-server
```

Linux 下建议直接按官方文档安装，或者用你所在发行版的包管理器安装。装好后同样运行：

```bash
nats-server
```

如果你只是做 Python-only 调试，也可以把 `src/egoanchor/config/defaults.toml` 里的：

```toml
[network.message_plane]
enabled = false
```

这样就不要求本机先起 NATS。

## 3. Windows 额外要求

### 3.1 为什么还要系统级 Build Tools

Windows 上 `FoundationPose/mycpp` 和 `nvdiffrast` 都会走本机 MSVC 工具链。当前主线使用 `vs2026_win-64`，但它的职责只是：

- 让 pixi 能定位系统里已经装好的 Visual Studio
- 在需要的时候提供 `vswhere` 和激活脚本

它不会提供这些东西：

- `cl.exe`
- MSVC STL 头文件
- Windows SDK / UCRT 头文件

所以 Windows 机器上还是要先装系统级 C++ Build Tools。

### 3.2 推荐的安装方式

当前主线的自动检查任务 `_ensure-msvc-buildtools`，缺失时会尝试调用 `winget` 安装。手动提前装好通常更稳：

```powershell
winget install --id Microsoft.VisualStudio.BuildTools --exact --source winget --accept-package-agreements --accept-source-agreements --override "--wait --passive --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```

说明：

- 通常需要管理员权限。
- 我们只要求 C++ workload，不需要完整 Visual Studio IDE。
- 安装完成后最好重开一个 PowerShell 再执行 pixi 命令。

如果机器上没有 `winget`，也可以用 Visual Studio Installer 或 `vs_BuildTools.exe` 手动装同样的 workload。

### 3.3 如何验证 Build Tools 已就位

先找安装目录：

```powershell
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
& $vswhere -products * -version "[18.0,19.0)" -requires Microsoft.VisualStudio.Workload.VCTools -property installationPath
```

常见输出会是下面这种路径：

```text
C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools
```

注意一点：虽然我们口头上叫它“VS2026 Build Tools”，实际落盘目录现在很可能是 `18\BuildTools`，这属于正常现象，不要误以为装错了版本。

再验证 `cl.exe`：

```powershell
cmd /c "\"%ProgramFiles(x86)%\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat\" && where cl && cl /Bv"
```

能看到 `cl.exe` 路径和 `Compiler Version 19.51...` 之类的版本信息，就说明工具链是通的。

### 3.4 现在的自动化行为

当前 `pixi run build` 在 Windows 上会先跑：

- `_ensure-msvc-buildtools`
- `_build-nvdiffrast`
- `_build-fp`

所以 fresh machine 的标准流程仍然是：

1. 先手动装好 Build Tools
2. 再运行 `pixi install`
3. 最后运行 `pixi run build`

不要指望只靠 `pixi install` 就把 MSVC 问题一起解决掉。

## 4. Linux 额外要求

Linux 端比 Windows 简单一点：

- 不需要系统级 MSVC
- pixi 环境会提供 `gcc_linux-64`、`gxx_linux-64` 和 `cuda-toolkit`
- 系统只需要准备好 NVIDIA 驱动、Pixi，以及可选的 `nats-server`

Linux 上的常规顺序就是：

```bash
pixi install
pixi run build
```

## 5. 项目安装步骤

在 `EgoAnchor_Python` 目录下执行：

```powershell
pixi install
```

这一步会创建 `.pixi/envs/default`，安装锁文件中声明的 conda 和 PyPI 依赖。

安装完之后，执行：

```powershell
pixi run build
```

这一步会完成主线构建。

## 6. `pixi run build` 现在会做什么

当前主线的 `build` 任务包含三部分：

### 6.1 `nvdiffrast`

`nvdiffrast` 不放在 `[pypi-dependencies]` 里。原因很直接：它在 `pixi install` 阶段编译不稳定，尤其是 Windows 上很容易拿不到正确的 MSVC / CUDA 环境。

现在的做法是：

- `pixi install` 只装普通依赖
- `pixi run build` 里由 `_build-nvdiffrast` 统一安装 `nvdiffrast==0.4.0`

所以，旧记录里那种“先 `pixi install`，后面第一次跑程序时再看 `nvdiffrast` 怎么样”的说法，已经不是当前主线流程了。当前主线的入口是 `pixi run build`。

### 6.2 FoundationPose C++ 扩展

Windows 下由：

```text
FoundationPose/mycpp/build_msvc.py
```

负责刷新 MSVC / CUDA 环境并调用 CMake + Ninja 构建。

Linux 下则直接用 pixi 环境里的编译器和工具链构建。

### 6.3 Fast-FoundationStereo ONNX / TensorRT

默认会构建主线正在使用的这一组配置：

- model: `23-36-37`
- height: `480`
- width: `640`
- valid_iters: `4`
- max_disp: `192`

并生成：

- 对应 ONNX 文件
- 默认 TensorRT FP16 engine

如果你还需要非默认组合，可以额外执行：

```powershell
pixi run build-trt-extra
```

## 7. 运行前的建议 smoke

环境装好、build 跑完以后，建议至少过一遍这些命令。

编译所有 Python 源码：

```powershell
pixi run python -m compileall src
```

跑主线单测：

```powershell
pixi run python -m unittest discover -s src -p "test_*.py" -t src
```

检查 CUDA / Torch 基础状态：

```powershell
pixi run python -c "import torch; print(torch.__version__); print(torch.version.cuda); print(torch.cuda.is_available())"
```

如果要直接跑一个对象服务：

```powershell
pixi run controller_right
```

也可以换成别的对象任务名，例如：

```powershell
pixi run blue_mouse
pixi run controller_left
```

## 8. 复现到另一台机器时怎么做

### 8.1 需要带过去的内容

至少要带这些：

- 整个仓库源码
- `pixi.toml`
- `pixi.lock`
- `Cutie/`
- `Fast-FoundationStereo/`
- `FoundationPose/`
- `sam3/`
- 模型权重和物体资产

### 8.2 不要带过去的内容

这些不要复制：

- `.pixi/`
- `data/eval/`
- `data/runtime_logs/`
- 其他本机运行时缓存和日志

新的机器应该自己执行：

```powershell
pixi install
pixi run build
```

### 8.3 Windows 新机器的最短流程

1. 安装或更新 NVIDIA 驱动
2. 安装 Pixi
3. 安装 Visual Studio Build Tools
4. 启动 `nats-server`（如果消息面启用）
5. 进入 `EgoAnchor_Python`
6. 执行 `pixi install`
7. 执行 `pixi run build`

### 8.4 Linux 新机器的最短流程

1. 安装或更新 NVIDIA 驱动
2. 安装 Pixi
3. 启动 `nats-server`（如果消息面启用）
4. 进入 `EgoAnchor_Python`
5. 执行 `pixi install`
6. 执行 `pixi run build`

## 9. 旧记录里哪些点已经过时

下面这些说法不要再沿用：

- “Windows 主线还是 `vs2022_win-64`。”
  现在主线已经是 `vs2026_win-64`，并且构建脚本按 VS 18 / 2026 这一套在找 `vcvars64.bat`。

- “`pixi install` 会顺便把 `nvdiffrast` 编译好。”
  现在不会。`nvdiffrast` 由 `pixi run build` 里的 `_build-nvdiffrast` 负责。

- “默认 TensorRT engine 是 FP32。”
  当前主线默认生成的是 FP16 engine。

- “当前实现依赖 `sitecustomize.py` 或固定的 `.torch_extensions/nvdiffrast_plugin/` 目录。”
  这些都不是当前主线的配置事实，后续不要再按这套描述写文档。

## 10. 常见错误和排查方向

### 10.1 `cl.exe` 找不到，或者提示缺少 `vcvars64.bat`

先看系统里是不是已经装了 C++ Build Tools，再看 `vswhere` 能不能找到安装目录。

常见原因：

- 根本没装 Build Tools
- 只装了 Installer 外壳，没有装 C++ workload
- 装完后没有重开终端

### 10.2 `fatal error C1083: 无法打开包括文件: "nv/target"`

这是 CUDA 13 头文件链路问题。当前主线已经在 Windows 构建任务里把：

- `...Library\include\targets\x64`
- `...Library\include\targets\x64\cccl`

都注入到 `CL` 和 `INCLUDE` 里了。出现这个错时，不要回退到旧的 `cmd /c call ... && set CL=...` 脚本做法，先检查你是不是在跑当前主线的 `pixi.toml`。

### 10.3 `.pixi/envs/default` 重建失败，提示文件占用

这在 Windows 上很常见，尤其是 VS Code 打开了 Python 解释器、Pylance 或测试进程的时候。

先关掉：

- VS Code 里绑定到该环境的 Python 进程
- 残留的 `python.exe`
- 可能占用 `.pyd` / `.dll` 的测试或 demo 进程

再重试 `pixi install`。

### 10.4 `pixi install` 一开始就报网络、TLS、代理错误

这类问题通常还没走到项目代码层面，先排网络：

- `prefix.dev`
- `conda-forge`
- `download.pytorch.org`
- `github.com`
- `pypi.org`
- `files.pythonhosted.org`

如果你在学校、公司或者远端服务器环境里，优先看代理和防火墙。

## 11. 一套最实用的命令顺序

如果你想少走弯路，按这套来就行。

Windows：

```powershell
nvidia-smi
winget install --id Microsoft.VisualStudio.BuildTools --exact --source winget --accept-package-agreements --accept-source-agreements --override "--wait --passive --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
scoop install main/nats-server
nats-server
cd EgoAnchor_Python
pixi install
pixi run build
pixi run python -m compileall src
pixi run controller_right
```

Linux：

```bash
nvidia-smi
nats-server
cd EgoAnchor_Python
pixi install
pixi run build
pixi run python -m compileall src
pixi run controller_right
```

如果只是做 Python-only 调试，可以先把 `defaults.toml` 里的 `network.message_plane.enabled` 关掉，再启动服务。
