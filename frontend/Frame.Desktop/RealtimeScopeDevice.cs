using System.IO;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using System.Windows.Controls;

namespace Frame.Desktop;

public sealed partial class RealtimeScopePage
{
    private readonly ComboBox sourceChoice = Choice("realtime_source", "设备", "模拟源");
    private readonly TextBlock sourceBadge = Text("设备");
    private bool deviceRunning;
    private RealtimeScopeAcquisition? deviceAcquisition;
    private Task deviceReceiveStopTask = Task.CompletedTask;
    private long displayedTriggerRevision;
    private int deviceGeneration;
    private Task deviceStopTask = Task.CompletedTask;
    private Task deviceStatusTask = Task.CompletedTask;
    private long deviceByteBudget;
    private long nextDeviceStatus;
    public string LastDeviceFault { get; private set; } = "";
    public string LastDeviceStatusError { get; private set; } = "";
    private string? verifiedDeviceBindings;
    private string? publicConnection;
    private string? synchronizedConnection;
    private Task deviceConfigurationTask = Task.CompletedTask;
    private int configurationRevision;
    private string? deviceConfigurationError;
    public Task ChannelConfigurationCompletion => deviceConfigurationTask;
    private void ApplyDeviceCapabilities(JsonObject capability)
    {
        int sampleRate = capability["sample_frequency"]?.GetValue<int>() ?? 0;
        bool available = capability["sample_frequency_available"]?.GetValue<bool>() ?? capability.ContainsKey("sample_frequency");
        frequency.Text = available ? sampleRate.ToString(System.Globalization.CultureInfo.InvariantCulture) : "未提供";
        frequency.ToolTip = available && sampleRate == 0 ? "设备尚未接入采样中断；可以配置通道，暂不能运行采样。" : null;
        frequency.IsReadOnly = true;
        if (capability["byte_budget"] != null) deviceByteBudget = capability["byte_budget"]!.GetValue<long>();
        UpdateSummary();
    }
    public override Task TickAsync(JsonObject state)
    {
        if (Closed || sourceChoice.SelectedIndex != 0) return Task.CompletedTask;
        string? connection = state["connected"]?.GetValue<bool>() == true ? ConnectionKey(state) : null;
        if (connection != publicConnection || connection == null) {
            publicConnection = connection; verifiedDeviceBindings = null; synchronizedConnection = null;
            frequency.Text = "待同步"; frequency.ToolTip = "添加通道或参数同步时读取设备采样率。";
            deviceByteBudget = 0; UpdateSummary();
        }
        return Task.CompletedTask;
    }
    private static string ConnectionKey(JsonObject state) => $"{state["epoch"]}|{state["endpoint"]}|{state["wire"]}";
    private async Task VerifyDeviceBindingsAsync(bool force = false)
    {
        string key = ConnectionKey(Client.Snapshot()) + "|" + symbolFingerprint;
        if (!force && verifiedDeviceBindings == key) return;
        var capability = await ControlAsync("capabilities");
        ApplyDeviceCapabilities(capability);
        await VerifyDeviceElfAsync(capability);
        verifiedDeviceBindings = key;
        publicConnection = ConnectionKey(Client.Snapshot());
    }
    private void QueueChannelUpdate(int channel)
    {
        if (sourceChoice.SelectedIndex != 0 || demonstrationSymbols) return;
        int revision = ++configurationRevision;
        synchronizedConnection = null;
        var channels = ActiveWireChannels();
        PendingDeviceConfiguration = workspace.Configuration.Enabled.Select(item => new RealtimeScopeChannelUpdate(item.Number, item.Name,
            item.Symbol!.Address, item.Type, item.Symbol.Size, item.Symbol.Encoding)).ToArray();
        if (BindingsNeedRefresh) { syncState.Text = "待同步"; return; }
        syncState.Text = "待下发";
        if (Client.Snapshot()["connected"]?.GetValue<bool>() != true) return;
        Task previous = deviceConfigurationTask;
        deviceConfigurationTask = SendChannelUpdateAsync(previous, channel, channels, revision);
    }
    private async Task SendChannelUpdateAsync(Task previous, int channel, JsonArray channels, int revision)
    {
        try {
            await previous; await deviceStopTask;
            if (Closed || BindingsNeedRefresh) return;
            if (symbolFingerprint != await FingerprintAsync(elf.Text.Trim(), map.Text.Trim()))
                throw new InvalidOperationException("ELF 已更新，请先参数同步。");
            syncState.Text = "下发中";
            await VerifyDeviceBindingsAsync();
            var ack = await ControlAsync("set-channel", new() { ["channel"] = channel, ["channels"] = channels });
            ApplyDeviceCapabilities(ack);
            if (revision == configurationRevision) {
                deviceConfigurationError = null; PendingDeviceConfiguration = [];
                synchronizedConnection = ConnectionKey(Client.Snapshot());
                syncState.Text = "已同步"; Status($"CH{channel} 已下发。");
            }
        }
        catch (Exception error) {
            if (!Closed && revision == configurationRevision) {
                deviceConfigurationError = error.Message; syncState.Text = "下发失败"; Status(error.Message);
            }
        }
    }
    private async Task<JsonObject> ControlAsync(string action, JsonObject? arguments = null)
    {
        if (Client.Snapshot()["connected"]?.GetValue<bool>() != true)
            throw new InvalidOperationException("请先连接顶部公共通信链路。");
        var request = arguments ?? new JsonObject();
        request["group"] = "realtime-scope-control"; request["action"] = action; request["response_timeout"] = 5000;
        var result = await Client.ExecuteAsync(request);
        if (result["ok"]?.GetValue<bool>() != true) throw new InvalidOperationException(result["error"]?.ToString() ?? "示波器控制失败。");
        return result["data"]!.AsObject();
    }


