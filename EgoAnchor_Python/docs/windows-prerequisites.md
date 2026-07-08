# Windows 下运行 `pixi install` 的前置配置教程

这个项目最终希望在新机器上直接运行：

```powershell
pixi install
```

但在一台全新的 Windows 机器上，这条命令能不能一次成功，取决于一些系统级条件是否已经准备好。Pixi 可以创建 Python/CUDA 包环境，但它不能完全替你安装 Windows 的 MSVC 编译器、NVIDIA 显卡驱动，也不能绕过网络或本地缓存权限问题。

## 快速检查清单

必须满足：

- Windows x64。
- 已安装 pixi，并且 `pixi` 在 `PATH` 中可用。
- 已安装 Visual Studio 2022 Build Tools 或 Visual Studio 2022，并包含 MSVC C++ x64 工具链。
- NVIDIA 驱动足够新，能支持 CUDA 13.x。
- 网络能访问项目依赖源：
  - `conda-forge`
  - PyTorch CUDA wheel index
  - GitHub
  - `miropsota.github.io`
  - Open3D GitHub release assets
- pixi/rattler 缓存目录可读写，不能是损坏的、被占用的、或者从别的用户拷贝来的无权限缓存。

## 1. Visual Studio 2022 Build Tools

这个项目会构建原生/CUDA Python 扩展。在 Windows 上，这意味着必须能找到 MSVC 的 `cl.exe`。

`pixi.toml` 里的 `vs2022_win-64` 只负责帮助 pixi 定位和激活系统中已经存在的 Visual Studio/MSVC 工具链；它不会把 MSVC 编译器本体打包进 pixi 环境。

### 一行命令安装

请在“管理员 PowerShell”中运行：

```powershell
winget install --id Microsoft.VisualStudio.2022.BuildTools --exact --silent --accept-package-agreements --accept-source-agreements --override "--wait --quiet --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```

说明：

- 通常需要管理员权限，因为 Visual Studio Build Tools 会安装到 `Program Files` 等系统目录。
- `Microsoft.VisualStudio.Workload.VCTools` 是 C++ Build Tools 工作负载。
- `--includeRecommended` 会安装推荐的 C++ 组件，避免只装到一个过于精简、后续编译仍缺组件的版本。
- 安装完成后，建议重新打开一个 PowerShell，再运行 pixi 命令。

如果机器上没有 `winget`，可以从 Microsoft 下载 `vs_BuildTools.exe`，然后在该安装器所在目录运行：

```powershell
.\vs_BuildTools.exe --wait --quiet --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended
```

### 一行命令检验

在本项目目录下运行：

```powershell
pixi run where cl
```

期望输出类似：

```text
C:\Program Files\Microsoft Visual Studio\2022\...\VC\Tools\MSVC\...\bin\Hostx64\x64\cl.exe
```

也可以让编译器打印版本：

```powershell
pixi run cl
```

期望输出包含类似内容：

```text
Microsoft (R) C/C++ Optimizing Compiler Version 19.xx.xxxxx for x64
```

如果 `pixi run where cl` 找不到 `cl.exe`，重点检查：

- 是否真的安装了 Visual Studio Build Tools。
- 是否安装了 C++ 工作负载，而不是只安装了 Visual Studio Installer 壳。
- 安装后是否重新打开了终端。
- 当前项目的 pixi 环境中是否包含 `vs2022_win-64`。

### `pixi run where cl` 能找到，但 `pixi install` 仍报找不到 `cl.exe`

有时会出现这种更隐蔽的情况：

```text
nvcc fatal : Cannot find compiler 'cl.exe' in PATH
```

这通常发生在安装 PyPI 源码包时，例如 `nvdiffrast`。原因是：

- `pixi run where cl` 检查的是 pixi 激活后的交互命令环境。
- `pixi install` 安装 PyPI 源码包时会再启动构建子流程。
- CUDA 的 `nvcc` 默认从 `PATH` 里找 MSVC host compiler。
- PyTorch 的 CUDA extension 构建逻辑会读取环境变量 `CC`，并把它传给 `nvcc -ccbin <CC>`。

所以本项目在 `pixi.toml` 里显式设置：

```toml
CC = "%VCToolsInstallDir%bin\\Hostx64\\x64\\cl.exe"
CXX = "%VCToolsInstallDir%bin\\Hostx64\\x64\\cl.exe"
```

