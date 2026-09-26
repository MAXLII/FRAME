using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Threading;
using Frame.Desktop;

internal static class HelpTests
{
    public static void Run(MainWindow window)
    {
        var navigation = (ListBox)window.FindName("Navigation");
        var help = (Button)window.FindName("HelpButton");
        string[] titles = ["串口调试", "参数读写", "参数波形", "Scope 录波", "SFRA", "Perf", "Trace", "链表顺序", "J-Link"];
        if (navigation.Items.Count != titles.Length) throw new Exception("Help page count does not match navigation");
        if (!help.IsVisible || help.ActualWidth == 0 || help.Content?.ToString() != "❓") throw new Exception("Top help button is not visible");

        for (int index = 0; index < titles.Length; index++)
        {
            navigation.SelectedIndex = index;
            var title = titles[index];
            string? error = null;
            bool opened = false;
            window.Dispatcher.BeginInvoke(new Action(() =>
            {
                var dialog = Application.Current.Windows.OfType<Window>().FirstOrDefault(item => item.Title == $"{title} · 帮助");
                if (dialog == null) { error = $"Help dialog did not open for {title}"; return; }
                opened = true;
                try
                {
                    var viewer = ((Grid)dialog.Content).Children.OfType<FlowDocumentScrollViewer>().Single();
                    var text = new TextRange(viewer.Document.ContentStart, viewer.Document.ContentEnd).Text;
                    if (!text.Contains(title, StringComparison.Ordinal) || text.Contains("帮助文件不可用", StringComparison.Ordinal))
                        error = $"Help content missing or routed to the wrong page: {title}";
                }
                catch (Exception exception) { error = exception.Message; }
                finally { dialog.Close(); }
            }), DispatcherPriority.Background);
            help.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            if (!opened || error != null) throw new Exception(error ?? $"Help dialog did not open for {title}");
        }
        Console.WriteLine("PASS: help button opens all nine local page documents.");
    }
}
