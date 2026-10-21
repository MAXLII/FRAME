using System.Collections;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Frame.Client;
using Frame.Desktop;

// Explicit opt-in only: this test writes reversible demo parameters on a real board.
internal static class RealtimeScopeHardwareTests
{
    private const BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    private static T Field<T>(object target, string name) => (T)target.GetType().GetField(name, Private)!.GetValue(target)!;
    private static async Task Start(RealtimeScopePage page) => await (Task)typeof(RealtimeScopePage).GetMethod("StartSelectedSourceAsync", Private)!.Invoke(page, null)!;
    public static async Task Run(MainWindow window, string root, string[] args)
    {
        string Arg(string key) => args[Array.IndexOf(args, key) + 1];
        foreach (string option in new[] { "--port", "--host", "--elf" })
            if (!args.Contains(option)) throw new ArgumentException("Hardware test requires " + option);
        string port = Arg("--port"), host = Arg("--host"), elf = Path.GetFullPath(Arg("--elf"));
        int requestedRate = args.Contains("--frequency") ? int.Parse(Arg("--frequency"), CultureInfo.InvariantCulture) : 10000;
        string output = args.Contains("--output") ? Path.GetFullPath(Arg("--output")) : Path.Combine(root, "build/realtime-scope-hardware"); Directory.CreateDirectory(output);
        var report = new JsonObject { ["hardware"] = true, ["passed"] = false, ["port"] = port, ["host"] = host, ["elf"] = elf, ["requested_hz"] = requestedRate, ["checks"] = new JsonArray() };
        void Save() => File.WriteAllText(Path.Combine(output, "result.json"), report.ToJsonString(new() { WriteIndented = true }));
        void Check(string name, bool valid) {
            report["checks"]!.AsArray().Add(new JsonObject { ["name"] = name, ["passed"] = valid }); Save();
            if (!valid) throw new InvalidOperationException(name + " / " + ((TextBlock)window.FindName("Feedback")).Text);
            Console.WriteLine("PASS hardware: " + name);
        }
        var common = Field<BackendClient>(window, "client");
        ((ComboBox)window.FindName("Port")).Text = port;
        window.Title = "FRAME · 实时示波器真机验证";
        var pages = Field<IDictionary>(window, "pages");
        ((ListBox)window.FindName("Navigation")).SelectedIndex = pages.Keys.Cast<string>().ToList().IndexOf("realtime-scope");
        var state = pages["realtime-scope"]!;
        var page = (RealtimeScopePage)state.GetType().GetField("Diagnostic")!.GetValue(state)!;
        Field<TextBox>(page, "linkHost").Text = host;
        Field<TextBox>(page, "linkTcpPort").Text = "9001";
        async Task<JsonNode?> Execute(JsonObject command) {
            var response = await common.ExecuteAsync(command);
            if (response["ok"]?.GetValue<bool>() != true) throw new InvalidOperationException(response.ToJsonString());
            return response["data"];
        }
        Task<JsonNode?> Status() => Execute(new() { ["group"] = "realtime-scope-control", ["action"] = "status" });
        Task<JsonNode?> Write(string name, double value) => Execute(new() { ["group"] = "param", ["action"] = "write", ["name"] = name, ["value"] = value.ToString("R", CultureInfo.InvariantCulture) });
        async Task Wait(Func<bool> predicate, string message, int milliseconds = 8000) {
            var watch = Stopwatch.StartNew();
            while (!predicate() && watch.ElapsedMilliseconds < milliseconds) await Task.Delay(40);
            Check(message, predicate());
        }
        double[] Recent(int channel, int count = 100) => page.Preview?.Samples(channel, Math.Max(0, page.Preview.NextSample - count), page.Preview.NextSample - 1) ?? [];
        double? originalGain = null, originalCounter = null;
        try {
            await Execute(new() { ["group"] = "connect", ["transport"] = "serial", ["port"] = port, ["baud"] = 115200, ["dst"] = 2, ["wire"] = "e8", ["response_timeout"] = 3000 });
            report["capabilities"] = (await Execute(new() { ["group"] = "realtime-scope-control", ["action"] = "capabilities" }))?.DeepClone();
            requestedRate = report["capabilities"]!["sample_frequency"]!.GetValue<int>();
            Check("sampling rate is queried from firmware", requestedRate > 0 && Field<TextBox>(page, "frequency").IsReadOnly);
            originalGain = (await Execute(new() { ["group"] = "param", ["action"] = "read", ["name"] = "DEMO_SHELL_GAIN" }))!["value"]!.GetValue<double>();
            originalCounter = (await Execute(new() { ["group"] = "param", ["action"] = "read", ["name"] = "DEMO_SHELL_COUNTER" }))!["value"]!.GetValue<double>();
            await Write("DEMO_SHELL_GAIN", 1.25); await Write("DEMO_SHELL_COUNTER", 1234);
            var discovery = await RealtimeScopeConnection.DiscoverAsync(CancellationToken.None);
            Check("UDP discovery finds physical board", discovery["data"]!["devices"]!.AsArray().Any(d => d!["ip"]!.ToString() == host));
            Field<TextBox>(page, "elf").Text = elf;
            await page.OpenParameterPickerAsync();
            var parameters = Field<DataGrid>(page, "parameterTable");
            var symbols = parameters.Items.Cast<RealtimeScopeSymbol>().ToArray();
            var gain = symbols.Single(s => s.Name == "s_demo_shell_gain");
            var counter = symbols.Single(s => s.Name == "s_demo_shell_counter");
            var sampler = symbols.Single(s => s.Name == "scope");
            await page.ExpandAsync(sampler);
            var samples = sampler.Children.Single(s => s.Name == "scope.samples");
            page.AssignSymbol(gain, 1); page.AssignSymbol(counter, 5); page.AssignSymbol(samples, 32);
            report["channels"] = new JsonArray(page.Workspace.Configuration.Enabled.Select(c => (JsonNode)new JsonObject { ["channel"] = c.Number, ["name"] = c.Name, ["address"] = c.Address, ["type"] = c.Type }).ToArray());
            Check("ELF scalar and structure member addresses resolved", gain.CanSample && counter.CanSample && samples.CanSample);
            page.ParameterPicker!.Hide();
            if (args.Contains("--throughput")) {
                for (int channel = 1; channel <= 32; channel++) page.Workspace.Configuration.Channels[channel - 1].Assign(null);
                for (int channel = 1; channel <= 8; channel++) page.AssignSymbol(channel == 8 ? samples : channel % 2 == 0 ? counter : gain, channel);
                Field<TextBox>(page, "frequency").Text = requestedRate.ToString(CultureInfo.InvariantCulture);
                Field<TextBox>(page, "windowMs").Text = "200";
                await page.ScopeLink.ConnectAsync(new("tcp", "", 0, host, 9001));
                await Start(page);
                int actualRate = page.Preview!.SampleRate;
                int seconds = args.Contains("--seconds") ? int.Parse(Arg("--seconds"), CultureInfo.InvariantCulture) : 30;
                long first = page.Preview.NextSample;
                var timer = Stopwatch.StartNew();
                for (int second = 0; second < seconds; second++) {
                    await Task.Delay(1000);
                    if (!page.PreviewRunning) break;
                    var recent = Recent(8, 1000);
                    Check("8-channel sequence second " + (second + 1), recent.Length == 1000 && recent.Zip(recent.Skip(1)).All(pair => pair.Second - pair.First == 1));
                }
                var finalStatus = await Status();
                report["throughput_status"] = finalStatus?.DeepClone(); report["actual_hz"] = actualRate;
                report["acquisition_fault"] = page.LastDeviceFault;
                report["elapsed_seconds"] = timer.Elapsed.TotalSeconds; report["received_samples"] = page.Preview.NextSample - first;
                report["application_bytes_per_second"] = (page.Preview.NextSample - first) * 37 / timer.Elapsed.TotalSeconds;
                report["feedback"] = ((TextBlock)window.FindName("Feedback")).Text; Save();
                Check("8-channel sustained stream without overflow or timing fault", page.PreviewRunning && finalStatus!["running"]!.GetValue<bool>() && finalStatus["fault"]!.ToString() == "" && page.Preview.NextSample - first >= actualRate * (seconds - 1));
                Check("8-channel actual RAM values", Enumerable.Range(1, 7).All(c => Recent(c).All(v => v == (c % 2 == 0 ? 1234 : 1.25))));
                Check("receive-only data link", page.ScopeLink.Snapshot()["tx_bytes"]!.GetValue<long>() == 0);
                report["passed"] = true; Save(); return;
            }
            Field<TextBox>(page, "frequency").Text = "2000";
            Field<TextBox>(page, "windowMs").Text = "1000";
            Field<ComboBox>(page, "sourceChoice").SelectedIndex = 0;
            await page.ScopeLink.ConnectAsync(new("tcp", "", 0, host, 9001));
            await page.SynchronizeParametersAsync();
            Check("public USB configuration ACK", page.PendingDeviceConfiguration.Count == 0 && !page.BindingsNeedRefresh);
            await Start(page);
            await Wait(() => Recent(1).Length == 100 && Recent(1).All(v => v == 1.25) && Recent(5).All(v => v == 1234), "EA matches actual float and uint32 variables");
            await Write("DEMO_SHELL_GAIN", 2.5); await Write("DEMO_SHELL_COUNTER", 5678);
            await Wait(() => Recent(1).All(v => v == 2.5) && Recent(5).All(v => v == 5678), "public parameter writes change real Wi-Fi samples");
            var sequence = Recent(32);
            Check("structure member records consecutive ISR sample counts", sequence.Length == 100 && sequence.Zip(sequence.Skip(1)).All(p => p.Second - p.First == 1));
            await Write("DEMO_SHELL_GAIN", 1.25);
            await Wait(() => Recent(1).All(v => v == 1.25), "physical low level ready for trigger");
            Field<TextBox>(page, "windowMs").Text = "50"; Field<TextBox>(page, "level").Text = "1.75";
            typeof(RealtimeScopePage).GetMethod("ConfigurePreview", Private)!.Invoke(page, null);
            Field<ComboBox>(page, "triggerMode").SelectedIndex = 1;
            page.Preview!.Rearm(); await Write("DEMO_SHELL_GAIN", 2.5);
            await Wait(() => page.Preview.CompletedTrigger != null, "normal trigger captures a physical parameter edge");
            var capture = page.Preview.Window(); var edgeSamples = page.Preview.Samples(1, capture.First, capture.Last);
            Check("trigger has real samples before and after the edge", edgeSamples.Contains(1.25) && edgeSamples.Contains(2.5));
            Field<TextBox>(page, "windowMs").Text = "1000";
            typeof(RealtimeScopePage).GetMethod("ConfigurePreview", Private)!.Invoke(page, null);
            long beforeFreeze = page.Preview!.NextSample; page.Preview.PauseDisplay();
            await Wait(() => page.Preview.NextSample > beforeFreeze + 1000, "frozen display keeps receiving physical samples");
            page.Preview.Rearm(); page.StopPreview(); await Field<Task>(page, "deviceStopTask");
            Check("public STOP stops device sampler", (await Status())!["running"]!.GetValue<bool>() == false);
            Field<TextBox>(page, "frequency").Text = requestedRate.ToString(CultureInfo.InvariantCulture);
            await Start(page);
            var watch = Stopwatch.StartNew();
            await Task.Delay(12000);
            var device = await Status(); report["sustained_status"] = device?.DeepClone();
            report["sustained_seconds"] = watch.Elapsed.TotalSeconds; report["received_samples"] = page.Preview!.NextSample;
            Check("sustained requested frequency without overflow/deadline fault", page.PreviewRunning && device!["running"]!.GetValue<bool>() && device["fault"]!.ToString() == "" && page.Preview.NextSample > requestedRate * 11);
            sequence = Recent(32, 1000);
            Check("sustained stream is sequential and bounded", sequence.Length == 1000 && sequence.Zip(sequence.Skip(1)).All(p => p.Second - p.First == 1) && page.Preview.Capacity == requestedRate * 10);
            Check("data link transmits zero application bytes", page.ScopeLink.Snapshot()["tx_bytes"]!.GetValue<long>() == 0);
            window.Width = 1560; window.Height = 980;
            page.Workspace.Displays[0].UnitsPerDivision = 1;
            page.Workspace.Displays[4].UnitsPerDivision = 2000;
            page.Workspace.Displays[31].UnitsPerDivision = requestedRate * 3;
            await Task.Delay(100); window.UpdateLayout();
            var image = new RenderTargetBitmap((int)window.ActualWidth, (int)window.ActualHeight, 96, 96, PixelFormats.Pbgra32); image.Render(window);
            var png = new PngBitmapEncoder(); png.Frames.Add(BitmapFrame.Create(image));
            using (var file = File.Create(Path.Combine(output, "physical-scope.png"))) png.Save(file);
            page.StopPreview(); await Field<Task>(page, "deviceStopTask");
            // Reconnect the public serial session with E9; keep host channels resident.
            await Execute(new() { ["group"] = "disconnect" });
            await Execute(new() { ["group"] = "connect", ["transport"] = "serial", ["port"] = port, ["baud"] = 115200, ["dst"] = 2, ["wire"] = "e9", ["response_timeout"] = 3000 });
            await page.SynchronizeParametersAsync(); Field<TextBox>(page, "frequency").Text = "2000";
            await Start(page);
            await Wait(() => Recent(1).Length == 100 && Recent(1).All(v => v == 2.5), "E9 registered control, parameter resync and fresh restart");
            page.StopPreview(); await Field<Task>(page, "deviceStopTask");
            for (int channel = 2; channel < 32; ++channel) page.AssignSymbol(channel % 2 == 0 ? gain : counter, channel);
            Field<TextBox>(page, "frequency").Text = "10000";
            bool rejected = false;
            try { await Start(page); } catch (InvalidOperationException error) { rejected = error.Message.Contains("上限"); }
            Check("32-channel over-budget acquisition rejected before start", rejected);
            for (int channel = 9; channel <= 32; channel++) page.Workspace.Configuration.Channels[channel - 1].Assign(null);
            await Start(page);
            await Task.Delay(5000);
            Check("eight physical channels at fixed firmware rate", page.PreviewRunning && page.Preview!.NextSample > requestedRate * 4 &&
                Enumerable.Range(1, 8).All(c => Recent(c).Length == 100 && Recent(c).All(v => v == (c == 1 || c % 2 == 0 ? 2.5 : 5678))));
            report["eight_channel_status"] = (await Status())?.DeepClone();
            await page.ScopeLink.DisconnectAsync();
            await Wait(() => !page.PreviewRunning, "data disconnect stops page acquisition");
            await Field<Task>(page, "deviceStopTask");
            Check("data disconnect stops physical sampler and keeps public link", (await Status())!["running"]!.GetValue<bool>() == false && common.Snapshot()["connected"]!.GetValue<bool>());
            await Start(page);
            await Wait(() => Recent(1).Length == 100 && Recent(1).All(v => v == 2.5), "data reconnect restores retained channels");
            page.StopPreview(); await Field<Task>(page, "deviceStopTask");
            await Execute(new() { ["group"] = "disconnect" });
            await Execute(new() { ["group"] = "connect", ["transport"] = "tcp", ["host"] = host, ["tcp_port"] = 5000, ["dst"] = 2, ["wire"] = "e8", ["response_timeout"] = 3000 });
            await page.SynchronizeParametersAsync(); await Start(page);
            await Wait(() => Recent(1).Length == 100 && Recent(1).All(v => v == 2.5), "public TCP 5000 controls independent data TCP 9001");
            if (symbols.FirstOrDefault(s => s.Name == "g_scope_demo") is { } demo) {
                page.StopPreview(); await Field<Task>(page, "deviceStopTask");
                await page.ExpandAsync(demo);
                var wave = demo.Children.Single(s => s.Name == "g_scope_demo.wave");
                await page.ExpandAsync(wave);
                foreach (var channel in page.Workspace.Configuration.Channels) channel.Assign(null);
                var names = new[] { "sine", "cosine", "triangle", "square" };
                for (int i = 0; i < names.Length; i++) page.AssignSymbol(wave.Children.Single(s => s.Name == "g_scope_demo.wave." + names[i]), i + 1);
                Field<TextBox>(page, "frequency").Text = "5000";
                Field<TextBox>(page, "windowMs").Text = "200";
                await Start(page); await Task.Delay(6000);
                var sine = Recent(1, 25000); var cosine = Recent(2, 25000); var triangle = Recent(3, 25000); var square = Recent(4, 25000);
                Check("real device demo waveform ranges", sine.Length == 25000 && sine.Min() < -1.9 && sine.Max() > 1.9 &&
                    cosine.Min() < -0.95 && cosine.Max() > 0.95 && triangle.Min() < -0.9 && triangle.Max() > 0.9 &&
                    square.Contains(0) && square.Contains(1) && square.All(v => v == 0 || v == 1));
                var edges = Enumerable.Range(1, sine.Length - 1).Where(i => sine[i - 1] < 0 && sine[i] >= 0).ToArray();
                double measuredHz = (edges.Length - 1) * (double)page.Preview!.SampleRate / (edges.Last() - edges.First());
                report["demo_frequency_hz"] = measuredHz;
                report["demo_status"] = (await Status())?.DeepClone();
                report["demo_channels"] = new JsonArray(page.Workspace.Configuration.Enabled.Select(c => (JsonNode)new JsonObject { ["channel"] = c.Number, ["name"] = c.Name, ["address"] = c.Address }).ToArray());
                Check("real 10 Hz device demo without timing/overflow faults", measuredHz > 9.5 && measuredHz < 10.5 &&
                    report["demo_status"]!["fault"]!.ToString() == "" && page.PreviewRunning);
                for (int i = 0; i < 4; i++) {
                    page.Workspace.Displays[i].UnitsPerDivision = i == 3 ? 0.5 : 1;
                    page.Workspace.Displays[i].Position = 0;
                }
                Field<TextBox>(page, "windowMs").Text = "50"; Field<TextBox>(page, "level").Text = "0";
                Field<ComboBox>(page, "triggerSource").SelectedValue = 1;
                typeof(RealtimeScopePage).GetMethod("ConfigurePreview", Private)!.Invoke(page, null);
                await Task.Delay(250);
                await Task.Delay(100); window.UpdateLayout();
                var demoImage = new RenderTargetBitmap((int)window.ActualWidth, (int)window.ActualHeight, 96, 96, PixelFormats.Pbgra32); demoImage.Render(window);
                var demoPng = new PngBitmapEncoder(); demoPng.Frames.Add(BitmapFrame.Create(demoImage));
                using (var file = File.Create(Path.Combine(output, "device-demo.png"))) demoPng.Save(file);
            }
            report["passed"] = true;
        }
        catch (Exception error) { report["error"] = error.ToString(); throw; }
        finally {
            page.StopPreview(); await Field<Task>(page, "deviceStopTask");
            try { if (originalGain is double gain) await Write("DEMO_SHELL_GAIN", gain); if (originalCounter is double counter) await Write("DEMO_SHELL_COUNTER", counter); }
            catch (Exception error) { report["restore_error"] = error.Message; }
            report["feedback"] = ((TextBlock)window.FindName("Feedback")).Text;
            Save();
        }
    }
}
