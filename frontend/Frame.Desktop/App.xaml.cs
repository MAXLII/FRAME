using System.Windows;
using System.Windows.Controls;
namespace Frame.Desktop;
public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        EventManager.RegisterClassHandler(typeof(FrameworkElement), ToolTipService.ToolTipOpeningEvent,
            new ToolTipEventHandler((_, args) => args.Handled = true), true);
        base.OnStartup(e);
    }
}