    private static int WireType(RealtimeScopeSymbol symbol) => (symbol.Encoding, symbol.Size) switch {
        (4, 4) => 9, (4, 8) => 10, (2, 1) => 11,
        (5 or 6, 1) => 1, (7 or 8, 1) => 2,
        (5, 2) => 3, (7, 2) => 4, (5, 4) => 5, (7, 4) => 6,
        (5, 8) => 7, (7, 8) => 8, _ => throw new ArgumentException("设备不支持此参数类型。")
    };
    private JsonArray ActiveWireChannels() => new(workspace.Configuration.Enabled.Select(channel => (JsonNode)new JsonObject {
        ["channel"] = channel.Number, ["address"] = channel.Symbol!.Address, ["type"] = WireType(channel.Symbol)
    }).ToArray());
    private async Task StartSelectedSourceAsync()
    {
        StopPreview(); await deviceStopTask; await deviceConfigurationTask;
        LastDeviceFault = "";
        LastDeviceStatusError = "";
        if (sourceChoice.SelectedIndex == 1) { StartSimulation(); return; }
        if (BindingsNeedRefresh) throw new InvalidOperationException(synchronizationError ?? "参数绑定待更新，请先参数同步。");
        if (demonstrationSymbols) throw new InvalidOperationException("示例地址不能用于设备采样。");
        if (symbolFingerprint != await FingerprintAsync(elf.Text.Trim(), map.Text.Trim())) {
            BindingsNeedRefresh = true; syncState.Text = "待同步";
            throw new InvalidOperationException("ELF 已更新，请先参数同步。");
        }
        var channels = ActiveWireChannels();
        var capability = await ControlAsync("capabilities");
        ApplyDeviceCapabilities(capability);
        if (capability["sample_frequency"]?.GetValue<int>() == 0)
            throw new InvalidOperationException("设备尚未接入采样中断，当前采样率为 0 Hz。");
        var candidate = ValidatePreview(workspace.Configuration);
        await VerifyDeviceElfAsync(capability);
        deviceByteBudget = capability["byte_budget"]!.GetValue<long>();
        long bytesPerSecond = (long)(workspace.Configuration.ByteCount + 5) * candidate.SampleRate;
        if (candidate.SampleRate > capability["max_frequency"]!.GetValue<int>() || bytesPerSecond > capability["byte_budget"]!.GetValue<long>())
            throw new InvalidOperationException($"设备固定采样率 {candidate.SampleRate} Hz，带宽上限 {deviceByteBudget / 1000} kB/s，请减少通道或使用更窄的数据类型。");
        if (!scopeLink.HasSettings)
            throw new InvalidOperationException("请先连接示波器数据链路。");
        if (deviceConfigurationError != null) throw new InvalidOperationException(deviceConfigurationError);
        if (synchronizedConnection != ConnectionKey(Client.Snapshot()))
            throw new InvalidOperationException("通道尚未同步到当前设备，请参数同步。");
        await scopeLink.ReconnectAsync();
        bool ready = false;
        for (int attempt = 0; attempt < 20; ++attempt) {
            if ((await ControlAsync("status"))["data_connected"]?.GetValue<bool>() == true) { ready = true; break; }
            await Task.Delay(50);
        }
        if (!ready) throw new InvalidOperationException("设备数据链路尚未就绪。");
        await scopeLink.CommandAsync("configure", new() { ["channels"] = channels });
        preview = candidate;
        UpdateSources(); ConfigurePreviewCore(); snapshot.Clear(); rawSnapshot.Clear(); retainedHistory = false; snapshotSource = null; snapshotOriginMs = 0; follow = true;
        try {
            await scopeLink.CommandAsync("start", new() { ["frequency"] = candidate.SampleRate });
            var started = await ControlAsync("start");
            if (started["frequency"]!.GetValue<int>() != candidate.SampleRate) throw new InvalidOperationException("设备采样率已变化，请重新查询后运行。");
            nextDeviceStatus = 0;
            deviceRunning = true; ++deviceGeneration;
            deviceAcquisition = new(scopeLink, candidate, workspace.Configuration.Enabled.Select(channel => channel.Number));
            displayedTriggerRevision = 0; deviceAcquisition.Start();
            previewRunning = true; previewTimer.Start();
            sourceBadge.Text = "设备"; syncState.Text = "已同步"; PendingDeviceConfiguration = [];
            frequency.IsEnabled = history.IsEnabled = sourceChoice.IsEnabled = false; UpdateSummary(); UpdateRunState();
        }
        catch { await ControlAsync("stop"); await scopeLink.CommandAsync("stop"); throw; }
    }
    private async Task VerifyDeviceElfAsync(JsonObject capability)
    {
        string deviceElf = capability["elf_sha256"]!.ToString();
        using var input = File.OpenRead(elf.Text.Trim());
        string localElf = Convert.ToHexString(await SHA256.HashDataAsync(input));
        if (!localElf.Equals(deviceElf, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException($"{Path.GetFileName(elf.Text.Trim())} 与当前设备固件不一致，请选择本次烧录对应的 ELF 后参数同步。");
    }
    private void StopDevice()
    {
        if (!deviceRunning) return;
        deviceRunning = false; ++deviceGeneration; sourceChoice.IsEnabled = true;
        deviceReceiveStopTask = deviceAcquisition?.StopAsync() ?? Task.CompletedTask;
        deviceAcquisition = null;
        deviceStopTask = StopDeviceCoreAsync();
    }
    private async Task StopDeviceCoreAsync()
    {
        try { await deviceReceiveStopTask; await ControlAsync("stop"); }
        catch (Exception error) { if (!Closed) Status(error.Message); }
    }
    private async Task PollDeviceStatusAsync(int generation)
    {
        try {
            var status = await ControlAsync("status");
            if (Closed || !deviceRunning || generation != deviceGeneration) return;
            if (LastDeviceStatusError.Length > 0) { LastDeviceStatusError = ""; Status("设备状态查询已恢复。"); }
            string fault = status["fault"]?.ToString() ?? "";
            if (fault.Length == 0 && status["link_fault"]?.GetValue<long>() is > 0)
                fault = $"设备数据链路异常（{status["link_fault"]}）。";
            if (fault.Length > 0 || status["running"]?.GetValue<bool>() != true) {
                LastDeviceFault = fault.Length > 0 ? fault : "设备已停止采样。";
                StopPreview(); Status(LastDeviceFault);
            }
        }
        catch (Exception error) {
            if (!Closed && deviceRunning && generation == deviceGeneration) {
                if (LastDeviceStatusError != error.Message) Status("设备状态查询失败，数据接收继续：" + error.Message);
                LastDeviceStatusError = error.Message;
            }
        }
        finally {
            if (generation == deviceGeneration) nextDeviceStatus = Environment.TickCount64 + 500;
        }
    }
    private void RefreshDevice()
    {
        if (!deviceRunning || preview == null || deviceAcquisition == null) return;
        bool controlIdle = Client.Snapshot()["jobs"]?.AsArray().OfType<JsonObject>()
            .Any(job => job["background_stream"]?.GetValue<bool>() == false) != true;
        if (Environment.TickCount64 >= nextDeviceStatus && deviceStatusTask.IsCompleted && controlIdle) {
            nextDeviceStatus = Environment.TickCount64 + 500;
            deviceStatusTask = PollDeviceStatusAsync(deviceGeneration);
        }
        if (!deviceRunning || deviceAcquisition == null) return;
        long revision = deviceAcquisition.TriggerRevision;
        if (revision != displayedTriggerRevision || (!preview.DisplayPaused && (preview.AutoFallback || !preview.TriggerEnabled || !follow))) {
            displayedTriggerRevision = revision; CaptureSnapshot();
        }
        RenderSnapshot();
        string fault = deviceAcquisition.Fault;
        if (fault.Length > 0) { LastDeviceFault = fault; StopPreview(); Status(fault); }
        else if (preview.SingleCompleted) StopPreview();
        UpdateRunState();
    }
}
