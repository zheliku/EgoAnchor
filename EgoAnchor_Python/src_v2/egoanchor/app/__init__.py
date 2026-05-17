"""v2 app 入口层。

注意：这里不要导入具体 demo/run_server 子模块。
原因是 pose debug demo 会加载 YOLOE/FFS/FoundationPose 等重依赖，若在包初始化
阶段导入，会拖慢甚至影响纯通信 demo 和单元测试。调用方应直接导入具体子模块。
"""

__all__: list[str] = []
