using System.Reflection;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using Frame.Client;
using Frame.Desktop;

internal static class RealtimeScopePanTests
{
    private const BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    private static T Field<T>(object instance, string name) => (T)instance.GetType().GetField(name, Private)!.GetValue(instance)!;
    private static void Set(object instance, string name, object value) => instance.GetType().GetField(name, Private)!.SetValue(instance, value);
    private static object? Call(object instance, string name, params object[] args) => instance.GetType().GetMethod(name, Private)!.Invoke(instance, args);
    private static void Require(bool condition, string message) { if (!condition) throw new Exception(message); }
    private static Point At(ScottPlot.WPF.WpfPlot plot, double x, double y)
    {
        var pixel = plot.Plot.GetPixel(new ScottPlot.Coordinates(x, y)); var dpi = VisualTreeHelper.GetDpi(plot);
        return new(pixel.X / dpi.DpiScaleX, pixel.Y / dpi.DpiScaleY);
    }
    public static async Task Run()
    {
        foreach (string state in new[] { "running", "frozen", "stopped" }) {
            await using var client = new BackendClient();
            var fields = new Dictionary<string, TextBox>();
            var page = new RealtimeScopePage(client, fields, _ => { });
            var window = new Window { Content = page, Width = 1200, Height = 780, ShowInTaskbar = false };
            window.Show(); window.UpdateLayout(); await Task.Delay(40);
            try {
                Field<ComboBox>(page, "sourceChoice").SelectedIndex = 1;
                fields["realtime_frequency"].Text = "1000"; fields["realtime_history"].Text = "4"; fields["realtime_window_ms"].Text = "1000";
                for (int channel = 1; channel <= 2; channel++) page.Workspace.Configuration.Add(new(new JsonObject {
                    ["name"] = "channel" + channel, ["kind"] = "scalar", ["type_name"] = "float", ["size"] = 4, ["encoding"] = 4, ["address"] = 0x20001000u }), channel);
                var preview = new RealtimeScopePreview(page.Workspace.Configuration, 1000, 4);
                for (int sample = 0; sample < 5000; sample++) preview.Append(new Dictionary<int, double> { [1] = 0.5, [2] = 0.7 });
                Set(page, "preview", preview); Set(page, "previewRunning", state != "stopped");
                Call(page, "UpdateSources"); Call(page, "ConfigurePreviewCore");
                if (state == "frozen") preview.PauseDisplay();
                Call(page, "CaptureSnapshot"); Call(page, "RenderSnapshot");
                var plot = Field<ScottPlot.WPF.WpfPlot>(page, "plot");
                var dpi = VisualTreeHelper.GetDpi(plot);
                plot.Plot.RenderInMemory((int)(plot.ActualWidth * dpi.DpiScaleX), (int)(plot.ActualHeight * dpi.DpiScaleY));
                long count = preview.NextSample; double scale = page.Workspace.Displays[1].UnitsPerDivision;
                var raw = preview.Samples(1, 2000, 3000);
                var limits = plot.Plot.Axes.GetLimits();
                var blank = At(plot, (limits.Left + limits.Right) / 2, 3);
                Require((bool)Call(page, "BeginWaveformDrag", blank)!, state + ": blank area must start a pan");
                Call(page, "MoveWaveformDrag", new Point(blank.X + 80, blank.Y - 45)); Call(page, "EndWaveformDrag");
                var moved = plot.Plot.Axes.GetLimits();
                Require(moved.Left < limits.Left && Math.Abs((moved.Right - moved.Left) - 1000) < 1e-8 && moved.Bottom == -4 && moved.Top == 4,
                    state + ": blank drag must pan time only without scaling axes");
                Require(!Field<bool>(page, "follow") && page.Workspace.Displays.Take(2).All(display => display.Position == 0),
                    state + ": blank drag must leave both channel positions alone and suspend following");
                if (state == "running") {
                    for (int sample = 0; sample < 50; sample++) preview.Append(new Dictionary<int, double> { [1] = 0.5, [2] = 0.7 });
                    count += 50;
                }
                Call(page, "CaptureSnapshot"); Call(page, "RenderSnapshot");
                Require(Math.Abs(plot.Plot.Axes.GetLimits().Left - moved.Left) < 1e-8, state + ": refresh must not undo a pan");
                Set(page, "follow", true); Call(page, "CaptureSnapshot"); Call(page, "RenderSnapshot");
                limits = plot.Plot.Axes.GetLimits();
                var nearSecond = At(plot, (limits.Left + limits.Right) / 2, 0.68);
                var frozen = Field<Dictionary<int, double[]>>(page, "rawSnapshot")[1];
                Require((bool)Call(page, "BeginWaveformDrag", nearSecond)!, state + ": a nearby waveform must be draggable");
                Require(Field<RealtimeScopeChannel>(page, "draggedWaveform").Number == 2, state + ": choose the closest trace when both are nearby");
                double height = Field<double>(page, "waveformDragHeight");
                Call(page, "MoveWaveformDrag", new Point(nearSecond.X + 50, nearSecond.Y - height / 8)); Call(page, "EndWaveformDrag");
                Require(Math.Abs(page.Workspace.Displays[1].Position - 1) < 1e-8 && page.Workspace.Displays[0].Position == 0 &&
                    page.Workspace.Displays[1].UnitsPerDivision == scale && Field<bool>(page, "follow"),
                    state + ": trace drag must move only the nearest channel without changing scale or following");
                Require(Math.Abs(plot.Plot.Axes.GetLimits().Left - limits.Left) < 1e-8 && preview.NextSample == count && preview.Samples(1, 2000, 3000).SequenceEqual(raw),
                    state + ": trace drag must preserve time limits, sample count and raw values");
                if (state != "running") Require(ReferenceEquals(frozen, Field<Dictionary<int, double[]>>(page, "rawSnapshot")[1]), state + ": retained raw history must not be replaced by display moves");
                fields["realtime_window_ms"].Text = "4000"; Call(page, "ConfigurePreviewCore");
                Call(page, "CaptureSnapshot"); Call(page, "RenderSnapshot");
                limits = plot.Plot.Axes.GetLimits(); blank = At(plot, (limits.Left + limits.Right) / 2, 3);
                Call(page, "BeginWaveformDrag", blank); Call(page, "MoveWaveformDrag", new Point(blank.X + 80, blank.Y)); Call(page, "EndWaveformDrag");
                Require(plot.Plot.Axes.GetLimits().Left < limits.Left && plot.Plot.GetPlottables<ScottPlot.Plottables.Scatter>().Any(),
                    state + ": a window equal to history capacity must still be draggable with retained data visible");
            }
            finally { page.Shutdown(); await page.ShutdownCompletion; window.Close(); }
        }
        Console.WriteLine("PASS: running/frozen/stopped blank-area time pan, nearest-trace independent vertical drag, stable raw samples/scales, refresh persistence and full-history window movement.");
    }
}
