# EgoAnchor Python server Ubuntu 迁移手册

这份文档只覆盖 `EgoAnchor_Python` 服务器侧。Unity/Quest 仍在 Windows/Quest 侧运行，只需要把网络地址改到 Ubuntu 服务器。Python server 运行时以 `EgoAnchor_Python` 为项目根目录；只拷贝这个目录到 Ubuntu 也可以启动。

## 先说结论

源码拷到 Ubuntu 后，可以继续用 Pixi 管环境，也可以执行 `pixi run build`。但它不是“拷过去立刻无脑跑”的那种轻量命令。当前 `build` 会做三件重活：

1. 编译 `FoundationPose/mycpp` 的 Python 扩展。
2. 用 Fast-FoundationStereo 的 `.pth` 权重导出 6 组 ONNX。
3. 用 TensorRT 生成 6 组 feature/post engine。

因此，Ubuntu 机器必须先具备 NVIDIA 驱动、能联网安装 Pixi/PyPI/Git 依赖，并且本地权重文件要完整。Windows 上已有的 `.win.fp16.engine` 不能复用到 Linux；Linux 必须重新生成 `.linux.fp16.engine`。

## 迁移前检查

在 Ubuntu 上先确认 GPU 和驱动：

```bash
nvidia-smi
```

看 `CUDA Version` 是否至少能覆盖项目声明的 CUDA 12.8。Pixi 会安装 CUDA toolkit，但不会安装 NVIDIA 内核驱动。

再确认基础工具：

```bash
git --version
curl --version || wget --version
```

如果没有 Pixi，按官方安装方式安装：

```bash
curl -fsSL https://pixi.sh/install.sh | sh
exec "$SHELL"
pixi --version
```

官方文档也给了 `wget -qO- https://pixi.sh/install.sh | sh` 作为没有 `curl` 时的替代命令。

## 拷贝哪些文件

推荐只拷 `EgoAnchor_Python`，这是服务器运行所需的根目录。完整仓库只有在你要重新生成共享 Protobuf、同步 Unity 生成代码或继续维护论文/Unity 工程时才需要一起拷。

不要拷 Windows 的环境目录：

- 不要拷：`EgoAnchor_Python/.pixi`
- 不要拷：`__pycache__`、`.mypy_cache`
- 不要依赖：`*.win.fp16.engine`

这些本地大文件必须一起带过去，因为它们通常被 `.gitignore` 忽略：

- `EgoAnchor_Python/weights/yoloe-26l-seg.pt`
- `EgoAnchor_Python/weights/mobileclip2_b.ts`
- `EgoAnchor_Python/Fast-FoundationStereo/weights/*/model_best_bp2_serialize.pth`
- `EgoAnchor_Python/FoundationPose/weights/*/model_best.pth`
- `EgoAnchor_Python/Cutie/weights/*`
- `EgoAnchor_Python/sam3/assets/sam3_ckpt/sam3.pt`
- `EgoAnchor_Python/data/model/*.glb` 和 `*.stl`

如果你用 `rsync`，可以这样排除环境缓存：

```bash
rsync -av --exclude '.pixi' --exclude '__pycache__' /path/to/EgoAnchor_Python/ user@ubuntu:/path/to/EgoAnchor_Python/
```

`subjects.v1.json` 已随 Python 包放在 `src/egoanchor/protocol/subjects.v1.json`，运行时不再依赖父级 `EgoAnchor_Protocol` 目录。以后如果修改中央协议源，请在完整仓库里运行协议生成脚本，它会同步更新 Python 包内的这份运行时 subject registry。

## 创建 Pixi 环境

进入 Python server 目录：

```bash
cd /path/to/EgoAnchor/EgoAnchor_Python
pixi install
```

先做一个不加载模型的 smoke：

```bash
pixi run python -c "import sys, torch, cv2; print(sys.version); print('cuda', torch.cuda.is_available(), torch.version.cuda); print('cv2', cv2.__version__)"
```

再检查关键运行依赖：

```bash
pixi run python -c "import tensorrt, huggingface_hub, egoanchor; print('runtime imports ok')"
```

