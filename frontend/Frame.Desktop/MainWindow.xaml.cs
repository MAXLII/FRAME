using System.ComponentModel;
using System.Data;
using System.Globalization;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using Frame.Client;
using Microsoft.Win32;
using ScottPlot.WPF;

namespace Frame.Desktop;

public partial class MainWindow : Window
{
    // UI state only. Wire formats, device state and operations remain in the DLL.
    private readonly BackendClient client = new();
    private readonly Dictionary<string, PageState> pages = new();
    private readonly Dictionary<ulong, (BackendJob Job, PageState Page)> jobs = new();
    private readonly DispatcherTimer timer = new() { Interval = TimeSpan.FromMilliseconds(250) };
    private bool updating, closing, disposed;
    private bool connectionBusy;
    private bool initializingConnection=true, refreshingPorts, editingBaud;
    private readonly SemaphoreSlim connectionGate=new(1,1);
    private string lastBaud="115200";
    private string current = "serial";
    private readonly string? settingsPath;
    public static readonly DependencyProperty SidebarCollapsedProperty=DependencyProperty.Register(nameof(SidebarCollapsed),typeof(bool),typeof(MainWindow),new PropertyMetadata(false));
    public bool SidebarCollapsed { get=>(bool)GetValue(SidebarCollapsedProperty);set=>SetValue(SidebarCollapsedProperty,value); }
    private sealed record NavigationItem(string Title,string Icon);
    private sealed record JobItem(ulong Id, string Label);
    private sealed class PageState(string key, string title, string hint)
    {
        public string Key { get; } = key;
        public string Title { get; } = title;
        public string Hint { get; } = hint;
        public StackPanel Form { get; } = new();
        public Dictionary<string, TextBox> Fields { get; } = new();
        public DataGrid Table { get; } = new();
        public Grid Body { get; } = new();
        public WpfPlot? Plot;
        public DiagnosticPage? Diagnostic;
        public WpfPlot? Phase;
        public TreeView? Symbols;
        public ParameterPanel? Parameters;
        public WaveSeriesPanel? Series;
        public WavePlotPanel? WavePlots;
        public ComboBox? WaveWindowPreset;
        public ComboBox? ScopeObjects;
        public ComboBox? ScopeHistory;
        public ScopePlotView? ScopeView;
        public SfraPlotView? SfraView;
        public int SfraConfigGeneration;
        public bool SfraConfigLoaded;
        public TextBlock ScopeStatus=new(){Text="状态：未查询",VerticalAlignment=VerticalAlignment.Center,Margin=new Thickness(8,0,0,8)};
        public readonly Dictionary<ulong,(int ObjectId,string Action)> ScopeActions=new();
        public readonly Dictionary<int,string> ScopeStates=new();
        public readonly Dictionary<int,long> ScopePollDue=new();
        public readonly List<ScopeCapture> ScopeCaptures=new();
        public readonly Dictionary<ulong,int> ScopeRequests=new();
        public CheckBox SendText { get; }=new(){Content="使用 UTF-8 文本发送",Margin=new Thickness(8)};
        public CheckBox SendNewline { get; }=new(){Content="追加 CRLF",Margin=new Thickness(8)};
        public CheckBox ReceiveText { get; }=new(){Content="接收显示 UTF-8 文本",Margin=new Thickness(8)};
        public TextBox ReceiveLog { get; }=new(){IsReadOnly=true,AcceptsReturn=true,TextWrapping=TextWrapping.Wrap,VerticalScrollBarVisibility=ScrollBarVisibility.Auto,FontFamily=new System.Windows.Media.FontFamily("Consolas"),Margin=new Thickness(0)};
        public bool SerialCleared;
        public CheckBox Pause { get; } = new(){Content="暂停显示",Margin=new Thickness(8),ToolTip="只冻结显示，设备采集与文件保存继续"};
        public CheckBox Follow { get; } = new() { Content = "跟随最新数据", IsChecked = true, Margin = new Thickness(8) };
        public TextBlock Cursor { get; } = new() { Margin = new Thickness(8), Text = "移动鼠标查看坐标；滚轮缩放，拖动平移" };
        public TextBox HistoryOffset { get; } = new() { Text="0", Width=75, Margin=new Thickness(4), ToolTip="关闭跟随后，从此历史记录偏移读取最多 10000 条" };
        public ulong Dataset;
        public ulong ResumeDataset;
        public Button? CaptureButton;
        public ulong CaptureJob;
        public bool Stopping;
        public bool WaveViewRefresh, WaveShowAll;
        public ulong WaveGeneration;
        public JsonArray Records { get; set; } = new();
    }

    public MainWindow() : this(System.IO.Path.Combine(DesktopSettings.DataDirectory,"config/native-ui.json")) { }
    public MainWindow(string? settingsPath)
    {
        this.settingsPath=settingsPath;
        InitializeComponent();
        Title=$"FRAME v{typeof(MainWindow).Assembly.GetName().Version!.ToString(3)}";
        CreatePages();
        string[] navigationIcons=[
            "M2,6 L20,6 M15,1 L20,6 L15,11 M22,18 L4,18 M9,13 L4,18 L9,23",
            "M3,2 L3,22 M12,2 L12,22 M21,2 L21,22 M0,8 L6,8 M9,16 L15,16 M18,6 L24,6",
            "M1,12 L5,12 L8,3 L12,21 L16,7 L19,12 L23,12",
            "M2,2 L22,2 L22,22 L2,22 Z M4,14 L8,14 L8,7 L14,7 L14,17 L20,17",
            "M2,2 L2,22 L23,22 M4,6 L10,6 L14,10 L18,17 L22,19",
            "M2,22 L23,22 M5,20 L5,12 L8,12 L8,20 M12,20 L12,4 L15,4 L15,20 M19,20 L19,8 L22,8 L22,20",
            "M2,4 L8,4 L8,10 L15,10 L15,17 L22,17 M2,22 L22,22",
            "M1,3 L7,3 L7,9 L1,9 Z M9,15 L15,15 L15,21 L9,21 Z M17,3 L23,3 L23,9 L17,9 Z M7,6 L12,6 L12,15 M15,18 L20,18 L20,9",
            "M5,5 L19,5 L19,19 L5,19 Z M9,9 L15,9 L15,15 L9,15 Z M8,1 L8,5 M16,1 L16,5 M8,19 L8,23 M16,19 L16,23 M1,8 L5,8 M1,16 L5,16 M19,8 L23,8 M19,16 L23,16"
        ];
        Navigation.ItemsSource = pages.Values.Select((p,i) => new NavigationItem(p.Title,navigationIcons[i])).ToArray();
        Navigation.SelectedIndex = 0;
        InitializePageDocking();
        Baud.ItemsSource=new[]{"1200","2400","4800","9600","14400","19200","38400","57600","115200","128000","230400","256000","460800","500000","576000","921600","1000000","自定义…"};
        RestoreSettings();
        lastBaud=Baud.Text;initializingConnection=false;
        timer.Tick += async (_, _) => await UpdateAsync();
        timer.Start();
        Closing += OnClosing;
        Loaded += async (_, _) => await RefreshPortsAsync();
    }

