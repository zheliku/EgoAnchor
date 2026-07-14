using System;

namespace EgoAnchor.Eval
{
    /// <summary>一条 render tick × variant 的 schema-v2 行输入。</summary>
    public readonly struct EvalRenderSnapshot
    {
        /// <summary>渲染 tick 的统一标识。</summary>
        public readonly int RenderTickId;

        /// <summary>变体渲染快照。</summary>
        public readonly EvalVariantSnapshot Variant;

        /// <summary>构造一条 render 行输入。</summary>
        public EvalRenderSnapshot(int renderTickId, EvalVariantSnapshot variant)
        {
            RenderTickId = renderTickId;
            Variant = variant;
        }
    }
}
