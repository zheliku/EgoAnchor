"""FoundationPose 本地子工程包标记。

EgoAnchor 只在适配器中按需导入 FoundationPose 的运行符号；这里不 re-export
重模型模块，避免普通包解析触发 CUDA、Warp 或渲染依赖初始化。
"""

__all__: list[str] = []