    private PageState Page(string key, string title, string hint, bool chart = false)
    {
        var p = new PageState(key, title, hint); pages.Add(key, p);
        if (chart)
        {
            p.Plot = new WpfPlot();
            p.Body.RowDefinitions.Add(new() { Height = GridLength.Auto });
            p.Body.RowDefinitions.Add(new() { Height = new GridLength(2, GridUnitType.Star) });
            p.Body.RowDefinitions.Add(new() { Height = new GridLength(1, GridUnitType.Star) });
            var bar = new WrapPanel();
            if(key!="wave")bar.Children.Add(p.Pause);
            if(key!="wave"){var live=new Button{Content="回到实时"};live.Click+=(_,_)=>{p.Pause.IsChecked=false;p.Follow.IsChecked=true;};bar.Children.Add(live);}
            if(key!="wave")bar.Children.Add(p.Follow);
            if(key!="wave"){bar.Children.Add(new TextBlock{Text="历史起点",VerticalAlignment=VerticalAlignment.Center});bar.Children.Add(p.HistoryOffset);}
            if(key!="wave")bar.Children.Add(p.Cursor);
            var fit = new Button { Content = "全图" }; fit.Click += (_, _) => {
                if(key=="wave"&&p.Dataset!=0){p.WaveShowAll=true;p.WaveViewRefresh=true;p.Follow.IsChecked=true;}
                else {p.Plot.Plot.Axes.AutoScale();p.Plot.Refresh();}
            }; bar.Children.Add(fit);
            if(key is not ("scope" or "sfra"))p.Body.Children.Add(bar); Grid.SetRow(p.Plot, 1); p.Body.Children.Add(p.Plot);
            if(key is not ("wave" or "scope" or "sfra")){
            p.Plot.MouseWheel += (_, _) => {p.Follow.IsChecked=false;p.WaveViewRefresh=true;};
            p.Plot.MouseDown += (_, _) => p.Follow.IsChecked = false;
            p.Plot.MouseUp += (_, _) => p.WaveViewRefresh=true;
            ScottPlot.Plottables.Crosshair? crosshair=null;
            p.Plot.MouseMove += (_, e) =>
            {
                var point = e.GetPosition(p.Plot);
                var dpi = System.Windows.Media.VisualTreeHelper.GetDpi(p.Plot);
                var xy = p.Plot.Plot.GetCoordinates(new ScottPlot.Pixel((float)(point.X * dpi.DpiScaleX), (float)(point.Y * dpi.DpiScaleY)));
                p.Cursor.Text = $"X = {xy.X:G6}   Y = {xy.Y:G6}";
                if(crosshair!=null)p.Plot.Plot.Remove(crosshair);
                crosshair=p.Plot.Plot.Add.Crosshair(xy.X,xy.Y);p.Plot.Refresh();
            };
            }
            if (key == "sfra")
            {
                p.Phase = new WpfPlot();p.Body.Children.Remove(p.Plot);p.SfraView=new SfraPlotView(p.Plot,p.Phase);p.SfraView.ViewChanged+=()=>p.Follow.IsChecked=false;p.Body.RowDefinitions.Clear();p.Body.Children.Add(p.SfraView);
                p.Phase.MouseWheel += (_, _) => p.Follow.IsChecked = false;
                p.Phase.MouseDown += (_, _) => p.Follow.IsChecked = false;
            }
            else if(key=="wave")
            {
                p.Body.Children.Remove(p.Plot);p.Body.RowDefinitions.RemoveAt(2);p.Body.RowDefinitions[1].Height=new GridLength(1,GridUnitType.Star);
                var content=new Grid();content.ColumnDefinitions.Add(new(){Width=new GridLength(340),MinWidth=240});content.ColumnDefinitions.Add(new(){Width=new GridLength(6)});content.ColumnDefinitions.Add(new(){Width=new GridLength(1,GridUnitType.Star),MinWidth=200});
                p.WavePlots=new WavePlotPanel(p.Plot);p.Series=new WaveSeriesPanel();p.Series.AttachPlots(p.WavePlots);
                p.WavePlots.ActiveChanged+=plot=>p.Plot=plot;
                p.WavePlots.ViewChanged+=()=>{p.Follow.IsChecked=false;p.WaveViewRefresh=true;};
                p.WavePlots.CursorChanged+=text=>{p.Cursor.Text=text;WaveCursor.Text=text;};
                p.WavePlots.Changed+=()=>Draw(p);p.Series.SelectionChanged+=()=>Draw(p);
                content.Children.Add(p.Series);var splitter=new GridSplitter{Width=6,HorizontalAlignment=HorizontalAlignment.Stretch,VerticalAlignment=VerticalAlignment.Stretch};Grid.SetColumn(splitter,1);content.Children.Add(splitter);
                Grid.SetColumn(p.WavePlots,2);content.Children.Add(p.WavePlots);Grid.SetRow(content,1);p.Body.Children.Add(content);
                var add=new Button{Content="增加波形框"};add.Click+=(_,_)=>p.WavePlots.AddPlot();bar.Children.Insert(0,add);
                var fitY=new Button{Content="自适应 Y 轴",ToolTip="按当前框的可见曲线调整纵轴，保持时间范围"};fitY.Click+=(_,_)=>p.WavePlots.FitY();bar.Children.Add(fitY);
                var measure=new Button{Content="测量时间差",ToolTip="依次点击两个时间位置，显示 Δt；再次点击按钮重新测量，Esc 清除测量"};
                measure.Click+=(_,_)=>p.WavePlots.BeginTimeMeasurement();bar.Children.Add(measure);
                var clearMeasurement=new Button{ToolTip="清除测量",Content=new System.Windows.Shapes.Path{Data=System.Windows.Media.Geometry.Parse("M 3,11 L 12,2 L 21,11 L 13,19 L 9,19 Z M 7,7 L 17,15 M 9,19 L 22,19"),Stroke=System.Windows.Media.Brushes.SlateGray,StrokeThickness=1.6,Stretch=System.Windows.Media.Stretch.Uniform,Width=18,Height=18}};
                System.Windows.Automation.AutomationProperties.SetName(clearMeasurement,"清除测量");System.Windows.Automation.AutomationProperties.SetAutomationId(clearMeasurement,"wave_clear_measurement");
                clearMeasurement.Click+=(_,_)=>{p.WavePlots.ClearTimeMeasurement();Feedback.Text="测量已清除";};bar.Children.Add(clearMeasurement);
                p.WavePlots.MeasurementChanged+=text=>{measure.ToolTip=string.IsNullOrEmpty(text)?"依次点击两个时间位置测量 Δt":text;Feedback.Text=text;};
                var clear=new Button{Content="清除波形",ToolTip="清除当前波形数据，保留连接、采集和曲线分配"};
                clear.Click+=async(_,_)=>{
                    clear.IsEnabled=false;
                    try {
                        if(p.Dataset!=0){
                            var result=await client.ExecuteAsync(new(){["group"]="data",["action"]="clear",["dataset"]=p.Dataset});
                            if(result["ok"]?.GetValue<bool>()!=true)throw new InvalidOperationException(result["error"]?.ToString());
                            p.WaveGeneration=result["data"]!["generation"]!.GetValue<ulong>();
                        }
                        ResetWaveDisplay(p);Feedback.Text="波形已清除";
                    }catch(Exception error){Feedback.Text=error.Message;}
                    finally{clear.IsEnabled=true;}
                };bar.Children.Add(clear);
                AlignWaveToolbar(bar);
                clearMeasurement.MinWidth=34;clearMeasurement.Width=34;clearMeasurement.Padding=new Thickness(0);
            }
            else if(key=="scope"){p.Body.Children.Remove(p.Plot);p.ScopeView=new ScopePlotView(p.Plot);Grid.SetRow(p.ScopeView,1);p.Body.Children.Add(p.ScopeView);p.Body.RowDefinitions.RemoveAt(2);p.Body.RowDefinitions[1].Height=new GridLength(1,GridUnitType.Star);}
            else { Grid.SetRow(p.Table, 2); p.Body.Children.Add(p.Table); }
        }
        else if(key=="jlink")
        {
            p.Body.ColumnDefinitions.Add(new(){Width=new GridLength(320)});p.Body.ColumnDefinitions.Add(new(){Width=new GridLength(1,GridUnitType.Star)});
            p.Symbols=new TreeView{Margin=new Thickness(0,0,12,0)};p.Body.Children.Add(p.Symbols);Grid.SetColumn(p.Table,1);p.Body.Children.Add(p.Table);
            p.Symbols.SelectedItemChanged+=(_,_)=>{if(p.Symbols.SelectedItem is TreeViewItem item&&item.Tag is string name)p.Fields["name"].Text=name;};
        }
        else p.Body.Children.Add(p.Table);
        p.Table.SelectionChanged += (_, _) =>
        {
            if (p.Table.SelectedItem is not DataRowView row) return;
            foreach (string name in new[] { "name", "value" })
                if (p.Fields.TryGetValue(name, out var field) && row.Row.Table.Columns.Contains(name)) field.Text = row[name].ToString() ?? "";
            if (p.Key == "section" && row.Row.Table.Columns.Contains("list_id")) p.Fields["id"].Text = row["list_id"].ToString()!;
        };
        return p;
    }

    private void Fields(PageState p, params (string Key, string Label, string Default)[] fields)
    {
        var wrap = new WrapPanel(); p.Form.Children.Add(wrap);
        foreach (var field in fields)
        {
            var stack = new StackPanel(); stack.Children.Add(new TextBlock { Text = field.Label, Foreground = System.Windows.Media.Brushes.SlateGray });
            var input = new TextBox { Text = field.Default, Width = field.Key is "elf" or "output" ? 320 : 150, ToolTip = field.Label };
            System.Windows.Automation.AutomationProperties.SetAutomationId(input, p.Key + "_" + field.Key);
            p.Fields.Add(field.Key, input); stack.Children.Add(input); wrap.Children.Add(stack);
        }
    }

    private void Actions(PageState p, params (string Action, string Label)[] actions)
    {
        var wrap = p.Key=="wave"?(WrapPanel)p.Form.Children[0]:new WrapPanel(); if(p.Key!="wave")p.Form.Children.Add(wrap);
        foreach (var action in actions)
        {
            var button = new Button { Content = action.Label, Tag = action.Action };
            System.Windows.Automation.AutomationProperties.SetAutomationId(button, p.Key + "_" + action.Action);
            if(p.Key=="wave"&&action.Action=="capture"){
                p.CaptureButton=button;button.Width=76;
                button.Click+=async(_,_)=>await RunPageAsync(p,p.CaptureJob!=0?"stop":"capture");
            }else button.Click += async (_, _) => await RunPageAsync(p, action.Action);
            wrap.Children.Add(button);
        }
    }

    private static void AlignWaveToolbar(Panel panel)
    {
        foreach(FrameworkElement item in panel.Children){
            item.Height=32;item.VerticalAlignment=VerticalAlignment.Center;item.Margin=new Thickness(0,0,8,8);
            if(item is Button button){button.MinWidth=76;button.Padding=new Thickness(12,0,12,0);}
            if(item is TextBox text)text.Padding=new Thickness(6,4,6,4);
            if(item is ComboBox combo)combo.Padding=new Thickness(6,4,6,4);
            if(item is CheckBox check)check.VerticalContentAlignment=VerticalAlignment.Center;
            if(item is TextBlock){item.Height=double.NaN;item.Margin=new Thickness(0,0,6,8);}
        }
    }

