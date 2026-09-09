using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Input;
using System.Windows.Media;

namespace Frame.Desktop;

public partial class MainWindow
{
    private sealed record DetachedPage(Window Window, Grid Layout)
    {
        public WindowState RestoreState { get; set; } = WindowState.Normal;
    }
    private readonly Dictionary<string, DetachedPage> detachedPages = new();
    private Point? navigationDragStart;
    private string? navigationDragPage;

    private void InitializePageDocking()
    {
        Navigation.PreviewMouseLeftButtonDown += (_, e) =>
        {
            var item = ItemsControl.ContainerFromElement(Navigation, e.OriginalSource as DependencyObject) as ListBoxItem;
            int index = item == null ? -1 : Navigation.ItemContainerGenerator.IndexFromContainer(item);
            navigationDragPage = index < 0 ? null : pages.Values.ElementAt(index).Key;
            navigationDragStart = e.GetPosition(Navigation);
        };
        Navigation.PreviewMouseLeftButtonUp += (_, _) =>
        {
            if (navigationDragPage is string key && detachedPages.TryGetValue(key, out var detached)) ActivateDetachedPage(detached);
            ResetNavigationDrag();
        };
        Navigation.AddHandler(Mouse.MouseMoveEvent, new MouseEventHandler(NavigationDrag), true);
    }

    private void ResetNavigationDrag()
    {
        navigationDragStart = null;
        navigationDragPage = null;
    }

    private void NavigationDrag(object sender, MouseEventArgs e)
    {
        if (e.LeftButton != MouseButtonState.Pressed) { ResetNavigationDrag(); return; }
        if (closing || navigationDragStart is not Point start || navigationDragPage is not string key) return;
        Point position = e.GetPosition(Navigation);
        if (Math.Abs(position.X - start.X) < SystemParameters.MinimumHorizontalDragDistance &&
            Math.Abs(position.Y - start.Y) < SystemParameters.MinimumVerticalDragDistance) return;
        // A normal click or drag within the navigation rail must not tear off a page.
        if (new Rect(0, 0, Navigation.ActualWidth, Navigation.ActualHeight).Contains(position)) return;
        Point screen = Navigation.PointToScreen(position);
        ResetNavigationDrag();
        Mouse.Capture(null);
        e.Handled = true;
        Window floating = DetachPage(key, screen);
        try { if (Mouse.LeftButton == MouseButtonState.Pressed) floating.DragMove(); }
        catch (InvalidOperationException) when (Mouse.LeftButton != MouseButtonState.Pressed) { }
    }

    private PageState[] VisiblePages() => pages.Values
        .Where(p => p.Key == current || detachedPages.ContainsKey(p.Key)).ToArray();

    // Move the existing controls; datasets, jobs and the BackendClient stay owned by MainWindow.
    private Window DetachPage(string key, Point screenPosition)
    {
        if (detachedPages.TryGetValue(key, out var existing)) { ActivateDetachedPage(existing); return existing.Window; }
        var page = pages[key];
        if (ReferenceEquals(Form.Content, page.Form)) Form.Content = null;
        if (ReferenceEquals(PageBody.Content, page.Body)) PageBody.Content = null;

        var layout = new Grid { Margin = new Thickness(16) };
        layout.RowDefinitions.Add(new() { Height = GridLength.Auto });
        layout.RowDefinitions.Add(new());
        Grid.SetRow(page.Form, 0); Grid.SetRow(page.Body, 1);
        layout.Children.Add(page.Form); layout.Children.Add(page.Body);
        var footer = new Grid { Margin = new Thickness(12, 5, 12, 5) };
        footer.ColumnDefinitions.Add(new()); footer.ColumnDefinitions.Add(new() { Width = GridLength.Auto });
        var feedback = new TextBlock { VerticalAlignment = VerticalAlignment.Center, TextTrimming = TextTrimming.CharacterEllipsis };
        feedback.SetBinding(TextBlock.TextProperty, new Binding(nameof(TextBlock.Text)) { Source = Feedback });
        feedback.SetBinding(ToolTipProperty, new Binding(nameof(TextBlock.Text)) { Source = Feedback });
        footer.Children.Add(feedback);
        if (key == "wave")
        {
            var cursor = new TextBlock { Margin = new Thickness(12, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center };
            cursor.SetBinding(TextBlock.TextProperty, new Binding(nameof(TextBlock.Text)) { Source = WaveCursor });
            Grid.SetColumn(cursor, 1); footer.Children.Add(cursor);
        }
        var root = new DockPanel();
        var status = new Border { Background = new SolidColorBrush(Color.FromRgb(231, 238, 245)), Child = footer, MinHeight = 34 };
        DockPanel.SetDock(status, Dock.Bottom); root.Children.Add(status); root.Children.Add(layout);
        var floating = new Window
        {
            Title = $"{page.Title} · FRAME", Owner = this, Content = root,
            Background = Background, FontFamily = FontFamily, FontSize = FontSize,
            Width = Math.Max(900, ActualWidth - SidebarColumn.ActualWidth), Height = Math.Max(600, ActualHeight - 74),
            MinWidth = 760, MinHeight = 450, WindowStartupLocation = WindowStartupLocation.Manual
        };
        // PointToScreen returns physical pixels; WPF window bounds use device-independent units.
        Point location = PresentationSource.FromVisual(this)!.CompositionTarget.TransformFromDevice.Transform(screenPosition);
        floating.Left = location.X - 120; floating.Top = location.Y - 16;
        var detached = new DetachedPage(floating, layout);
        detachedPages.Add(key, detached);
        floating.StateChanged += (_, _) =>
        {
            if (floating.WindowState != WindowState.Minimized) detached.RestoreState = floating.WindowState;
        };
        floating.Closing += (_, _) => DockPage(key, !closing, false);
        floating.Show();
        if (current == key) ShowPage(page);
        return floating;
    }

    private bool ShowDetachedPage(PageState page)
    {
        if (!detachedPages.TryGetValue(page.Key, out var detached)) return false;
        Form.Content = null; PageHeading.Visibility = Visibility.Collapsed; WaveCursor.Visibility = Visibility.Collapsed;
        var placeholder = new StackPanel { HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center };
        placeholder.Children.Add(new TextBlock { Text = $"{page.Title}已在独立窗口中打开", Margin = new Thickness(0, 0, 0, 12) });
        var activate = new Button { Content = "显示窗口" };
        activate.Click += (_, _) => ActivateDetachedPage(detached);
        var dock = new Button { Content = "放回主窗口" };
        dock.Click += (_, _) => DockPage(page.Key, true);
        placeholder.Children.Add(activate); placeholder.Children.Add(dock);
        PageBody.Content = placeholder;
        ActivateDetachedPage(detached);
        return true;
    }

    private static void ActivateDetachedPage(DetachedPage detached)
    {
        if (detached.Window.WindowState == WindowState.Minimized) detached.Window.WindowState = detached.RestoreState;
        detached.Window.Activate();
    }

    private void DockPage(string key, bool selectPage, bool closeWindow = true)
    {
        if (!detachedPages.Remove(key, out var detached)) return;
        var page = pages[key];
        detached.Layout.Children.Remove(page.Form); detached.Layout.Children.Remove(page.Body);
        if (closeWindow) detached.Window.Close();
        if (closing) return;
        if (selectPage) Navigation.SelectedIndex = pages.Keys.ToList().IndexOf(key);
        if (current == key) ShowPage(page);
        if (selectPage) Activate();
    }
}
