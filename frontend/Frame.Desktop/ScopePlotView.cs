using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using ScottPlot.WPF;

namespace Frame.Desktop;

public sealed class ScopePlotView : UserControl
{
    private readonly WpfPlot plot;
    private readonly WrapPanel legend=new();
    private readonly TextBlock values=new(){Margin=new Thickness(6),TextWrapping=TextWrapping.Wrap};
    private readonly Dictionary<int,Dictionary<int,string>> names=new();
    private readonly HashSet<(int Object,int Channel)> hidden=new();
    private JsonArray records=new();
    private int objectId;
    private ScottPlot.Plottables.VerticalLine? cursor;
    private readonly List<ScottPlot.IPlottable> highlights=new();
    public JsonObject? TriggerMetadata{get;set;}
    private static ScottPlot.Color ColorFor(int index)=>ScottPlot.Color.FromHex(new[]{"#2563EB","#DC2626","#16A34A","#D97706","#9333EA","#0891B2"}[index%6]);
    public ScopePlotView(WpfPlot chart)
    {
        plot=chart;var root=new DockPanel();Content=root;
        PlotWheelZoom.Attach(plot);
        DockPanel.SetDock(legend,Dock.Top);root.Children.Add(legend);root.Children.Add(plot);
        plot.MouseMove+=(_,e)=>{var position=e.GetPosition(plot);var dpi=VisualTreeHelper.GetDpi(plot);var xy=plot.Plot.GetCoordinates(new ScottPlot.Pixel((float)(position.X*dpi.DpiScaleX),(float)(position.Y*dpi.DpiScaleY)));ShowCursor(xy.X);};
    }
    public void SetChannels(int id,JsonArray channels){names[id]=channels.OfType<JsonObject>().ToDictionary(r=>r["index"]!.GetValue<int>(),r=>r["name"]!.ToString());if(id==objectId)Render(records,id,false);}
    private string ChannelName(int channel)=>names.TryGetValue(objectId,out var channels)&&channels.TryGetValue(channel,out var name)?name:$"CH{channel}";
    public void Render(JsonArray data,int id,bool fit)
    {
        records=data;objectId=id;var limits=plot.Plot.Axes.GetLimits();plot.Plot.Clear();cursor=null;highlights.Clear();legend.Children.Clear();
        int count=records.FirstOrDefault()?["values"]?.AsArray().Count??(names.TryGetValue(id,out var channels)?channels.Count:0);
        for(int index=0;index<count;index++){
            int channel=index;bool visible=!hidden.Contains((id,index));var color=ColorFor(index);
            var button=new Button{Content="━  "+ChannelName(index),Foreground=visible?new SolidColorBrush(Color.FromRgb(color.R,color.G,color.B)):Brushes.Gray,Background=Brushes.Transparent,BorderThickness=new Thickness(0),Padding=new Thickness(6,3,6,3),Margin=new Thickness(0,0,6,4),ToolTip="点击显示/隐藏此通道"};
            button.Click+=(_,_)=>{if(!hidden.Add((id,channel)))hidden.Remove((id,channel));Render(records,id,false);};legend.Children.Add(button);
            if(visible&&records.Count>0){var line=plot.Plot.Add.Scatter(records.Select(r=>r!["time"]!.GetValue<double>()).ToArray(),records.Select(r=>r!["values"]![index]!.GetValue<double>()).ToArray());line.Color=color;line.MarkerSize=0;}
        }
        plot.Plot.HideLegend();plot.Plot.XLabel("Time (s)");plot.Plot.YLabel("Value");if(fit&&records.Count>0)plot.Plot.Axes.AutoScale();else plot.Plot.Axes.SetLimits(limits);plot.Refresh();
        if(TriggerMetadata?["trigger_display_index"] is JsonNode triggerIndex&&TriggerMetadata?["period_us"] is JsonNode period){
            double index=triggerIndex.GetValue<double>();double sampleCount=TriggerMetadata["count"]?.GetValue<double>()??records.Count;
            if(index>=0&&index<sampleCount){var trigger=plot.Plot.Add.VerticalLine(index*period.GetValue<double>()/1e6);trigger.Color=ScottPlot.Colors.Orange;trigger.LinePattern=ScottPlot.LinePattern.Dashed;trigger.LineWidth=2;plot.Refresh();}
        }
    }
    public void ShowCursor(double time)
    {
        if(records.Count==0)return;
        var row=records.OfType<JsonObject>().MinBy(r=>Math.Abs(r["time"]!.GetValue<double>()-time))!;
        double sampleTime=row["time"]!.GetValue<double>();if(cursor!=null)plot.Plot.Remove(cursor);cursor=plot.Plot.Add.VerticalLine(sampleTime);cursor.Color=ScottPlot.Colors.Gray;
        foreach(var highlight in highlights)plot.Plot.Remove(highlight);highlights.Clear();
        for(int index=0;index<row["values"]!.AsArray().Count;index++){
            if(hidden.Contains((objectId,index)))continue;
            double value=row["values"]![index]!.GetValue<double>();if(!double.IsFinite(value))continue;
            var marker=plot.Plot.Add.Marker(sampleTime,value);marker.Color=ColorFor(index);marker.Size=9;highlights.Add(marker);
            var label=plot.Plot.Add.Text($"{ChannelName(index)} = {value:G7}",sampleTime,value);label.LabelFontColor=ColorFor(index);label.LabelFontSize=13;label.LabelBold=true;label.LabelAlignment=sampleTime>(plot.Plot.Axes.GetLimits().Left+plot.Plot.Axes.GetLimits().Right)/2?ScottPlot.Alignment.LowerRight:ScottPlot.Alignment.LowerLeft;highlights.Add(label);
        }
        values.Text=$"t = {sampleTime:G7} s    "+string.Join("    ",row["values"]!.AsArray().Select((value,index)=>$"{ChannelName(index)} = {value!.GetValue<double>():G7}"));plot.Refresh();
    }
}
