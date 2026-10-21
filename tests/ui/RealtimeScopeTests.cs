using System.Collections;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Frame.Desktop;
using Frame.Client;

internal static class RealtimeScopeTests
{
    private static void Require(bool condition, string message) { if (!condition) throw new Exception(message); }
    private static RealtimeScopeSymbol Scalar(string name = "test") => new(new JsonObject { ["name"] = name, ["address"] = 0x20001000UL, ["kind"] = "scalar", ["type_name"] = "float", ["size"] = 4, ["encoding"] = 4 });
    private static IEnumerable<T> Logical<T>(DependencyObject root) where T : DependencyObject {
        foreach (var item in LogicalTreeHelper.GetChildren(root).OfType<DependencyObject>()) {
            if (item is T match) yield return match;
            foreach (var nested in Logical<T>(item)) yield return nested;
        }
    }
    private static T Control<T>(DependencyObject root, string id) where T : DependencyObject {
        var controls = DiagnosticPageTests.Visuals<T>(root);
        if (root is RealtimeScopePage { ParameterPicker: { } picker }) controls = controls.Concat(DiagnosticPageTests.Visuals<T>(picker));
        return controls.Distinct().Single(item => AutomationProperties.GetAutomationId(item) == id);
    }
    private static void Click(DependencyObject root, string id) => Control<Button>(root, id).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
    private static void Add(DataGrid table) => table.ContextMenu.Items.OfType<MenuItem>().Single(item => item.Header?.ToString() == "加入通道").RaiseEvent(new RoutedEventArgs(MenuItem.ClickEvent));
    private static void Models()
    {
        double[] knotsX = [0, 1, 2, 3, 4], knotsY = [0, 1, 1, -1, 0];
        var smooth = RealtimeScopeCurve.Interpolate(knotsX, knotsY);
        Require(knotsX.SequenceEqual(new double[] { 0, 1, 2, 3, 4 }) && knotsY.SequenceEqual(new double[] { 0, 1, 1, -1, 0 }), "Display interpolation must not modify source samples");
        for (int i = 0; i < knotsX.Length; i++) Require(smooth.Y[Array.IndexOf(smooth.X, knotsX[i])] == knotsY[i], "Interpolation must pass through every supplied sample");
        for (int i = 0; i < smooth.X.Length; i++) {
            int segment = Math.Min((int)Math.Floor(smooth.X[i]), knotsX.Length - 2);
            Require(smooth.Y[i] >= Math.Min(knotsY[segment], knotsY[segment + 1]) && smooth.Y[i] <= Math.Max(knotsY[segment], knotsY[segment + 1]), "Display interpolation must not create overshoot or new extrema");
        }
        var gap = RealtimeScopeCurve.Interpolate([0, 1, 2, 3], [1, double.NaN, 2, 3]);
        Require(double.IsNaN(gap.Y[Array.IndexOf(gap.X, 1d)]), "Missing samples must remain gaps");
        var dense = Enumerable.Range(0, 100000).Select(i => Math.Sin(i * 0.01)).ToArray();
        var envelope = RealtimeScopeCurve.Window(dense, 0, 0.032, 0, 3199.968, 200);
        var bounded = RealtimeScopeCurve.Interpolate(envelope.X, envelope.Raw, 800);
        Require(bounded.X.Length <= 1206 && dense[12345] == Math.Sin(12345 * 0.01),
            "Dense waveform rendering must remain bounded by the viewport budget without altering raw samples");
        var workspace = new RealtimeScopeWorkspace(); var b = workspace.Configuration;
        Require(workspace.Displays.All(display => display.Unit == "" && display.ScaleText == "1/div"), "Channels must default to no unit");
        foreach (int invalid in new[] { 0, 33 }) {
            try { b.Add(Scalar(), invalid); throw new Exception("Invalid channel accepted"); }
            catch (ArgumentOutOfRangeException) { }
        }
        b.Add(Scalar("last"), 32); b.Add(Scalar("first"), 1);
        Require(b.Enabled.Select(channel => channel.Number).SequenceEqual(new[] { 1, 32 }), "Sparse configuration must be ordered by channel number");
        workspace.Configuration.Add(Scalar("new"), 4);
        Require(ReferenceEquals(workspace.Configuration, b) && b.Channels[3].Symbol?.Name == "new", "One resident list must be updated directly");
        for (int number = 1; number <= 32; number++) workspace.Configuration.Add(Scalar(), number);
        Require(!workspace.Configuration.Add(Scalar()), "Channel 33 must report full");
        var channel = workspace.Displays[0]; channel.Unit = "A"; channel.UnitsPerDivision = 0.5; channel.Gain = 2; channel.Bias = 1; channel.Position = -1;
        Require(channel.Engineering(2) == 5 && channel.Divisions(2) == 9 && workspace.Displays[1].UnitsPerDivision == 1, "Each channel needs independent unit/div and gain/offset");
        try { channel.UnitsPerDivision = 0; throw new Exception("Zero unit/div accepted"); } catch (ArgumentOutOfRangeException) { }
        var unsupported = Scalar(); unsupported.Data["unsupported_location"] = true;
        Require(!unsupported.CanSample, "Unsupported DWARF locations and bitfields must not be draggable as ordinary scalars");

        var signals = new RealtimeScopeWorkspace(); signals.Configuration.Add(Scalar());
        foreach (double seconds in new[] { 0.05, 0.1, 0.2, 0.499999, 0.5, 0.500001, 0.6 }) {
            var engine = new RealtimeScopePreview(signals.Configuration, 10000, 1);
            engine.Configure(seconds, new(true, 1, 0, RealtimeScopeEdge.Rising, 0.5, true));
            engine.Advance(10000);
            Require(engine.IsRolling == (seconds >= 0.5) && engine.TriggerEnabled == (seconds < 0.5) &&
                (engine.CompletedTrigger != null) == (seconds < 0.5) && engine.DisplayPaused == (seconds < 0.5), $"500 ms mode boundary failed: {seconds}");
            if (engine.IsRolling) {
                long previousEnd = engine.Window().Last; engine.ForceTrigger(); engine.Advance(100);
                Require(engine.CompletedTrigger == null && !engine.SingleCompleted && engine.Window().Last > previousEnd, "Roll must ignore Force and continue moving its window");
            }
            long before = engine.NextSample; engine.Advance(6000);
            Require(engine.NextSample == before + 6000 && engine.Capacity == 10000 && engine.Oldest == engine.NextSample - 10000, "Paused display must keep bounded reception running");
            engine.Rearm(); Require(!engine.DisplayPaused, "Rearm must release the displayed capture");
        }
        Require(RealtimeScopePreview.Crosses(1, -1, 0, RealtimeScopeEdge.Falling) && !RealtimeScopePreview.Crosses(1, -1, 0, RealtimeScopeEdge.Rising), "Trigger edges must differ");
        var disabled = new RealtimeScopePreview(signals.Configuration, 10000, 0.5);
        disabled.Configure(0.05, new(false, 1, 0, RealtimeScopeEdge.Rising, 0.5, true)); disabled.Advance(2000);
        Require(!disabled.DisplayPaused && disabled.CompletedTrigger == null, "Disabled trigger must not freeze a small window");
        disabled.Configure(0.5, new(true, 33, double.NaN, RealtimeScopeEdge.Rising, double.NaN, true, RealtimeScopeTriggerMode.Single));
        disabled.Advance(3000);
        Require(disabled.IsRolling && !disabled.TriggerEnabled && !disabled.SingleCompleted && disabled.CompletedTrigger == null, "Roll must disregard all trigger settings, including an invalid source, level or pretrigger");
        foreach (var mode in new[] { RealtimeScopeTriggerMode.Auto, RealtimeScopeTriggerMode.Normal, RealtimeScopeTriggerMode.Single }) {
            var engine = new RealtimeScopePreview(signals.Configuration, 10000, 0.5);
            engine.Configure(0.05, new(true, 1, 10, RealtimeScopeEdge.Rising, 0.3, false, mode)); engine.Advance(3000);
            Require(engine.CanDisplay == (mode == RealtimeScopeTriggerMode.Auto), "Auto must free-run, Normal/Single must wait without a crossing");
            engine.ForceTrigger(); engine.Advance(1000);
            Require(engine.CompletedTrigger != null, "Force must complete a capture even at an unreachable level");
            long completed = engine.NextSample; engine.Advance(1000);
            Require(engine.SingleCompleted == (mode == RealtimeScopeTriggerMode.Single) && (engine.NextSample == completed) == (mode == RealtimeScopeTriggerMode.Single), "Single must stop sampling, other modes must keep receiving");
            if (mode == RealtimeScopeTriggerMode.Single) {
                var view = engine.Window(); long triggerAt = engine.CompletedTrigger!.Value;
                Require(triggerAt - view.First == 149 && view.Last - triggerAt == 350, "Trigger position must control pre/post samples");
            }
        }
        var samples = Enumerable.Range(0, 1000).Select(i => RealtimeScopePreview.Signal(1, i, 10000)).ToArray();
        var measured = RealtimeScopeMeasurements.Calculate(samples, new(), 10000)!;
        Require(Math.Abs(measured.Frequency!.Value - 50) < 0.001 && Math.Abs(measured.Rms - Math.Sqrt(0.5)) < 0.001 && Math.Abs(measured.Duty!.Value - 50) < 0.1 && Math.Abs(measured.PeakToPeak - 2) < 0.001, "Sine frequency, RMS, duty and peak-to-peak measurements failed");
        Require(RealtimeScopeMeasurements.Calculate([1, 1, 1], new(), 10000)!.Frequency == null && RealtimeScopeMeasurements.Calculate([double.NaN], new(), 10000) == null, "DC and invalid samples must not produce invented frequency");
        var received = new RealtimeScopeWorkspace(); received.Configuration.Add(Scalar("wire1"), 1); received.Configuration.Add(Scalar("wire32"), 32);
        var actual = new RealtimeScopePreview(received.Configuration, 1000, 1);
        actual.Configure(0.01, new(true, 1, 0, RealtimeScopeEdge.Rising, 0.5, true, RealtimeScopeTriggerMode.Normal));
        for (int i = 0; i < 20; i++) actual.Append(new Dictionary<int, double> { [1] = i < 10 ? -2 : 4, [32] = 17 });
        Require(actual.CompletedTrigger == 10 && actual.DisplayPaused && actual.Samples(32, 0, 19).All(value => value == 17), "Device history and trigger must use received values, not the demonstration signal");
        try { _ = new RealtimeScopePreview(signals.Configuration, 200000, 1000); throw new Exception("Unbounded history accepted"); } catch (ArgumentException) { }
        Console.WriteLine("PASS: 32 slots, sparse order, single resident list, independent scaling, trigger edges, strict <500ms boundary, rearm and bounded background reception.");
    }
    private static async Task IndependentLink(MainWindow window, RealtimeScopePage page)
    {
        const BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
        var common = (BackendClient)typeof(MainWindow).GetField("client", flags)!.GetValue(window)!;
        using var publicServer = new TcpListener(IPAddress.Loopback, 0); publicServer.Start();
        using var scopeServer = new TcpListener(IPAddress.Loopback, 0); scopeServer.Start();
        int publicPort = ((IPEndPoint)publicServer.LocalEndpoint).Port;
        int scopePort = ((IPEndPoint)scopeServer.LocalEndpoint).Port;
        async Task ConnectCommon()
        {
            var result = await common.ExecuteAsync(new() { ["group"] = "connect", ["transport"] = "tcp", ["host"] = "127.0.0.1", ["tcp_port"] = publicPort, ["wire"] = "e8" });
            Require(result["ok"]?.GetValue<bool>() == true, "Common loopback connection failed");
        }
        await ConnectCommon();
        using var publicPeer = await publicServer.AcceptTcpClientAsync().WaitAsync(TimeSpan.FromSeconds(2));
        Control<ComboBox>(page, "realtime_link_transport").SelectedIndex = 1;
        Control<TextBox>(page, "realtime_link_host").Text = "127.0.0.1";
        Control<TextBox>(page, "realtime_link_tcp_port").Text = scopePort.ToString();
        await page.ToggleScopeLinkAsync();
        using var scopePeer = await scopeServer.AcceptTcpClientAsync().WaitAsync(TimeSpan.FromSeconds(2));
        Require(common.Snapshot()["endpoint"]?.ToString() == $"tcp://127.0.0.1:{publicPort}" && page.ScopeLink.Snapshot()["endpoint"]?.ToString() == $"tcp://127.0.0.1:{scopePort}", "Scope and common links must use different native transports");
        long publicRx = common.Snapshot()["rx_bytes"]?.GetValue<long>() ?? 0;
        byte[] sample = [0xEA, 0x00, 0x12, 0x01, 0x00, 0xFD];
        await scopePeer.GetStream().WriteAsync(sample);
        for (int i = 0; i < 100 && (page.ScopeLink.Snapshot()["rx_bytes"]?.GetValue<long>() ?? 0) < sample.Length; i++) await Task.Delay(20);
        Require((page.ScopeLink.Snapshot()["rx_bytes"]?.GetValue<long>() ?? 0) >= sample.Length && (common.Snapshot()["rx_bytes"]?.GetValue<long>() ?? 0) == publicRx, "Private RX must not appear in the common connection");
        Require(scopePeer.Available == 0, "Opening the dedicated endpoint must not emit common E9 negotiation");
        await common.ExecuteAsync(new() { ["group"] = "disconnect" });
        Require(page.ScopeLink.Snapshot()["connected"]?.GetValue<bool>() == true, "Disconnecting common transport must not close scope transport");
        await ConnectCommon();
        using var nextPublicPeer = await publicServer.AcceptTcpClientAsync().WaitAsync(TimeSpan.FromSeconds(2));
        await page.ToggleScopeLinkAsync();
        Require(page.ScopeLink.Snapshot()["connected"]?.GetValue<bool>() == false && common.Snapshot()["connected"]?.GetValue<bool>() == true, "Disconnecting scope transport must not close common transport");
        await common.ExecuteAsync(new() { ["group"] = "disconnect" });
        Console.WriteLine("PASS: separate live TCP endpoints, independent RX, no common negotiation, common disconnect/reconnect isolation and scope disconnect isolation.");
    }
    private static MenuItem OpenAddMenu(DataGrid table)
    {
        table.ContextMenu.RaiseEvent(new RoutedEventArgs(ContextMenu.OpenedEvent));
        return table.ContextMenu.Items.OfType<MenuItem>().Single(item => item.Header?.ToString() == "加入通道");
    }
    private static async Task VerifyParameterSearch(RealtimeScopePage page, string label)
    {
        var table = Control<DataGrid>(page, "realtime_parameters");
        var input = Control<TextBox>(page, "realtime_search");
        var original = table.Items.Cast<RealtimeScopeSymbol>().ToArray();
        int revision = page.SymbolRevision, replacements = 0;
        var property = System.ComponentModel.DependencyPropertyDescriptor.FromProperty(ItemsControl.ItemsSourceProperty, typeof(DataGrid))!;
        EventHandler changed = (_, _) => replacements++;
        property.AddValueChanged(table, changed);
        double slowestInput = 0;
        try {
            foreach (string query in new[] { "g", "g_scope_demo", "G_SCOPE_DEMO", "__missing_parameter__", "" }) {
                int before = replacements;
                var watch = System.Diagnostics.Stopwatch.StartNew();
                input.Text = "discard_this_query"; input.Text = query;
                double inputMs = watch.Elapsed.TotalMilliseconds;
                slowestInput = Math.Max(slowestInput, inputMs);
                Require(replacements == before, "Typing must not synchronously rebuild the parameter grid");
                await Task.Delay(300);
                page.ParameterPicker!.UpdateLayout();
                var expected = original.Where(symbol => symbol.Name.Contains(query, StringComparison.OrdinalIgnoreCase));
                Require(table.Items.Cast<RealtimeScopeSymbol>().SequenceEqual(expected), "Search results must match the latest query in original order: " + query);
                Require(replacements == before + 1, "Rapid edits must publish one result list, not per-row notifications");
            }
            Require(page.SymbolRevision == revision, "Typing must not reload ELF or alter its generation");
            Require(original.Length < 100 || DiagnosticPageTests.Visuals<DataGridRow>(table).Count() < 100, "Only viewport rows should be realized for a large parameter list");
            Console.WriteLine($"PASS search {label}: {original.Length} roots, input handler max {slowestInput:F2} ms; one batched update per query, case-insensitive matches and virtualized rows.");
        }
        finally { property.RemoveValueChanged(table, changed); }
    }
    private static async Task VerifySymbolFile(RealtimeScopePage page, string path)
    {
        Control<TextBox>(page, "realtime_elf").Text = path;
        Control<TextBox>(page, "realtime_map").Text = "";
        await page.OpenParameterPickerAsync(); page.ParameterPicker!.UpdateLayout();
        await VerifyParameterSearch(page, Path.GetFileName(path));
        var table = Control<DataGrid>(page, "realtime_parameters");
        if (table.Items.Cast<RealtimeScopeSymbol>().FirstOrDefault(symbol => symbol.Name == "g_demo_fal") is { } array) {
            await page.ExpandAsync(array);
            var parent = array.Children.Single(symbol => symbol.Name == "g_demo_fal[0]");
            await page.ExpandAsync(parent);
            var members = new[] { "state", "operation" }.Select(name => parent.Children.Single(symbol => symbol.Name == "g_demo_fal[0]." + name)).ToArray();
            table.SelectedItem = parent;
            foreach (var member in members) table.SelectedItems.Add(member);
            for (int i = 0; i < members.Length; i++) {
                var member = members[i];
                Require(member.CanSample, "Reported member must be sampleable: " + member.Name);
                table.ScrollIntoView(member); table.UpdateLayout();
                var row = (DataGridRow)table.ItemContainerGenerator.ContainerFromItem(member);
                table.RaiseEvent(new System.Windows.Input.MouseButtonEventArgs(System.Windows.Input.Mouse.PrimaryDevice, Environment.TickCount, System.Windows.Input.MouseButton.Right) {
                    RoutedEvent = UIElement.PreviewMouseRightButtonDownEvent, Source = row
                });
                Require(OpenAddMenu(table).IsEnabled, "Reported member must enable Add");
                var target = table.ContextMenu.Items.OfType<MenuItem>().Single(item => item.Header?.ToString() == "指定通道");
                Require(target.IsEnabled, "Right-clicked member must enable target channel even when the parent is first selected");
                table.ContextMenu.RaiseEvent(new RoutedEventArgs(ContextMenu.ClosedEvent));
                ((MenuItem)target.Items[30 + i]).RaiseEvent(new RoutedEventArgs(MenuItem.ClickEvent));
                Require(page.Workspace.Configuration.Channels[30 + i].Symbol?.Name == member.Name, "Target channel must use the right-clicked member, not the first selected row");
                Console.WriteLine($"PASS: specified CH{31 + i}: {member.Name} {member.AddressText} {member.Type}");
            }
            foreach (var channel in page.Workspace.Configuration.Channels) channel.Assign(null);
            table.SelectedItems.Clear();
        }
        foreach (var parent in table.Items.Cast<RealtimeScopeSymbol>().Where(symbol => symbol.Kind == "struct").Take(100).ToArray()) {
            await page.ExpandAsync(parent);
            if (parent.Children.FirstOrDefault(symbol => symbol.CanSample) is not { } member) continue;
            table.SelectedItem = parent;
            Require(!OpenAddMenu(table).IsEnabled && table.ContextMenu.Items.OfType<MenuItem>().First().IsEnabled, "Structure must offer expansion, not scalar acquisition");
            table.SelectedItem = member;
            Require(OpenAddMenu(table).IsEnabled, "Actual ELF scalar member menu must be enabled: " + member.Name);
            table.SelectedItems.Add(parent);
            Require(OpenAddMenu(table).IsEnabled, "A selected parent must not disable its scalar member");
            Add(table);
            Require(page.Workspace.Configuration.Enabled.Single().Symbol?.Name == member.Name, "Mixed selection must add only the actual scalar member");
            Console.WriteLine($"PASS: actual ELF member menu and mixed parent selection: {member.Name} {member.AddressText} {member.Type}");
            page.Workspace.Configuration.Channels[0].Assign(null);
            return;
        }
        throw new Exception("No selectable scalar structure member found in " + path);
    }
    public static async Task Run(MainWindow window, string root, string? symbolElf = null)
    {
        Models();
        await RealtimeScopeDeviceTests.Run();
        await RealtimeScopeConfigurationTests.Run(root);
        var flags = BindingFlags.Instance | BindingFlags.NonPublic;
        var pages = (IDictionary)typeof(MainWindow).GetField("pages", flags)!.GetValue(window)!;
        int index = pages.Keys.Cast<string>().ToList().IndexOf("realtime-scope");
        Require(index >= 0, "实时示波器 must be registered in navigation");
        ((ListBox)window.FindName("Navigation")).SelectedIndex = index;
        var state = pages["realtime-scope"]!;
        var page = (RealtimeScopePage)state.GetType().GetField("Diagnostic")!.GetValue(state)!;
        window.Width = 1560; window.Height = 980; window.UpdateLayout();
        var defaultX = (CheckBox)typeof(RealtimeScopePage).GetField("xCursors", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(page)!;
        var defaultY = (CheckBox)typeof(RealtimeScopePage).GetField("yCursors", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(page)!;
        Require(Control<TabControl>(page, "realtime_inspector").SelectedIndex == 0 && defaultX.IsChecked == false && defaultY.IsChecked == false,
            "Scope must default to Channels with measurement cursors disabled");
        defaultX.IsChecked = true;
        defaultY.IsChecked = true;
        window.UpdateLayout();
        await IndependentLink(window, page);
        await page.OpenParameterPickerAsync(); window.UpdateLayout();
        if (symbolElf != null) await VerifySymbolFile(page, symbolElf);
        Control<TextBox>(page, "realtime_elf").Text = Path.Combine(root, "build/symbol-fixture.elf");
        await page.OpenParameterPickerAsync(); page.ParameterPicker!.UpdateLayout();
        await VerifyParameterSearch(page, "fixture");
        var parameters = Control<DataGrid>(page, "realtime_parameters");
        var controller = parameters.Items.Cast<RealtimeScopeSymbol>().Single(symbol => symbol.Name == "controller");
        await page.ExpandAsync(controller);
        Require(controller.Children.Count == 2 && controller.Children.All(symbol => symbol.CanSample), "Real ELF struct members must be selectable without reading target memory");
        Require(controller.Children[1].Address - controller.Children[0].Address == 4, "DWARF member offset mismatch");
        await page.ExpandAsync(controller);
        var searchBox = Control<TextBox>(page, "realtime_search");
        searchBox.Text = controller.Children[0].Name.ToUpperInvariant();
        await Task.Delay(300);
        Require(parameters.Items.Cast<RealtimeScopeSymbol>().SequenceEqual(new[] { controller, controller.Children[0] }), "Member search must retain its collapsed ancestor and matching member only");
        searchBox.Clear(); await Task.Delay(300);
        Require(!parameters.Items.Contains(controller.Children[0]) && !controller.Expanded, "Clearing search must restore the original collapsed tree");
        await page.ExpandAsync(controller);
        var member = controller.Children[0];
        parameters.SelectedItem = controller;
        Require(!OpenAddMenu(parameters).IsEnabled, "Container must not be treated as a scalar");
        parameters.SelectedItem = member;
        Require(OpenAddMenu(parameters).IsEnabled, "Expanded member must enable Add");
        parameters.SelectedItems.Add(controller);
        Require(OpenAddMenu(parameters).IsEnabled, "Parent/child mixed selection must not disable the member");
        Add(parameters);
        Require(page.Workspace.Configuration.Channels[0].Symbol?.Name == "controller.gain", "Add must use the first empty channel");

        var channels = Control<DataGrid>(page, "realtime_channels");
        parameters.SelectedItem = controller.Children[1];
        OpenAddMenu(parameters);
        ((MenuItem)parameters.ContextMenu.Items.OfType<MenuItem>().Single(item => item.Header?.ToString() == "指定通道").Items[31]).RaiseEvent(new RoutedEventArgs(MenuItem.ClickEvent));
        Require(page.Workspace.Configuration.Channels[31].Symbol?.Name == "controller.count" && !channels.AllowDrop, "Context menu must target CH32 without drag-and-drop");
        parameters.SelectedItem = parameters.Items.Cast<RealtimeScopeSymbol>().Single(symbol => symbol.Name == "gain");
        Add(parameters); Require(page.Workspace.Configuration.Channels[1].Symbol?.Name == "gain", "Automatic add must fill CH2 after sparse CH32 assignment");
        page.ParameterPicker.UpdateLayout();
        var pickerContent = (FrameworkElement)page.ParameterPicker.Content;
        var pickerImage = new RenderTargetBitmap((int)pickerContent.ActualWidth, (int)pickerContent.ActualHeight, 96, 96, PixelFormats.Pbgra32);
        var pickerBackground = new DrawingVisual();
        using (var drawing = pickerBackground.RenderOpen()) drawing.DrawRectangle(page.ParameterPicker.Background, null, new Rect(0, 0, pickerContent.ActualWidth, pickerContent.ActualHeight));
        pickerImage.Render(pickerBackground);
        pickerImage.Render(pickerContent);
        var pickerPng = new PngBitmapEncoder(); pickerPng.Frames.Add(BitmapFrame.Create(pickerImage));
        using (var file = File.Create(Path.Combine(root, "build/ui-verification/realtime-scope-parameters.png"))) pickerPng.Save(file);
        Require(page.Workspace.Configuration.Enabled.Count() == 3, "Added parameters must be immediately present without Apply");
        Require(!DiagnosticPageTests.Visuals<ComboBox>(page).Any(c => AutomationProperties.GetAutomationId(c) == "realtime_channel_view") &&
            !DiagnosticPageTests.Visuals<Button>(page).Any(c => AutomationProperties.GetAutomationId(c) == "realtime_apply"), "Firmware bank controls must not be exposed on the host");
        channels.SelectedIndex = 0; channels.ScrollIntoView(channels.Items[0]);
        window.UpdateLayout();
        T ChannelCell<T>(int number, string id) where T : FrameworkElement {
            channels.ScrollIntoView(channels.Items[number - 1]); window.UpdateLayout();
            return DiagnosticPageTests.Visuals<T>(channels).First(item => AutomationProperties.GetAutomationId(item) == id && item.DataContext is RealtimeScopeChannel channel && channel.Number == number);
        }
        Require(!DiagnosticPageTests.Visuals<TextBlock>(page).Any(item => item.Text.Contains("独立显示设置")), "The redundant bottom channel editor must be removed");
        Require(!channels.Columns.Any(column => column.Header?.ToString() == "单位"), "Channel table must omit the unit column");
        page.Workspace.Displays[0].UnitsPerDivision = 0.5;
        page.Workspace.Displays[1].Unit = "A"; page.Workspace.Displays[1].UnitsPerDivision = 1; page.Workspace.Displays[1].Position = -1.5;
        page.Workspace.Displays[31].Unit = "rpm"; page.Workspace.Displays[31].Gain = 500; page.Workspace.Displays[31].UnitsPerDivision = 500; page.Workspace.Displays[31].Position = 1.5;
        Control<TextBox>(page, "realtime_window_ms").Text = "50";
        Control<CheckBox>(page, "realtime_trigger_pause").IsChecked = true;
        Control<ComboBox>(page, "realtime_source").SelectedIndex = 1;
        Click(page, "realtime_preview"); Require(page.PreviewRunning, "Preview start failed");
        page.AdvancePreviewForTest(6000);
        Require(page.Preview!.DisplayPaused, "A 50ms triggered window must pause after collecting post-trigger samples");
        var plot = Control<ScottPlot.WPF.WpfPlot>(page, "realtime_plot");
        Require(!plot.Plot.Axes.Left.TickLabelStyle.IsVisible && plot.Plot.Axes.Left.Label.Text.Length == 0, "Shared vertical axis must show no numbers or div title");
        Require(plot.Plot.GetPlottables<ScottPlot.Plottables.Scatter>().Count() == 3, "Three active channels should share one waveform window");
        long received = page.Preview.NextSample; page.AdvancePreviewForTest(page.Preview.Capacity + 100);
        Require(page.Preview.NextSample > received && plot.Plot.GetPlottables<ScottPlot.Plottables.Scatter>().Count() == 3, "Frozen display must survive raw-ring overwrite");
        double otherScale = page.Workspace.Displays[1].UnitsPerDivision;
        var division = ChannelCell<TextBox>(1, "realtime_vertical_div");
        Require(division.Text == "0.5" && division.ActualHeight >= 24 && division.ActualWidth >= 60 &&
            division.ActualHeight - division.Padding.Top - division.Padding.Bottom - division.BorderThickness.Top - division.BorderThickness.Bottom >= division.FontSize * 1.4,
            "Division values must have enough visible text area inside the compact channel row");
        void EnterDivision(string value) {
            division.Text = value;
            division.RaiseEvent(new System.Windows.Input.KeyEventArgs(System.Windows.Input.Keyboard.PrimaryDevice, PresentationSource.FromVisual(division)!, Environment.TickCount, System.Windows.Input.Key.Enter) { RoutedEvent = System.Windows.Input.Keyboard.KeyDownEvent });
        }
        void WheelDivision(int delta) {
            var wheel = new System.Windows.Input.MouseWheelEventArgs(System.Windows.Input.Mouse.PrimaryDevice, Environment.TickCount, delta) { RoutedEvent = System.Windows.Input.Mouse.PreviewMouseWheelEvent };
            division.RaiseEvent(wheel); Require(wheel.Handled, "Division wheel must not bubble into waveform time zoom");
        }
        EnterDivision("0.25");
        Require(page.Workspace.Displays[0].UnitsPerDivision == 0.25 && page.Workspace.Displays[1].UnitsPerDivision == otherScale, "Direct division input must only affect the selected channel");
        double timeSpan = plot.Plot.Axes.GetLimits().Right - plot.Plot.Axes.GetLimits().Left;
        WheelDivision(60); Require(page.Workspace.Displays[0].UnitsPerDivision == 0.25, "High resolution wheel deltas should accumulate without prematurely changing the scale");
        WheelDivision(60); Require(page.Workspace.Displays[0].UnitsPerDivision == 0.5, "Wheel up must select the next 1-2-5 division value");
        WheelDivision(-120); Require(page.Workspace.Displays[0].UnitsPerDivision == 0.2 && page.Workspace.Displays[1].UnitsPerDivision == otherScale && plot.Plot.Axes.GetLimits().Right - plot.Plot.Axes.GetLimits().Left == timeSpan, "Wheel down must change only channel scale, not another channel or the timebase");
        EnterDivision("0"); Require(System.Windows.Controls.Validation.GetHasError(division) && page.Workspace.Displays[0].UnitsPerDivision == 0.2, "Invalid division input must leave the last valid scale intact");
        EnterDivision("0.25");
        Control<DataGrid>(page, "realtime_channels").SelectedIndex = 31;
        division = ChannelCell<TextBox>(32, "realtime_vertical_div");
        Require(division.Text == "500", "Each channel row must show its own division");
        WheelDivision(120); Require(page.Workspace.Displays[31].UnitsPerDivision == 1000 && page.Workspace.Displays[0].UnitsPerDivision == 0.25, "Wheel must follow the selected channel");
        WheelDivision(-120); Control<DataGrid>(page, "realtime_channels").SelectedIndex = 0;
        void WheelTime(int delta) {
            var before = plot.Plot.Axes.GetLimits();
            var scales = page.Workspace.Displays.Select(display => display.UnitsPerDivision).ToArray();
            var wheel = new System.Windows.Input.MouseWheelEventArgs(System.Windows.Input.Mouse.PrimaryDevice, Environment.TickCount, delta) { RoutedEvent = System.Windows.Input.Mouse.PreviewMouseWheelEvent };
            plot.RaiseEvent(wheel);
            var after = plot.Plot.Axes.GetLimits();
            Require(wheel.Handled && before.Bottom == after.Bottom && before.Top == after.Top && scales.SequenceEqual(page.Workspace.Displays.Select(display => display.UnitsPerDivision)), "Plot wheel must be consumed and preserve vertical limits and all channel scales");
        }
        page.ParameterPicker.Hide();
        window.UpdateLayout();
        var channelImage = new RenderTargetBitmap((int)channels.ActualWidth, (int)channels.ActualHeight, 96, 96, PixelFormats.Pbgra32);
        channelImage.Render(channels);
        var channelPng = new PngBitmapEncoder(); channelPng.Frames.Add(BitmapFrame.Create(channelImage));
        using (var channelFile = File.Create(Path.Combine(root, "build/ui-verification/realtime-scope-channels.png"))) channelPng.Save(channelFile);
        Control<TabControl>(page, "realtime_inspector").SelectedIndex = 1; window.UpdateLayout();
        Require(plot.Plot.GetPlottables<ScottPlot.Plottables.VerticalLine>().Count() == 2 && plot.Plot.GetPlottables<ScottPlot.Plottables.HorizontalLine>().Count() == 2 && plot.Plot.GetPlottables<ScottPlot.Plottables.Marker>().Count() == 1 && plot.Plot.GetPlottables<ScottPlot.Plottables.Polygon>().Count() == 1, "Idle trigger must show a rotated T triangle and top marker without a horizontal reference line");
        var triggerLevelBox = (TextBox)typeof(RealtimeScopePage).GetField("level", flags)!.GetValue(page)!;
        var triggerPositionBox = (TextBox)typeof(RealtimeScopePage).GetField("pretrigger", flags)!.GetValue(page)!;
        var dragField = typeof(RealtimeScopePage).GetField("draggedCursor", BindingFlags.Instance | BindingFlags.NonPublic)!;
        var renderMethod = typeof(RealtimeScopePage).GetMethod("RenderSnapshot", BindingFlags.Instance | BindingFlags.NonPublic)!;
        dragField.SetValue(page, 5); renderMethod.Invoke(page, null);
        Require(plot.Plot.GetPlottables<ScottPlot.Plottables.HorizontalLine>().Count() == 3, "Dragging T must reveal the horizontal level reference");
        dragField.SetValue(page, -1); renderMethod.Invoke(page, null);
        var handleMethod = typeof(RealtimeScopePage).GetMethod("TriggerLevelHandle", flags)!;
        var levelHandle = (ScottPlot.Coordinates)handleMethod.Invoke(page, new object[] { new ScottPlot.Coordinates(0, 0) })!;
        var rightPixel = plot.Plot.GetPixel(new ScottPlot.Coordinates(plot.Plot.Axes.GetLimits().Right, 0));
        Require(Math.Abs(rightPixel.X - plot.Plot.GetPixel(levelHandle).X - 7) < 0.1, "T triangle base must touch the right plot border");
        string readout = Control<TextBlock>(page, "realtime_cursor_values").Text;
        Require(readout.Contains("X1 =") && readout.Contains("X2 =") && readout.Contains("ΔX =") && readout.Contains("Y1 =") && readout.Contains("Y2 =") && readout.Contains("ΔY = 0.5"), "Cursor panel must use selected channel engineering scale and signed deltas");
        Require(readout.Split('\n').Length == 7 && readout.Split('\n').Count(line => line.StartsWith("X1 =") || line.StartsWith("X2 =")) == 2, "Each X cursor must show time and sample value on one row");
        Require(Control<TextBlock>(page, "realtime_measurements").Text.Contains("50 Hz"), "Frozen full samples must retain automatic measurements after ring overwrite");
        foreach (string id in new[] { "realtime_preview", "realtime_pause", "realtime_single", "realtime_autoset", "realtime_select_parameters", "realtime_sync", "realtime_link_connect" })
            Require(Math.Abs(Control<Button>(page, id).ActualHeight - 28) < 0.1, "Toolbar buttons must share a compact 28px height: " + id);
        Require(!DiagnosticPageTests.Visuals<FrameworkElement>(page).Any(item => new[] { "realtime_time_in", "realtime_time_out", "realtime_time_div", "realtime_vertical_source", "realtime_settings", "realtime_trigger_level", "realtime_pretrigger" }.Contains(AutomationProperties.GetAutomationId(item))) && plot.ActualHeight > 450, "All acquisition, trigger and link controls must be on the main page without a Settings button");
        await Task.Delay(80); window.UpdateLayout(); plot.Refresh(); await Task.Delay(80);
        string output = Path.Combine(root, "build/ui-verification/realtime-scope.png"); Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        var content = (FrameworkElement)window.Content;
        var image = new RenderTargetBitmap((int)content.ActualWidth, (int)content.ActualHeight, 96, 96, PixelFormats.Pbgra32);
        var background = new DrawingVisual();
        using (var drawing = background.RenderOpen()) drawing.DrawRectangle(window.Background, null, new Rect(0, 0, content.ActualWidth, content.ActualHeight));
        image.Render(background); image.Render(content);
        var png = new PngBitmapEncoder(); png.Frames.Add(BitmapFrame.Create(image)); using (var stream = File.Create(output)) png.Save(stream);
        window.Width = 1280; window.Height = 800; window.UpdateLayout(); plot.Refresh(); await Task.Delay(60);
        Require(plot.ActualHeight > 440 && plot.ActualWidth > 730 && Control<Button>(page, "realtime_sync").ActualHeight == 28, $"Compact scope must remain usable at 1280x800: plot {plot.ActualWidth} x {plot.ActualHeight}");
        var compactImage = new RenderTargetBitmap((int)content.ActualWidth, (int)content.ActualHeight, 96, 96, PixelFormats.Pbgra32);
        var compactBackground = new DrawingVisual();
        using (var drawing = compactBackground.RenderOpen()) drawing.DrawRectangle(window.Background, null, new Rect(0, 0, content.ActualWidth, content.ActualHeight));
        compactImage.Render(compactBackground); compactImage.Render(content);
        var compactPng = new PngBitmapEncoder(); compactPng.Frames.Add(BitmapFrame.Create(compactImage));
        using (var stream = File.Create(Path.Combine(root, "build/ui-verification/realtime-scope-compact.png"))) compactPng.Save(stream);
        window.Width = 1560; window.Height = 980; window.UpdateLayout();
        WheelTime(-60); Require(Control<TextBox>(page, "realtime_window_ms").Text == "50", "Partial wheel deltas must accumulate");
        WheelTime(-60); Require(Control<TextBox>(page, "realtime_window_ms").Text == "100", "Time wheel should reach exactly 100ms");
        Require(page.Preview.AutoPauseEligible && !page.Preview.IsRolling, "100ms must remain eligible for triggering and pause");
        Control<TextBox>(page, "realtime_window_ms").Text = "250"; WheelTime(-120);
        Require(Control<TextBox>(page, "realtime_window_ms").Text == "500" && !page.Preview.AutoPauseEligible && Control<CheckBox>(page, "realtime_trigger_pause").IsEnabled == false, "500ms window must disable trigger pause");
        Require(page.Preview.IsRolling && !page.Preview.TriggerEnabled && !page.Preview.DisplayPaused && !Control<ComboBox>(page, "realtime_trigger_mode").IsEnabled &&
            Control<ComboBox>(page, "realtime_trigger_mode").SelectedItem?.ToString() == "滚动" && !Control<Button>(page, "realtime_single").IsEnabled, "500ms must enter untriggered Roll and clear the old triggered hold");
        Require(!triggerLevelBox.IsEnabled && !Control<Button>(page, "realtime_force").IsEnabled, "Roll must disable trigger controls");
        Require(plot.Plot.GetPlottables<ScottPlot.Plottables.HorizontalLine>().Count() == 2 && plot.Plot.GetPlottables<ScottPlot.Plottables.Marker>().Count() == 1 && plot.Plot.GetPlottables<ScottPlot.Plottables.Polygon>().Count() == 1, "Running Roll must retain both trigger indicators without a level line");
        dragField.SetValue(page, 5); renderMethod.Invoke(page, null);
        Require(plot.Plot.GetPlottables<ScottPlot.Plottables.HorizontalLine>().Count() == 3, "Dragging T in running Roll must reveal its reference line");
        var rollDrag = typeof(RealtimeScopePage).GetMethod("SetTriggerFromPlot", flags)!;
        rollDrag.Invoke(page, new object[] { false, 0d, 2d });
        Require(triggerLevelBox.Text == "0.5" && page.Preview.IsRolling && !page.Preview.TriggerEnabled, "Roll cursor drag must update the saved level without enabling triggering");
        dragField.SetValue(page, -1); renderMethod.Invoke(page, null);
        Require(plot.Plot.GetPlottables<ScottPlot.Plottables.HorizontalLine>().Count() == 2, "Releasing T in Roll must hide its reference line");
        typeof(RealtimeScopePage).GetField("follow", flags)!.SetValue(page, false);
        double left = (page.Preview.NextSample - 2000) * 1000.0 / page.Preview.SampleRate;
        double right = (page.Preview.NextSample - 1000) * 1000.0 / page.Preview.SampleRate;
        double origin = (double)typeof(RealtimeScopePage).GetField("snapshotOriginMs", flags)!.GetValue(page)!;
        plot.Plot.Axes.SetLimitsX(left - origin, right - origin); page.AdvancePreviewForTest(100);
        var snapshot = (Dictionary<int, (double[] X, double[] Raw)>)typeof(RealtimeScopePage).GetField("snapshot", flags)!.GetValue(page)!;
        Require(snapshot.Values.All(points => points.X.Length > 0 && points.X.First() >= left - 1000.0 / page.Preview.SampleRate && points.X.Last() <= right + 1000.0 / page.Preview.SampleRate), "Panning must render the selected history instead of only the latest window");
        page.StopPreview();
        WheelTime(120);
        Require(Control<ComboBox>(page, "realtime_trigger_mode").Items.Cast<string>().SequenceEqual(new[] { "自动", "普通" }), "Below 500ms only Auto and Normal should appear in the mode selector");
        var setTrigger = typeof(RealtimeScopePage).GetMethod("SetTriggerFromPlot", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!;
        var limits = plot.Plot.Axes.GetLimits();
        setTrigger.Invoke(page, new object[] { true, limits.Left + (limits.Right - limits.Left) * 0.3, 0d });
        Require(triggerPositionBox.Text == "30", "Dragging the top trigger marker must set the pretrigger percentage");
        setTrigger.Invoke(page, new object[] { false, 0d, 2d });
        Require(triggerLevelBox.Text == "0.5", "Trigger level drag must use the trigger source's independent division scale");
        triggerPositionBox.Text = "50";
        triggerLevelBox.Text = "0";
        Control<CheckBox>(page, "realtime_trigger_pause").IsChecked = false;
        Control<ComboBox>(page, "realtime_trigger_mode").SelectedIndex = 1;
        WheelTime(-120); WheelTime(120);
        Require(Control<ComboBox>(page, "realtime_trigger_mode").SelectedIndex == 1, "Roll-to-triggered transition must restore the previous Normal preference");
        triggerLevelBox.Text = "10";
        page.StartPreview(); page.AdvancePreviewForTest(9000);
        Require(page.Preview!.CompletedTrigger == null && !page.Preview.AutoFallback && plot.Plot.GetPlottables<ScottPlot.Plottables.Scatter>().Count() == 0, "Normal must wait on an unreachable trigger level");
        page.StopPreview();
        Control<ComboBox>(page, "realtime_trigger_mode").SelectedIndex = 0;
        page.StartPreview(); page.AdvancePreviewForTest(9000);
        Require(page.Preview!.AutoFallback && plot.Plot.GetPlottables<ScottPlot.Plottables.Scatter>().Count() == 3, "Auto must display even when the same trigger is unreachable");
        page.StopPreview();
        triggerLevelBox.Text = "0";
        Click(page, "realtime_single"); page.AdvancePreviewForTest(9000);
        Require(page.Preview!.SingleCompleted && !page.PreviewRunning, "Single must stop the page timer after one trigger capture");
        long stopped = page.Preview.NextSample; page.AdvancePreviewForTest(1000);
        Require(page.Preview.NextSample == stopped, "Single must retain a stopped acquisition, not merely a frozen display");
        Click(page, "realtime_autoset");
        Require(Control<ComboBox>(page, "realtime_trigger_mode").SelectedIndex == 0 && page.Workspace.Displays[0].UnitsPerDivision > 0, "Auto Set must restore Auto and fit waveforms");
        page.StopPreview();
        var source = Control<ComboBox>(page, "realtime_source"); source.SelectedIndex = 1;
        page.StartPreview(); page.AdvancePreviewForTest(9000); page.StopPreview();
        source.SelectedIndex = 0;
        Require(page.Preview == null && !plot.Plot.GetPlottables<ScottPlot.Plottables.Scatter>().Any() &&
            ((TextBlock)typeof(RealtimeScopePage).GetField("sourceBadge", flags)!.GetValue(page)!).Text == "设备", "Switching to device must clear simulated samples and the simulated source badge");
        await ReloadAndSynchronize(page, root);
        Console.WriteLine("PASS: ELF member expansion, parameter picker, context-menu CH32 and sequential add, single channel list, scope modes, measurements, cursor readouts and screenshot: " + output);
    }
    private static async Task ReloadAndSynchronize(RealtimeScopePage page, string root)
    {
        string path = Path.Combine(root, "build/ui-verification/reload-fixture.elf");
        string relocated = Path.Combine(root, "build/ui-verification/relocated-fixture.elf");
        var command = new System.Diagnostics.ProcessStartInfo("arm-none-eabi-g++") { WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true, RedirectStandardError = true };
        foreach (string argument in new[] { "-std=c++20", "-g", "-O0", "-mcpu=cortex-m4", "-mthumb", "-nostdlib", "-Wl,-Ttext=0x08000000", "-Wl,-Tdata=0x20000100", "-Wl,--section-start=.resolved=0x20001000", "-Wl,--section-start=.resolved_node=0x20001010", "-Wl,-e,fixture_entry", "tests/native/symbol_fixture.cpp", "-o", relocated }) command.ArgumentList.Add(argument);
        using var compiler = System.Diagnostics.Process.Start(command)!;
        string error = await compiler.StandardError.ReadToEndAsync(); await compiler.WaitForExitAsync();
        Require(compiler.ExitCode == 0, "Relocated ELF fixture build failed: " + error);
        File.Copy(Path.Combine(root, "build/symbol-fixture.elf"), path, true);
        Control<TextBox>(page, "realtime_elf").Text = path;
        await page.OpenParameterPickerAsync();
        ulong oldAddress = page.Workspace.Configuration.Channels[0].Symbol!.Address;
        int revision = page.SymbolRevision;
        await page.OpenParameterPickerAsync();
        Require(page.SymbolRevision == revision + 1 && page.Workspace.Configuration.Enabled.Count() == 3, "Every Select Parameters click must reload, without deleting resident channels");
        // Replace the very same pathname with a freshly linked image while the application remains open.
        File.Copy(relocated, path, true);
        await page.OpenParameterPickerAsync();
        Require(page.BindingsNeedRefresh && page.Workspace.Configuration.Channels[0].Symbol!.Address == oldAddress, "Changed disk image must invalidate bindings without silently rewriting resident channels");
        var parameters = Control<DataGrid>(page, "realtime_parameters");
        var controller = parameters.Items.Cast<RealtimeScopeSymbol>().Single(symbol => symbol.Name == "controller");
        await page.ExpandAsync(controller);
        Require(controller.Children[0].Address == oldAddress + 0x100, "Same-path reload must read new DWARF addresses from disk");
        await page.SynchronizeParametersAsync();
        Require(!page.BindingsNeedRefresh && page.Workspace.Configuration.Channels[0].Symbol!.Address == oldAddress + 0x100 && page.PendingDeviceConfiguration.Select(item => item.Channel).SequenceEqual(new[] { 1, 2, 32 }), "Update Sync must re-resolve nested members and preserve sparse channel numbers");
        Require(page.Workspace.Displays[1].Unit == "A" && page.Workspace.Displays[31].Unit == "rpm", "Synchronization must preserve per-channel display settings");
        var previous = page.Workspace.Configuration.Channels[0].Symbol;
        page.Workspace.Configuration.Add(Scalar("missing_after_upgrade"), 4);
        try { await page.SynchronizeParametersAsync(); throw new Exception("Missing resident symbol accepted"); }
        catch (InvalidOperationException exception) { Require(exception.Message.Contains("missing_after_upgrade"), "Missing symbol must be identified"); }
        Require(ReferenceEquals(previous, page.Workspace.Configuration.Channels[0].Symbol) && page.PendingDeviceConfiguration.Count == 0 && page.BindingsNeedRefresh, "A failed update must be atomic and cannot retain a sendable stale layout");
        await File.WriteAllTextAsync(path, "not an elf");
        try { await page.OpenParameterPickerAsync(); throw new Exception("Invalid ELF accepted"); } catch (InvalidOperationException) { }
        Require(parameters.Items.Count == 0 && page.Workspace.Configuration.Enabled.Count() == 4, "Failed reload must clear stale picker data while retaining resident channels");
        page.ParameterPicker!.Close(); Require(!page.ParameterPicker.IsVisible, "Closing the picker should hide it for reuse");
        Console.WriteLine("PASS: repeated disk reload, same-path rebuilt ELF, resident channel preservation, nested member relocation, atomic refresh failure and no fake device ACK.");
    }
}