`VCToolsInstallDir` 由 `vs2022_win-64` 激活 Visual Studio 后提供。这样 `nvcc` 不需要只依赖 `PATH` 搜索 `cl.exe`，而是能拿到明确的 MSVC 编译器路径。

验证命令：

```powershell
pixi run python -c "import os; print(os.environ.get('CC')); print(os.path.exists(os.environ.get('CC', '')))"
```

期望输出中第一行是 Visual Studio 2022 的 `cl.exe` 路径，第二行是：

```text
True
```

### 一行命令删除

请在“管理员 PowerShell”中运行：

```powershell
winget uninstall --id Microsoft.VisualStudio.2022.BuildTools --exact --silent
```

如果你安装的是完整 Visual Studio IDE，而不是 Build Tools，可以先查看已安装包：

```powershell
winget list VisualStudio
```

然后卸载对应的 Visual Studio 包。

如果 winget 找不到对应实例，也可以打开 Visual Studio Installer 手动卸载。

### 是否需要管理员权限？

安装和卸载通常需要管理员权限。

检验命令一般不需要管理员权限：

```powershell
pixi run where cl
```

## 2. NVIDIA 驱动与 CUDA 13.x

这个项目会在 pixi 环境中安装 CUDA 13 相关包，并使用 PyTorch CUDA wheel。注意：pixi 环境里的 CUDA Toolkit 不等于显卡驱动。

Windows 系统中的 NVIDIA 显卡驱动必须足够新，才能支持 CUDA 13.x。

### 一行命令查看当前驱动

运行：

```powershell
nvidia-smi
```

重点看输出里的：

- `Driver Version`
- `CUDA Version`

对本项目来说，`CUDA Version` 最好显示 CUDA 13.x 或更新。

在当前已经跑通的机器上，pixi 检测到：

```text
__cuda=13.1
```

这说明当前 NVIDIA 驱动暴露出来的 CUDA 运行时能力兼容 CUDA 13.1。

你也可以让 pixi 自己报告它看到的虚拟包：

```powershell
pixi info
```

在 `Virtual packages` 部分查找：

```text
__cuda=...
```

### 如何更新驱动：交互式方式

最稳妥的方式：

1. 打开 NVIDIA 官方驱动下载页面。
2. 选择准确的 GPU 型号和 Windows 版本。
3. 下载最新的 Game Ready、Studio 或生产/企业驱动。
4. 运行安装器。
5. 如果安装器要求重启，就重启。
6. 再次运行：

```powershell
nvidia-smi
```

对于开发机器，通常推荐 Studio Driver，因为它更偏稳定性。纯游戏用途的 GeForce 机器用 Game Ready Driver 也可以，只要 `nvidia-smi` 显示支持 CUDA 13.x 即可。

### 是否有命令行版本？

有，但前提是你已经下载好了正确的 NVIDIA 驱动安装包。

在“管理员 PowerShell”中进入驱动安装器所在目录，然后运行：

```powershell
.\NVIDIA-driver-installer.exe -s
```

把 `NVIDIA-driver-installer.exe` 换成真实文件名。例如：

```powershell
.\572.83-desktop-win10-win11-64bit-international-dch-whql.exe -s
```

注意：

- 需要管理员权限。
- 静默安装后仍然可能需要重启。
- 驱动必须匹配 GPU 类型：
  - GeForce/RTX 消费级显卡使用 GeForce/RTX desktop 或 laptop 驱动。
  - RTX/Quadro/数据中心显卡使用工作站或数据中心驱动。
- 不建议盲目把另一台机器的驱动安装包拿来复用，除非 GPU 型号/驱动分支确定匹配。

安装后验证：

```powershell
nvidia-smi
```

然后在本项目目录运行：

```powershell
pixi info
```

确认 `Virtual packages` 中出现 `__cuda=13.x`。

### 能不能完全用命令行自动更新到最新版？

部分可以，完全自动不太建议。

如果你已经有正确的驱动 `.exe`，静默安装是一行命令：

```powershell
.\NVIDIA-driver-installer.exe -s
```

但“自动识别 GPU 并下载最新驱动”这件事在命令行里不够稳定。NVIDIA 下载链接、驱动分支、笔记本 OEM 驱动要求都可能变化。

如果是实验室或多台固定配置机器，建议保存一份已经验证过的驱动安装包，然后用静默安装命令统一部署。

## 3. 网络访问

`pixi install` 需要访问 conda、PyPI、GitHub 和一些直接 wheel 链接。

