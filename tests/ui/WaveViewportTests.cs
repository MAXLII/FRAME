using System.Text.Json.Nodes;
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
        Console.WriteLine("PASS: first batches at 0s, 1000s and host time, single samples, and stable empty axes.");
    }
}
