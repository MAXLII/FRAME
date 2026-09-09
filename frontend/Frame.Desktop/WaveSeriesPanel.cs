using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;

namespace Frame.Desktop;

// Display selection never changes device reporting or dataset contents.
public sealed class WaveSeriesPanel : UserControl
{
    private readonly Dictionary<string,(System.Windows.Controls.Primitives.ToggleButton Check,TextBlock Value,FrameworkElement Row)> series=new();
    private HashSet<string>? selectedParameters;
    private WavePlotPanel? plots;
    public void AttachPlots(WavePlotPanel panel){plots=panel;panel.ParameterAssigned+=name=>SetSeriesVisible(name,true);panel.HoverTimeChanged+=SetHoverTime;}
    private readonly TextBlock valueTitle=new(){Text="曲线显示 / 最新值",Margin=new Thickness(4)};
    private Dictionary<string,JsonObject[]> samples=new();
    private Dictionary<string,JsonObject> latest=new();
    private double? hoverTime;
    public IEnumerable<string> VisibleNames=>series.Keys.Where(IsSeriesVisible);
    private readonly StackPanel items=new();
    private readonly TextBox search=new(){ToolTip="搜索曲线名称",Margin=new Thickness(4)};
    public event Action? SelectionChanged;
    public WaveSeriesPanel()
    {
        var root=new DockPanel();Content=root;
        var top=new StackPanel();DockPanel.SetDock(top,Dock.Top);root.Children.Add(top);
        top.Children.Add(valueTitle);top.Children.Add(search);
        var buttons=new WrapPanel();top.Children.Add(buttons);
        foreach(var option in new[]{("全选",true),("全不选",false)})
        {
            var button=new Button{Content=option.Item1};button.Click+=(_,_)=>{foreach(var entry in series.Values)entry.Check.IsChecked=option.Item2;};buttons.Children.Add(button);
        }
        root.Children.Add(new ScrollViewer{Content=items,VerticalScrollBarVisibility=ScrollBarVisibility.Auto});
        search.TextChanged+=(_,_)=>Filter();
    }
    public bool IsSeriesVisible(string name)=>(selectedParameters==null||selectedParameters.Contains(name))&&series.TryGetValue(name,out var item)&&item.Check.IsChecked==true;
    public void SetSelectedParameters(IReadOnlyList<string> names)
    {
        selectedParameters=new HashSet<string>(names,StringComparer.Ordinal);
        foreach(string name in series.Keys.Where(name=>!selectedParameters.Contains(name)).ToArray()){items.Children.Remove(series[name].Row);series.Remove(name);}
        foreach(string name in names)Ensure(name);
        items.Children.Clear();foreach(string name in names)items.Children.Add(series[name].Row);
        SelectionChanged?.Invoke();
    }
    public void SetSeriesVisible(string name,bool visible){Ensure(name);series[name].Check.IsChecked=visible;}
    public void Select(string name)
    {
        Ensure(name);
        series[name].Check.IsChecked=true;
    }
    private void Ensure(string name)
    {
        if(series.ContainsKey(name))return;
        var row=new DockPanel{Margin=new Thickness(4,2,8,2),Height=28};
        var value=new TextBlock{Width=92,TextAlignment=TextAlignment.Right,TextTrimming=TextTrimming.CharacterEllipsis,Text="—",VerticalAlignment=VerticalAlignment.Center};
        DockPanel.SetDock(value,Dock.Right);row.Children.Add(value);
        var swatch=new System.Windows.Shapes.Line{X1=2,X2=22,Y1=12,Y2=12,StrokeThickness=3,Width=24,Height=24,IsHitTestVisible=false};
        var check=new System.Windows.Controls.Primitives.ToggleButton{Content=swatch,ToolTip="点击图例显示/隐藏曲线",Width=28,Height=26,Padding=new Thickness(0),Background=System.Windows.Media.Brushes.Transparent,BorderThickness=new Thickness(0),Cursor=System.Windows.Input.Cursors.Hand,VerticalAlignment=VerticalAlignment.Center,IsChecked=false,Margin=new Thickness(0,0,5,0)};
        var template=new ControlTemplate(typeof(System.Windows.Controls.Primitives.ToggleButton));
        var presenter=new FrameworkElementFactory(typeof(ContentPresenter));presenter.SetValue(ContentPresenter.HorizontalAlignmentProperty,HorizontalAlignment.Center);presenter.SetValue(ContentPresenter.VerticalAlignmentProperty,VerticalAlignment.Center);
        var hitArea=new FrameworkElementFactory(typeof(Border));hitArea.SetValue(Border.BackgroundProperty,System.Windows.Media.Brushes.Transparent);hitArea.AppendChild(presenter);template.VisualTree=hitArea;check.Template=template;
        System.Windows.Automation.AutomationProperties.SetName(check,name+" 曲线显示");
        void RefreshSwatch(){var color=plots?.SeriesColor(name)??ScottPlot.Colors.Blue;swatch.Stroke=check.IsChecked==true?new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(color.R,color.G,color.B)):System.Windows.Media.Brushes.Gray;}
        RefreshSwatch();DockPanel.SetDock(check,Dock.Left);row.Children.Add(check);
        var label=new TextBlock{Text=name,TextTrimming=TextTrimming.CharacterEllipsis,Background=System.Windows.Media.Brushes.Transparent,VerticalAlignment=VerticalAlignment.Stretch,Padding=new Thickness(0,5,0,0),Cursor=System.Windows.Input.Cursors.Hand,ToolTip=name+" · 拖到目标波形框"};row.Children.Add(label);
        Point? dragStart=null;
        label.PreviewMouseLeftButtonDown+=(_,e)=>{dragStart=e.GetPosition(label);label.CaptureMouse();e.Handled=true;};
        label.PreviewMouseLeftButtonUp+=(_,e)=>{dragStart=null;label.ReleaseMouseCapture();e.Handled=true;};
        label.PreviewMouseMove+=(_,e)=>{if(plots!=null&&dragStart is Point start&&e.LeftButton==System.Windows.Input.MouseButtonState.Pressed){var point=e.GetPosition(label);if(Math.Abs(point.X-start.X)>SystemParameters.MinimumHorizontalDragDistance||Math.Abs(point.Y-start.Y)>SystemParameters.MinimumVerticalDragDistance){dragStart=null;label.ReleaseMouseCapture();DragDrop.DoDragDrop(label,new DataObject("FRAME.WaveParameter",name),DragDropEffects.Move);e.Handled=true;}}};
        series.Add(name,(check,value,row));items.Children.Add(row);
        check.Checked+=(_,_)=>{RefreshSwatch();SelectionChanged?.Invoke();};check.Unchecked+=(_,_)=>{RefreshSwatch();SelectionChanged?.Invoke();};Filter();
    }
    public void SetHoverTime(double? time){hoverTime=time;RefreshValues();}
    private void RefreshValues()
    {
        valueTitle.Text=hoverTime.HasValue?"曲线显示 / 光标值":"曲线显示 / 最新值";
        foreach(var (name,item) in series){
            JsonObject? sample=null;
            if(hoverTime is double time){
                if(samples.TryGetValue(name,out var rows)&&rows.Length>0){
                    int lo=0,hi=rows.Length;
                    while(lo<hi){int mid=(lo+hi)/2;if(rows[mid]["time"]!.GetValue<double>()<time)lo=mid+1;else hi=mid;}
                    int index=Math.Min(lo,rows.Length-1);
                    if(index>0&&Math.Abs(rows[index-1]["time"]!.GetValue<double>()-time)<=Math.Abs(rows[index]["time"]!.GetValue<double>()-time))index--;
                    sample=rows[index];
                }
            }else latest.TryGetValue(name,out sample);
            item.Value.Text=sample==null?"—":ParameterRow.Format(sample["value"],sample["type"]?.GetValue<int>()??6);
        }
    }
    public void Update(JsonArray records,JsonArray? latestRecords=null)
    {
        samples=records.OfType<JsonObject>().Where(r=>r["name"]!=null&&r["time"]!=null).GroupBy(r=>r["name"]!.ToString()).ToDictionary(g=>g.Key,g=>g.OrderBy(r=>r["time"]!.GetValue<double>()).ToArray());
        latest=(latestRecords??records).OfType<JsonObject>().Where(r=>r["name"]!=null).GroupBy(r=>r["name"]!.ToString()).ToDictionary(g=>g.Key,g=>g.Last());
        foreach(var group in records.OfType<JsonObject>().Where(r=>r["name"]!=null).GroupBy(r=>r["name"]!.ToString()))
        {
            if(selectedParameters!=null&&!selectedParameters.Contains(group.Key))continue;
            Ensure(group.Key);
        }
        RefreshValues();
    }
    private void Filter(){foreach(var pair in series)pair.Value.Row.Visibility=ParameterPanel.Matches(pair.Key,search.Text)?Visibility.Visible:Visibility.Collapsed;}
}
