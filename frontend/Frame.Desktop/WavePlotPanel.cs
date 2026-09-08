using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using ScottPlot.WPF;

namespace Frame.Desktop;

public sealed class WavePlotPanel : UserControl
{
    private sealed record Pane(int Id,WpfPlot Plot,Border Frame,StackPanel Legend);
    private readonly List<Pane> panes=new();
    private readonly Dictionary<string,int> assignments=new();
    private readonly StackPanel stack=new();
    private WpfPlot? active;
    private readonly Dictionary<string,ScottPlot.Color> colors=new();
    public ScottPlot.Color SeriesColor(string name)
    {
        if(!colors.TryGetValue(name,out var color)){string[] palette=["#2563EB","#DC2626","#16A34A","#D97706","#9333EA","#0891B2","#DB2777","#4F46E5"];color=ScottPlot.Color.FromHex(palette[colors.Count%palette.Length]);colors[name]=color;}
        return color;
    }
    private readonly Dictionary<int,string[]> legendNames=new();
    private int nextId=1;
    private bool hostTime;
    private bool prepared,tracking=true,scrolling;
    private (double Left,double Right)? pendingRange;
    private WpfPlot? fitY;
    private double latestTime=double.NaN,windowSeconds;
    private readonly HashSet<WpfPlot> manualY=new();
    public void ResetView(){prepared=false;tracking=true;scrolling=false;pendingRange=null;latestTime=double.NaN;manualY.Clear();}
    public void FitY(){fitY=active;Changed?.Invoke();}
    public (double Left,double Right) PrepareView(double latest,double seconds)
    {
        var limits=active!.Plot.Axes.GetLimits();
        double width=seconds>0?seconds:30,left=pendingRange?.Left??limits.Left,right=pendingRange?.Right??limits.Right;
        if(!prepared||windowSeconds!=seconds){left=latest;right=left+width;tracking=true;scrolling=false;}
        else if(tracking&&(scrolling||latest>right)){width=right-left;right=latest+width*0.2;left=right-width;scrolling=true;}
        latestTime=latest;windowSeconds=seconds;prepared=true;
        pendingRange=(left,right);
        return(left,right);
    }
    private void RememberView(WpfPlot source)
    {
        pendingRange=null;scrolling=false;
        var limits=source.Plot.Axes.GetLimits();
        tracking=double.IsNaN(latestTime)||(limits.Left<=latestTime&&limits.Right>=latestTime);
        SynchronizeTime(source);ViewChanged?.Invoke();
    }
    private void Zoom(WpfPlot plot,ScottPlot.Coordinates anchor,int delta,bool x,bool y)
    {
        PlotWheelZoom.Apply(plot,anchor,delta,x,y);
        if(y)manualY.Add(plot);
        RememberView(plot);plot.Refresh();
    }
    private readonly Dictionary<WpfPlot,(ScottPlot.Plottables.VerticalLine Vertical,ScottPlot.Plottables.HorizontalLine? Horizontal)> cursors=new();
    private WpfPlot? cursorPlot;
    private ScottPlot.Coordinates cursorPosition;
    public static string FormatTime(double seconds,bool host)=>host&&seconds>=946684800&&seconds<=253402271999
        ?DateTimeOffset.UnixEpoch.AddSeconds(seconds).ToOffset(TimeSpan.FromHours(8)).ToString("HH:mm:ss.fff",System.Globalization.CultureInfo.InvariantCulture)
        :seconds.ToString("0.####",System.Globalization.CultureInfo.InvariantCulture);
    public event Action? Changed;
    public event Action<WpfPlot>? ActiveChanged;
    public event Action? ViewChanged;
    public event Action<string>? CursorChanged;
    public event Action<string>? ParameterAssigned;
    public event Action<double?>? HoverTimeChanged;
    public IReadOnlyList<int> PlotIds=>panes.Select(p=>p.Id).ToArray();
    public WavePlotPanel(WpfPlot first)
    {
        Content=new ScrollViewer{Content=stack,VerticalScrollBarVisibility=ScrollBarVisibility.Auto,HorizontalScrollBarVisibility=ScrollBarVisibility.Disabled};
        SizeChanged+=(_,_)=>LayoutPlots();AddPlot(first);
    }
    public int AddPlot()=>AddPlot(new WpfPlot());
    private int AddPlot(WpfPlot plot)
    {
        if(active!=null){var shared=active.Plot.Axes.GetLimits();plot.Plot.Axes.SetLimitsX(shared.Left,shared.Right);}
        int id=nextId++;var frame=new Border{BorderThickness=new Thickness(2),Margin=new Thickness(0,0,0,8),BorderBrush=Brushes.LightSlateGray};
        var layout=new DockPanel();frame.Child=layout;
        var header=new DockPanel{Background=Brushes.AliceBlue};DockPanel.SetDock(header,Dock.Top);layout.Children.Add(header);
        var close=new Button{Content="×",ToolTip="关闭此波形框",Width=28,Height=26,Padding=new Thickness(0),Margin=new Thickness(2)};DockPanel.SetDock(close,Dock.Right);header.Children.Add(close);
        var legend=new StackPanel{Orientation=Orientation.Horizontal};header.Children.Add(new ScrollViewer{Content=legend,HorizontalScrollBarVisibility=ScrollBarVisibility.Auto,VerticalScrollBarVisibility=ScrollBarVisibility.Disabled,MaxHeight=46});
        layout.Children.Add(plot);
        plot.Plot.Layout.Fixed(new ScottPlot.PixelPadding(85,24,55,16));
        var pane=new Pane(id,plot,frame,legend);panes.Add(pane);stack.Children.Add(frame);
        frame.AllowDrop=true;plot.AllowDrop=true;
        frame.PreviewDragOver+=(_,e)=>{e.Effects=e.Data.GetDataPresent("FRAME.WaveParameter")?DragDropEffects.Move:DragDropEffects.None;e.Handled=true;};
        frame.PreviewDrop+=(_,e)=>{if(e.Data.GetData("FRAME.WaveParameter") is string name){Activate(pane);Assign(name,id);e.Effects=DragDropEffects.Move;e.Handled=true;}};
        close.Click+=(_,_)=>RemovePlot(id);
        frame.PreviewMouseDown+=(_,_)=>Activate(pane);
        void SyncAfterInput()=>Dispatcher.BeginInvoke(new Action(()=>{Activate(pane);manualY.Add(plot);RememberView(plot);}),System.Windows.Threading.DispatcherPriority.Input);
        plot.PreviewMouseWheel+=(_,e)=>{
            Activate(pane);var point=e.GetPosition(plot);var dpi=VisualTreeHelper.GetDpi(plot);
            var anchor=plot.Plot.GetCoordinates(new ScottPlot.Pixel((float)(point.X*dpi.DpiScaleX),(float)(point.Y*dpi.DpiScaleY)));
            var modifiers=System.Windows.Input.Keyboard.Modifiers;
            Zoom(plot,anchor,e.Delta,!modifiers.HasFlag(System.Windows.Input.ModifierKeys.Control),!modifiers.HasFlag(System.Windows.Input.ModifierKeys.Shift));e.Handled=true;
        };
        plot.AddHandler(UIElement.MouseUpEvent,new System.Windows.Input.MouseButtonEventHandler((_,_)=>SyncAfterInput()),true);
        plot.MouseMove+=(_,e)=>{
            var point=e.GetPosition(plot);var dpi=VisualTreeHelper.GetDpi(plot);
            var xy=plot.Plot.GetCoordinates(new ScottPlot.Pixel((float)(point.X*dpi.DpiScaleX),(float)(point.Y*dpi.DpiScaleY)));
            CursorChanged?.Invoke($"X = {FormatTime(xy.X,hostTime)}   Y = {xy.Y:G6}");
            if(e.LeftButton==System.Windows.Input.MouseButtonState.Pressed||e.RightButton==System.Windows.Input.MouseButtonState.Pressed)SyncAfterInput();
            UpdateCursor(plot,xy);
        };
        plot.MouseLeave+=(_,_)=>{
            cursorPlot=null;HoverTimeChanged?.Invoke(null);
            foreach(var (chart,lines) in cursors){chart.Plot.Remove(lines.Vertical);if(lines.Horizontal!=null)chart.Plot.Remove(lines.Horizontal);chart.Refresh();}cursors.Clear();
        };
        LayoutPlots();Activate(pane);Changed?.Invoke();return id;
    }
    private void Activate(Pane pane){active=pane.Plot;foreach(var item in panes)item.Frame.BorderBrush=item==pane?Brushes.SteelBlue:Brushes.LightSlateGray;ActiveChanged?.Invoke(pane.Plot);}
    private void SynchronizeTime(WpfPlot source){var limits=source.Plot.Axes.GetLimits();foreach(var pane in panes){pane.Plot.Plot.Axes.SetLimitsX(limits.Left,limits.Right);pane.Plot.Refresh();}}
    private void UpdateCursor(WpfPlot source,ScottPlot.Coordinates position)
    {
        cursorPlot=source;cursorPosition=position;
        HoverTimeChanged?.Invoke(position.X);
        foreach(var pane in panes){
            var plot=pane.Plot;
            if(cursors.Remove(plot,out var old)){plot.Plot.Remove(old.Vertical);if(old.Horizontal!=null)plot.Plot.Remove(old.Horizontal);}
            var vertical=plot.Plot.Add.VerticalLine(position.X);vertical.Color=ScottPlot.Colors.Gray;
            var horizontal=plot==source?plot.Plot.Add.HorizontalLine(position.Y):null;if(horizontal!=null)horizontal.Color=ScottPlot.Colors.Gray;
            cursors[plot]=(vertical,horizontal);plot.Refresh();
        }
    }
    private void LayoutPlots(){foreach(var pane in panes)pane.Frame.Height=Math.Max(250,ActualHeight/panes.Count-8);}
    public void RemovePlot(int id)
    {
        if(panes.Count==1)return;
        var pane=panes.FirstOrDefault(p=>p.Id==id);if(pane==null)return;
        panes.Remove(pane);stack.Children.Remove(pane.Frame);
        legendNames.Remove(id);
        cursors.Remove(pane.Plot);if(cursorPlot==pane.Plot){cursorPlot=null;HoverTimeChanged?.Invoke(null);}
        foreach(var name in assignments.Where(p=>p.Value==id).Select(p=>p.Key).ToArray())assignments[name]=panes[0].Id;
        Activate(panes[0]);LayoutPlots();Changed?.Invoke();
    }
    public int PlotFor(string name)=>assignments.TryGetValue(name,out int id)&&panes.Any(p=>p.Id==id)?id:panes[0].Id;
    public void Assign(string name,int id){if(!panes.Any(p=>p.Id==id))return;assignments[name]=id;ParameterAssigned?.Invoke(name);Changed?.Invoke();}
    public static (double[] X,double[] Y) CurvePoints(JsonObject[] rows)
    {
        var intervals=rows.Zip(rows.Skip(1),(a,b)=>b["time"]!.GetValue<double>()-a["time"]!.GetValue<double>()).Where(d=>d>0).Order().ToArray();
        double spacing=intervals.Length==0?0:intervals[intervals.Length/2];
        var x=new List<double>();var y=new List<double>();JsonObject? previous=null;
        foreach(var row in rows){
            double time=row["time"]!.GetValue<double>();
            double threshold=Math.Max(0.5,Math.Max(spacing*5,(row["period_ms"]?.GetValue<double>()??10)*0.005));
            if(previous!=null&&(row["segment"]?.ToString()!=previous["segment"]?.ToString()||time-previous["time"]!.GetValue<double>()>threshold||time<previous["time"]!.GetValue<double>())){x.Add(double.NaN);y.Add(double.NaN);}
            x.Add(time);y.Add(row["value"]!.GetValue<double>());previous=row;
        }
        return(x.ToArray(),y.ToArray());
    }
    public void Render(JsonArray records,WaveSeriesPanel series,bool follow)
    {
        hostTime=records.OfType<JsonObject>().LastOrDefault()?["time_source"]?.ToString()=="host_receive";
        var groups=records.OfType<JsonObject>().Where(r=>r["name"]!=null).GroupBy(r=>r["name"]!.ToString()).ToArray();
        var times=records.OfType<JsonObject>().Where(r=>r["time"]!=null).Select(r=>r["time"]!.GetValue<double>()).ToArray();
        var sharedTime=active!.Plot.Axes.GetLimits();
        double sharedLeft=pendingRange?.Left??sharedTime.Left,sharedRight=pendingRange?.Right??sharedTime.Right;
        pendingRange=null;
        foreach(var pane in panes){
            var plot=pane.Plot;var limits=plot.Plot.Axes.GetLimits();plot.Plot.Clear();cursors.Remove(plot);
            var names=series.VisibleNames.Where(name=>PlotFor(name)==pane.Id).ToArray();
            foreach(var name in names)SeriesColor(name);
            foreach(var group in groups.Where(g=>series.IsSeriesVisible(g.Key)&&PlotFor(g.Key)==pane.Id)){
                var points=CurvePoints(group.ToArray());var line=plot.Plot.Add.Scatter(points.X,points.Y);line.LegendText=group.Key;line.MarkerSize=0;
                line.Color=SeriesColor(group.Key);
            }
            if(!legendNames.TryGetValue(pane.Id,out var oldNames)||!oldNames.SequenceEqual(names)){
              pane.Legend.Children.Clear();legendNames[pane.Id]=names;
              foreach(var name in names){var color=colors[name];
                var item=new StackPanel{Orientation=Orientation.Horizontal,Margin=new Thickness(8,5,6,5)};
                item.Children.Add(new System.Windows.Shapes.Line{X2=18,StrokeThickness=2,Stroke=new SolidColorBrush(Color.FromRgb(color.R,color.G,color.B)),VerticalAlignment=VerticalAlignment.Center,Margin=new Thickness(0,0,5,0)});
                item.Children.Add(new TextBlock{Text=name});pane.Legend.Children.Add(item);
              }
            }
            plot.Plot.Axes.Bottom.TickGenerator=new ScottPlot.TickGenerators.NumericAutomatic{LabelFormatter=value=>FormatTime(value,hostTime)};
            plot.Plot.XLabel(hostTime?"":"Simulation time (s)");plot.Plot.YLabel("Value");plot.Plot.HideLegend();
            if(prepared){if(!manualY.Contains(plot))plot.Plot.Axes.AutoScale();else plot.Plot.Axes.SetLimits(limits);plot.Plot.Axes.SetLimitsX(sharedLeft,sharedRight);}
            else if(follow){plot.Plot.Axes.AutoScale();if(times.Length>1&&times.Max()>times.Min())plot.Plot.Axes.SetLimitsX(times.Min(),times.Max());}
            else{plot.Plot.Axes.SetLimits(limits);plot.Plot.Axes.SetLimitsX(sharedTime.Left,sharedTime.Right);}
            if(fitY==plot){var x=plot.Plot.Axes.GetLimits();plot.Plot.Axes.AutoScale();plot.Plot.Axes.SetLimitsX(x.Left,x.Right);manualY.Add(plot);fitY=null;}
            plot.Refresh();
        }
        if(cursorPlot!=null)UpdateCursor(cursorPlot,cursorPosition);
    }
}
