using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using Frame.Client;
using ScottPlot.WPF;
using LayoutGrid = System.Windows.Controls.Grid;

namespace Frame.Desktop;

public sealed partial class RealtimeScopePage : DiagnosticPage
{
    private static readonly string[] UnitPresets = ["", "V", "A", "W", "var", "VA"];
    private static readonly string[] Colors = ["#2563EB", "#E11D48", "#059669", "#D97706", "#7C3AED", "#0891B2", "#C026D3", "#475569"];
    private List<RealtimeScopeSymbol> symbols = new();
    private readonly List<RealtimeScopeSymbol> roots = new();
    private readonly RealtimeScopeWorkspace workspace = new();
    private readonly TextBox elf, map, search, frequency, history, windowMs, level;
    private readonly TextBlock symbolCount = Text("尚未加载"), selectionInfo = Text(""), summary = Text(""), runState = Text("STOP"), triggerUnit = Text(""), cursor = Text("");
    private readonly DataGrid parameterTable, channelTable;
    private readonly ComboBox triggerSource, edge;
    private readonly CheckBox triggerEnabled, triggerPause;
    private readonly Button previewButton, pauseButton, armButton, removeButton, singleButton, forceButton;
    private readonly WpfPlot plot = new();
    private readonly DispatcherTimer previewTimer = new() { Interval = TimeSpan.FromMilliseconds(33) };
    private readonly DispatcherTimer searchTimer = new(DispatcherPriority.Background) { Interval = TimeSpan.FromMilliseconds(150) };
    private readonly Stopwatch clock = new();
    private readonly RealtimeScopeConnection scopeLink = new();
    private readonly DispatcherTimer linkTimer = new() { Interval = TimeSpan.FromMilliseconds(250) };
    private readonly TextBox linkPort, linkBaud, linkHost, linkTcpPort;
    private readonly ComboBox linkTransport, linkPorts;
    private readonly TextBlock linkStatus = Text("数据链路未连接");
    private readonly WrapPanel serialLinkSettings = new(), tcpLinkSettings = new();
    private readonly Button linkConnect, linkRefresh;
    private bool linkBusy;
    private EthernetDiscoveryWindow? discoveryWindow;
    private readonly Dictionary<int, (double[] X, double[] Raw)> snapshot = new();
    private RealtimeScopePreview? preview;
    private BackendClient? symbolClient;
    public Task ShutdownCompletion { get; private set; } = Task.CompletedTask;
    private long generated;
    private bool refreshing, follow = true, previewRunning, demonstrationSymbols;
    private double snapshotFirst, snapshotLast, snapshotOriginMs;
    private double snapshotAnchorLast;
    private bool retainedHistory;
    private RealtimeScopePreview? snapshotSource;
    public RealtimeScopeWorkspace Workspace => workspace;
    public RealtimeScopePreview? Preview => preview;
    public bool PreviewRunning => previewRunning;
    public RealtimeScopeConnection ScopeLink => scopeLink;

