# QFramework 导入说明（Unity 6.x 兼容性指南）

## 概述

本文档说明在 **Unity 6.x**（如 Unity 6000.0.x/6000.3.x）版本中导入 QFramework 时可能遇到的问题及解决方案。

---

## ⚠️ 已知问题

- 问题 1：导入后 Unity 卡死
   在 Unity 6000.3.5f2 前首次导入 QFramework 后，Unity 编辑器可能会出现卡死/无响应的情况

- 问题 2：PackageKit 页面崩溃

  在使用 DirectX 12 渲染器时，打开 QFramework 的 PackageKit 窗口后编辑器崩溃或页面显示异常

---

## ✅ 解决方案

- 步骤 1：当 Unity 在导入 QFramework 时出现卡死，强制关闭 Unity 并重启，之后手动刷新 Addressables 支持的符号定义：

  - 在 Unity 编辑器菜单栏中，点击 **QFramework**
  - 选择 **Addressables Support**
  - 点击 **Refresh Symbols**

  <img src="https://raw.githubusercontent.com/zheliku/TyporaImgBed/main/ImgBed202601111723013.png" alt="image-20260111172342853" style="zoom:50%;" />

- 步骤 2：手动刷新 Addressables 符号

- 步骤 3：设置 DirectX 11 渲染器

  1. 打开菜单 **Edit → Project Settings**

  2. 在左侧列表中选择 **Player**

  3. 展开 **Other Settings** 部分

  4. 找到 **Rendering** 区域

  5. **取消勾选** `Auto Graphics API for Windows`

     在 **Graphics APIs for Windows** 列表中：
     - 确保 **Direct3D11** 在列表最顶部
     - 如果列表中有 `Direct3D12`，将其移到 `Direct3D11` 下方，或直接删除

     <img src="https://raw.githubusercontent.com/zheliku/TyporaImgBed/main/ImgBed202601111724596.png" alt="image-20260111172408537" style="zoom:50%;" />

  6. Unity 会提示需要重启编辑器，点击确认重启


## ❓ 常见问题 FAQ

**Q: 为什么需要使用 DirectX 11 而不是 DirectX 12？**

A: QFramework 的 PackageKit 使用了 IMGUI 进行界面绘制，在 DirectX 12 模式下可能存在兼容性问题，导致渲染异常或崩溃。DirectX 11 提供了更好的稳定性。

**Q: 设置 DirectX 11 会影响游戏性能吗？**

A: 这只影响编辑器的渲染模式。在构建游戏时，你可以为目标平台选择不同的图形 API。对于大多数项目，DirectX 11 在编辑器中的性能表现已经足够好。

**Q: Refresh Symbols 按钮找不到怎么办？**

A: 确保已正确导入 QFramework 的 Addressables Support 扩展模块。如果菜单项不存在，可能需要检查相关脚本是否编译成功。