    private void CreatePages()
    {
        var p = Page("serial", "串口调试", "独占串口 · HEX 收发 · 定时发送与接收保存");
        Fields(p, ("hex", "发送 HEX", ""), ("text", "发送文本 / UTF-8", ""), ("duration", "接收时长 / 秒", "1"), ("interval", "重复间隔 / 秒（0 禁用）", "0"), ("output", "接收保存路径（可选）", ""));
        var serial=p;var serialOptions=new WrapPanel();serialOptions.Children.Add(p.SendText);serialOptions.Children.Add(p.SendNewline);serialOptions.Children.Add(p.ReceiveText);p.Form.Children.Add(serialOptions);
        p.ReceiveText.Checked+=(_,_)=>RenderSerial(serial);p.ReceiveText.Unchecked+=(_,_)=>RenderSerial(serial);
        p.Body.Children.Clear();p.Body.Children.Add(p.ReceiveLog);
        Actions(p, ("send", "发送并接收"), ("raw", "接收"), ("stop", "停止接收"), ("clear-view", "清空显示"), ("export", "导出接收数据…"));
        p = Page("param", "参数读写", "读取设备字典后选择参数；写入由后端校验类型、范围并回读确认。");
        p.Parameters = new ParameterPanel(async request => await client.ExecuteAsync(request), message => Feedback.Text=message,(request,progress)=>client.ExecuteAsync(request,progress:progress));
        p.Parameters.WaveSelectionChanged+=names=>pages["wave"].Series!.SetSelectedParameters(names);
        p.Parameters.WaveParameterEnabled+=name=>pages["wave"].Series!.Select(name);
        p.Body.Children.Clear(); p.Body.Children.Add(p.Parameters);
        p = Page("wave", "参数波形", "在参数页双击名称加入波形（绿色），再次双击移出；此处勾选只控制曲线显示。", true);
        var waveControls=new WrapPanel();p.Form.Children.Add(waveControls);
        var wavePage=p;
        foreach(var field in new[]{("period","周期 ms","10"),("window","窗口 s","30")}){
            waveControls.Children.Add(new TextBlock{Text=field.Item2,VerticalAlignment=VerticalAlignment.Center,Margin=new Thickness(4,0,6,6)});
            var input=new TextBox{Text=field.Item3,Width=65,ToolTip=field.Item1=="window"?"只控制显示范围；0 为全部历史，不停止采集":"设备上报周期（毫秒）"};
            System.Windows.Automation.AutomationProperties.SetAutomationId(input,"wave_"+field.Item1);p.Fields.Add(field.Item1,input);waveControls.Children.Add(input);
            if(field.Item1=="window"){
                input.Visibility=Visibility.Collapsed;
                var presets=new ComboBox{Width=110,ItemsSource=new[]{"最近10秒","最近30秒","最近1分钟","最近10分钟","自定义","全部"},SelectedIndex=1};waveControls.Children.Insert(waveControls.Children.Count-1,presets);
                p.WaveWindowPreset=presets;
                presets.SelectionChanged+=(_,_)=>{
                    input.Visibility=presets.SelectedIndex==4?Visibility.Visible:Visibility.Collapsed;
                    if(presets.SelectedIndex!=4)input.Text=new[]{"10","30","60","600","30","0"}[presets.SelectedIndex];
                    wavePage.Pause.IsChecked=false;wavePage.Follow.IsChecked=true;
                    if(presets.SelectedIndex==5){wavePage.WaveShowAll=true;wavePage.WaveViewRefresh=true;}
                };
            }
        }
        p.Fields.Add("output",new TextBox());
        p.Fields["period"].KeyDown+=async(_,e)=>{if(e.Key==System.Windows.Input.Key.Enter){e.Handled=true;await RunPageAsync(wavePage,"period");}};
        Actions(p, ("capture", "开始"), ("export", "导出…"), ("open-data", "打开…"));
        AlignWaveToolbar(waveControls);
        p = Page("scope", "Scope 录波", "设备环形录波 · 启动 → 触发 → 查询就绪 → 拉取。数据按采样顺序显示。", true);
        p.Fields.Add("id",new TextBox{Text="0"});var scopePage=p;
        var objectBar=new WrapPanel();objectBar.Children.Add(new TextBlock{Text="对象",VerticalAlignment=VerticalAlignment.Center,Margin=new Thickness(0,0,8,8)});
        p.ScopeObjects=new ComboBox{Width=280,Height=32,Margin=new Thickness(0,0,8,8),DisplayMemberPath="Label",SelectedValuePath="Id",ToolTip="点击获取对象刷新，然后选择录波对象"};objectBar.Children.Add(p.ScopeObjects);p.Form.Children.Add(objectBar);
        p.ScopeObjects.SelectionChanged+=(_,_)=>{if(scopePage.ScopeObjects!.SelectedItem is ScopeObject item)scopePage.Fields["id"].Text=item.Id.ToString(CultureInfo.InvariantCulture);RefreshScopeHistory(scopePage);};
        objectBar.Children.Add(new TextBlock{Text="录波记录",VerticalAlignment=VerticalAlignment.Center,Margin=new Thickness(0,0,8,8)});
        p.ScopeHistory=new ComboBox{Width=250,Height=32,Margin=new Thickness(0,0,8,8),DisplayMemberPath="Label",ToolTip="切换当前对象已缓存的录波"};objectBar.Children.Add(p.ScopeHistory);
        p.ScopeHistory.SelectionChanged+=(_,_)=>SelectScopeCapture(scopePage);
        var getObjects=new Button{Content="获取对象",Height=32};objectBar.Children.Add(getObjects);
        getObjects.Click+=async(_,_)=>{getObjects.IsEnabled=false;try{var result=await client.ExecuteAsync(new(){["group"]="scope",["action"]="list"});if(result["ok"]!.GetValue<bool>()&&result["data"] is JsonArray objects){ApplyScopeObjects(scopePage,objects);Feedback.Text=$"已获取 {objects.Count} 个录波对象";}else Feedback.Text=result["error"]?.ToString()??"获取对象失败";}catch(Exception error){Feedback.Text=error.Message;}finally{getObjects.IsEnabled=true;}};
        Actions(p, ("channels", "通道"), ("start", "启动"), ("trigger", "触发"), ("pull", "拉取录波"), ("stop", "停止"), ("reset", "复位"), ("export", "导出…"), ("open-data", "打开数据…"));
        var scopeButtons=(WrapPanel)p.Form.Children[p.Form.Children.Count-1];p.Form.Children.Remove(scopeButtons);var scopeBar=new DockPanel();p.Form.Children.Add(scopeBar);
        var statusArea=new StackPanel{Orientation=Orientation.Horizontal};DockPanel.SetDock(statusArea,Dock.Right);scopeBar.Children.Add(statusArea);
        var statusButton=new Button{Content="状态"};statusButton.Click+=async(_,_)=>await RunPageAsync(scopePage,"info");statusArea.Children.Add(statusButton);statusArea.Children.Add(p.ScopeStatus);scopeBar.Children.Add(scopeButtons);
        p = Page("sfra", "SFRA", "软件扫频分析 · 上图幅值 dB，下图相位 °；配置与运行状态均来自设备。", true);
        p.Fields.Add("id",new TextBox{Text="0"});var sfraPage=p;
        var sfraSelector=new DockPanel();p.Form.Children.Add(sfraSelector);
        var sfraStatus=new StackPanel{Orientation=Orientation.Horizontal};DockPanel.SetDock(sfraStatus,Dock.Right);sfraSelector.Children.Add(sfraStatus);var sfraInfo=new Button{Content="状态"};sfraInfo.Click+=async(_,_)=>await RunPageAsync(sfraPage,"info");sfraStatus.Children.Add(sfraInfo);sfraStatus.Children.Add(p.ScopeStatus);
        var sfraChoices=new WrapPanel();sfraSelector.Children.Add(sfraChoices);
        p.ScopeObjects=new ComboBox{Width=220,Height=32,DisplayMemberPath="Label",SelectedValuePath="Id",Margin=new Thickness(0,0,8,8),ToolTip="扫频对象"};sfraChoices.Children.Add(p.ScopeObjects);
        p.ScopeHistory=new ComboBox{Width=220,Height=32,DisplayMemberPath="Label",Margin=new Thickness(0,0,8,8),ToolTip="已缓存的扫频记录"};sfraChoices.Children.Add(p.ScopeHistory);
        p.ScopeObjects.SelectionChanged+=async(_,_)=>{if(sfraPage.ScopeObjects!.SelectedItem is ScopeObject item)sfraPage.Fields["id"].Text=item.Id.ToString();RefreshScopeHistory(sfraPage);await ReadSfraConfigAsync(sfraPage);};p.ScopeHistory.SelectionChanged+=(_,_)=>SelectScopeCapture(sfraPage);
        var sfraGet=new Button{Content="获取对象"};sfraChoices.Children.Add(sfraGet);sfraGet.Click+=async(_,_)=>{sfraGet.IsEnabled=false;try{var result=await client.ExecuteAsync(new(){["group"]="sfra",["action"]="list"});if(result["ok"]!.GetValue<bool>())ApplyScopeObjects(sfraPage,result["data"]!.AsArray());else Feedback.Text=result["error"]?.ToString();}catch(Exception error){Feedback.Text=error.Message;}finally{sfraGet.IsEnabled=true;}};
        Fields(p, ("start_hz", "起始频率 / Hz", ""), ("stop_hz", "终止频率 / Hz", ""), ("amplitude", "注入幅度", ""));
        foreach(var key in new[]{"start_hz","stop_hz","amplitude"})p.Fields[key].IsEnabled=false;
        Actions(p, ("configure", "应用配置"), ("start", "启动"), ("stop", "停止"), ("reset", "复位"), ("export", "导出…"), ("open-data", "打开数据…"));
        var sfraFit=new Button{Content="窗口自适应",ToolTip="按当前扫频数据调整幅频、相频范围，并同步频率轴"};
        sfraFit.Click+=(_,_)=>{sfraPage.Follow.IsChecked=true;sfraPage.SfraView!.FitWindow();};
        ((WrapPanel)p.Form.Children[p.Form.Children.Count-1]).Children.Add(sfraFit);
        var sfraFields=(WrapPanel)p.Form.Children[1];var sfraActions=(WrapPanel)p.Form.Children[2];
        var applyConfig=sfraActions.Children.OfType<Button>().Single(button=>button.Tag?.ToString()=="configure");sfraActions.Children.Remove(applyConfig);
        p.Form.Children.Clear();var sfraHeader=new Grid();sfraHeader.ColumnDefinitions.Add(new(){Width=new GridLength(1,GridUnitType.Star)});sfraHeader.ColumnDefinitions.Add(new(){Width=GridLength.Auto});p.Form.Children.Add(sfraHeader);
        var sfraLeft=new StackPanel();sfraLeft.Children.Add(sfraSelector);sfraLeft.Children.Add(sfraActions);sfraHeader.Children.Add(sfraLeft);
        var sfraRight=new StackPanel{Margin=new Thickness(16,0,0,0)};Grid.SetColumn(sfraRight,1);sfraHeader.Children.Add(sfraRight);
        foreach(var key in new[]{"start_hz","stop_hz","amplitude"})p.Fields[key].Width=110;
        sfraRight.Children.Add(sfraFields);
        var sfraFooter=new DockPanel();DockPanel.SetDock(applyConfig,Dock.Right);sfraFooter.Children.Add(applyConfig);
        var pointCount=new TextBox{Text="",Width=72,IsReadOnly=true,IsEnabled=false,ToolTip="设备上报的扫频总点数；当前协议不支持修改点数"};
        System.Windows.Automation.AutomationProperties.SetAutomationId(pointCount,"sfra_count");p.Fields.Add("count",pointCount);
        var pointSetting=new StackPanel{Orientation=Orientation.Horizontal};pointSetting.Children.Add(new TextBlock{Text="扫频点数",VerticalAlignment=VerticalAlignment.Center,Margin=new Thickness(0,0,8,8)});pointSetting.Children.Add(pointCount);sfraFooter.Children.Add(pointSetting);sfraRight.Children.Add(sfraFooter);
        foreach(var (key,title) in new[]{("perf","Perf"),("trace","Trace"),("section","链表顺序"),("jlink","J-Link")}){
            p=Page(key,title,"");p.Body.Children.Clear();p.Body.ColumnDefinitions.Clear();p.Symbols=null;
            p.Diagnostic=key switch{
                "perf"=>new PerfPage(client,p.Fields,text=>Feedback.Text=text),
                "trace"=>new TracePage(client,p.Fields,text=>Feedback.Text=text),
                "section"=>new SectionPage(client,p.Fields,text=>Feedback.Text=text),
                _=>new JlinkPage(client,p.Fields,text=>Feedback.Text=text)};
            p.Body.Children.Add(p.Diagnostic);
        }
    }