如果这里失败，先修环境，不要直接跑 `pixi run build`。常见原因是网络无法拉 Git/PyPI 包，或 NVIDIA 驱动不匹配。

## 分阶段构建

不要一开始就跑完整 build。建议按阶段来，哪个阶段失败就只排查那个阶段。

### 1. 编译 FoundationPose mycpp

```bash
pixi run _build-fp
```

这个阶段会生成 Linux 的 `FoundationPose/mycpp/build/mycpp*.so`。如果运行时看到 `FoundationPose mycpp 扩展不可用`，就说明这一步没成功或切换平台后没有重编。

### 2. 导出 FFS ONNX

```bash
pixi run _make-onnx
```

这一步需要 CUDA，并会读取：

```text
Fast-FoundationStereo/weights/20-26-39/model_best_bp2_serialize.pth
Fast-FoundationStereo/weights/20-30-48/model_best_bp2_serialize.pth
Fast-FoundationStereo/weights/23-36-37/model_best_bp2_serialize.pth
```

如果你确认 ONNX 已经是当前代码和参数导出的，可以暂时跳过这一步，但完整迁移建议在 Ubuntu 上重新导出一次。

### 3. 构建 Linux TensorRT engine

```bash
pixi run _build-trt-only
```

这一步只读取已有 ONNX 并构建 engine。输出文件名会包含 `.linux.fp16.engine`。这是预期行为。

如果你想让 Pixi 自动按 ONNX -> TRT 的顺序执行，可以直接运行：

```bash
pixi run _build-trt
```

运行时默认 `module.ffs.use_trt=true`，但 `trt_strict=false`。如果 engine 缺失或加载失败，系统会回退到 PyTorch FFS 路径。迁移初期可以先接受回退，等主线跑通后再优化 TensorRT。

### 4. 完整 build

上面三步都清楚后，再使用：

```bash
pixi run build
```

它等价于完整重建 FoundationPose mycpp、FFS ONNX 和 FFS TensorRT engine。这个命令耗时较长，不适合当日常 smoke。

## Headless/SSH 启动

Ubuntu 服务器如果没有桌面环境，必须关闭 OpenCV 窗口。新建一个本地覆盖配置，例如：

```bash
cat > local_linux_headless.toml <<'EOF'
[debug]
enable_tracking_window = false # Ubuntu SSH/无显示器运行时关闭 OpenCV 主窗口和键盘热键。
show_mask_snapshot = false # Ubuntu SSH/无显示器运行时关闭 register mask snapshot 弹窗。

[network.message_plane]
url = "nats://127.0.0.1:4222" # NATS 地址；如果 nats-server 不在 Ubuntu 本机，改成实际 IP。
EOF
```

启动服务器：

```bash
pixi run python src/tracking_server.py --object controller_right --config local_linux_headless.toml
```

如果你用仓库里的 `run.sh`：

```bash
chmod +x run.sh
./run.sh --object controller_right --config local_linux_headless.toml
```

`run.sh` 已经改成相对自身目录，不再绑定某台机器的 `/home/...` 路径。默认 `TORCH_CUDA_ARCH_LIST=8.0`，A800/A100 可直接用；其他显卡可以执行前覆盖：

```bash
TORCH_CUDA_ARCH_LIST="8.6" ./run.sh --object controller_right --config local_linux_headless.toml
```

## 网络配置

Python 数据面默认监听：

```text
tcp://*:15557
```

Unity/Quest 端需要连 Ubuntu 机器的实际局域网 IP，不是 `127.0.0.1`。

NATS 默认是：

```text
nats://127.0.0.1:4222
```

如果 `nats-server` 跑在 Ubuntu 本机，保持默认即可；Unity 侧也要连 Ubuntu IP。如果 NATS 跑在 Windows 或另一台机器，把 `local_linux_headless.toml` 里的 URL 改成那台机器的地址。

Ubuntu 防火墙至少放行：

```bash
sudo ufw allow 15557/tcp
sudo ufw allow 4222/tcp
```

如果只是 Python-only 模型调试，不接 Unity 的消息面，可以临时关闭 NATS：

