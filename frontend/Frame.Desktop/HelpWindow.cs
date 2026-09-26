using System.IO;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;

namespace Frame.Desktop;

internal sealed class HelpWindow : Window
{
    public HelpWindow(Window owner, string pageKey, string pageTitle)
    {
        Owner = owner;
        Title = $"{pageTitle} · 帮助";
        Width = 760;
        Height = 660;
        MinWidth = 520;
        MinHeight = 400;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        Background = Brushes.White;
        FontFamily = new FontFamily("Microsoft YaHei UI");
        FontSize = 14;

        var layout = new Grid { Margin = new Thickness(20) };
        layout.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        layout.RowDefinitions.Add(new RowDefinition());
        layout.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

        layout.Children.Add(new TextBlock
        {
            Text = $"{pageTitle} · 操作介绍",
            FontSize = 23,
            FontWeight = FontWeights.SemiBold,
            Margin = new Thickness(0, 0, 0, 12)
        });

        var path = Path.Combine(AppContext.BaseDirectory, "help", pageKey + ".md");
        string content;
        try { content = File.ReadAllText(path, new UTF8Encoding(false, true)); }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or DecoderFallbackException)
        {
            content = $"# 帮助文件不可用\n\n无法读取 {pageTitle} 的本地帮助文件。请检查安装目录中的 help/{pageKey}.md，或重新安装 FRAME。";
        }

        var viewer = new FlowDocumentScrollViewer
        {
            Document = Render(content),
            IsToolBarVisible = false,
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        };
        Grid.SetRow(viewer, 1);
        layout.Children.Add(viewer);

        var close = new Button { Content = "关闭", Width = 90, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 12, 0, 0) };
        close.Click += (_, _) => Close();
        Grid.SetRow(close, 2);
        layout.Children.Add(close);
        Content = layout;
    }

    private static FlowDocument Render(string markdown)
    {
        var document = new FlowDocument { PagePadding = new Thickness(4), LineHeight = 23 };
        var paragraph = new List<string>();
        void FlushParagraph()
        {
            if (paragraph.Count == 0) return;
            document.Blocks.Add(new Paragraph(new Run(string.Join(" ", paragraph))) { Margin = new Thickness(0, 0, 0, 13) });
            paragraph.Clear();
        }

        foreach (var raw in markdown.Replace("\r\n", "\n", StringComparison.Ordinal).Split('\n'))
        {
            var line = raw.Trim();
            if (line.Length == 0) { FlushParagraph(); continue; }
            if (line.StartsWith("# ", StringComparison.Ordinal) || line.StartsWith("## ", StringComparison.Ordinal) || line.StartsWith("### ", StringComparison.Ordinal))
            {
                FlushParagraph();
                var level = line.TakeWhile(character => character == '#').Count();
                document.Blocks.Add(new Paragraph(new Run(line[(level + 1)..]))
                {
                    FontSize = level == 1 ? 21 : level == 2 ? 17 : 15,
                    FontWeight = FontWeights.SemiBold,
                    Foreground = new SolidColorBrush(Color.FromRgb(0x10, 0x2A, 0x43)),
                    Margin = new Thickness(0, level == 1 ? 0 : 15, 0, 8)
                });
                continue;
            }
            var numberEnd = line.IndexOf(". ", StringComparison.Ordinal);
            var numbered = numberEnd > 0 && int.TryParse(line[..numberEnd], out _);
            if (line.StartsWith("- ", StringComparison.Ordinal) || numbered)
            {
                FlushParagraph();
                document.Blocks.Add(new Paragraph(new Run(line.StartsWith("- ", StringComparison.Ordinal) ? "• " + line[2..] : line))
                {
                    Margin = new Thickness(16, 0, 0, 6)
                });
                continue;
            }
            paragraph.Add(line);
        }
        FlushParagraph();
        return document;
    }
}
