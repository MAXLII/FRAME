using System.Buffers.Binary;
using System.Collections.Concurrent;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Frame.Client;
using Frame.Desktop;

internal static class RealtimeScopeConfigurationTests
{
    private static void Require(bool condition, string message) { if (!condition) throw new Exception(message); }
    private static T Field<T>(object instance, string name) => (T)instance.GetType().GetField(name, BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(instance)!;
    private static ushort Crc(byte[] bytes) {
        ushort crc = 0xFFFF;
        foreach (byte value in bytes) {
            crc ^= (ushort)(value << 8);
            for (int bit = 0; bit < 8; bit++) crc = unchecked((ushort)((crc & 0x8000) != 0 ? crc << 1 ^ 0x1021 : crc << 1));
        }
        return crc;
    }
    public static async Task RunHardware(MainWindow window, string root, string[] args)
    {
        string Arg(string key) => args[Array.IndexOf(args, key) + 1];
        string path = Path.GetFullPath(Arg("--elf")), port = Arg("--port");
        string host = args.Contains("--host") ? Arg("--host") : "192.168.1.17";
        var common = Field<BackendClient>(window, "client");
        var pages = Field<System.Collections.IDictionary>(window, "pages");
        ((ListBox)window.FindName("Navigation")).SelectedIndex = pages.Keys.Cast<string>().ToList().IndexOf("realtime-scope");
        var state = pages["realtime-scope"]!;
        var page = (RealtimeScopePage)state.GetType().GetField("Diagnostic")!.GetValue(state)!;
        string output = args.Contains("--output") ? Path.GetFullPath(Arg("--output")) : Path.Combine(root, "build/scope-configuration-hardware"); Directory.CreateDirectory(output);
        var report = new JsonObject { ["hardware"] = true, ["passed"] = false, ["port"] = port, ["elf"] = path };
        bool demoParameters = args.Contains("--demo-parameters");
        double? originalAmplitude = null, originalFrequency = null;
        async Task<JsonNode?> Query(JsonObject command) {
            var result = await common.ExecuteAsync(command);
            Require(result["ok"]?.GetValue<bool>() == true, result.ToJsonString());
            return result["data"];
        }
        async Task<JsonObject> Execute(JsonObject command) => (await Query(command))!.AsObject();
        Task<JsonObject> WriteParameter(string name, double value) => Execute(new() { ["group"] = "param", ["action"] = "write", ["name"] = name,
            ["value"] = value.ToString("R", System.Globalization.CultureInfo.InvariantCulture) });
        async Task SetDemo(double amplitude, int hz) {
            await WriteParameter("DEMO_SCOPE_AMPLITUDE", amplitude);
            await WriteParameter("DEMO_SCOPE_FREQUENCY", hz);
            var a = await Execute(new() { ["group"] = "param", ["action"] = "read", ["name"] = "DEMO_SCOPE_AMPLITUDE" });
            var f = await Execute(new() { ["group"] = "param", ["action"] = "read", ["name"] = "DEMO_SCOPE_FREQUENCY" });
            Require(Math.Abs(a["value"]!.GetValue<double>() - amplitude) < 1e-5 && f["value"]!.GetValue<double>() == hz,
                "Physical amplitude/frequency parameter readback mismatch");
        }
        try {
            await Execute(args.Contains("--control-tcp")
                ? new() { ["group"] = "connect", ["transport"] = "tcp", ["host"] = host, ["tcp_port"] = 5000, ["dst"] = 2, ["wire"] = "e8" }
                : new() { ["group"] = "connect", ["transport"] = "serial", ["port"] = port, ["baud"] = 115200, ["dst"] = 2, ["wire"] = "e8" });
            if (demoParameters) {
                var directory = (await Query(new() { ["group"] = "param", ["action"] = "list" }))!.AsArray();
                Require(new[] { "DEMO_SCOPE_AMPLITUDE", "DEMO_SCOPE_FREQUENCY" }.All(name => directory.Any(row => row!["name"]!.ToString() == name)),
                    "Physical parameter directory is missing the writable waveform settings");
                originalAmplitude = (await Execute(new() { ["group"] = "param", ["action"] = "read", ["name"] = "DEMO_SCOPE_AMPLITUDE" }))["value"]!.GetValue<double>();
                originalFrequency = (await Execute(new() { ["group"] = "param", ["action"] = "read", ["name"] = "DEMO_SCOPE_FREQUENCY" }))["value"]!.GetValue<double>();
                await SetDemo(2, 50);
                report["demo_parameters"] = new JsonArray();
            }
            Field<TextBox>(page, "elf").Text = path; Field<TextBox>(page, "map").Clear();
            foreach (var channel in page.Workspace.Configuration.Channels) channel.Assign(null);
            await page.SynchronizeParametersAsync();
            Task Expand(RealtimeScopeSymbol symbol) => page.ExpandAsync(symbol);
            var demo = Field<List<RealtimeScopeSymbol>>(page, "roots").Single(symbol => symbol.Name == "g_scope_demo");
            await Expand(demo);
            var wave = demo.Children.Single(symbol => symbol.Name == "g_scope_demo.wave"); await Expand(wave);
            page.AssignSymbol(wave.Children.Single(symbol => symbol.Name.EndsWith(".sine")), 1);
            page.AssignSymbol(wave.Children.Single(symbol => symbol.Name.EndsWith(".cosine")), 2);
            page.AssignSymbol(wave.Children.Single(symbol => symbol.Name.EndsWith(".square")), 32);
            await page.ChannelConfigurationCompletion;
            Require(Field<TextBlock>(page, "syncState").Text == "已同步" && page.PendingDeviceConfiguration.Count == 0,
                "Physical channel additions were not acknowledged");
            string rate = Field<TextBox>(page, "frequency").Text;
            Require(int.TryParse(rate, out int actual) && actual >= 0, "Physical sampling rate remained pending after adding channels");
            await page.SynchronizeParametersAsync();
            Require(Field<TextBlock>(page, "syncState").Text == "已同步" && Field<TextBox>(page, "frequency").Text == rate,
                "Physical full synchronization failed or lost the acknowledged rate");
            report["sample_hz"] = actual; report["channels"] = new JsonArray(1, 2, 32);
            report["status"] = (await Execute(new() { ["group"] = "realtime-scope-control", ["action"] = "status" })).DeepClone();
            Require(report["status"]!["running"]?.GetValue<bool>() == false, "Channel synchronization must leave acquisition stopped");
            if (args.Contains("--stream-seconds")) {
                int seconds = int.Parse(Arg("--stream-seconds"));
                foreach (var channel in page.Workspace.Configuration.Channels) channel.Assign(null);
                var counter = demo.Children.Single(symbol => symbol.Name.EndsWith(".sample_count"));
                for (int i = 1; i <= 8; i++) page.AssignSymbol(i <= 4 ? wave.Children[i - 1] : counter, i);
                await page.ChannelConfigurationCompletion;
                await page.SynchronizeParametersAsync();
                Field<TextBox>(page, "linkHost").Text = host;
                Field<TextBox>(page, "windowMs").Text = "1000";
                bool historyChecks = args.Contains("--history-checks");
                if (historyChecks) Field<CheckBox>(page, "triggerPause").IsChecked = false;
                await page.ScopeLink.ConnectAsync(new("tcp", "", 0, host, 9001));
                await (Task)typeof(RealtimeScopePage).GetMethod("StartSelectedSourceAsync", BindingFlags.Instance | BindingFlags.NonPublic)!.Invoke(page, null)!;
                long last = 0; double? previous = null; long gaps = 0;
                double[]? frozen = null, frozenCopy = null;
                long frozenEnd = 0; bool resumed = false; int scaleChanges = 0;
                double nextScale = 2;
                int parameterStage = 0;
                void MeasureDemo(double amplitude, int hz) {
                    var preview = page.Preview!;
                    var measurements = new JsonArray();
                    for (int channel = 1; channel <= 3; channel++) {
                        var raw = preview.Samples(channel, preview.NextSample - preview.SampleRate / 2, preview.NextSample - 1);
                        var measured = RealtimeScopeMeasurements.Calculate(raw, new(), preview.SampleRate);
                        double peak = channel == 1 ? amplitude : amplitude / 2;
                        // Triangle slope is 4*peak/period. The nearest sample can
                        // miss the apex by half a sample plus one 625-entry LUT step.
                        double tolerance = channel == 3
                            ? Math.Max(0.01, peak * (2.0 * hz / preview.SampleRate + 4.0 / 625) + 1e-6)
                            : Math.Max(0.01, peak * 0.01);
                        Require(measured?.Frequency is double frequency && Math.Abs(frequency - hz) < hz * 0.005 &&
                            Math.Abs(measured.Maximum - peak) < tolerance && Math.Abs(measured.Minimum + peak) < tolerance,
                            $"Physical CH{channel} does not match amplitude {amplitude}/frequency {hz}: {measured}");
                        measurements.Add(new JsonObject { ["channel"] = channel, ["minimum"] = measured!.Minimum,
                            ["maximum"] = measured.Maximum, ["frequency_hz"] = measured.Frequency, ["peak_tolerance"] = tolerance });
                    }
                    report["demo_parameters"]!.AsArray().Add(new JsonObject { ["amplitude"] = amplitude, ["waveform_hz"] = hz, ["measured"] = measurements });
                    Console.WriteLine($"PASS physical waveform parameters: amplitude {amplitude}, frequency {hz} Hz; CH1/2/3 peaks and periods match");
                }
                var configure = typeof(RealtimeScopePage).GetMethod("ConfigurePreview", BindingFlags.Instance | BindingFlags.NonPublic)!;
                void SetWindow(string value) { Field<TextBox>(page, "windowMs").Text = value; configure.Invoke(page, null); }
                void Pause() => Field<Button>(page, "pauseButton").RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                var watch = System.Diagnostics.Stopwatch.StartNew();
                while (watch.Elapsed.TotalSeconds < seconds && page.PreviewRunning) {
                    await Task.Delay(250);
                    var preview = page.Preview!;
                    foreach (double value in preview.Samples(5, last, preview.NextSample - 1)) {
                        if (previous != null && value != previous + 1) gaps++;
                        previous = value;
                    }
                    last = preview.NextSample;
                    if (demoParameters) {
                        if (parameterStage == 0 && watch.Elapsed.TotalSeconds >= 2) { MeasureDemo(2, 50); await SetDemo(0.8, 25); parameterStage++; }
                        else if (parameterStage == 1 && watch.Elapsed.TotalSeconds >= 5) { MeasureDemo(0.8, 25); await SetDemo(3.2, 100); parameterStage++; }
                        else if (parameterStage == 2 && watch.Elapsed.TotalSeconds >= 8) { MeasureDemo(3.2, 100); parameterStage++; }
                        else if (parameterStage == 3 && watch.Elapsed.TotalSeconds >= 20) { await SetDemo(2, 50); parameterStage++; }
                        else if (parameterStage == 4 && watch.Elapsed.TotalSeconds >= 23) { MeasureDemo(2, 50); parameterStage++; }
                    }
                    if (historyChecks) {
                        if (frozen == null && watch.Elapsed.TotalSeconds >= 4) {
                            var expected = preview.Samples(5, preview.Oldest, preview.NextSample - 1);
                            Pause(); frozen = Field<Dictionary<int, double[]>>(page, "rawSnapshot")[5]; frozenCopy = frozen.ToArray();
                            frozenEnd = preview.NextSample;
                            Require(preview.DisplayPaused && frozen.SequenceEqual(expected), "Physical freeze did not retain all history");
                        }
                        if (frozen != null && !resumed && watch.Elapsed.TotalSeconds >= 16) {
                            Require(preview.Oldest > frozenEnd && frozen.SequenceEqual(frozenCopy!), "Physical frozen history changed after live-ring overwrite");
                            SetWindow("1000"); Pause(); resumed = true;
                        }
                        if (watch.Elapsed.TotalSeconds >= nextScale) {
                            long oldest = preview.Oldest, next = preview.NextSample;
                            var expected = preview.Samples(5, oldest, Math.Min(oldest + 127, next - 1));
                            string[] durations = ["50", "500", "5000", "0.01", "1000", "10000"];
                            SetWindow(durations[scaleChanges++ % durations.Length]);
                            Require(preview.NextSample == next && preview.Oldest == oldest &&
                                preview.Samples(5, oldest, Math.Min(oldest + 127, next - 1)).SequenceEqual(expected),
                                "Physical timebase change discarded or rewrote cached samples");
                            if (frozen != null && !resumed)
                                Require(preview.DisplayPaused && ReferenceEquals(frozen, Field<Dictionary<int, double[]>>(page, "rawSnapshot")[5]) && frozen.SequenceEqual(frozenCopy!),
                                    "Physical frozen timebase change replaced retained history");
                            nextScale += 2;
                        }
                    }
                }
                report["stream_seconds"] = watch.Elapsed.TotalSeconds; report["stream_samples"] = page.Preview!.NextSample;
                report["counter_gaps"] = gaps; report["last_fault"] = page.LastDeviceFault;
                report["stream_status"] = (await Execute(new() { ["group"] = "realtime-scope-control", ["action"] = "status" })).DeepClone();
                Require(page.PreviewRunning && gaps == 0 && report["stream_status"]!["overflows"]!.GetValue<int>() == 0,
                    "Physical GUI stream stopped, lost samples or overflowed: " + report.ToJsonString());
                if (demoParameters) {
                    Require(parameterStage == 5 && (await Execute(new() { ["group"] = "realtime-scope-control", ["action"] = "capabilities" }))["sample_frequency"]!.GetValue<int>() == actual,
                        "Waveform settings must not change the fixed sampling rate");
                    report["fixed_sampling_hz"] = actual;
                }
                page.StopPreview();
                if (historyChecks) {
                    Require(resumed && scaleChanges >= 8, "Physical history test did not complete freeze/overwrite/resume/zoom phases");
                    var preview = page.Preview!;
                    var stopped = Field<Dictionary<int, double[]>>(page, "rawSnapshot")[5];
                    var expected = preview.Samples(5, preview.Oldest, preview.NextSample - 1);
                    Require(stopped.Length == preview.Capacity && stopped.SequenceEqual(expected), "Physical stop retained less than the configured history");
                    foreach (string duration in new[] { "0.01", "50", "10000", "60" }) {
                        SetWindow(duration);
                        Require(ReferenceEquals(stopped, Field<Dictionary<int, double[]>>(page, "rawSnapshot")[5]) && stopped.SequenceEqual(expected),
                            "Physical stopped zoom discarded historical samples");
                    }
                    report["history_checks"] = new JsonObject { ["passed"] = true, ["timebase_changes"] = scaleChanges,
                        ["retained_samples_per_channel"] = stopped.Length, ["frozen_samples_per_channel"] = frozen!.Length,
                        ["live_overwrite_while_frozen"] = true, ["stopped_zoom_retained_full_capacity"] = true };
                }
                Console.WriteLine($"PASS physical GUI stream: {seconds} s, {last} samples, zero counter gaps/overflows");
            }
            window.UpdateLayout();
            var image = new RenderTargetBitmap((int)window.ActualWidth, (int)window.ActualHeight, 96, 96, PixelFormats.Pbgra32);
            image.Render(window); var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(image));
            using (var file = File.Create(Path.Combine(output, "page.png"))) encoder.Save(file);
            report["passed"] = true;
            Console.WriteLine($"PASS physical UI: COM {port}, incremental channels 1/2/32, full sync, sample rate {actual} Hz, stopped acquisition");
        }
        finally {
            await common.ExecuteAsync(new() { ["group"] = "realtime-scope-control", ["action"] = "stop" });
            if (originalAmplitude is double amplitude) await WriteParameter("DEMO_SCOPE_AMPLITUDE", amplitude);
            if (originalFrequency is double frequency) await WriteParameter("DEMO_SCOPE_FREQUENCY", frequency);
            await common.ExecuteAsync(new() { ["group"] = "disconnect" });
            File.WriteAllText(Path.Combine(output, "result.json"), report.ToJsonString(new() { WriteIndented = true }));
        }
    }
    public static async Task Run(string root)
    {
        string elf = Path.Combine(root, "build/symbol-fixture.elf");
        byte[] hash = SHA256.HashData(File.ReadAllBytes(elf));
        using var server = new TcpListener(IPAddress.Loopback, 0); server.Start();
        await using var common = new BackendClient();
        var fields = new Dictionary<string, TextBox>();
        string feedback = "";
        var page = new RealtimeScopePage(common, fields, text => feedback = text);
        var commands = new ConcurrentQueue<byte[]>();
        using var cancel = new CancellationTokenSource(TimeSpan.FromSeconds(40));
        Require((await common.ExecuteAsync(new() { ["group"] = "connect", ["transport"] = "tcp", ["wire"] = "e8",
            ["host"] = "127.0.0.1", ["tcp_port"] = ((IPEndPoint)server.LocalEndpoint).Port }))["ok"]!.GetValue<bool>(), "Configuration test connection failed");
        using var peer = await server.AcceptTcpClientAsync();
        int sampleRate = 0; bool reject = false;
        var responder = Task.Run(async () => {
            try {
                while (!cancel.IsCancellationRequested) {
                    byte[] header = new byte[11]; await peer.GetStream().ReadExactlyAsync(header, cancel.Token);
                    int size = BinaryPrimitives.ReadUInt16LittleEndian(header.AsSpan(9));
                    byte[] tail = new byte[size + 4]; await peer.GetStream().ReadExactlyAsync(tail, cancel.Token);
                    byte[] request = tail[..size]; commands.Enqueue(request);
                    byte status = 0; byte[] result = [];
                    if (request[0] == 1) {
                        result = new byte[46]; result[0] = 1; result[1] = 32;
                        BinaryPrimitives.WriteUInt32LittleEndian(result.AsSpan(2), (uint)sampleRate);
                        BinaryPrimitives.WriteUInt32LittleEndian(result.AsSpan(6), 1000000);
                        hash.CopyTo(result, 10); BinaryPrimitives.WriteUInt32LittleEndian(result.AsSpan(42), (uint)sampleRate);
                    }
                    if (request[0] is 3 or 4) { result = new byte[4]; BinaryPrimitives.WriteUInt32LittleEndian(result, (uint)sampleRate); }
                    if (request[0] == 4 && reject) { status = 2; reject = false; }
                    byte[] payload = [.. request[..3], status, .. result];
                    byte[] reply = [0xE8, 1, header[4], header[5], header[2], header[3], 1, 0x3A, 1, (byte)payload.Length, 0, .. payload, 0, 0, 13, 10];
                    BinaryPrimitives.WriteUInt16LittleEndian(reply.AsSpan(reply.Length - 4), Crc(reply[..^4]));
                    await peer.GetStream().WriteAsync(reply, cancel.Token);
                }
            }
            catch (Exception error) when (error is OperationCanceledException or EndOfStreamException or IOException or ObjectDisposedException) { }
        });
        try {
            fields["realtime_elf"].Text = elf;
            await page.SynchronizeParametersAsync();
            Require(fields["realtime_frequency"].Text == "0" && Field<TextBlock>(page, "syncState").Text == "已同步", "Zero Hz must allow full/empty channel synchronization");
            var symbol = Field<List<RealtimeScopeSymbol>>(page, "roots").First(item => item.CanSample);
            int before = commands.Count;
            page.AssignSymbol(symbol, 1); page.AssignSymbol(symbol, 32);
            await page.ChannelConfigurationCompletion;
            Require(commands.Skip(before).Select(item => item[0]).SequenceEqual(new byte[] { 4, 4 }), "Adding channels must immediately send ordered individual configuration commands");
            Require(fields["realtime_frequency"].Text == "0" && page.PendingDeviceConfiguration.Count == 0, "An acknowledged zero rate is known, not pending or a synchronization failure");
            sampleRate = 10000;
            before = commands.Count;
            page.AssignSymbol(symbol, 1); await page.ChannelConfigurationCompletion;
            Require(commands.Skip(before).Select(item => item[0]).SequenceEqual(new byte[] { 4 }) && fields["realtime_frequency"].Text == "10000", "Channel ACK must refresh rate without a separate capability poll");
            Field<DataGrid>(page, "channelTable").SelectedIndex = 31;
            Field<Button>(page, "removeButton").RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            await page.ChannelConfigurationCompletion;
            byte[] removal = commands.Last();
            Require(removal[0] == 4 && removal[3] == 32 && BinaryPrimitives.ReadUInt32LittleEndian(removal.AsSpan(5)) == 0,
                "Removing a resident channel must clear that slot on the MCU");
            reject = true; page.AssignSymbol(symbol, 2); await page.ChannelConfigurationCompletion;
            Require(Field<TextBlock>(page, "syncState").Text == "下发失败" && page.PendingDeviceConfiguration.Count > 0, "A rejected configuration cannot be shown as synchronized");
            before = commands.Count;
            await page.SynchronizeParametersAsync();
            Require(commands.Skip(before).Select(item => item[0]).SequenceEqual(new byte[] { 1, 2, 3, 4, 4 })
                && Field<TextBlock>(page, "syncState").Text == "已同步", "Parameter Sync must rebuild the complete resident list and recover after a rejected slot");
            foreach (var channel in page.Workspace.Configuration.Channels) channel.Assign(null);
            before = commands.Count; await page.SynchronizeParametersAsync();
            Require(commands.Skip(before).Select(item => item[0]).SequenceEqual(new byte[] { 1, 2, 3 }), "Empty synchronization must clear the device configuration");
            Require(!commands.Any(item => item[0] is 5 or 6), "Channel changes and synchronization must not activate sampling");
            before = commands.Count; await page.TickAsync(common.Snapshot());
            Require(commands.Count == before, "Idle UI ticks must not poll the sampling rate");
            VerifyAutoSet(page, fields, symbol);
            VerifyZoom(page, fields);
        }
        finally { page.Shutdown(); await page.ShutdownCompletion; cancel.Cancel(); peer.Dispose(); await responder; }
        Console.WriteLine("PASS: immediate channel ACKs, zero-Hz configuration, ACK rate refresh, removal, full/empty sync, failed ACK recovery and no polling");
    }
    private static void VerifyZoom(RealtimeScopePage page, Dictionary<string, TextBox> fields)
    {
        const BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
        var source = new RealtimeScopePreview(page.Workspace.Configuration, 31250, 2);
        source.Configure(1, new(false, 1, 0, RealtimeScopeEdge.Rising, 0.5, false));
        for (int n = 0; n < 31250; n++) source.Append(source.Channels.ToDictionary(channel => channel, channel => Math.Sin(n * 2 * Math.PI * 50 / 31250)));
        typeof(RealtimeScopePage).GetField("preview", flags)!.SetValue(page, source);
        fields["realtime_history"].Text = "2"; fields["realtime_window_ms"].Text = "1000";
        typeof(RealtimeScopePage).GetMethod("ConfigurePreviewCore", flags)!.Invoke(page, null);
        typeof(RealtimeScopePage).GetMethod("CaptureSnapshot", flags)!.Invoke(page, null);
        var raw = Field<Dictionary<int, double[]>>(page, "rawSnapshot");
        var held = raw[1]; var original = held.ToArray();
        var zoom = typeof(RealtimeScopePage).GetMethod("ZoomTime", flags)!;
        for (int i = 0; i < 18; i++) zoom.Invoke(page, [0.5d]);
        Require(raw.TryGetValue(1, out var remaining) && ReferenceEquals(held, remaining) && held.SequenceEqual(original),
            "Stopped zoom across Roll/trigger boundaries must retain the original raw snapshot");
        var plot = Field<ScottPlot.WPF.WpfPlot>(page, "plot");
        var limits = plot.Plot.Axes.GetLimits();
        var window = RealtimeScopeCurve.Window(held, 0, 1000d / 31250, limits.Left, limits.Right);
        Require(window.X.Length >= 2 && window.X[0] <= limits.Left && window.X[^1] >= limits.Right - 1000d / 31250 &&
            plot.Plot.GetPlottables<ScottPlot.Plottables.Scatter>().Any(), "Sub-sample zoom must retain adjacent samples and render the waveform");
        zoom.Invoke(page, [200000d]);
        Require(raw.Count > 0 && plot.Plot.GetPlottables<ScottPlot.Plottables.Scatter>().Any(), "Zooming back out to the history capacity must not erase a stopped trace");
        Console.WriteLine("PASS: stopped trace survives extreme time zoom and mode boundaries without modifying raw samples");
    }
    private static void VerifyAutoSet(RealtimeScopePage page, Dictionary<string, TextBox> fields, RealtimeScopeSymbol symbol)
    {
        Field<ComboBox>(page, "sourceChoice").SelectedIndex = 1;
        for (int channel = 1; channel <= 3; channel++) page.Workspace.Configuration.Add(symbol, channel);
        page.Workspace.Displays[2].Visible = false;
        foreach (var display in page.Workspace.Displays) display.UnitsPerDivision = 100;
        fields["realtime_frequency"].Text = "1000"; fields["realtime_history"].Text = "2"; fields["realtime_window_ms"].Text = "1000";
        var preview = new RealtimeScopePreview(page.Workspace.Configuration, 1000, 2);
        preview.Configure(1, new(false, 1, 0, RealtimeScopeEdge.Rising, 0.5, false));
        var data = new Dictionary<int, double[]> {
            [1] = Enumerable.Range(0, 1000).Select(i => 1000 + 2 * Math.Sin(2 * Math.PI * 10 * i / 1000)).ToArray(),
            [2] = Enumerable.Range(0, 1000).Select(i => 0.02 * Math.Sin(2 * Math.PI * 25 * i / 1000)).ToArray(),
            [3] = Enumerable.Range(0, 1000).Select(i => 500 * Math.Sin(2 * Math.PI * i / 1000)).ToArray()
        };
        for (int i = 0; i < 1000; i++) preview.Append(data.ToDictionary(item => item.Key, item => item.Value[i]));
        typeof(RealtimeScopePage).GetField("preview", BindingFlags.Instance | BindingFlags.NonPublic)!.SetValue(page, preview);
        var raw = Field<Dictionary<int, double[]>>(page, "rawSnapshot");
        foreach (var item in data) raw[item.Key] = item.Value.ToArray();
        typeof(RealtimeScopePage).GetMethod("AutoSet", BindingFlags.Instance | BindingFlags.NonPublic)!.Invoke(page, null);
        Require(page.Workspace.Displays[0].UnitsPerDivision == 1 && page.Workspace.Displays[1].UnitsPerDivision == 0.01,
            "Auto Set must independently fit each visible channel's amplitude, including small AC riding a large DC offset");
        Require(page.Workspace.Displays[2].UnitsPerDivision == 100, "Hidden channels must retain their scale");
        Require(Math.Abs(double.Parse(fields["realtime_window_ms"].Text, System.Globalization.CultureInfo.InvariantCulture) - 300) < 1,
            "Auto Set must fit three periods of the slowest visible periodic channel, ignoring hidden channels");
        Require(preview.NextSample == 1000 && preview.SampleRate == 1000 && preview.Samples(1, 0, 999).SequenceEqual(data[1]),
            "Auto Set must preserve all retained raw sample positions, values and sampling rate");
        raw.Clear(); raw[1] = Enumerable.Repeat(3.0, 1000).ToArray(); raw[2] = new double[1000];
        var dc = new RealtimeScopePreview(page.Workspace.Configuration, 1000, 2);
        for (int i = 0; i < 1000; i++) dc.Append(new Dictionary<int, double> { [1] = 3, [2] = 0, [3] = 100 });
        typeof(RealtimeScopePage).GetField("preview", BindingFlags.Instance | BindingFlags.NonPublic)!.SetValue(page, dc);
        fields["realtime_window_ms"].Text = "123";
        typeof(RealtimeScopePage).GetMethod("AutoSet", BindingFlags.Instance | BindingFlags.NonPublic)!.Invoke(page, null);
        Require(fields["realtime_window_ms"].Text == "123", "DC-only Auto Set must not invent a period or overwrite a useful time window");
        Console.WriteLine("PASS: Auto Set fits visible channel divisions and time window, preserves hidden scales/raw data, and handles DC");
    }
}