    private async Task ReadSfraConfigAsync(PageState p)
    {
        int generation=++p.SfraConfigGeneration;p.SfraConfigLoaded=false;
        foreach(var key in new[]{"start_hz","stop_hz","amplitude","count"}){p.Fields[key].Text="";p.Fields[key].IsEnabled=false;}
        if(p.ScopeObjects?.SelectedItem is not ScopeObject selected)return;
        try{
            var result=await client.ExecuteAsync(new(){["group"]="sfra",["action"]="info",["id"]=selected.Id});
            if(generation!=p.SfraConfigGeneration)return;
            if(result["ok"]?.GetValue<bool>()!=true)throw new InvalidOperationException(result["error"]?.ToString()??"设备配置读取失败");
            ApplySfraConfig(p,result["data"]!.AsObject());Feedback.Text="已读取设备的扫频频率、注入幅度和点数";
        }catch(Exception error){if(generation==p.SfraConfigGeneration)Feedback.Text="读取 SFRA 配置失败："+error.Message;}
    }
    private static void ApplySfraConfig(PageState p,JsonObject info)
    {
        var values=new[]{info["start_hz"]!.GetValue<double>(),info["stop_hz"]!.GetValue<double>(),info["amplitude"]!.GetValue<double>()};
        if(values.Any(value=>!double.IsFinite(value)))throw new InvalidOperationException("设备返回了无效的扫频配置");
        string[] keys={"start_hz","stop_hz","amplitude"};for(int i=0;i<keys.Length;i++){p.Fields[keys[i]].Text=values[i].ToString("G9",CultureInfo.InvariantCulture);p.Fields[keys[i]].IsEnabled=true;}
        p.Fields["count"].Text=info["count"]?.ToString()??"";p.Fields["count"].IsEnabled=info["count"]!=null;p.SfraConfigLoaded=true;
    }
    private sealed record ScopeObject(int Id,string Label);
    private sealed record ScopeCapture(int ObjectId,ulong Dataset,JsonArray Records,string Label){public JsonObject? Metadata{get;init;}}
    private static void SelectScopeCapture(PageState p)
    {
        var capture=p.ScopeHistory?.SelectedItem as ScopeCapture;
        if(p.ScopeView!=null)p.ScopeView.TriggerMetadata=capture?.Metadata;
        p.Dataset=capture?.Dataset??0;p.Records=capture?.Records??new JsonArray();p.Follow.IsChecked=true;p.Pause.IsChecked=false;
        Draw(p);
    }
    private static void RefreshScopeHistory(PageState p)
    {
        if(p.ScopeHistory==null)return;
        var id=(p.ScopeObjects?.SelectedItem as ScopeObject)?.Id;
        p.ScopeStatus.Text="状态："+(id.HasValue&&p.ScopeStates.TryGetValue(id.Value,out var status)?status:"未查询");
        p.ScopeHistory.ItemsSource=p.ScopeCaptures.Where(c=>c.ObjectId==id).ToArray();
        p.ScopeHistory.SelectedIndex=p.ScopeHistory.Items.Count-1;
        if(p.ScopeHistory.SelectedIndex<0)SelectScopeCapture(p);
    }
    private static void ApplyScopeObjects(PageState p,JsonArray objects)
    {
        int.TryParse(p.Fields["id"].Text,out int previous);
        var choices=objects.OfType<JsonObject>().Select(row=>new ScopeObject(row["id"]!.GetValue<int>(),$"{row["id"]} · {row["name"]}")).ToArray();
        p.ScopeObjects!.ItemsSource=choices;
        p.ScopeObjects.SelectedItem=choices.FirstOrDefault(item=>item.Id==previous)??choices.FirstOrDefault();
    }

