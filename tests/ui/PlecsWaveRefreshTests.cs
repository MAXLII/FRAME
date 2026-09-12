using System.Collections;
using System.IO;
using System.Reflection;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using Frame.Client;
using Frame.Desktop;

internal static class PlecsWaveRefreshTests
{
    public static async Task Run(MainWindow main, string root, string host)
    {
        const BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
        var client = (BackendClient)typeof(MainWindow).GetField("client", flags)!.GetValue(main)!;
        var pages = (IDictionary)typeof(MainWindow).GetField("pages", flags)!.GetValue(main)!;
        var wave = pages["wave"]!;
        var type = wave.GetType();
        var fields = (Dictionary<string, TextBox>)type.GetProperty("Fields")!.GetValue(wave)!;
        var pause = (CheckBox)type.GetProperty("Pause")!.GetValue(wave)!;
        var body = (Grid)type.GetProperty("Body")!.GetValue(wave)!;
        var latest = body.Children.OfType<WrapPanel>().SelectMany(bar => bar.Children.OfType<Button>()).Single(b => b.Content?.ToString() == "最新数据");
        var series = (WaveSeriesPanel)type.GetField("Series")!.GetValue(wave)!;
        JsonArray Records() => (JsonArray)type.GetProperty("Records")!.GetValue(wave)!;
        double Latest() => Records().Select(r => r!["time"]!.GetValue<double>()).DefaultIfEmpty(-1).Max();
        var connected = await client.ExecuteAsync(new() { ["group"] = "connect", ["transport"] = "tcp", ["host"] = host, ["tcp_port"] = 5000, ["dst"] = 2 });
        if (connected["ok"]?.GetValue<bool>() != true) throw new Exception(connected.ToJsonString());
        ((ListBox)main.FindName("Navigation")).SelectedIndex = 2;
        fields["window"].Text = "30"; fields["period"].Text = "1";
        await (Task)typeof(MainWindow).GetMethod("RunPageAsync", flags)!.Invoke(main, [wave, "capture"])!;
        for (int i = 0; i < 40 && Records().Count == 0; ++i) await Task.Delay(250);
        if (Records().Count == 0) throw new Exception("Live PLECS stream did not reach the waveform UI");
        series.Select(Records()[0]!["name"]!.ToString());
        var evidence = new JsonArray();
        async Task Observe(string stage, Action action)
        {
            double before = Latest(); action();
            await Task.Delay(1800);
            double after = Latest();
            var snapshot = client.Snapshot();
            evidence.Add(new JsonObject { ["stage"] = stage, ["before"] = before, ["after"] = after,
                ["display_records"] = Records().Count, ["paused"] = pause.IsChecked == true, ["rx_bytes"] = snapshot["rx_bytes"]!.DeepClone() });
            if (pause.IsChecked == true || after <= before) throw new Exception($"PLECS waveform stopped refreshing at {stage}: {before} -> {after}");
        }
        await Observe("normal", () => { });
        await Observe("latest_data", () => latest.RaiseEvent(new RoutedEventArgs(Button.ClickEvent)));
        await Observe("after_latest_data", () => { });
        await File.WriteAllTextAsync(Path.Combine(root, "build/plecs-ui-refresh.json"), evidence.ToJsonString(new() { WriteIndented = true }));
        Console.WriteLine("PASS: live PLECS TCP waveform advances before/after moving to latest data.");
        Console.WriteLine(evidence.ToJsonString());
    }
}
