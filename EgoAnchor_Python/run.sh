#!/bin/bash
#SBATCH --job-name=run
#SBATCH --output=logs/id_%j.out
#SBATCH --error=logs/id_%j.err
#SBATCH --time=24:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=4
#SBATCH --cpus-per-task=1
#SBATCH --gres=gpu:1
#SBATCH --mem=64G
#SBATCH --qos=default
#SBATCH --partition=general

set -euo pipefail

# 脚本所在目录即 EgoAnchor_Python 根目录，避免迁移到新 Ubuntu 用户名或路径后失效。
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$SCRIPT_DIR/logs"

# 禁用 Python stdout 缓冲，确保日志实时输出
export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"

# 加速 CUDA JIT 编译；默认适配 A800/A100，可在执行前覆盖为当前 GPU 架构。
export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-8.0}"

# 如果用户显式设置 CUDA_HOME，则把系统 CUDA 放到前面；默认优先使用 pixi 环境内 CUDA 12.8。
if [[ -n "${CUDA_HOME:-}" ]]; then
  export PATH="$CUDA_HOME/bin:$PATH"
  export LD_LIBRARY_PATH="$CUDA_HOME/lib64:${LD_LIBRARY_PATH:-}"
fi

# SSH/SLURM 无 DISPLAY 时默认关闭 Qt 显示后端；tracking_server 仍建议配合 debug.enable_tracking_window=false。
if [[ -z "${DISPLAY:-}" ]]; then
  export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
fi

cd "$SCRIPT_DIR"
exec pixi run python -u src/tracking_server.py "$@"