    private async Task RunPageAsync(PageState p, string action)
    {
        if (closing) return;
        try
        {
            if(p.Key=="sfra"&&action=="configure"&&!p.SfraConfigLoaded)throw new ArgumentException("请先获取对象并成功读取设备配置");
            if(p.Key is "scope" or "sfra"&&action is not ("export" or "open-data" or "list")&&p.ScopeObjects?.SelectedItem==null)throw new ArgumentException("请先获取并选择对象");
            if(action=="clear-view"){p.SerialCleared=true;p.ReceiveLog.Clear();Feedback.Text="已清空显示，原始接收数据仍可导出";return;}
            if(p.Key=="serial"&&action=="stop"){foreach(var pending in jobs.Where(x=>x.Value.Page==p))client.Cancel(pending.Key);return;}
            if (action is "browse" or "open-data")
            {
                var dialog = new OpenFileDialog { Filter = action == "browse" ? "符号文件|*.elf;*.map|所有文件|*.*" : "FRAME 数据|*.json" };
                if (dialog.ShowDialog(this) != true) return;
                if (action == "browse") { p.Fields["elf"].Text = dialog.FileName; return; }
                var data = JsonNode.Parse(await System.IO.File.ReadAllTextAsync(dialog.FileName))!;
                if (data["group"]?.GetValue<string>() != p.Key) throw new ArgumentException("数据类型与当前页面不符");
                if(jobs.Values.Any(j=>j.Page==p))throw new ArgumentException("请先停止当前页面的任务，再打开历史文件");
                if(p.Series!=null&&data["records"] is JsonArray savedRecords)p.Series.SetSelectedParameters(savedRecords.OfType<JsonObject>().Where(r=>r["name"]!=null).Select(r=>r["name"]!.ToString()).Distinct().ToArray());
                p.Dataset=0;p.Pause.IsChecked=false;
                if(p.Key=="wave"){p.WaveGeneration=data?["generation"]?.GetValue<ulong>()??0;ResetWaveDisplay(p);}
                ShowData(p, data); Feedback.Text = "已打开 " + dialog.FileName; return;
            }
            JsonObject request = new() { ["group"] = p.Key, ["action"] = action, ["timeout"] = 60000 };
            if(p.Key is "wave" or "trace" && action=="capture")request.Remove("timeout");
            foreach (var pair in p.Fields)
            {
                if(p.Key=="sfra"&&pair.Key=="count")continue;
                if(p.Key=="wave"&&pair.Key=="window")continue;
                string value = pair.Value.Text.Trim(); if (value.Length == 0) continue;
                request[pair.Key] = pair.Key switch
                {
                    "id" or "period" or "probe" => JsonValue.Create(int.Parse(value, CultureInfo.InvariantCulture)),
                    "duration" or "interval" or "start_hz" or "stop_hz" or "amplitude" => JsonValue.Create(double.Parse(value, CultureInfo.InvariantCulture)),
                    "filter" when p.Key == "perf" => JsonValue.Create(int.Parse(value, CultureInfo.InvariantCulture)),
                    _ => JsonValue.Create(value)
                };
            }
            if(p.Key=="serial")
            {
                request.Remove("text");
                if(action=="raw")request.Remove("hex");
                else if(action=="send"&&p.SendText.IsChecked==true){request.Remove("hex");request["text"]=p.Fields["text"].Text+(p.SendNewline.IsChecked==true?"\r\n":"");}
                else if(action=="send"&&p.SendNewline.IsChecked==true)request["hex"]=(request["hex"]?.ToString()??"")+"0D0A";
                if(action is "raw" or "send"){request.Remove("timeout");p.SerialCleared=false;}
            }
            if (action.StartsWith("report-")) { request["action"] = "report"; request["enable"] = action == "report-on"; }
            if (action.StartsWith("batch-"))
            {
                var input = new OpenFileDialog { Filter = "批量参数 JSON|*.json" }; if (input.ShowDialog(this) != true) return; request["input"] = input.FileName;
            }
            if (action == "export")
            {
                if (p.Dataset == 0) throw new ArgumentException("当前会话尚无可导出的采集数据");
                var save = new SaveFileDialog { Filter = "FRAME JSON|*.json|CSV|*.csv", FileName = p.Key + "-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") };
                if (save.ShowDialog(this) != true) return;
                request = new() { ["group"] = "data", ["action"] = "export", ["dataset"] = p.Dataset, ["output"] = save.FileName };
            }
            if(p.Key=="wave"&&action=="capture")
            {
                if(jobs.Values.Any(j=>j.Page==p))throw new ArgumentException("参数波形正在采集，请先停止");
                pages["param"].Parameters!.RefreshWaveSelection();
                request["duration"]=0;
                if(!request.ContainsKey("output")){
                    string directory=System.IO.Path.Combine(DesktopSettings.DataDirectory,"exports");
                    System.IO.Directory.CreateDirectory(directory);
                    request["output"]=System.IO.Path.Combine(directory,"wave-"+DateTime.Now.ToString("yyyyMMdd-HHmmss-fff")+".json");
                }
                p.ResumeDataset=p.Dataset;
                if(p.Dataset!=0)request["resume_dataset"]=p.Dataset;
                p.Follow.IsChecked=true;p.WaveShowAll=false;p.WaveViewRefresh=false;
                if(p.Dataset==0){p.WaveGeneration=0;p.WavePlots!.ResetView();}
            }
            var job = client.Submit(request); jobs.Add(job.Id, (job, p));
            if(p.Key is "scope" or "sfra"){
                int objectId=int.Parse(p.Fields["id"].Text,CultureInfo.InvariantCulture);p.ScopeActions[job.Id]=(objectId,action);
                if(action is "stop" or "reset" or "pull")p.ScopePollDue.Remove(objectId);
                if(action=="pull"){p.ScopeStates[objectId]="拉取录波中";p.ScopeStatus.Text="状态：拉取录波中";}
            }
            if(p.Key=="scope"&&action=="pull")p.ScopeRequests[job.Id]=int.Parse(p.Fields["id"].Text,CultureInfo.InvariantCulture);
            if(p.Key=="wave"){
                if(action=="capture")p.CaptureJob=job.Id;
                if(action=="stop")p.Stopping=true;
                UpdateCaptureButton(p);
            }
            if (action == "capture" || p.Key=="serial"&&action is "raw" or "send") {p.Dataset = job.Id;p.Pause.IsChecked=false;}
            Feedback.Text = $"{p.Title}：{action}，任务 {job.Id} 已提交";
        }
        catch (Exception e) { Feedback.Text = e.Message; }
    }

    private static void SetTable(PageState p, JsonNode? data)
    {
        var rows = data as JsonArray ?? new JsonArray(data?.DeepClone());
        var table = new DataTable();
        foreach (var row in rows.OfType<JsonObject>()) foreach (var field in row) if (!table.Columns.Contains(field.Key)) table.Columns.Add(field.Key);
        foreach (var row in rows.OfType<JsonObject>()) { var values = table.NewRow(); foreach (var field in row) values[field.Key] = field.Value is JsonValue ? field.Value.ToString() : field.Value?.ToJsonString() ?? ""; table.Rows.Add(values); }
        p.Table.ItemsSource = table.DefaultView;
    }

    private void ResetWaveDisplay(PageState p)
    {
        p.Records=new();p.Series?.SetHoverTime(null);p.Series?.Update(p.Records);
        p.WavePlots?.ClearTimeMeasurement();p.WavePlots?.ResetView();p.WaveShowAll=false;p.WaveViewRefresh=true;
        p.Pause.IsChecked=false;p.Follow.IsChecked=true;WaveCursor.Text="";Draw(p);
    }
    private void ShowData(PageState p, JsonNode? data)
    {
        if (data is null) return;
        if(p.Diagnostic!=null){p.Diagnostic.Apply(data);return;}
        if(p.Pause.IsChecked==true&&!p.WaveViewRefresh)return;
        if(p.Parameters!=null){p.Parameters.Apply(data);return;}
        if (data is JsonObject obj && obj["records"] is JsonArray records)
        {
            if(p.Key=="wave"&&obj["dataset_id"] is JsonNode sourceId&&sourceId.GetValue<ulong>()!=p.Dataset)return;
            if(p.ScopeView!=null)p.ScopeView.TriggerMetadata=obj["metadata"] as JsonObject;
            if(p.Key=="wave"&&obj["generation"] is JsonNode generation){
                ulong current=generation.GetValue<ulong>();
                if(current<p.WaveGeneration)return;
                if(current!=p.WaveGeneration){p.WaveGeneration=current;ResetWaveDisplay(p);return;}
            }
            p.Records = records;if(p.Key!="wave")SetTable(p,records);
            if(p.Key=="serial")RenderSerial(p);
            p.Series?.Update(records,obj["latest_records"] as JsonArray);
            if (p.Plot != null) Draw(p);
        }
        else
        {
            SetTable(p, data);
            if(p.Symbols!=null&&data is JsonArray symbols){p.Symbols.Items.Clear();foreach(var symbol in symbols.OfType<JsonObject>())p.Symbols.Items.Add(SymbolNode(p,symbol));}
        }
    }

    private TreeViewItem SymbolNode(PageState p,JsonObject symbol)
    {
        string name=symbol["name"]?.GetValue<string>()??"?";
        var item=new TreeViewItem{Header=name,Tag=name,ToolTip=symbol.ToJsonString()};
        string kind=symbol["kind"]?.GetValue<string>()??"";
        if(kind is "struct" or "union" or "array")
        {
            item.Items.Add(new TreeViewItem{Header="展开以读取成员"});bool loaded=false;
            item.Expanded+=async (_,e)=>
            {
                e.Handled=true;if(loaded)return;loaded=true;
                try
                {
                    var result=await client.ExecuteAsync(new(){["group"]="jlink",["action"]="expand",["name"]=name,["limit"]=1000});
                    item.Items.Clear();if(!result["ok"]!.GetValue<bool>())throw new Exception(result["error"]!.ToString());
                    foreach(var child in result["data"]!.AsArray().OfType<JsonObject>())item.Items.Add(SymbolNode(p,child));
                }
                catch(Exception error){loaded=false;Feedback.Text=error.Message;}
            };
        }
        return item;
    }

    private static double Number(JsonNode? value) => value == null ? double.NaN : value.GetValue<double>();
    private static void RenderSerial(PageState p)
    {
        if(p.SerialCleared)return;
        // Bound the text control while the backend owns the complete retained data.
        string hex=string.Concat(p.Records.Select(r=>r?["hex"]?.ToString()?.Replace(" ","")));
        if(hex.Length>131072)hex=hex[^131072..];
        string text=p.ReceiveText.IsChecked==true?System.Text.Encoding.UTF8.GetString(Convert.FromHexString(hex)):string.Join(" ",Enumerable.Range(0,hex.Length/2).Select(i=>hex.Substring(i*2,2)));
        if(p.ReceiveLog.Text!=text){p.ReceiveLog.Text=text;p.ReceiveLog.ScrollToEnd();}
    }
    private static void Draw(PageState p)
    {
        if(p.ScopeView!=null){p.ScopeView.Render(p.Records,(p.ScopeObjects?.SelectedItem as ScopeObject)?.Id??-1,p.Follow.IsChecked==true);return;}
        if(p.SfraView!=null){p.SfraView.Render(p.Records,p.Follow.IsChecked==true);return;}
        if(p.WavePlots!=null){p.WavePlots.Render(p.Records,p.Series!,p.Follow.IsChecked==true);return;}
        var plot = p.Plot!; var limits = plot.Plot.Axes.GetLimits(); plot.Plot.Clear();
        if (p.Key == "wave")
        {
            foreach (var group in p.Records.GroupBy(r => r!["name"]?.GetValue<string>() ?? "?"))
            {
                if(p.Series?.IsSeriesVisible(group.Key)==false)continue;
                var rows = group.ToArray(); var scatter = plot.Plot.Add.Scatter(rows.Select(r => Number(r!["time"])).ToArray(), rows.Select(r => Number(r!["value"])).ToArray()); scatter.LegendText = group.Key; scatter.MarkerSize = 0;
            }
            plot.Plot.XLabel("Time (s)"); plot.Plot.YLabel("Value");
        }
        else if (p.Key == "scope" && p.Records.Count > 0)
        {
            int count = p.Records[0]!["values"]!.AsArray().Count;
            for (int i = 0; i < count; i++) { int channel = i; var line = plot.Plot.Add.Scatter(p.Records.Select(r => Number(r!["time"])).ToArray(), p.Records.Select(r => Number(r!["values"]![channel])).ToArray()); line.LegendText = "CH" + i; line.MarkerSize = 0; }
            plot.Plot.XLabel("Time (s)"); plot.Plot.YLabel("Value");
        }
        else if (p.Key == "sfra")
        {
            double[] x = p.Records.Select(r => Number(r!["frequency"])).ToArray();
            plot.Plot.Add.Scatter(x, p.Records.Select(r => Number(r!["db"])).ToArray()); plot.Plot.XLabel("Frequency (Hz)"); plot.Plot.YLabel("Magnitude (dB)");
            var phaseLimits=p.Phase!.Plot.Axes.GetLimits();
            p.Phase.Plot.Clear(); p.Phase.Plot.Add.Scatter(x, p.Records.Select(r => Number(r!["phase"])).ToArray()); p.Phase.Plot.XLabel("Frequency (Hz)"); p.Phase.Plot.YLabel("Phase (degrees)");
            if(p.Follow.IsChecked==true)p.Phase.Plot.Axes.AutoScale();else p.Phase.Plot.Axes.SetLimits(phaseLimits);
            p.Phase.Refresh();
        }
        plot.Plot.ShowLegend();
        if (p.Follow.IsChecked == true) plot.Plot.Axes.AutoScale(); else plot.Plot.Axes.SetLimits(limits);
        plot.Refresh();
    }

    private static void UpdateCaptureButton(PageState p)
    {
        if(p.CaptureButton==null)return;
        p.CaptureButton.Content=p.Stopping?"停止中":p.CaptureJob!=0?"停止":"开始";
        p.CaptureButton.IsEnabled=!p.Stopping;
    }

    private async Task UpdateAsync()
    {
        if (updating || closing || connectionBusy) return; updating = true;
        try
        {
            foreach (var pair in jobs.Where(x => x.Value.Job.Completion.IsCompleted).ToArray())
            {
                var result = await pair.Value.Job.Completion; var p = pair.Value.Page; var data = result["data"];
                Feedback.Text = result["ok"]!.GetValue<bool>() ? $"{p.Title}：完成  {data?.ToJsonString()}" : $"{p.Title}：错误 {result["code"]} · {result["error"]}";
                if(p.Key is "scope" or "sfra"&&p.ScopeActions.Remove(pair.Key,out var scopeAction)){
                    if(result["ok"]!.GetValue<bool>()){
                        if(scopeAction.Action=="channels"&&data is JsonArray channels)p.ScopeView!.SetChannels(scopeAction.ObjectId,channels);
                        string? scopeState=scopeAction.Action=="pull"?"拉取完成":data is JsonObject stateData&&stateData["state"]!=null
                            ?stateData["transition_pending"]?.GetValue<bool>()==true?(scopeAction.Action=="start"?"启动已接受，等待运行":"触发已接受，等待录波"):stateData["ready"]?.GetValue<int>()==1?"录波完成":stateData["state"]!.GetValue<int>() switch{1=>"正在运行",2=>"正在录波",_=>"空闲"}:null;
                        if(p.Key=="sfra"){
                            var info=data?["metadata"] as JsonObject??data as JsonObject;
                            scopeState=info?["done"]?.GetValue<int>()==1?"扫频完成":info?["state"] is JsonNode sfraState?sfraState.GetValue<int>() switch{0=>"空闲",1=>"准备频点",2=>"等待稳定",3=>"正在采样",4=>"计算频点",5=>"扫频完成",_=>"未知状态"}:null;
                            if(scopeAction.Action=="start"&&data?["dataset_id"] is JsonNode liveId){p.ScopeCaptures.Add(new ScopeCapture(scopeAction.ObjectId,liveId.GetValue<ulong>(),new JsonArray(),$"{DateTime.Now:HH:mm:ss} · #{liveId}"));if((p.ScopeObjects?.SelectedItem as ScopeObject)?.Id==scopeAction.ObjectId)RefreshScopeHistory(p);}
                        }
                        if(scopeState!=null)p.ScopeStates[scopeAction.ObjectId]=scopeState;
                        if(p.Key=="scope"&&scopeAction.Action is "start" or "trigger"){
                            if(data?["ready"]?.GetValue<int>()!=1)p.ScopePollDue[scopeAction.ObjectId]=Environment.TickCount64+1000;
                        }
                        if(scopeAction.Action=="info"&&(data?["ready"]?.GetValue<int>()==1||data?["state"]?.GetValue<int>()==0))p.ScopePollDue.Remove(scopeAction.ObjectId);
                        if(scopeAction.Action is "stop" or "reset" or "pull")p.ScopePollDue.Remove(scopeAction.ObjectId);
                    }else {p.ScopeStates[scopeAction.ObjectId]="操作失败："+result["error"];p.ScopePollDue.Remove(scopeAction.ObjectId);}
                    if((p.ScopeObjects?.SelectedItem as ScopeObject)?.Id==scopeAction.ObjectId&&p.ScopeStates.TryGetValue(scopeAction.ObjectId,out var stateText))p.ScopeStatus.Text="状态："+stateText;
                }
                if(p.Key=="scope"&&p.ScopeRequests.Remove(pair.Key,out int objectId)){
                    if(data?["dataset_id"] is JsonNode datasetNode){
                        ulong dataset=datasetNode.GetValue<ulong>();var records=new JsonArray();int total;
                        do{var part=await client.ExecuteAsync(new(){["group"]="data",["action"]="read",["dataset"]=dataset,["offset"]=records.Count,["limit"]=10000});
                            if(part["ok"]?.GetValue<bool>()!=true)throw new InvalidOperationException(part["error"]?.ToString());
                            total=part["data"]!["total"]!.GetValue<int>();foreach(var row in part["data"]!["records"]!.AsArray())records.Add(row!.DeepClone());
                        }while(records.Count<total);
                        p.ScopeCaptures.Add(new ScopeCapture(objectId,dataset,records,$"{DateTime.Now:HH:mm:ss} · #{dataset} · {records.Count} 点"){Metadata=data["metadata"]?.DeepClone() as JsonObject});
                        if((p.ScopeObjects?.SelectedItem as ScopeObject)?.Id==objectId)RefreshScopeHistory(p);
                    }
                }
                else if (p.Key!="sfra"&&data is JsonObject d && d["dataset_id"] != null) p.Dataset = d["dataset_id"]!.GetValue<ulong>();
                else ShowData(p, data);
                jobs.Remove(pair.Key);
                if(p.Key=="wave"){
                    if(pair.Key==p.CaptureJob){if(data?["dataset_id"]==null&&!result["ok"]!.GetValue<bool>())p.Dataset=p.ResumeDataset;p.CaptureJob=0;p.Stopping=false;}
                    else if(!result["ok"]!.GetValue<bool>())p.Stopping=false;
                    UpdateCaptureButton(p);
                }
            }
            var visibleJobs=jobs.Select(x=>new JobItem(x.Key,$"#{x.Key}  {x.Value.Page.Title}")).Concat(pages.Values.Where(p=>p.Diagnostic!=null).SelectMany(p=>p.Diagnostic!.ActiveJobs.Select(job=>new JobItem(job.Id,$"#{job.Id}  {p.Title}")))).ToArray();
            if(!JobList.Items.Cast<JobItem>().Select(x=>x.Id).SequenceEqual(visibleJobs.Select(x=>x.Id)))
            {
                var selected = (JobList.SelectedItem as JobItem)?.Id;
                JobList.ItemsSource = visibleJobs;
                JobList.SelectedItem = JobList.Items.Cast<JobItem>().FirstOrDefault(x => x.Id == selected) ?? JobList.Items.Cast<JobItem>().FirstOrDefault();
            }
            JobControls.Visibility=visibleJobs.Length>0?Visibility.Visible:Visibility.Collapsed;
            var state = client.Snapshot();
            foreach(var diagnostic in pages.Values.Select(p=>p.Diagnostic).OfType<DiagnosticPage>())await diagnostic.TickAsync(state);
            UpdateConnectionDisplay(state["connected"]!.GetValue<bool>(),state["endpoint"]?.ToString() ?? "");
            var scopePage=pages["scope"];
            if(!state["connected"]!.GetValue<bool>())scopePage.ScopePollDue.Clear();
            foreach(var (objectId,due) in scopePage.ScopePollDue.ToArray()){
                if(Environment.TickCount64<due||scopePage.ScopeActions.Values.Any(a=>a.ObjectId==objectId))continue;
                var poll=client.Submit(new(){["group"]="scope",["action"]="info",["id"]=objectId,["timeout"]=2000});
                jobs.Add(poll.Id,(poll,scopePage));scopePage.ScopeActions[poll.Id]=(objectId,"info");scopePage.ScopePollDue[objectId]=Environment.TickCount64+1000;
            }
            Status.Text = $"{(state["connected"]!.GetValue<bool>() ? "已连接 " + state["endpoint"] : "未连接")}   |   RX {state["rx_bytes"]} B   TX {state["tx_bytes"]} B   |   后台任务 {state["jobs"]!.AsArray().Count}   |   丢弃 {state["dropped"]}";
            foreach(var page in VisiblePages()) await RefreshPageAsync(page,state);
        }
        catch (Exception e) { Feedback.Text = e.Message; }
        finally { updating = false; }
    }

    private async Task RefreshPageAsync(PageState page, JsonObject state)
    {
            if(page.Diagnostic!=null)return;
            if(page.Key=="scope")return;
            if(page.Key=="sfra"){
                var dataset=state["datasets"]!.AsArray().FirstOrDefault(d=>d!["id"]!.GetValue<ulong>()==page.Dataset);
                if(dataset!=null){
                    string status=dataset["state"]?.ToString()??"";page.ScopeStatus.Text="状态："+(status switch{"running"=>"正在扫频", "complete"=>"扫频完成", "partial"=>"扫频数据不完整", "stopped"=>"已停止",_=>status})+$" · {dataset["count"]} 点";
                    if(dataset["count"]!.GetValue<int>()>page.Records.Count){
                        ulong selected=page.Dataset;var updated=new JsonArray();int total;
                        do{var result=await client.ExecuteAsync(new(){["group"]="data",["action"]="read",["dataset"]=selected,["offset"]=updated.Count,["limit"]=10000});if(!result["ok"]!.GetValue<bool>())throw new InvalidOperationException(result["error"]?.ToString());total=result["data"]!["total"]!.GetValue<int>();foreach(var row in result["data"]!["records"]!.AsArray())updated.Add(row!.DeepClone());}while(updated.Count<total);
                        if(page.Dataset==selected){page.Records.Clear();foreach(var row in updated)page.Records.Add(row!.DeepClone());Draw(page);}
                    }
                }
                return;
            }
            if(page.Parameters!=null && state["datasets"]!.AsArray().LastOrDefault(d=>d!["group"]?.GetValue<string>()=="wave"&&d["state"]?.GetValue<string>()=="running") is JsonNode waveSet)
            {
                int waveCount=waveSet["count"]!.GetValue<int>();
                var reported=await client.ExecuteAsync(new(){["group"]="data",["action"]="read",["dataset"]=waveSet["id"]!.DeepClone(),["offset"]=Math.Max(0,waveCount-1000),["limit"]=1000});
                if(reported["data"]?["records"] is JsonArray records)page.Parameters.ApplyReported(records);
            }
            if(page.Key=="wave"&&state["datasets"]!.AsArray().FirstOrDefault(d=>d!["id"]!.GetValue<ulong>()==page.Dataset) is JsonNode waveState){
                ulong generation=waveState["generation"]?.GetValue<ulong>()??0;
                if(generation>page.WaveGeneration){page.WaveGeneration=generation;ResetWaveDisplay(page);}
            }
            if ((page.Pause.IsChecked!=true||page.WaveViewRefresh) && page.Dataset != 0 && state["datasets"]!.AsArray().FirstOrDefault(d => d!["id"]!.GetValue<ulong>() == page.Dataset) is JsonNode set)
            {
                if(page.Key=="wave")
                {
                    double seconds=double.Parse(page.Fields["window"].Text,CultureInfo.InvariantCulture);
                    if(!double.IsFinite(seconds)||seconds<0||seconds>86400)throw new ArgumentException("显示窗口应为 0～86400 秒；0 表示全部历史");
                    JsonObject view=new(){["group"]="data",["action"]="view",["dataset"]=page.Dataset,["seconds"]=page.WaveShowAll?0:seconds};
                    if(!page.WaveShowAll&&seconds>0&&set["count"]!.GetValue<int>()>0){
                        var latest=await client.ExecuteAsync(new(){["group"]="data",["action"]="read",["dataset"]=page.Dataset,["offset"]=set["count"]!.GetValue<int>()-1,["limit"]=1});
                        if(latest["data"]?["records"] is JsonArray latestRows&&latestRows.Count>0){
                            var range=page.WavePlots!.PrepareView(latestRows[0]!["time"]!.GetValue<double>(),seconds);view["left"]=range.Left;view["right"]=range.Right;
                        }
                    }
                    var viewResult=await client.ExecuteAsync(view);
                    if(viewResult["ok"]!.GetValue<bool>()){if(page.WaveShowAll||seconds==0)page.WavePlots!.ResetView();ShowData(page,viewResult["data"]);}
                    else Feedback.Text=viewResult["error"]?.ToString()??"波形读取失败";
                    if(page.WaveShowAll){page.Pause.IsChecked=true;page.Follow.IsChecked=false;page.WaveShowAll=false;}
                    page.WaveViewRefresh=false;
                    return;
                }
                int count = set["count"]!.GetValue<int>(); int offset = Math.Max(0, count - 10000);
                if(page.Follow.IsChecked!=true&&int.TryParse(page.HistoryOffset.Text,out var history))offset=Math.Clamp(history,0,Math.Max(0,count-1));
                if(page.Follow.IsChecked==true)page.HistoryOffset.Text=offset.ToString();
                var result = await client.ExecuteAsync(new() { ["group"] = "data", ["action"] = "read", ["dataset"] = page.Dataset, ["offset"] = offset, ["limit"] = 10000 });
                if (result["ok"]!.GetValue<bool>() || (result["code"]!.GetValue<int>()==6 && result["data"] is JsonObject)) ShowData(page, result["data"]);
            }
    }

    private void Navigate(object sender, SelectionChangedEventArgs e)
    {
        if (Navigation.SelectedIndex < 0 || pages.Count == 0) return;
        var p = pages.Values.ElementAt(Navigation.SelectedIndex);
        ShowPage(p);
    }

    private void ShowPage(PageState p)
    {
        current = p.Key; PageTitle.Text = p.Title; PageHint.Text = p.Hint;
        if (ShowDetachedPage(p)) return;
        Form.Content = p.Form; PageBody.Content = p.Body;
        PageHeading.Visibility=p.Diagnostic!=null||p.Key is "wave" or "scope" or "sfra"?Visibility.Collapsed:Visibility.Visible;
        WaveCursor.Visibility=p.Key=="wave"?Visibility.Visible:Visibility.Collapsed;
    }
    private void ToggleSidebar(object sender, RoutedEventArgs e)
    {
        SidebarCollapsed=!SidebarCollapsed;
        SidebarColumn.Width=new GridLength(SidebarCollapsed?60:185);
        SidebarToggle.ToolTip=SidebarCollapsed?"展开侧边栏":"收起侧边栏";
    }
    private async Task RefreshPortsAsync()
    {
        try {
            string previous=SelectedPort();
            var result = await client.ExecuteAsync(new() { ["group"] = "serial", ["action"] = "ports" });
            var ports=result["data"]!.AsArray().Select(x => x is JsonValue
                ? new SerialPortItem(x!.ToString(), "")
                : new SerialPortItem(x!["port"]!.ToString(), x["description"]?.ToString() ?? "")).ToArray();
            refreshingPorts=true;
            try{Port.ItemsSource=ports;Port.SelectedItem=ports.FirstOrDefault(x=>string.Equals(x.Port,previous,StringComparison.OrdinalIgnoreCase));if(Port.SelectedItem==null)Port.Text=previous;}
            finally{refreshingPorts=false;}
        }
        catch (Exception e) { Feedback.Text = e.Message; }
    }
    private string SelectedPort() => Port.SelectedItem is SerialPortItem item && Port.Text==item.Display ? item.Port : Port.Text.Trim();
    private void UpdateConnectionDisplay(bool connected,string endpoint)
    {
        if(!connectionBusy)ConnectButton.Content=connected?"断开":"连接";
        ConnectionIndicator.Fill=connected?System.Windows.Media.Brushes.LimeGreen:System.Windows.Media.Brushes.SlateGray;
        string connectionText=connected?"已连接 "+endpoint:"未连接";
        ConnectionIndicator.ToolTip=connectionText;
        System.Windows.Automation.AutomationProperties.SetName(ConnectionIndicator,connectionText);
        ConnectionType.IsEnabled=true;
        Port.ToolTip=connected?"当前连接："+endpoint+"；更换串口后自动断开":"串口端口及设备名称";
    }
    private async void RefreshPorts(object sender, RoutedEventArgs e) => await RefreshPortsAsync();
    private async void SearchEthernet(object sender,RoutedEventArgs e)
    {
        var dialog=new EthernetDiscoveryWindow(token=>client.ExecuteAsync(new(){["group"]="ethernet",["action"]="discover",["scan_ms"]=800,["timeout"]=3000},token)){Owner=this};
        if(dialog.ShowDialog()==true&&dialog.SelectedDevice is EthernetDevice device)
            await ConnectDiscoveredAsync(device);
    }
    private Task ConnectDiscoveredAsync(EthernetDevice device)=>RunConnectionChangeAsync(async ()=>{
                await DisconnectCurrentAsync();
                TcpHost.Text=device.Ip;TcpPort.Text=device.Port.ToString(CultureInfo.InvariantCulture);
                var request=ConnectionRequest();request["transport"]="tcp";request["host"]=device.Ip;request["tcp_port"]=device.Port;
                CheckConnectionResult(await client.ExecuteAsync(request));Feedback.Text=$"已连接 {device.Name}（{device.Ip}:{device.Port}）";
            },"连接中…");
    private async void ChangeConnectionType(object sender,SelectionChangedEventArgs e)
    {
        if(SerialSettings==null||TcpSettings==null)return;
        bool tcp=ConnectionType.SelectedIndex==1;
        SerialSettings.Visibility=tcp?Visibility.Collapsed:Visibility.Visible;
        TcpSettings.Visibility=tcp?Visibility.Visible:Visibility.Collapsed;
        if(!initializingConnection)await RunConnectionChangeAsync(async ()=>{await DisconnectCurrentAsync();Feedback.Text="已切换连接类型，请点击连接";},"断开中…");
    }
    private JsonObject ConnectionRequest()
    {
        JsonObject request=new(){["group"]="connect",["dst"]=int.Parse(Address.Text),["dynamic_dst"]=int.Parse(DynamicAddress.Text)};
        if(ConnectionType.SelectedIndex==1){request["transport"]="tcp";request["host"]=TcpHost.Text.Trim();request["tcp_port"]=int.Parse(TcpPort.Text);}
        else{request["transport"]="serial";request["port"]=SelectedPort();request["baud"]=int.Parse(Baud.Text);}
        return request;
    }
    private async void ToggleConnection(object sender, RoutedEventArgs e)
    {
        if(connectionBusy||closing)return;
        await RunConnectionChangeAsync(async ()=>{
            bool connected=client.Snapshot()["connected"]!.GetValue<bool>();
            ConnectButton.Content=connected?"断开中…":"连接中…";
            if(connected)await DisconnectCurrentAsync();
            else CheckConnectionResult(await client.ExecuteAsync(ConnectionRequest()));
            Feedback.Text=connected?"已断开连接":"连接成功";
        },"连接中…");
    }
    private static void CheckConnectionResult(JsonObject result)
    {
        if(result["ok"]?.GetValue<bool>()!=true)throw new InvalidOperationException(result["error"]?.ToString()??"连接操作失败");
    }
    private async Task RunConnectionChangeAsync(Func<Task> action,string label)
    {
        if(initializingConnection||closing)return;
        await connectionGate.WaitAsync();
        try{
            if(closing)return;
            connectionBusy=true;ConnectButton.IsEnabled=false;ConnectButton.Content=label;
            while(updating&&!closing)await Task.Delay(20);
            if(!closing)await action();
        }
        catch(Exception ex){Feedback.Text=ex.Message;}
        finally{
            connectionBusy=false;ConnectButton.IsEnabled=true;
            connectionGate.Release();
            if(!closing&&!disposed){var state=client.Snapshot();UpdateConnectionDisplay(state["connected"]!.GetValue<bool>(),state["endpoint"]?.ToString()??"");await UpdateAsync();}
        }
    }
    private async Task DisconnectCurrentAsync()
    {
        pages["scope"].ScopePollDue.Clear();
        var deadline=DateTime.UtcNow.AddSeconds(8);
        while(true){
            var active=client.Snapshot()["jobs"]!.AsArray().Where(j=>j!["group"]?.ToString()!="jlink").ToArray();
            if(active.Length==0)break;
            foreach(var job in active)client.Cancel(job!["id"]!.GetValue<ulong>());
            if(DateTime.UtcNow>=deadline)throw new InvalidOperationException("设备任务仍在收尾，请稍后重试切换");
            await Task.Delay(30);
        }
        if(client.Snapshot()["connected"]!.GetValue<bool>())CheckConnectionResult(await client.ExecuteAsync(new(){["group"]="disconnect"}));
    }
    private async Task CommitPortAsync(string selected)
    {
        if(initializingConnection||refreshingPorts||ConnectionType.SelectedIndex!=0)return;
        var currentState=client.Snapshot();
        if(!connectionBusy&&(!currentState["connected"]!.GetValue<bool>()||string.Equals(selected,currentState["endpoint"]?.ToString(),StringComparison.OrdinalIgnoreCase)))return;
        await RunConnectionChangeAsync(async ()=>{
            var state=client.Snapshot();var endpoint=state["endpoint"]?.ToString()??"";
            if(state["connected"]!.GetValue<bool>()&&!string.Equals(selected,endpoint,StringComparison.OrdinalIgnoreCase)){
                await DisconnectCurrentAsync();Feedback.Text="已更换串口，请点击连接";
            }
        },"断开中…");
    }
    private async void ChangePort(object sender,SelectionChangedEventArgs e)
    {
        if(e.AddedItems.Count>0&&e.AddedItems[0] is SerialPortItem item)await CommitPortAsync(item.Port);
    }
    private async void CommitPort(object sender,System.Windows.Input.KeyboardFocusChangedEventArgs e)=>await CommitPortAsync(SelectedPort());
    private async void PortKeyDown(object sender,System.Windows.Input.KeyEventArgs e){if(e.Key==System.Windows.Input.Key.Enter){e.Handled=true;await CommitPortAsync(SelectedPort());}}
    private async Task ApplyBaudAsync(string text)
    {
        if(initializingConnection||editingBaud||text=="自定义…"||text==lastBaud)return;
        await RunConnectionChangeAsync(async ()=>{
            var state=client.Snapshot();
            bool live=state["connected"]!.GetValue<bool>()&&(state["baud"]?.GetValue<int>()??0)>0;
            string previous=live?state["baud"]!.ToString():lastBaud;
            try{
                if(!int.TryParse(text,out int baud)||baud<1||baud>12000000)throw new ArgumentException("波特率应为 1～12000000 的整数");
                if(live){var result=await client.ExecuteAsync(new(){["group"]="serial",["action"]="baud",["baud"]=baud});CheckConnectionResult(result);}
                lastBaud=text;Feedback.Text=live?$"当前串口波特率已修改为 {text}":$"波特率已设置为 {text}";
            }catch{editingBaud=true;Baud.Text=previous;editingBaud=false;lastBaud=previous;throw;}
        },"设置中…");
    }
    private async void ChangeBaud(object sender,SelectionChangedEventArgs e)
    {
        if(initializingConnection||editingBaud||e.AddedItems.Count==0)return;
        string selected=e.AddedItems[0]?.ToString()??"";
        await System.Windows.Threading.Dispatcher.Yield();
        if(selected=="自定义…"){
            editingBaud=true;
            var dialog=new BaudRateWindow(lastBaud){Owner=this};bool accepted=dialog.ShowDialog()==true;
            string value=accepted?dialog.Value:lastBaud;Baud.Text=value;editingBaud=false;
            if(accepted)await ApplyBaudAsync(value);
        }else await ApplyBaudAsync(selected);
    }
    private async void CommitBaud(object sender,System.Windows.Input.KeyboardFocusChangedEventArgs e)=>await ApplyBaudAsync(Baud.Text.Trim());
    private async void BaudKeyDown(object sender,System.Windows.Input.KeyEventArgs e){if(e.Key==System.Windows.Input.Key.Enter){e.Handled=true;await ApplyBaudAsync(Baud.Text.Trim());}}
    private void RestoreSettings()
    {
        if(settingsPath==null)return;
        try
        {
            var settings=DesktopSettings.Load(settingsPath);
            DynamicAddress.Text=settings["dynamic_address"]?.ToString()??"0";
            foreach(var entry in new[]{("port",(Action<string>)(v=>Port.Text=v)),("baud",v=>Baud.Text=v),("address",v=>Address.Text=v),("host",v=>TcpHost.Text=v),("tcp_port",v=>TcpPort.Text=v)})
                if(settings[entry.Item1] is JsonValue value&&value.TryGetValue<string>(out var text))entry.Item2(text);
            ConnectionType.SelectedIndex=settings["transport"]?.ToString()=="tcp"?1:0;
            if(settings["sidebar_collapsed"]?.ToString()=="true")ToggleSidebar(this,new RoutedEventArgs());
            if(double.TryParse(settings["width"]?.ToString(),CultureInfo.InvariantCulture,out var width)&&double.IsFinite(width))Width=Math.Clamp(width,MinWidth,Math.Max(MinWidth,SystemParameters.VirtualScreenWidth));
            if(double.TryParse(settings["height"]?.ToString(),CultureInfo.InvariantCulture,out var height)&&double.IsFinite(height))Height=Math.Clamp(height,MinHeight,Math.Max(MinHeight,SystemParameters.VirtualScreenHeight));
            if(settings["fields"] is JsonObject fields)foreach(var page in pages.Values)foreach(var field in page.Fields)
                if(!(page.Key=="sfra"&&field.Key is "start_hz" or "stop_hz" or "amplitude" or "count")&&field.Key is not ("value" or "hex" or "text" or "output")&&fields[page.Key+"."+field.Key] is JsonValue saved&&saved.TryGetValue<string>(out var text))field.Value.Text=text;
            if(pages.TryGetValue("wave",out var wave))wave.WaveWindowPreset!.SelectedIndex=wave.Fields["window"].Text switch{"10"=>0,"30"=>1,"60"=>2,"600"=>3,"0"=>5,_=>4};
        }
        catch(Exception error){Feedback.Text="读取界面设置失败，已使用默认值："+error.Message;}
    }
    private void SaveSettings()
    {
        if(settingsPath==null)return;
        JsonObject fields=new();foreach(var page in pages.Values)foreach(var field in page.Fields)
            if(field.Key is not ("value" or "hex" or "text" or "output"))fields[page.Key+"."+field.Key]=field.Value.Text;
        var bounds=WindowState==WindowState.Normal?new Rect(Left,Top,ActualWidth,ActualHeight):RestoreBounds;
        DesktopSettings.Save(settingsPath,new(){["version"]=1,["port"]=SelectedPort(),["baud"]=Baud.Text,["address"]=Address.Text,["dynamic_address"]=DynamicAddress.Text,["host"]=TcpHost.Text,["tcp_port"]=TcpPort.Text,["transport"]=ConnectionType.SelectedIndex==1?"tcp":"serial",["sidebar_collapsed"]=SidebarCollapsed,["width"]=bounds.Width,["height"]=bounds.Height,["fields"]=fields});
    }
    private async void OnClosing(object? sender, CancelEventArgs e)
    {
        if (disposed) return; e.Cancel = true; if (closing) return; closing = true; timer.Stop(); IsEnabled = false; Status.Text = "正在停止任务并关闭设备…";
        foreach(var key in detachedPages.Keys.ToArray()) DockPage(key,false);
        foreach(var diagnostic in pages.Values.Select(p=>p.Diagnostic).OfType<DiagnosticPage>())diagnostic.Shutdown();
        try{SaveSettings();}catch(Exception error){Feedback.Text="保存界面设置失败："+error.Message;}
        while (updating) await Task.Delay(20);
        await client.DisposeAsync();
        if(client.ShutdownError!=null)MessageBox.Show(this,client.ShutdownError,"设备关闭结果",MessageBoxButton.OK,MessageBoxImage.Warning);
        disposed = true; Close();
    }
}
