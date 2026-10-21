using System.IO;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using Frame.Client;

namespace Frame.Desktop;

public sealed record RealtimeScopeChannelUpdate(int Channel, string Name, ulong Address, string Type, int Size, int Encoding);

public sealed partial class RealtimeScopePage
{
    private Window? parameterPicker;
    private string? symbolFingerprint;
    private string? synchronizationError;
    private readonly TextBlock syncState = Text("");
    public Window? ParameterPicker => parameterPicker;
    public bool BindingsNeedRefresh { get; private set; }
    public int SymbolRevision { get; private set; }
    // Prepared host-side layout. It is never represented as a device ACK.
    public IReadOnlyList<RealtimeScopeChannelUpdate> PendingDeviceConfiguration { get; private set; } = [];
    private void InvalidatePendingConfiguration()
    {
        PendingDeviceConfiguration = [];
        if (!BindingsNeedRefresh) syncState.Text = "";
    }

    private void ConfigureParameterMenu()
    {
        var menu = new ContextMenu();
        RealtimeScopeSymbol? clickedSymbol = null;
        RealtimeScopeSymbol? CurrentSymbol() => clickedSymbol ??
            (parameterTable.CurrentCell.Item as RealtimeScopeSymbol is { CanSample: true } cell ? cell :
             parameterTable.SelectedItem as RealtimeScopeSymbol is { CanSample: true } selected ? selected :
             parameterTable.SelectedItems.Cast<RealtimeScopeSymbol>().FirstOrDefault(symbol => symbol.CanSample) ?? parameterTable.SelectedItem as RealtimeScopeSymbol);
        var expand = new MenuItem { Header = "展开成员" };
        expand.Click += async (_, _) => { if (expand.Tag is RealtimeScopeSymbol symbol) await Run(() => ExpandAsync(symbol)); };
        menu.Items.Add(expand);
        var add = new MenuItem { Header = "加入通道" }; AutomationProperties.SetAutomationId(add, "realtime_add");
        add.Click += (_, _) => AddSelected(); menu.Items.Add(add);
        var target = new MenuItem { Header = "指定通道" }; menu.Items.Add(target);
        for (int i = 1; i <= 32; i++) {
            int number = i;
            var item = new MenuItem { Header = "CH" + i };
            item.Click += (_, _) => Try(() => {
                if (item.Tag is RealtimeScopeSymbol { CanSample: true } symbol) AssignSymbol(symbol, number);
            }); target.Items.Add(item);
        }
        parameterTable.ContextMenu = menu;
        parameterTable.PreviewMouseRightButtonDown += (_, e) => {
            clickedSymbol = (Ancestor<DataGridRow>(e.OriginalSource as DependencyObject)?.Item as RealtimeScopeSymbol);
            if (clickedSymbol is { } symbol && !parameterTable.SelectedItems.Contains(symbol)) parameterTable.SelectedItem = symbol;
        };
        void UpdateMenu() {
            var current = CurrentSymbol();
            expand.Tag = current;
            foreach (var entry in target.Items.OfType<MenuItem>()) entry.Tag = current;
            expand.IsEnabled = !Busy && current is { Expandable: true };
            expand.Header = current is { Expanded: true } ? "收起成员" : "展开成员";
            add.IsEnabled = !Busy && parameterTable.SelectedItems.Cast<RealtimeScopeSymbol>().Any(symbol => symbol.CanSample);
            target.IsEnabled = !Busy && current is { CanSample: true };
            string hint = Busy ? "正在读取参数" : current?.SamplingHint ?? "请先选择参数";
            add.ToolTip = add.IsEnabled ? "按顺序将选中的数值成员加入空通道" : hint;
            target.ToolTip = target.IsEnabled ? "将当前数值成员加入指定通道" : hint;
        }
        ToolTipService.SetShowOnDisabled(add, true); ToolTipService.SetShowOnDisabled(target, true);
        parameterTable.ContextMenuOpening += (_, e) => { if (e.CursorLeft < 0) clickedSymbol = null; UpdateMenu(); };
        menu.Opened += (_, _) => UpdateMenu();
        menu.Closed += (_, _) => clickedSymbol = null;
    }
    public async Task OpenParameterPickerAsync()
    {
        if (Closed) return;
        if (parameterPicker == null) {
            var body = new DockPanel { Margin = new Thickness(12) };
            var files = BuildFiles(); DockPanel.SetDock(files, Dock.Top); body.Children.Add(files);
            body.Children.Add(BuildParameters());
            parameterPicker = new Window { Title = "选择参数", Owner = Window.GetWindow(this), Content = body,
                Width = 720, Height = 590, MinWidth = 560, MinHeight = 400, ShowInTaskbar = false,
                WindowStartupLocation = WindowStartupLocation.CenterOwner, Background = Window.GetWindow(this)?.Background ?? System.Windows.Media.Brushes.White };
            parameterPicker.Closing += (_, e) => { if (!Closed) { e.Cancel = true; parameterPicker.Hide(); } };
        }
        if (!parameterPicker.IsVisible) parameterPicker.Show(); parameterPicker.Activate();
        if (string.IsNullOrWhiteSpace(elf.Text)) {
            roots.Clear(); ReplaceSymbols([]); symbolCount.Text = "请选择 ELF";
            BindingsNeedRefresh = workspace.Configuration.Enabled.Any();
            if (BindingsNeedRefresh) { StopPreview(); syncState.Text = "待同步"; }
            return;
        }
        await ReloadSymbolsFromDiskAsync();
    }
    private static async Task<string> FingerprintAsync(string elfPath, string mapPath)
    {
        async Task<string> Hash(string path) {
            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete, 65536, true);
            return Convert.ToHexString(await SHA256.HashDataAsync(stream));
        }
        return Path.GetFullPath(elfPath) + ":" + await Hash(elfPath) +
            (mapPath.Length == 0 ? "" : ":" + Path.GetFullPath(mapPath) + ":" + await Hash(mapPath));
    }
    private async Task ReloadSymbolsFromDiskAsync()
    {
        if (Closed) return;
        string path = elf.Text.Trim(), mapPath = map.Text.Trim();
        StopPreview();
        roots.Clear(); ReplaceSymbols([]); symbolCount.Text = "读取中…";
        PendingDeviceConfiguration = [];
        try {
            if (!File.Exists(path)) throw new ArgumentException("ELF 文件不存在。");
            if (mapPath.Length > 0 && !File.Exists(mapPath)) throw new ArgumentException("MAP 文件不存在。");
            string before = await FingerprintAsync(path, mapPath);
            // Release the previous mapped binary and create a new index, even at the same path.
            if (symbolClient != null) { await symbolClient.DisposeAsync(); symbolClient = null; }
            var args = new JsonObject { ["path"] = path }; if (mapPath.Length > 0) args["map"] = mapPath;
            await SymbolCommand("load", args);
            var loaded = new List<RealtimeScopeSymbol>();
            for (int offset = 0; !Closed;) {
                var part = (await SymbolCommand("symbols", new() { ["offset"] = offset, ["limit"] = 4096, ["variables_only"] = true }))!.AsArray();
                loaded.AddRange(part.OfType<JsonObject>().Select(data => new RealtimeScopeSymbol((JsonObject)data.DeepClone())));
                offset += part.Count; if (part.Count < 4096) break;
            }
            string after = await FingerprintAsync(path, mapPath);
            if (before != after) throw new IOException("ELF/MAP 正在更新，请重试。");
            if (Closed) return;
            if (symbolFingerprint != after && (workspace.Configuration.Enabled.Any())) {
                BindingsNeedRefresh = true; syncState.Text = "待同步";
                preview = null; snapshot.Clear(); rawSnapshot.Clear();
            }
            symbolFingerprint = after; SymbolRevision++; demonstrationSymbols = false;
            roots.AddRange(loaded); RebuildSymbols(); RenderSnapshot();
        }
        catch {
            BindingsNeedRefresh = workspace.Configuration.Enabled.Any();
            if (BindingsNeedRefresh) syncState.Text = "待同步";
            roots.Clear(); ReplaceSymbols([]); symbolCount.Text = "读取失败";
            if (symbolClient != null) { await symbolClient.DisposeAsync(); symbolClient = null; }
            throw;
        }
    }
    private async Task<RealtimeScopeSymbol> ResolveResidentAsync(string name)
    {
        bool Parent(string prefix) => name == prefix || name.StartsWith(prefix + ".", StringComparison.Ordinal) || name.StartsWith(prefix + "[", StringComparison.Ordinal);
        var current = roots.Where(symbol => Parent(symbol.Name)).OrderByDescending(symbol => symbol.Name.Length).FirstOrDefault()
            ?? throw new InvalidOperationException("参数不存在：" + name);
        for (int depth = 0; current.Name != name && depth < 32; depth++) {
            if (!current.Expandable || current.Data["ambiguous"]?.GetValue<bool>() == true) throw new InvalidOperationException("参数无法解析：" + name);
            if (current.Kind == "array") {
                int start = current.Name.Length + 1, end = name.IndexOf(']', start);
                if (end < start || !int.TryParse(name[start..end], out int index) || index < 0) throw new InvalidOperationException("数组索引无效：" + name);
                var part = (await SymbolCommand("expand", new() { ["name"] = current.Name, ["offset"] = index, ["limit"] = 1 }))!.AsArray();
                current = part.OfType<JsonObject>().Select(data => new RealtimeScopeSymbol((JsonObject)data.DeepClone(), current.Depth + 1)).SingleOrDefault()
                    ?? throw new InvalidOperationException("数组元素不存在：" + name);
            }
            else {
                if (!current.Loaded) { await ExpandAsync(current); current.Expanded = false; }
                current = current.Children.Where(symbol => Parent(symbol.Name)).OrderByDescending(symbol => symbol.Name.Length).FirstOrDefault()
                    ?? throw new InvalidOperationException("成员不存在：" + name);
            }
        }
        if (current.Name != name || !current.CanSample) throw new InvalidOperationException("参数类型或地址无效：" + name);
        return current;
    }
    public async Task SynchronizeParametersAsync()
    {
        synchronizationError = null;
        await deviceConfigurationTask;
        await ReloadSymbolsFromDiskAsync();
        var replacements = new List<(RealtimeScopeChannel Channel, RealtimeScopeSymbol Symbol)>();
        var resolved = new Dictionary<string, RealtimeScopeSymbol>(StringComparer.Ordinal);
        try {
            foreach (var channel in workspace.Configuration.Enabled) {
                if (!resolved.TryGetValue(channel.Name, out var symbol)) { symbol = await ResolveResidentAsync(channel.Name); resolved.Add(channel.Name, symbol); }
                replacements.Add((channel, symbol));
            }
            // Validation is complete before changing any resident binding. Never retain a mixture of old/new addresses.
            foreach (var item in replacements) item.Channel.Assign(item.Symbol);
            BindingsNeedRefresh = false;
            PendingDeviceConfiguration = workspace.Configuration.Enabled.Select(channel => new RealtimeScopeChannelUpdate(channel.Number, channel.Name,
                channel.Symbol!.Address, channel.Type, channel.Symbol.Size, channel.Symbol.Encoding)).ToArray();
            preview = null; snapshot.Clear(); rawSnapshot.Clear(); UpdateSources(); UpdateChannelView(); UpdateSummary(); RenderSnapshot();
            syncState.Text = "待下发";
            Status("地址已更新，待下发。");
            if (Client.Snapshot()["connected"]?.GetValue<bool>() == true) {
                await deviceStopTask;
                await VerifyDeviceBindingsAsync(force: true);
                ApplyDeviceCapabilities(await ControlAsync("configure", new() { ["channels"] = ActiveWireChannels() }));
                deviceConfigurationError = null;
                synchronizedConnection = ConnectionKey(Client.Snapshot());
                PendingDeviceConfiguration = []; syncState.Text = "已同步"; Status("参数已同步到设备。");
            }
        }
        catch (Exception error) {
            synchronizationError = error.Message;
            BindingsNeedRefresh = true; PendingDeviceConfiguration = []; syncState.Text = "同步失败"; throw;
        }
    }
}
