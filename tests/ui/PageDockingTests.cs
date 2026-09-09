using System.Collections;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using Frame.Desktop;

internal static class PageDockingTests
{
    private const BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    private static Window Detach(MainWindow main, string key) => (Window)typeof(MainWindow)
        .GetMethod("DetachPage", Private)!.Invoke(main, [key, main.PointToScreen(new Point(300, 180))])!;

    public static async Task Run(MainWindow main, bool testMouse)
    {
        var pages = (IDictionary)typeof(MainWindow).GetField("pages", Private)!.GetValue(main)!;
        var navigation = (ListBox)main.FindName("Navigation");
        var body = (ContentControl)main.FindName("PageBody");
        var form = (ContentControl)main.FindName("Form");
        int index = 0;
        foreach (DictionaryEntry entry in pages)
        {
            navigation.SelectedIndex = index++;
            var originalBody = body.Content;
            var originalForm = form.Content;
            var floating = Detach(main, (string)entry.Key);
            if (ReferenceEquals(body.Content, originalBody) || Window.GetWindow((DependencyObject)originalBody) != floating)
                throw new Exception("Detached page must reuse its original controls in the floating window");
            if (!ReferenceEquals(floating, Detach(main, (string)entry.Key)))
                throw new Exception("Repeated tear-off must not create a duplicate page");
            floating.WindowState = WindowState.Minimized;
            await Task.Delay(40);
            if (Window.GetWindow((DependencyObject)originalBody) != floating || ReferenceEquals(body.Content, originalBody))
                throw new Exception("Minimize must keep the page in its floating window");
            floating.Close();
            if (floating.IsVisible || !ReferenceEquals(body.Content, originalBody) || !ReferenceEquals(form.Content, originalForm))
                throw new Exception("Close must restore the original page and controls");
        }
        var wave = Detach(main, "wave");
        var scope = Detach(main, "scope");
        var sfra = Detach(main, "sfra");
        if (new[] { wave, scope, sfra }.Any(w => !w.IsVisible)) throw new Exception("Multiple pages must float concurrently");
        navigation.SelectedIndex = 2;
        wave.WindowState = WindowState.Maximized;
        wave.WindowState = WindowState.Minimized;
        navigation.SelectedIndex = 0;
        navigation.SelectedIndex = 2;
        if (wave.WindowState != WindowState.Maximized) throw new Exception("Navigation must restore the floating window's previous state");
        if (!wave.IsVisible || ReferenceEquals(body.Content, pages["wave"]!.GetType().GetProperty("Body")!.GetValue(pages["wave"])))
            throw new Exception("Navigation must not steal floating page controls");
        wave.Close(); scope.Close(); sfra.Close();
        if (navigation.SelectedIndex != 4 || Window.GetWindow((DependencyObject)body.Content) != main)
            throw new Exception("Closing floating windows must dock their pages");
        Console.WriteLine("PASS: all nine pages detach/minimize/close-to-dock; concurrent windows; navigation restores minimized windows.");
        if (testMouse)
        {
            await DragFromNavigation(main, collapsed: false);
            await DragFromNavigation(main, collapsed: true);
            Console.WriteLine("PASS: actual mouse tear-off in expanded and collapsed navigation.");
        }
    }

    public static async Task VerifyLiveWave(MainWindow main, object page)
    {
        var navigation = (ListBox)main.FindName("Navigation");
        var records = page.GetType().GetProperty("Records")!;
        var floating = Detach(main, "wave");
        navigation.SelectedIndex = 4;
        var before = records.GetValue(page);
        await Task.Delay(800);
        if (ReferenceEquals(before, records.GetValue(page))) throw new Exception("Floating waveform stopped refreshing after main page navigation");
        floating.WindowState = WindowState.Minimized;
        await Task.Delay(300);
        if (navigation.SelectedIndex != 4) throw new Exception("Minimize must not navigate or dock the page");
        floating.Close();
        if (navigation.SelectedIndex != 2 || !ReferenceEquals(((ContentControl)main.FindName("PageBody")).Content, page.GetType().GetProperty("Body")!.GetValue(page)))
            throw new Exception("Live waveform must dock without rebuilding controls");
        Console.WriteLine("PASS: detached waveform refreshes during capture and returns to the main window.");
    }

    private static async Task DragFromNavigation(MainWindow main, bool collapsed)
    {
        if (main.SidebarCollapsed != collapsed) ((Button)main.FindName("SidebarToggle")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        var navigation = (ListBox)main.FindName("Navigation");
        navigation.SelectedIndex = 0;
        main.Topmost = true; main.Activate(); main.UpdateLayout();
        await Task.Delay(120);
        var item = (ListBoxItem)navigation.ItemContainerGenerator.ContainerFromIndex(2);
        Point start = item.PointToScreen(new Point(item.ActualWidth / 2, item.ActualHeight / 2));
        Point end = navigation.PointToScreen(new Point(navigation.ActualWidth + 100, item.TranslatePoint(new Point(0, item.ActualHeight / 2), navigation).Y));
        GetCursorPos(out var previous);
        try
        {
            if (GetAncestor(WindowFromPoint(new NativePoint { X = (int)start.X, Y = (int)start.Y }), 2) != new WindowInteropHelper(main).Handle)
                throw new Exception("UI drag test navigation is obscured; refusing to click another window");
            await Task.Run(() =>
            {
                SetCursorPos((int)start.X, (int)start.Y);
                mouse_event(0x0002, 0, 0, 0, UIntPtr.Zero);
                Thread.Sleep(100);
                SetCursorPos((int)end.X, (int)end.Y);
                Thread.Sleep(350);
                mouse_event(0x0004, 0, 0, 0, UIntPtr.Zero);
            });
            await Task.Delay(100);
            var windows = (IDictionary)typeof(MainWindow).GetField("detachedPages", Private)!.GetValue(main)!;
            if (!windows.Contains("wave")) throw new Exception("Dragging navigation outside the rail did not detach the page");
            var floating = (Window)windows["wave"]!.GetType().GetProperty("Window")!.GetValue(windows["wave"])!;
            floating.Close();
        }
        finally
        {
            mouse_event(0x0004, 0, 0, 0, UIntPtr.Zero);
            SetCursorPos(previous.X, previous.Y);
            main.Topmost = false;
            if (main.SidebarCollapsed) ((Button)main.FindName("SidebarToggle")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        }
    }

    [StructLayout(LayoutKind.Sequential)] private struct NativePoint { public int X, Y; }
    [DllImport("user32.dll")] private static extern bool GetCursorPos(out NativePoint point);
    [DllImport("user32.dll")] private static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] private static extern IntPtr WindowFromPoint(NativePoint point);
    [DllImport("user32.dll")] private static extern IntPtr GetAncestor(IntPtr window, uint flags);
    [DllImport("user32.dll")] private static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
}
