using System.Text;
using EgoAnchor.Eval;
using NUnit.Framework;

namespace EgoAnchor.Tests
{
    /// <summary>评估公共状态文本测试，固定实验界面共用的显示规则。</summary>
    public sealed class EvalStatusTextTests
    {
        /// <summary>录制、session 与时长文本必须使用稳定格式。</summary>
        [Test]
        public void CommonStatusTextUsesStableFormatting()
        {
            Assert.That(EvalStatusText.Recording(true), Is.EqualTo("● Recording"));
            Assert.That(EvalStatusText.Recording(false), Is.EqualTo("○ Not Recording"));
            Assert.That(EvalStatusText.Session(string.Empty), Is.EqualTo("Session: Not Started"));
            Assert.That(EvalStatusText.Session("session-01"), Is.EqualTo("Session: session-01"));
            Assert.That(EvalStatusText.Duration(-1.0), Is.EqualTo("00:00"));
            Assert.That(EvalStatusText.Duration(65.9), Is.EqualTo("01:05"));
        }

        /// <summary>公共活动行样式只包裹选中内容。</summary>
        [Test]
        public void SelectionRowHighlightsOnlyActiveContent()
        {
            var builder = new StringBuilder();
            EvalStatusText.AppendSelectionRow(builder, "[1]  Static", false);
            EvalStatusText.AppendSelectionRow(builder, "[2]  Occlusion", true);

            Assert.That(
                builder.ToString(),
                Is.EqualTo("[1]  Static\n<color=#FFD700><b>[2]  Occlusion  ◀</b></color>\n"));
        }
    }
}