    public RealtimeScopePage(BackendClient client, Dictionary<string, TextBox> fields, Action<string> feedback)
        : base(client, fields, feedback)
    {
        elf = Input("realtime_elf"); map = Input("realtime_map"); search = Input("realtime_search");
        frequency = Input("realtime_frequency", "30000", 82); history = Input("realtime_history", "10", 55);
        windowMs = Input("realtime_window_ms", "100", 60); level = Input("realtime_trigger_level", "0", 62);
        linkPort = Input("realtime_link_port", "", 85); linkBaud = Input("realtime_link_baud", "20000000", 95);
        linkHost = Input("realtime_link_host", "192.168.1.10", 125); linkTcpPort = Input("realtime_link_tcp_port", "9001", 65);
        foreach (var input in new[] { elf, map, search, frequency, history, windowMs, level, linkPort, linkBaud, linkHost, linkTcpPort }) {
            input.Height = 28; input.Padding = new Thickness(6, 2, 6, 2); input.Margin = new Thickness(0, 0, 6, 4); input.VerticalContentAlignment = VerticalAlignment.Center;
        }
        linkTransport = Choice("realtime_link_transport", "串口", "以太网 TCP");
        linkTransport.SelectedIndex = 1;
        linkPorts = new ComboBox { IsEditable = true, IsTextSearchEnabled = false, Width = 100, Height = 28, Padding = new Thickness(3), Margin = new Thickness(0, 0, 6, 4), DataContext = linkPort };
        linkPorts.SetBinding(ComboBox.TextProperty, new Binding("Text") { Mode = BindingMode.TwoWay, UpdateSourceTrigger = UpdateSourceTrigger.PropertyChanged });
        AutomationProperties.SetAutomationId(linkPorts, "realtime_link_ports");
        linkConnect = ScopeButton("连接数据链路", "realtime_link_connect");
        AutomationProperties.SetAutomationId(linkConnect, "realtime_link_connect"); linkConnect.Click += async (_, _) => await ToggleScopeLinkAsync();
        linkRefresh = ScopeButton("刷新端口", "realtime_link_refresh");
        linkRefresh.Click += async (_, _) => await RefreshScopePortsAsync();
        linkTransport.SelectionChanged += (_, _) => UpdateLinkStatus();
        foreach (var pair in fields) AutomationProperties.SetAutomationId(pair.Value, pair.Key);
        foreach (var input in new[] { elf, map, search }) { input.Width = double.NaN; input.Margin = new Thickness(0, 2, 6, 5); }

        parameterTable = MakeTable("realtime_parameters"); parameterTable.ItemsSource = symbols;
        VirtualizingPanel.SetVirtualizationMode(parameterTable, VirtualizationMode.Recycling);
        ScrollViewer.SetCanContentScroll(parameterTable, true);
        var name = new FrameworkElementFactory(typeof(DockPanel));
        var arrow = new FrameworkElementFactory(typeof(Button)); arrow.SetBinding(ContentControl.ContentProperty, new Binding("Arrow"));
        arrow.SetValue(WidthProperty, 23d); arrow.SetValue(MarginProperty, new Thickness(0)); arrow.SetValue(PaddingProperty, new Thickness(0));
        var arrowStyle = new Style(typeof(Button)); arrowStyle.Setters.Add(new Setter(Control.BackgroundProperty, Brushes.Transparent)); arrowStyle.Setters.Add(new Setter(Control.BorderThicknessProperty, new Thickness(0)));
        var leaf = new DataTrigger { Binding = new Binding("Expandable"), Value = false }; leaf.Setters.Add(new Setter(VisibilityProperty, Visibility.Hidden)); arrowStyle.Triggers.Add(leaf); arrow.SetValue(StyleProperty, arrowStyle);
        arrow.AddHandler(System.Windows.Controls.Button.ClickEvent, new RoutedEventHandler(async (sender, e) => {
            if ((sender as FrameworkElement)?.DataContext is RealtimeScopeSymbol symbol) await Run(() => ExpandAsync(symbol)); e.Handled = true;
        }));
        name.SetBinding(MarginProperty, new Binding("Indent")); name.AppendChild(arrow);
        var title = new FrameworkElementFactory(typeof(TextBlock)); title.SetBinding(TextBlock.TextProperty, new Binding("Name"));
        title.SetBinding(ToolTipProperty, new Binding("Name")); title.SetValue(TextBlock.TextTrimmingProperty, TextTrimming.CharacterEllipsis); title.SetValue(VerticalAlignmentProperty, VerticalAlignment.Center); name.AppendChild(title);
        parameterTable.Columns.Add(new DataGridTemplateColumn { Header = "参数 / 结构体成员", CellTemplate = new DataTemplate { VisualTree = name }, Width = new DataGridLength(1, DataGridLengthUnitType.Star) });
        parameterTable.SelectionChanged += (_, _) => { if (parameterTable.SelectedItem is RealtimeScopeSymbol symbol) selectionInfo.Text = $"{symbol.Type} · {symbol.AddressText}\n{symbol.Name} · {symbol.SamplingHint}"; };
        parameterTable.MouseDoubleClick += async (_, e) => {
            if (Ancestor<DataGridRow>(e.OriginalSource as DependencyObject) is { Item: RealtimeScopeSymbol { Expandable: true } symbol }) {
                e.Handled = true; await Run(() => ExpandAsync(symbol));
            }
        };
        ConfigureParameterMenu();
        searchTimer.Tick += (_, _) => RebuildSymbols();
        search.TextChanged += (_, _) => { searchTimer.Stop(); if (!Closed) searchTimer.Start(); };

        channelTable = MakeTable("realtime_channels"); channelTable.SelectionMode = DataGridSelectionMode.Single;
        channelTable.IsReadOnly = false; channelTable.RowHeight = 28;
        var visibleStyle = new Style(typeof(CheckBox)); visibleStyle.Setters.Add(new Setter(IsEnabledProperty, new Binding("Enabled"))); visibleStyle.Setters.Add(new Setter(HorizontalAlignmentProperty, HorizontalAlignment.Center));
        channelTable.Columns.Add(new DataGridCheckBoxColumn { Header = "显", Binding = new Binding("Display.Visible") { Mode = BindingMode.TwoWay, UpdateSourceTrigger = UpdateSourceTrigger.PropertyChanged }, ElementStyle = visibleStyle, EditingElementStyle = visibleStyle, Width = 30 });
        AddColumn(channelTable, "通道", "Label", 45, true);
        AddColumn(channelTable, "参数", "Name", 0, true);
        var divisionCell = new FrameworkElementFactory(typeof(TextBox));
        divisionCell.SetValue(AutomationProperties.AutomationIdProperty, "realtime_vertical_div");
        divisionCell.SetValue(MarginProperty, new Thickness(2, 1, 2, 1));
        divisionCell.SetValue(Control.PaddingProperty, new Thickness(3, 0, 3, 0));
        divisionCell.SetValue(HeightProperty, 24d);
        divisionCell.SetValue(Control.VerticalContentAlignmentProperty, VerticalAlignment.Center);
        divisionCell.SetValue(ToolTipProperty, "每格量程：输入正数，回车或失焦生效；悬停滚轮调整。");
        divisionCell.SetBinding(TextBox.TextProperty, new Binding("Display.UnitsPerDivision") {
            Mode = BindingMode.TwoWay, UpdateSourceTrigger = UpdateSourceTrigger.LostFocus, ValidatesOnExceptions = true,
            ConverterCulture = CultureInfo.InvariantCulture, StringFormat = "{0:R}"
        });
        divisionCell.AddHandler(Keyboard.KeyDownEvent, new KeyEventHandler((sender, e) => {
            if (e.Key == Key.Enter) { ((TextBox)sender).GetBindingExpression(TextBox.TextProperty)?.UpdateSource(); e.Handled = true; }
        }));
        divisionCell.AddHandler(Mouse.PreviewMouseWheelEvent, new MouseWheelEventHandler(ChangeChannelDivision));
        channelTable.Columns.Add(new DataGridTemplateColumn { Header = "/div", Width = 70, CellTemplate = new DataTemplate { VisualTree = divisionCell } });
        removeButton = Click("移除所选", "realtime_remove", () => {
            if (Busy) return;
            if (channelTable.SelectedItem is RealtimeScopeChannel channel) { StopPreview(); channel.Assign(null); ChannelsChanged(channel.Number); }
        });

        triggerSource = new ComboBox { Width = 74, Height = 28, DisplayMemberPath = "Label", SelectedValuePath = "Number", Margin = new Thickness(0, 0, 6, 4) };
        AutomationProperties.SetAutomationId(triggerSource, "realtime_trigger_source");
        edge = Choice("realtime_trigger_edge", "上升沿", "下降沿");
        triggerEnabled = new CheckBox { Content = "触发", IsChecked = true, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 10, 4) };
        triggerPause = new CheckBox { Content = "触发冻结", IsChecked = false, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 8, 4) };
        AutomationProperties.SetAutomationId(triggerEnabled, "realtime_trigger"); AutomationProperties.SetAutomationId(triggerPause, "realtime_trigger_pause");
        foreach (var control in new[] { triggerEnabled, triggerPause }) { control.Checked += (_, _) => ConfigurePreview(); control.Unchecked += (_, _) => ConfigurePreview(); }
        triggerSource.SelectionChanged += (_, _) => ConfigurePreview(); edge.SelectionChanged += (_, _) => ConfigurePreview();
        foreach (var input in new[] { windowMs, level }) {
            input.LostKeyboardFocus += (_, _) => ConfigurePreview();
            input.KeyDown += (_, e) => { if (e.Key == Key.Enter) { ConfigurePreview(); e.Handled = true; } };
        }

        previewButton = Click("运行", "realtime_preview", () => { if (previewRunning) StopPreview(); else { singleArmed = false; _ = Run(StartSelectedSourceAsync); } });
        pauseButton = Click("冻结", "realtime_pause", () => {
            if (preview == null) return;
            if (preview.DisplayPaused) { preview.Rearm(); retainedHistory = false; follow = true; }
            else { preview.PauseDisplay(); RetainHistorySnapshot(); }
            RenderSnapshot(); UpdateRunState();
        });
        armButton = Click("重新触发", "realtime_arm", () => { preview?.Rearm(); retainedHistory = false; follow = true; UpdateRunState(); });
        singleButton = Click("单次", "realtime_single", () => { if (!rollMode) { singleArmed = true; _ = Run(StartSelectedSourceAsync); } });
        forceButton = Click("强制触发", "realtime_force", () => { preview?.ForceTrigger(); retainedHistory = false; });
        InitializeInstrument();
        var root = new LayoutGrid(); root.RowDefinitions.Add(new() { Height = GridLength.Auto }); root.RowDefinitions.Add(new()); root.RowDefinitions.Add(new() { Height = GridLength.Auto });
        root.Children.Add(BuildHeader());
        var body = new LayoutGrid { Margin = new Thickness(0, 8, 0, 6) };
        body.ColumnDefinitions.Add(new() { MinWidth = 240 });
        body.ColumnDefinitions.Add(new() { Width = new GridLength(7) }); body.ColumnDefinitions.Add(new() { Width = new GridLength(280), MinWidth = 250 });
        LayoutGrid.SetRow(body, 1); root.Children.Add(body);
        var chart = BuildChart(); body.Children.Add(chart);
        var inspector = new TabControl(); AutomationProperties.SetAutomationId(inspector, "realtime_inspector");
        inspector.Items.Add(new TabItem { Header = "通道", Content = BuildChannels() });
        inspector.Items.Add(new TabItem { Header = "测量 / 游标", Content = BuildReadouts() }); inspector.SelectedIndex = 0;
        LayoutGrid.SetColumn(inspector, 2); body.Children.Add(inspector);
        var splitter = new GridSplitter { Width = 5, HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Stretch, Background = Brushes.Transparent }; LayoutGrid.SetColumn(splitter, 1); body.Children.Add(splitter);
        LayoutGrid.SetRow(summary, 2); root.Children.Add(summary);
        Content = root;
        foreach (var display in workspace.Displays) display.PropertyChanged += (_, _) => {
            bool paused = preview?.DisplayPaused == true;
            ConfigurePreview(); if (paused) preview?.PauseDisplay();
            RenderSnapshot(); UpdateSummary();
        };
        foreach (var input in new[] { frequency, history }) input.LostKeyboardFocus += (_, _) => { ConfigurePreview(); UpdateSummary(); };
        previewTimer.Tick += (_, _) => AdvancePreview();
        linkTimer.Tick += (_, _) => UpdateLinkStatus(); linkTimer.Start();
        UpdateChannelView(); UpdateSummary(); ConfigurePreview(); UpdateLinkStatus();
    }

    private UIElement BuildHeader()
    {
        var linkControls = new WrapPanel(); linkControls.Children.Add(Toolbar(Text("数据链路"), linkTransport));
        serialLinkSettings.Children.Add(Text("端口")); serialLinkSettings.Children.Add(linkPorts); serialLinkSettings.Children.Add(linkRefresh);
        serialLinkSettings.Children.Add(Text("波特率")); serialLinkSettings.Children.Add(linkBaud);
        var searchTcp = ScopeButton("搜索设备", "realtime_link_search");
        searchTcp.Click += async (_, _) => await SearchScopeTcpAsync();
        tcpLinkSettings.Children.Add(searchTcp);
        tcpLinkSettings.Children.Add(Text("IP")); tcpLinkSettings.Children.Add(linkHost); tcpLinkSettings.Children.Add(Text("端口")); tcpLinkSettings.Children.Add(linkTcpPort);
        linkControls.Children.Add(serialLinkSettings); linkControls.Children.Add(tcpLinkSettings); linkControls.Children.Add(linkConnect);
        linkStatus.TextWrapping = TextWrapping.NoWrap; linkStatus.MaxWidth = 120; linkStatus.TextTrimming = TextTrimming.CharacterEllipsis;
        linkControls.Children.Add(linkStatus);
        var settings = new WrapPanel();
        settings.Children.Add(previewButton); settings.Children.Add(pauseButton); settings.Children.Add(singleButton);
        settings.Children.Add(Click("自动设置", "realtime_autoset", AutoSet));
        var selectParameters = ActionButton("选择参数", OpenParameterPickerAsync); AutomationProperties.SetAutomationId(selectParameters, "realtime_select_parameters"); settings.Children.Add(selectParameters);
        var sync = ActionButton("参数同步", SynchronizeParametersAsync); AutomationProperties.SetAutomationId(sync, "realtime_sync"); settings.Children.Add(sync); settings.Children.Add(syncState);
        settings.Children.Add(runState);
        settings.Children.Add(Toolbar(Text("数据源"), sourceChoice));
        settings.Children.Add(Toolbar(Text("采样率 / Hz"), frequency));
        settings.Children.Add(Toolbar(Text("缓存 / s"), history));
        settings.Children.Add(Toolbar(Text("窗口 / ms"), windowMs));
        var linkItems = linkControls.Children.Cast<UIElement>().ToArray(); linkControls.Children.Clear();
        foreach (var item in linkItems) settings.Children.Add(item);
        settings.Children.Add(Click("实时", "realtime_follow", () => { follow = true; if (preview?.DisplayPaused == false && preview.CanDisplay) CaptureSnapshot(); RenderSnapshot(); }));
        settings.Children.Add(triggerMode);
        settings.Children.Add(Toolbar(Text("触发源"), triggerSource, edge));
        settings.Children.Add(triggerPause); settings.Children.Add(forceButton); settings.Children.Add(armButton);
        return settings;
    }
    private UIElement BuildFiles()
    {
        var files = new LayoutGrid { Margin = new Thickness(0, 8, 0, 0) };
        files.ColumnDefinitions.Add(new() { Width = GridLength.Auto }); files.ColumnDefinitions.Add(new()); files.ColumnDefinitions.Add(new() { Width = GridLength.Auto }); files.ColumnDefinitions.Add(new() { Width = GridLength.Auto });
        files.RowDefinitions.Add(new() { Height = GridLength.Auto }); files.RowDefinitions.Add(new() { Height = GridLength.Auto });
        AddCell(files, Text("ELF"), 0, 0); AddCell(files, elf, 0, 1);
        AddCell(files, Click("选择…", "realtime_browse_elf", () => { if (ChooseFile("固件符号|*.elf;*.axf;*.out|所有文件|*.*") is string path) elf.Text = path; }), 0, 2);
        var select = ActionButton("选择参数", LoadParametersAsync); AutomationProperties.SetAutomationId(select, "realtime_select_reload"); AddCell(files, select, 0, 3);
        AddCell(files, Text("MAP（可选）"), 1, 0); AddCell(files, map, 1, 1);
        AddCell(files, Click("选择…", "realtime_browse_map", () => { if (ChooseFile("链接映射|*.map|所有文件|*.*") is string path) map.Text = path; }), 1, 2);
        return files;
    }
    private UIElement BuildParameters()
    {
        var searchBar = new DockPanel(); var searchLabel = Text("搜索"); DockPanel.SetDock(searchLabel, Dock.Left); searchBar.Children.Add(searchLabel); searchBar.Children.Add(search);
        var tools = new StackPanel(); tools.Children.Add(searchBar); tools.Children.Add(symbolCount);
        var panel = new DockPanel(); DockPanel.SetDock(tools, Dock.Top); panel.Children.Add(tools);
        selectionInfo.FontSize = 11; selectionInfo.Margin = new Thickness(2, 8, 2, 0); DockPanel.SetDock(selectionInfo, Dock.Bottom); panel.Children.Add(selectionInfo); panel.Children.Add(parameterTable); return panel;
    }
    private async Task SearchScopeTcpAsync()
    {
        if (linkBusy || Closed) return;
        discoveryWindow = new EthernetDiscoveryWindow(RealtimeScopeConnection.DiscoverAsync, 9001) { Owner = Window.GetWindow(this) };
        try {
            if (discoveryWindow.ShowDialog() == true && discoveryWindow.SelectedDevice is { } device && !Closed) {
                linkHost.Text = device.Ip; linkTcpPort.Text = device.Port.ToString(CultureInfo.InvariantCulture);
                await ToggleScopeLinkAsync();
            }
        }
        finally { discoveryWindow = null; }
    }
    public async Task ToggleScopeLinkAsync()
    {
        if (Closed || linkBusy) return;
        linkBusy = true; UpdateLinkStatus();
        try {
            if (scopeLink.Snapshot()["connected"]?.GetValue<bool>() == true) {
                StopPreview(); await deviceStopTask;
                await scopeLink.DisconnectAsync();
                if (!Closed) Status("实时示波器数据链路已断开。");
            }
            else {
                uint baud = 0; int tcpPort = 0;
                if (linkTransport.SelectedIndex == 0 && (!uint.TryParse(linkBaud.Text, out baud) || baud == 0)) throw new ArgumentException("请输入有效的数据链路波特率。");
                if (linkTransport.SelectedIndex == 1 && !int.TryParse(linkTcpPort.Text, out tcpPort)) throw new ArgumentException("请输入有效的独立 TCP 端口。");
                await scopeLink.ConnectAsync(new(linkTransport.SelectedIndex == 1 ? "tcp" : "serial", linkPort.Text, baud, linkHost.Text, tcpPort));
                if (!Closed) Status("实时示波器数据链路已连接。");
            }
        }
        catch (Exception error) { if (!Closed) Status(error.Message); }
        finally { linkBusy = false; if (!Closed) UpdateLinkStatus(); }
    }
    private async Task RefreshScopePortsAsync()
    {
        if (Closed || linkBusy) return;
        linkBusy = true; UpdateLinkStatus();
        try { var ports = await scopeLink.PortsAsync(); if (!Closed) { string text = linkPort.Text; linkPorts.ItemsSource = ports; linkPorts.Text = text; } }
        catch (Exception error) { if (!Closed) Status(error.Message); }
        finally { linkBusy = false; if (!Closed) UpdateLinkStatus(); }
    }
    private void UpdateLinkStatus()
    {
        if (Closed) return;
        var state = scopeLink.Snapshot(); bool connected = state["connected"]?.GetValue<bool>() == true;
        serialLinkSettings.Visibility = linkTransport.SelectedIndex == 0 ? Visibility.Visible : Visibility.Collapsed;
        tcpLinkSettings.Visibility = linkTransport.SelectedIndex == 1 ? Visibility.Visible : Visibility.Collapsed;
        linkTransport.IsEnabled = serialLinkSettings.IsEnabled = tcpLinkSettings.IsEnabled = !linkBusy && !connected;
        linkConnect.IsEnabled = !linkBusy; linkConnect.Content = linkBusy ? "处理中…" : connected ? "断开" : "连接";
        linkStatus.Text = connected
            ? $"{state["endpoint"]}   RX {state["rx_bytes"] ?? JsonValue.Create(0)} B / TX {state["tx_bytes"] ?? JsonValue.Create(0)} B"
            : "未连接";
        linkStatus.ToolTip = linkStatus.Text;
    }
    private UIElement BuildChannels()
    {
        var panel = new DockPanel();
        var top = Toolbar(removeButton); DockPanel.SetDock(top, Dock.Top); panel.Children.Add(top);
        panel.Children.Add(channelTable); return panel;
    }
    private UIElement BuildChart()
    {
        var area = new DockPanel();
        plot.MinHeight = 180; plot.Plot.XLabel("t / ms"); plot.Plot.Axes.SetLimits(0, 100, -4, 4);
        plot.Plot.Axes.Left.TickLabelStyle.IsVisible = false;
        plot.Plot.Axes.Left.TickGenerator = new ScottPlot.TickGenerators.NumericFixedInterval(1);
        AutomationProperties.SetAutomationId(plot, "realtime_plot");
        plot.SizeChanged += (_, _) => Dispatcher.BeginInvoke(DispatcherPriority.ContextIdle, new Action(() => { if (!Closed) RenderSnapshot(); }));
        plot.PreviewMouseDown += BeginCursorDrag;
        plot.PreviewMouseMove += MoveCursor;
        plot.PreviewMouseUp += EndCursorDrag;
        plot.LostMouseCapture += (_, _) => { draggedCursor = -1; RenderSnapshot(); };
        plot.MouseUp += (_, _) => Dispatcher.BeginInvoke(new Action(() => {
            if (draggedCursor >= 0 || Closed) return;
            if (!follow && preview?.DisplayPaused == false) CaptureSnapshot();
            RenderSnapshot();
        }));
        plot.PreviewMouseWheel += (_, e) => {
            // Consume before ScottPlot's default handler can zoom either axis.
            e.Handled = true;
            if (refreshing || Closed) return;
            long accumulated = Math.Clamp((long)timeWheelRemainder + e.Delta, -3840, 3840);
            int steps = (int)(accumulated / Mouse.MouseWheelDeltaForOneLine);
            timeWheelRemainder = (int)(accumulated % Mouse.MouseWheelDeltaForOneLine);
            if (steps != 0) ZoomTime(Math.Pow(0.5, steps));
        };
        plot.MouseMove += (_, e) => {
            if (snapshot.Count == 0) return;
            var point = MouseCoordinates(e);
            var texts = new List<string>();
            foreach (var channel in workspace.Configuration.Enabled.Where(channel => channel.Display.Visible)) {
                if (preview == null || !rawSnapshot.TryGetValue(channel.Number, out var data) || data.Length == 0) continue;
                int index = (int)Math.Clamp(Math.Round((point.X + snapshotOriginMs - snapshotFirst) * preview.SampleRate / 1000), 0, data.Length - 1);
                texts.Add($"{channel.Label} {channel.Display.Engineering(data[index]):G5} {channel.Display.Unit}".TrimEnd());
            }
            cursor.Text = $"{point.X:G6} ms   " + string.Join("   ", texts);
            plot.ToolTip = cursor.Text;
        };
        area.Children.Add(plot); return area;
    }

    public async Task LoadParametersAsync()
    {
        await ReloadSymbolsFromDiskAsync();
    }
    public async Task ExpandAsync(RealtimeScopeSymbol symbol)
    {
        if (!symbol.Expandable || symbol.Depth >= 32) return;
        if (!symbol.Loaded) {
            if (!demonstrationSymbols) {
                for (int offset = 0; !Closed;) {
                    var part = (await SymbolCommand("expand", new() { ["name"] = symbol.Name, ["offset"] = offset, ["limit"] = 256 }))!.AsArray();
                    symbol.Children.AddRange(part.OfType<JsonObject>().Select(data => new RealtimeScopeSymbol((JsonObject)data.DeepClone(), symbol.Depth + 1)));
                    offset += part.Count; if (part.Count < 256) break;
                    if (offset >= 4096) { Status("当前节点最多展开 4096 个成员；大型数组请缩小选择范围。"); break; }
                }
            }
            symbol.Loaded = true;
        }
        symbol.Expanded = !symbol.Expanded; RebuildSymbols();
    }
    private void RebuildSymbols()
    {
        searchTimer.Stop();
        if (Closed) return;
        string query = search.Text.Trim();
        var result = new List<RealtimeScopeSymbol>(roots.Count);
        bool Add(RealtimeScopeSymbol symbol) {
            int position = result.Count;
            result.Add(symbol);
            bool matched = query.Length == 0 || symbol.Name.Contains(query, StringComparison.OrdinalIgnoreCase);
            if (symbol.Expanded || query.Length > 0) {
                foreach (var child in symbol.Children) matched |= Add(child);
            }
            // Unmatched descendants have already been removed, so this removes only the tail.
            if (!matched) result.RemoveAt(position);
            return matched;
        }
        foreach (var symbol in roots) Add(symbol);
        ReplaceSymbols(result);
        symbolCount.Text = $"{roots.Count} 个根变量 · 当前 {symbols.Count} 项";
    }
    private void ReplaceSymbols(List<RealtimeScopeSymbol> result)
    {
        searchTimer.Stop();
        symbols = result;
        parameterTable.ItemsSource = symbols;
        selectionInfo.Text = "";
    }
    private async Task<JsonNode?> SymbolCommand(string action, JsonObject arguments)
    {
        if (Closed) throw new OperationCanceledException();
        symbolClient ??= new BackendClient();
        arguments["group"] = "jlink"; arguments["action"] = action;
        var result = await symbolClient.ExecuteAsync(arguments);
        if (Closed) throw new OperationCanceledException();
        if (result["ok"]?.GetValue<bool>() != true) throw new InvalidOperationException(result["error"]?.ToString() ?? "符号解析失败。");
        return result["data"];
    }
    public void LoadDemonstrationSymbols()
    {
        sourceChoice.SelectedIndex = 1;
        roots.Clear(); demonstrationSymbols = true;
        var controller = new RealtimeScopeSymbol(new JsonObject { ["name"] = "controller", ["kind"] = "struct", ["address"] = 0x20001000UL, ["type_name"] = "Controller", ["size"] = 12 }) { Loaded = true, Expanded = true };
        foreach (var item in new[] { ("controller.voltage", 0x20001000UL), ("controller.current", 0x20001004UL), ("controller.reference", 0x20001008UL) })
            controller.Children.Add(new RealtimeScopeSymbol(new JsonObject { ["name"] = item.Item1, ["kind"] = "scalar", ["address"] = item.Item2, ["type_name"] = "float", ["encoding"] = 4, ["size"] = 4 }, 1));
        roots.Add(controller); search.Clear(); RebuildSymbols();
        Status("示例参数：地址仅用于界面演示，波形由模拟源生成。");
    }
    private void AddSelected() => Try(() => {
        var selected = parameterTable.SelectedItems.Cast<RealtimeScopeSymbol>().Where(symbol => symbol.CanSample).OrderBy(symbol => symbols.IndexOf(symbol)).ToArray();
        if (selected.Length == 0) throw new ArgumentException("请先选择参数，或展开结构体选择具体成员。");
        foreach (var symbol in selected) AssignSymbol(symbol);
    });
    public void AssignSymbol(RealtimeScopeSymbol symbol, int? number = null)
    {
        if (Busy) throw new InvalidOperationException("正在读取参数，请稍后操作。");
        StopPreview();
        int? target = number ?? workspace.Configuration.Channels.FirstOrDefault(channel => !channel.Enabled)?.Number;
        if (target == null || !workspace.Configuration.Add(symbol, target)) throw new InvalidOperationException("通道已满（32/32）。");
        Status($"已添加 CH{target}：{symbol.Name}");
        ChannelsChanged(target.Value);
    }
    private void ChannelsChanged(int? changedChannel = null)
    {
        preview = null; snapshot.Clear(); rawSnapshot.Clear(); snapshotSource = null; retainedHistory = false; InvalidatePendingConfiguration();
        UpdateSources(); UpdateSummary(); RenderSnapshot();
        if (changedChannel is int number) QueueChannelUpdate(number);
    }
    private void UpdateChannelView()
    {
        channelTable.ItemsSource = workspace.Configuration.Channels;
        channelTable.SelectedIndex = 0;
    }
    private void UpdateSources()
    {
        refreshing = true;
        try {
            int triggerNumber = triggerSource.SelectedValue is int old ? old : 1;
            int measureNumber = measureSource.SelectedValue is int selected ? selected : 1;
            var channels = workspace.Configuration.Enabled.ToArray();
            triggerSource.ItemsSource = channels; triggerSource.SelectedValue = triggerNumber; if (triggerSource.SelectedIndex < 0) triggerSource.SelectedIndex = 0;
            measureSource.ItemsSource = channels; measureSource.SelectedValue = measureNumber; if (measureSource.SelectedIndex < 0) measureSource.SelectedIndex = 0;
        }
        finally { refreshing = false; }
    }
    private RealtimeScopePreview ValidatePreview(RealtimeScopeConfiguration configuration)
    {
        var settings = PreviewSettings();
        return new RealtimeScopePreview(configuration, settings.Frequency, settings.History);
    }
    private (int Frequency, double History) PreviewSettings()
    {
        double hz = Read(frequency, "采样频率"); if (hz != Math.Truncate(hz)) throw new ArgumentException("预览采样频率请输入整数 Hz。");
        return (checked((int)hz), Read(history, "历史容量"));
    }
    public void StartPreview() => Try(() => {
        if (Busy) throw new InvalidOperationException("正在读取参数，请稍后操作。");
        StartSimulation();
    });
    private void StartSimulation()
    {
        if (BindingsNeedRefresh) throw new InvalidOperationException("ELF 已更新，请先参数同步。");
        preview = ValidatePreview(workspace.Configuration);
        preview.TriggerCompleted += CaptureSnapshot;
        UpdateSources(); ConfigurePreviewCore();
        snapshot.Clear(); rawSnapshot.Clear(); retainedHistory = false; snapshotSource = null; generated = 0; snapshotOriginMs = 0; follow = true;
        clock.Restart(); previewRunning = true; previewTimer.Start(); previewButton.Content = "停止预览";
        sourceBadge.Text = "模拟源"; sourceChoice.IsEnabled = false;
        frequency.IsEnabled = history.IsEnabled = false; UpdateSummary(); UpdateRunState();
    }
    public void StopPreview()
    {
        if (previewRunning) RetainHistorySnapshot();
        StopDevice();
        previewTimer.Stop(); clock.Stop(); previewRunning = false; previewButton.Content = "开始预览";
        sourceChoice.IsEnabled = true;
        frequency.IsEnabled = history.IsEnabled = true; UpdateRunState();
    }
    private void AdvancePreview()
    {
        if (Closed || !previewRunning || preview == null) return;
        if (deviceRunning) { RefreshDevice(); return; }
        long target = (long)(clock.Elapsed.TotalSeconds * preview.SampleRate);
        int count = (int)Math.Clamp(target - generated, 0, preview.SampleRate / 5 + 1);
        bool wasPaused = preview.DisplayPaused;
        preview.Advance(count); generated += count;
        if (!wasPaused) { if (!preview.DisplayPaused && (preview.AutoFallback || triggerEnabled.IsChecked != true || !follow)) CaptureSnapshot(); RenderSnapshot(); }
        if (preview.SingleCompleted) StopPreview();
        UpdateRunState();
    }
    public void AdvancePreviewForTest(int count)
    {
        if (preview == null) throw new InvalidOperationException("Preview is not started.");
        bool wasPaused = preview.DisplayPaused; preview.Advance(count); generated += count;
        if (!wasPaused) { if (!preview.DisplayPaused && (preview.AutoFallback || triggerEnabled.IsChecked != true || !follow)) CaptureSnapshot(); RenderSnapshot(); }
        if (preview.SingleCompleted) StopPreview(); UpdateRunState();
    }
    private void CaptureSnapshot()
    {
        if (preview == null) return;
        if (preview.DisplayPaused || preview.SingleCompleted || !previewRunning) {
            if ((!retainedHistory || !ReferenceEquals(snapshotSource, preview)) && follow) {
                var retained = preview.CaptureHistory();
                snapshotAnchorLast = retained.WindowLast * 1000.0 / preview.SampleRate;
                snapshotOriginMs = triggerEnabled.IsChecked == true && retained.Trigger is long completed ? completed * 1000.0 / preview.SampleRate : 0;
            }
            RetainHistorySnapshot(); return;
        }
        RealtimeScopeHistory capture;
        if (!follow && !preview.DisplayPaused) {
            var limits = plot.Plot.Axes.GetLimits();
            capture = preview.Capture((long)Math.Floor((limits.Left + snapshotOriginMs) * preview.SampleRate / 1000), (long)Math.Ceiling((limits.Right + snapshotOriginMs) * preview.SampleRate / 1000));
        }
        else capture = preview.CaptureWindow();
        if (follow) snapshotOriginMs = triggerEnabled.IsChecked == true && capture.Trigger is long triggerAt ? triggerAt * 1000.0 / preview.SampleRate : 0;
        if (capture.Last < capture.First) return;
        snapshot.Clear(); rawSnapshot.Clear(); retainedHistory = false;
        snapshotFirst = capture.First * 1000.0 / preview.SampleRate; snapshotLast = capture.Last * 1000.0 / preview.SampleRate;
        snapshotAnchorLast = snapshotLast;
        snapshotSource = preview;
        foreach (var channel in workspace.Configuration.Enabled) {
            var raw = capture.Values[channel.Number];
            rawSnapshot[channel.Number] = raw;
            snapshot[channel.Number] = raw.Length == 0 ? ([], []) : ([snapshotFirst, snapshotLast], [raw[0], raw[^1]]);
        }
    }
    private void RetainHistorySnapshot()
    {
        if (preview == null || preview.NextSample == 0 || (retainedHistory && ReferenceEquals(snapshotSource, preview))) return;
        var capture = preview.CaptureHistory();
        if (snapshot.Count == 0 || !ReferenceEquals(snapshotSource, preview)) snapshotAnchorLast = capture.WindowLast * 1000.0 / preview.SampleRate;
        snapshotFirst = capture.First * 1000.0 / preview.SampleRate;
        snapshotLast = capture.Last * 1000.0 / preview.SampleRate;
        snapshot.Clear(); rawSnapshot.Clear();
        foreach (var channel in workspace.Configuration.Enabled) {
            var raw = capture.Values[channel.Number];
            rawSnapshot[channel.Number] = raw;
            snapshot[channel.Number] = raw.Length == 0 ? ([], []) : ([snapshotFirst, snapshotLast], [raw[0], raw[^1]]);
        }
        retainedHistory = true;
        snapshotSource = preview;
    }
    private void RenderSnapshot()
    {
        if (Closed) return;
        plot.Plot.Clear();
        if (follow && snapshot.Count > 0) {
            double span = ReadSafe(windowMs, 100); double right = Math.Max(snapshotAnchorLast, snapshotFirst + span) - snapshotOriginMs;
            plot.Plot.Axes.SetLimitsX(right - span, right);
        }
        var visible = plot.Plot.Axes.GetLimits();
        int pixelWidth = Math.Max(200, (int)plot.ActualWidth);
        foreach (var channel in workspace.Configuration.Enabled.Where(channel => channel.Display.Visible)) {
            if (!snapshot.TryGetValue(channel.Number, out var points) || points.X.Length == 0) continue;
            if (preview != null && rawSnapshot.TryGetValue(channel.Number, out var raw))
                points = RealtimeScopeCurve.Window(raw, snapshotFirst, 1000.0 / preview.SampleRate,
                    visible.Left + snapshotOriginMs, visible.Right + snapshotOriginMs, pixelWidth / 2);
            var curve = RealtimeScopeCurve.Interpolate(points.X.Select(x => x - snapshotOriginMs).ToArray(), points.Raw.Select(channel.Display.Divisions).ToArray(), pixelWidth * 2);
            var series = plot.Plot.Add.Scatter(curve.X, curve.Y);
            series.Color = ScottPlot.Color.FromHex(Colors[(channel.Number - 1) % Colors.Length]); series.MarkerSize = curve.X.Length == 1 ? 4 : 0; series.LineWidth = 1.5f;
        }
        plot.Plot.Axes.SetLimitsY(-4, 4);
        var limits = plot.Plot.Axes.GetLimits();
        plot.Plot.Axes.Bottom.TickGenerator = new ScottPlot.TickGenerators.NumericFixedInterval((limits.Right - limits.Left) / 10);
        RenderCursors(); RenderTrigger(); UpdateReadouts();
        plot.Refresh();
    }
    private void ConfigurePreview() { if (!refreshing && !Closed) Try(() => { ConfigurePreviewCore(); RenderSnapshot(); }); }
    private void ConfigurePreviewCore()
    {
        double milliseconds = Read(windowMs, "显示时长");
        if (milliseconds <= 0 || milliseconds > Read(history, "历史容量") * 1000) throw new ArgumentException("显示时长须大于 0 且不超过历史容量。");
        bool nextRolling = milliseconds >= RealtimeScopePreview.RollThresholdSeconds * 1000;
        bool changed = modeInitialized && rollMode != nextRolling;
        if (changed) {
            singleArmed = false;
            follow = true;
        }
        rollMode = nextRolling; modeInitialized = true;
        bool wasRefreshing = refreshing; refreshing = true;
        try {
            triggerMode.ItemsSource = rollMode ? new[] { "滚动" } : new[] { "自动", "普通" };
            triggerMode.SelectedIndex = rollMode || shortMode != RealtimeScopeTriggerMode.Normal ? 0 : 1;
            triggerMode.IsEnabled = !rollMode;
            triggerEnabled.IsChecked = !rollMode;
            triggerSource.IsEnabled = edge.IsEnabled = level.IsEnabled = pretrigger.IsEnabled = !rollMode;
            triggerPause.IsEnabled = !rollMode && !singleArmed;
        }
        finally { refreshing = wasRefreshing; }
        int sourceNumber = triggerSource.SelectedValue is int source ? source : 1;
        triggerUnit.Text = workspace.Displays[sourceNumber - 1].Unit;
        if (preview != null) {
            int number = triggerSource.SelectedValue is int selected ? selected : workspace.Configuration.Enabled.First().Number;
            var display = workspace.Displays[number - 1];
            if (!rollMode && display.Gain == 0) throw new ArgumentException("触发源倍率为 0，不能反算原始触发电平。");
            double rawLevel = rollMode ? 0 : (Read(level, "触发电平") - display.Bias) / display.Gain;
            var direction = edge.SelectedIndex == 1 ? RealtimeScopeEdge.Falling : RealtimeScopeEdge.Rising;
            if (display.Gain < 0) direction = direction == RealtimeScopeEdge.Rising ? RealtimeScopeEdge.Falling : RealtimeScopeEdge.Rising;
            double position = rollMode ? 50 : Read(pretrigger, "触发位置"); if (position < 0 || position > 100) throw new ArgumentException("触发位置范围为 0～100%。");
            var mode = rollMode ? RealtimeScopeTriggerMode.Roll : singleArmed ? RealtimeScopeTriggerMode.Single : shortMode;
            preview.Configure(milliseconds / 1000, new(!rollMode, number, rawLevel, direction, position / 100, !rollMode && triggerPause.IsChecked == true, mode));
        }
        timebase.Text = $"窗口 {milliseconds:G6} ms";
        UpdateRunState();
    }
    private void ZoomTime(double factor) => Try(() => {
        bool paused = preview?.DisplayPaused == true, wasRolling = rollMode;
        double milliseconds = Math.Clamp(Read(windowMs, "显示时长") * factor, 0.01, Read(history, "历史容量") * 1000);
        windowMs.Text = milliseconds.ToString("G6", CultureInfo.InvariantCulture); ConfigurePreviewCore();
        if (paused && wasRolling == rollMode) preview?.PauseDisplay();
        follow = true;
        if (previewRunning && !paused && preview?.CanDisplay == true) CaptureSnapshot();
        RenderSnapshot();
    });
    private void UpdateRunState()
    {
        if (previewButton == null) return;
        string state = preview?.SingleCompleted == true ? "已停止 · 单次" : !previewRunning ? "已停止" : preview?.DisplayPaused == true ? "已冻结" : triggerEnabled.IsChecked != true ? "滚动" : preview?.AutoFallback == true ? "自动" : preview?.CompletedTrigger != null ? "已触发" : "等待触发";
        previewButton.Content = previewRunning ? "■ 停止" : "▶ 运行";
        previewButton.Background = new SolidColorBrush(previewRunning ? Color.FromRgb(0xBE, 0x36, 0x49) : Color.FromRgb(0x12, 0x80, 0x60)); previewButton.Foreground = Brushes.White;
        runState.Text = state; runState.FontWeight = FontWeights.SemiBold; pauseButton.Content = preview?.DisplayPaused == true ? "继续" : "冻结";
        pauseButton.IsEnabled = previewRunning;
        armButton.IsEnabled = forceButton.IsEnabled = previewRunning && !rollMode;
        singleButton.IsEnabled = !rollMode;
    }
    private void UpdateSummary()
    {
        if (sourceChoice.SelectedIndex == 0 && !double.TryParse(frequency.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out _)) {
            summary.Text = $"{workspace.Configuration.Enabled.Count()}/32 CH   采样率{frequency.Text}   缓存 {ReadSafe(history, 10):G5} s"; return;
        }
        int bytes = workspace.Configuration.ByteCount; double hz = ReadSafe(frequency, 30000);
        if (sourceChoice.SelectedIndex == 0 && hz == 0) { summary.Text = $"{workspace.Configuration.Enabled.Count()}/32 CH   0 Hz · 未接入采样源   缓存 {ReadSafe(history, 10):G5} s"; return; }
        summary.Text = $"{workspace.Configuration.Enabled.Count()}/32 CH   {hz:G6} Hz   {(hz > 0 ? 1e6 / hz : 0):G7} μs   缓存 {ReadSafe(history, 10):G5} s   约 {hz * (bytes + 5) / 1000:G6} kB/s";
        if (sourceChoice.SelectedIndex == 0 && deviceByteBudget > 0)
            summary.Text += $" / {deviceByteBudget / 1000} kB/s（{hz * (bytes + 5) * 100 / deviceByteBudget:F1}%）";
    }
    public override void Shutdown()
    {
        if (Closed) return;
        StopDevice();
        previewTimer.Stop(); searchTimer.Stop(); linkTimer.Stop(); clock.Stop(); previewRunning = false; base.Shutdown();
        discoveryWindow?.Close();
        parameterPicker?.Close();
        var symbols = symbolClient is { } client ? client.DisposeAsync().AsTask() : Task.CompletedTask;
        ShutdownCompletion = Task.WhenAll(symbols, deviceStopTask, deviceStatusTask, deviceConfigurationTask, scopeLink.DisposeAsync().AsTask());
    }
    private void Try(Action action) { if (Closed) return; try { action(); } catch (Exception error) { Status(error.Message); } }
    private static double Read(TextBox input, string name) => double.TryParse(input.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out var value) && double.IsFinite(value) ? value : throw new ArgumentException(name + "请输入有效数值。");
    private static double ReadSafe(TextBox input, double fallback) => double.TryParse(input.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out var value) && double.IsFinite(value) ? value : fallback;
    private static TextBlock Text(string value) => new() { Text = value, Foreground = new SolidColorBrush(Color.FromRgb(0x47, 0x55, 0x69)), VerticalAlignment = VerticalAlignment.Center, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 0, 7, 4) };
    private static Button ScopeButton(string text, string id) {
        var button = new Button { Content = text, Height = 28, MinHeight = 28, MinWidth = 72, FontSize = 12,
            Padding = new Thickness(6, 0, 6, 0), Margin = new Thickness(0, 0, 5, 4), VerticalContentAlignment = VerticalAlignment.Center };
        AutomationProperties.SetAutomationId(button, id); return button;
    }
    private static Button Click(string text, string id, Action action) { var button = ScopeButton(text, id); button.Click += (_, _) => action(); return button; }
    private new Button ActionButton(string text, Func<Task> action) { var button = ScopeButton(text, ""); button.Click += async (_, _) => await Run(action); return button; }
    private static ComboBox Choice(string id, params string[] items) { var box = new ComboBox { ItemsSource = items, SelectedIndex = 0, MinWidth = 76, Height = 28, Margin = new Thickness(0, 0, 6, 4), Padding = new Thickness(3) }; AutomationProperties.SetAutomationId(box, id); return box; }
    private static DataGrid MakeTable(string id) { var table = new DataGrid { AutoGenerateColumns = false, IsReadOnly = true, CanUserAddRows = false, CanUserDeleteRows = false, SelectionUnit = DataGridSelectionUnit.FullRow, SelectionMode = DataGridSelectionMode.Extended, HeadersVisibility = DataGridHeadersVisibility.Column, EnableRowVirtualization = true, EnableColumnVirtualization = true, HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalGridLinesBrush = new SolidColorBrush(Color.FromRgb(0xE2, 0xE8, 0xF0)), GridLinesVisibility = DataGridGridLinesVisibility.Horizontal }; AutomationProperties.SetAutomationId(table, id); return table; }
    private static void AddColumn(DataGrid table, string title, string path, double width, bool readOnly) { var style = new Style(typeof(TextBlock)); style.Setters.Add(new Setter(TextBlock.TextTrimmingProperty, TextTrimming.CharacterEllipsis)); style.Setters.Add(new Setter(ToolTipProperty, new Binding(path))); table.Columns.Add(new DataGridTextColumn { Header = title, Binding = new Binding(path) { Mode = readOnly ? BindingMode.OneWay : BindingMode.TwoWay, UpdateSourceTrigger = UpdateSourceTrigger.LostFocus, ValidatesOnExceptions = true }, IsReadOnly = readOnly, Width = width == 0 ? new DataGridLength(1, DataGridLengthUnitType.Star) : new DataGridLength(width), ElementStyle = style }); }
    private static Border Pane(string title, UIElement content) { var dock = new DockPanel(); var label = Text(title); label.FontWeight = FontWeights.SemiBold; DockPanel.SetDock(label, Dock.Top); dock.Children.Add(label); dock.Children.Add(content); return new Border { Background = Brushes.White, BorderBrush = new SolidColorBrush(Color.FromRgb(0xDF, 0xE5, 0xED)), BorderThickness = new Thickness(1), Padding = new Thickness(8), Child = dock }; }
    private static void AddCell(LayoutGrid grid, UIElement content, int row, int column) { LayoutGrid.SetRow(content, row); LayoutGrid.SetColumn(content, column); grid.Children.Add(content); }
    private static T? Ancestor<T>(DependencyObject? element) where T : DependencyObject { while (element != null) { if (element is T match) return match; element = VisualTreeHelper.GetParent(element); } return null; }
}