最低限度可以先跑：

```powershell
pixi info
```

然后：

```powershell
pixi install -vv
```

如果错误里出现 request retry、DNS、TLS、proxy、`tcp connect`、`os error 10013` 等信息，通常是网络、代理或防火墙问题，还没走到 Python/MSVC 编译阶段。

本项目常用 host 包括：

- `prefix.dev`
- `conda.anaconda.org`
- `download.pytorch.org`
- `github.com`
- `githubusercontent.com`
- `miropsota.github.io`
- `pypi.org`
- `files.pythonhosted.org`

如果机器在公司/学校代理后面，需要给 pixi 配置代理，或者先设置标准代理环境变量，再运行 `pixi install`。

## 4. pixi/rattler 缓存

pixi 使用 rattler 缓存 conda repodata 和包文件。如果这个缓存是从别的用户拷来的、被其他进程占用、或者 Windows ACL 权限坏了，`pixi install` 可能在依赖求解前就失败。

典型错误：

```text
failed to open 'C:\Users\<user>\AppData\Local\rattler\cache\...'
拒绝访问。 (os error 5)
```

### 修复全局缓存

先关闭所有 pixi/python 相关进程，然后运行：

```powershell
Remove-Item -LiteralPath "$env:LOCALAPPDATA\rattler\cache" -Recurse -Force
```

再重新安装：

```powershell
pixi install
```

如果删除缓存也报“拒绝访问”，就用管理员 PowerShell 删除，或者在资源管理器里手动删除。

这个缓存是可丢弃的，删掉后 pixi 会重新生成。

### 可选：项目本地缓存

如果你希望某台机器上的这个项目完全不碰全局 rattler 缓存，可以运行：

```powershell
pixi config set --local cache.root ".pixi\cache"
```

然后：

```powershell
pixi install
```

这会写入 `.pixi/config.toml`。它通常属于本机配置，不建议提交到 git。

## 5. 安装后的完整验证

完成前置配置并运行 `pixi install` 后，验证核心 Python/CUDA 包：

```powershell
pixi run python -c "import sys, torch, nvdiffrast; print(sys.version); print('torch', torch.__version__, 'cuda', torch.version.cuda); print('cuda available', torch.cuda.is_available()); print('nvdiffrast', nvdiffrast.__file__)"
```

期望结果：

- Python 是 pixi 环境中的 3.13.x。
- Torch 可以 import。
- `torch.version.cuda` 显示当前 PyTorch wheel 对应的 CUDA 版本。
- `torch.cuda.is_available()` 是 `True`。
- `nvdiffrast` 可以 import。

验证 MSVC 和 CUDA 编译器：

```powershell
pixi run where cl
```

```powershell
pixi run where nvcc
```

期望结果：

- `cl.exe` 来自 Visual Studio 2022。
- 第一个 `nvcc.exe` 最好来自本项目 pixi 环境，通常类似：

```text
<repo>\.pixi\envs\default\Library\bin\nvcc.exe
```

## 6. 新机器推荐安装流程

管理员 PowerShell 安装 VS 2022 Build Tools：

```powershell
winget install --id Microsoft.VisualStudio.2022.BuildTools --exact --silent --accept-package-agreements --accept-source-agreements --override "--wait --quiet --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```

安装或更新 NVIDIA 驱动，必要时重启，然后检查：

```powershell
nvidia-smi
```

普通 PowerShell 进入项目目录：

```powershell
pixi install
```

验证：

```powershell
pixi run python -c "import torch, nvdiffrast; print(torch.__version__, torch.version.cuda, torch.cuda.is_available()); print(nvdiffrast.__file__)"
```

如果第一次 `pixi install` 报 rattler 缓存权限错误，清掉缓存再试：

```powershell
Remove-Item -LiteralPath "$env:LOCALAPPDATA\rattler\cache" -Recurse -Force
```

```powershell
pixi install
```

## 参考资料

- Microsoft Visual Studio 命令行安装参数：
  https://learn.microsoft.com/en-us/visualstudio/install/use-command-line-parameters-to-install-visual-studio?view=vs-2022
- Microsoft winget install 命令：
  https://learn.microsoft.com/en-us/windows/package-manager/winget/install
- NVIDIA CUDA Toolkit Release Notes：
  https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html
- NVIDIA Windows Driver Installation Guide：
  https://docs.nvidia.com/datacenter/tesla/driver-installation-guide/windows.html
