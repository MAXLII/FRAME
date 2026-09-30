using System.Text.Json.Nodes;
using System.Windows.Controls;
using Frame.Desktop;
using ScottPlot.WPF;

internal static class WaveViewportTests
{
    public static void Run()
    {
        var chart=new WpfPlot();
        var panel=new WavePlotPanel(chart);
        var series=new WaveSeriesPanel();
        series.AttachPlots(panel);
        foreach(double start in new[]{0d,1000d,1704067200d}){
            panel.ResetView();
            var rows=new JsonArray(Enumerable.Range(0,101).Select(i=>(JsonNode)new JsonObject{
                ["name"]="V_ALPHA",["time"]=start+i*0.001,["value"]=Math.Sin(i*0.1)
            }).ToArray());
            var range=panel.PrepareView(start+0.1,1);
            var visible=new JsonArray(rows.Where(r=>r!["time"]!.GetValue<double>()>=range.Left&&r["time"]!.GetValue<double>()<=range.Right).Select(r=>r!.DeepClone()).ToArray());
            if(visible.Count!=rows.Count)throw new Exception($"First waveform batch was clipped at {start}s: {visible.Count}/{rows.Count}");
            series.Update(visible);series.SetSeriesVisible("V_ALPHA",true);
            panel.Render(visible,series,true);
            var limits=chart.Plot.Axes.GetLimits();
            if(Math.Abs(limits.Right-limits.Left-1)>1e-6)throw new Exception("Initial window must retain its configured span");
            var single=new JsonArray(rows[0]!.DeepClone());
            panel.Render(single,series,true);
            if(chart.Plot.GetPlottables<ScottPlot.Plottables.Scatter>().Single().MarkerSize<=0)throw new Exception("Single sample must have a visible marker");
        }
        panel.ResetView();
        chart.Plot.Axes.SetLimits(999,1001,-2,2);
        var before=chart.Plot.Axes.GetLimits();
        for(int i=0;i<50;i++)panel.Render(new JsonArray(),series,true);
        var after=chart.Plot.Axes.GetLimits();
        if(after.Left!=before.Left||after.Right!=before.Right||after.Bottom!=before.Bottom||after.Top!=before.Top)throw new Exception("Empty refreshes must not expand axes");
        CheckPaneReordering();
        Console.WriteLine("PASS: first batches at 0s, 1000s and host time, single samples, and stable empty axes.");
    }

    private static void CheckPaneReordering()
    {
        var firstChart=new WpfPlot();var panel=new WavePlotPanel(firstChart);
        int first=panel.PlotIds[0],second=panel.AddPlot(),third=panel.AddPlot();
        var stack=(StackPanel)((ScrollViewer)panel.Content).Content;
        var originalFrames=stack.Children.Cast<Border>().ToArray();
        var charts=originalFrames.Select(frame=>((DockPanel)frame.Child).Children.OfType<WpfPlot>().Single()).ToArray();
        var series=new WaveSeriesPanel();series.AttachPlots(panel);
        foreach(string name in new[]{"A","B","C"})series.SetSeriesVisible(name,true);
        panel.Assign("B",second);panel.Assign("C",third);
        var rows=new JsonArray(new JsonObject{["name"]="A",["time"]=1d,["value"]=10d},new JsonObject{["name"]="B",["time"]=1d,["value"]=20d},new JsonObject{["name"]="C",["time"]=1d,["value"]=30d});
        foreach(var chart in charts)chart.Plot.Axes.SetLimits(0,2,-40,40);
        panel.Render(rows,series,false);
        int activeChanges=0;panel.ActiveChanged+=_=>activeChanges++;
        void CheckOrder(params int[] ids)
        {
            if(!panel.PlotIds.SequenceEqual(ids)||!stack.Children.Cast<Border>().SequenceEqual(ids.Select(id=>originalFrames[id-first])))throw new Exception("Wave pane order must match the visible frames");
            if(panel.PlotFor("A")!=first||panel.PlotFor("B")!=second||panel.PlotFor("C")!=third)throw new Exception("Moving panes must retain default and explicit curve assignments");
            panel.Render(rows,series,false);
            for(int i=0;i<charts.Length;i++){
                if(charts[i].Plot.GetPlottables<ScottPlot.Plottables.Scatter>().Single().LegendText!=new[]{"A","B","C"}[i])throw new Exception("Refreshed curves must remain in their original pane after reordering");
                var limits=charts[i].Plot.Axes.GetLimits();
                if(limits.Left!=0||limits.Right!=2||limits.Bottom!=-40||limits.Top!=40)throw new Exception("Reordering must retain plot zoom");
            }
            if(activeChanges!=0)throw new Exception("Reordering must retain the active plot");
        }
        panel.MovePlot(first,third,true);CheckOrder(second,third,first);
        panel.MovePlot(first,second,false);CheckOrder(first,second,third);
        panel.MovePlot(third,second,false);CheckOrder(first,third,second);
        panel.MovePlot(third,third,true);panel.MovePlot(-1,first,false);panel.MovePlot(first,-1,true);CheckOrder(first,third,second);
        panel.RemovePlot(first);
        if(panel.PlotFor("A")!=third||panel.PlotFor("C")!=third||panel.PlotFor("B")!=second)throw new Exception("Closing a reordered default pane must preserve remaining curves");
        Console.WriteLine("PASS: waveform panes move up/down with visual order, assignments, active plot, zoom and refresh preserved.");
    }
}
