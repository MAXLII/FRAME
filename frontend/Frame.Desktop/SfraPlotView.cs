using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using ScottPlot.WPF;

namespace Frame.Desktop;

public sealed class SfraPlotView : UserControl
{
    private readonly WpfPlot[] plots;
    private readonly bool[] visible={true,true};
    private readonly List<ScottPlot.IPlottable>[] cursors={new(),new()};
    private JsonObject[] points=Array.Empty<JsonObject>();
    private readonly string[] names={"增益 / dB","相位 / °"};
    private readonly string[] keys={"db","phase"};
    private readonly ScottPlot.Color[] colors={ScottPlot.Color.FromHex("#2563EB"),ScottPlot.Color.FromHex("#DC2626")};
    public event Action? ViewChanged;
    public SfraPlotView(WpfPlot gain,WpfPlot phase)
    {
        plots=new[]{gain,phase};var grid=new Grid();Content=grid;
        for(int i=0;i<2;i++){
            int pane=i;grid.RowDefinitions.Add(new(){Height=new GridLength(1,GridUnitType.Star)});
            var body=new DockPanel{Margin=new Thickness(0,0,0,6)};Grid.SetRow(body,i);grid.Children.Add(body);
            var color=colors[i];var legend=new Button{Content="━  "+names[i],HorizontalAlignment=HorizontalAlignment.Left,Foreground=new SolidColorBrush(Color.FromRgb(color.R,color.G,color.B)),Background=Brushes.Transparent,BorderThickness=new Thickness(0),Padding=new Thickness(6,3,6,3),Margin=new Thickness(0,0,0,4)};
            DockPanel.SetDock(legend,Dock.Top);body.Children.Add(legend);body.Children.Add(plots[i]);
            legend.Click+=(_,_)=>{visible[pane]=!visible[pane];legend.Foreground=visible[pane]?new SolidColorBrush(Color.FromRgb(colors[pane].R,colors[pane].G,colors[pane].B)):Brushes.Gray;Draw(false);};
            plots[i].Plot.Layout.Fixed(new ScottPlot.PixelPadding(85,24,55,16));
            plots[i].MouseMove+=(_,e)=>{var p=e.GetPosition(plots[pane]);var dpi=VisualTreeHelper.GetDpi(plots[pane]);var xy=plots[pane].Plot.GetCoordinates(new ScottPlot.Pixel((float)(p.X*dpi.DpiScaleX),(float)(p.Y*dpi.DpiScaleY)));ShowCursor(xy.X);};
            plots[i].MouseUp+=(_,_)=>Sync(pane);PlotWheelZoom.Attach(plots[i],()=>Sync(pane));
        }
    }
    private void Sync(int pane){var x=plots[pane].Plot.Axes.GetLimits();foreach(var plot in plots){plot.Plot.Axes.SetLimitsX(x.Left,x.Right);plot.Refresh();}ViewChanged?.Invoke();}
    public void Render(JsonArray records,bool fit){points=records.OfType<JsonObject>().Where(p=>p["frequency"]!=null&&p["frequency"]!.GetValue<double>()>0).OrderBy(p=>p["frequency"]!.GetValue<double>()).ToArray();Draw(fit);}
    public void FitWindow()=>Draw(true);
    private void Draw(bool fit)
    {
        for(int i=0;i<2;i++){
            var chart=plots[i];var limits=chart.Plot.Axes.GetLimits();chart.Plot.Clear();cursors[i].Clear();
            var rows=points.Where(p=>p[keys[i]]!=null&&double.IsFinite(p[keys[i]]!.GetValue<double>())).ToArray();
            if(visible[i]&&rows.Length>0){var line=chart.Plot.Add.Scatter(rows.Select(p=>Math.Log10(p["frequency"]!.GetValue<double>())).ToArray(),rows.Select(p=>p[keys[i]]!.GetValue<double>()).ToArray());line.Color=colors[i];line.MarkerSize=5;}
            chart.Plot.Axes.Bottom.TickGenerator=new ScottPlot.TickGenerators.NumericAutomatic{LabelFormatter=x=>Math.Pow(10,x).ToString("G4")};chart.Plot.XLabel("Frequency (Hz)");chart.Plot.YLabel(i==0?"Gain (dB)":"Phase (°)");chart.Plot.HideLegend();
            if(fit&&rows.Length>0){chart.Plot.Axes.AutoScale();var x=points.Select(p=>Math.Log10(p["frequency"]!.GetValue<double>())).ToArray();double margin=Math.Max(.05,(x.Max()-x.Min())*.05);chart.Plot.Axes.SetLimitsX(x.Min()-margin,x.Max()+margin);}else chart.Plot.Axes.SetLimits(limits);chart.Refresh();
        }
    }
    public void ShowCursor(double logFrequency)
    {
        if(points.Length==0)return;var point=points.MinBy(p=>Math.Abs(Math.Log10(p["frequency"]!.GetValue<double>())-logFrequency))!;
        double frequency=point["frequency"]!.GetValue<double>(),x=Math.Log10(frequency);
        for(int i=0;i<2;i++){
            var chart=plots[i];foreach(var item in cursors[i])chart.Plot.Remove(item);cursors[i].Clear();
            var vertical=chart.Plot.Add.VerticalLine(x);vertical.Color=ScottPlot.Colors.Gray;cursors[i].Add(vertical);
            if(visible[i]&&point[keys[i]]!=null){double y=point[keys[i]]!.GetValue<double>();if(double.IsFinite(y)){var marker=chart.Plot.Add.Marker(x,y);marker.Size=9;marker.Color=colors[i];cursors[i].Add(marker);var label=chart.Plot.Add.Text($"{frequency:G6} Hz · {y:G6} {(i==0?"dB":"°")}",x,y);label.LabelFontColor=colors[i];label.LabelBold=true;label.LabelAlignment=x>(chart.Plot.Axes.GetLimits().Left+chart.Plot.Axes.GetLimits().Right)/2?ScottPlot.Alignment.LowerRight:ScottPlot.Alignment.LowerLeft;cursors[i].Add(label);}}
            chart.Refresh();
        }
    }
}