```toml
[network.message_plane]
enabled = false # Python-only 调试时关闭 NATS，避免没有 nats-server 时反复重连。
```

## 迁移后验证顺序

先跑轻量验证：

```bash
pixi run python -m compileall src
pixi run python -m unittest src/egoanchor/tests/test_tracking_server_app.py
pixi run python -m unittest src/egoanchor/tests/test_segmenter_config.py
pixi run python -m unittest src/egoanchor/tests/test_foundationpose_estimator.py
```

再跑全量单测：

```bash
pixi run python -m unittest discover -s src -p "test_*.py"
pixi run python -m unittest discover -s eval -p "test_*.py"
```

最后再接 Quest/Unity 真机。真机前先确认 Ubuntu 能收到端口：

```bash
ss -ltnp | grep 15557
ss -ltnp | grep 4222
```

## 常见问题

### `torch.cuda.is_available()` 是 `False`

先看 `nvidia-smi`。如果系统看不到 GPU，Pixi 里装多少 CUDA 包都没用。修 NVIDIA driver、容器 GPU 透传或远程机器权限。

### `FoundationPose mycpp 扩展不可用`

运行：

```bash
pixi run _build-fp
```

Windows 编出来的是 `.pyd`，Ubuntu 需要 `.so`。不要复用旧 build 目录。

### 找不到 FFS `.pth`

检查：

```bash
find Fast-FoundationStereo/weights -name 'model_best_bp2_serialize.pth' -print
```

如果没有，把 Windows 机器上的权重目录拷过来。

### TRT engine 找不到或加载失败

Ubuntu 需要 `.linux.fp16.engine`，不能用 `.win.fp16.engine`。运行：

```bash
pixi run _build-trt
```

如果只是想先跑通系统，可以保持 `trt_strict=false`，让 FFS 回退 PyTorch。

### SAM3 试图联网下载

默认配置 `load_from_hf=false`，应使用本地：

```text
sam3/assets/sam3_ckpt/sam3.pt
```

如果文件缺失，先补权重，不建议迁移时打开在线下载。

### Cutie 自动下载权重失败

把 `Cutie/weights` 从 Windows 拷过来。离线 Ubuntu 不要依赖 Cutie 首次运行时自动下载。

### OpenCV 窗口报错

用 `local_linux_headless.toml` 关闭：

```toml
[debug]
enable_tracking_window = false # 关闭 OpenCV 主窗口。
show_mask_snapshot = false # 关闭 register mask snapshot 弹窗。
```

当前代码已经保证 `enable_tracking_window=false` 时不会创建 tracking window，也不会显示 register mask snapshot。

### Unity 收不到 pose 或命令无 ack

检查三件事：

1. Unity ZMQ 目标 IP 是否是 Ubuntu IP。
2. Python/NATS/Unity 是否使用同一个 NATS 地址。
3. Ubuntu 防火墙是否放行 `15557` 和 `4222`。

## 推荐的第一次完整流程

```bash
cd /path/to/EgoAnchor/EgoAnchor_Python

# 1. 创建环境
pixi install

# 2. 轻量 smoke
pixi run python -c "import torch, cv2, tensorrt, egoanchor; print('ok', torch.cuda.is_available())"

# 3. 编译 FoundationPose mycpp
pixi run _build-fp

# 4. 构建 FFS ONNX/TRT
pixi run _build-trt

# 5. 写 headless 覆盖配置
cat > local_linux_headless.toml <<'EOF'
[debug]
enable_tracking_window = false # Ubuntu SSH/无显示器运行时关闭 OpenCV 主窗口和键盘热键。
show_mask_snapshot = false # Ubuntu SSH/无显示器运行时关闭 register mask snapshot 弹窗。

[network.message_plane]
url = "nats://127.0.0.1:4222" # NATS 地址；如果 nats-server 不在 Ubuntu 本机，改成实际 IP。
EOF

# 6. 启动
pixi run python src/tracking_server.py --object controller_right --config local_linux_headless.toml
```

如果这条链路跑通，再接 Unity/Quest，并把 Unity 侧 Python IP/NATS URL 都改到 Ubuntu 机器。
