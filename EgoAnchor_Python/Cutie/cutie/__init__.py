"""Cutie 本地子工程包标记。

EgoAnchor 只在适配器中按需导入 Cutie 的运行符号；这里不 re-export 重模型模块，
避免普通包解析触发模型配置或权重加载。
"""

__all__: list[str] = []
