using System.Text.Json.Nodes;
using Frame.Client;

namespace Frame.Desktop;

public sealed record RealtimeScopeLinkSettings(string Transport, string Port, uint Baud, string Host, int TcpPort)
{
    public JsonObject Request()
    {
        // Dedicated native decoder; never inherit the common parameter connection.
        var request = new JsonObject { ["group"] = "connect", ["transport"] = Transport, ["protocol"] = "realtime-scope", ["wire"] = "e8", ["timeout"] = 5000 };
        if (Transport == "serial") {
            if (string.IsNullOrWhiteSpace(Port) || Baud == 0) throw new ArgumentException("请设置实时示波器的独立串口和有效波特率。");
            request["port"] = Port.Trim(); request["baud"] = Baud;
        }
        else if (Transport == "tcp") {
            if (string.IsNullOrWhiteSpace(Host) || TcpPort is < 1 or > 65535) throw new ArgumentException("请设置实时示波器的独立 IP 和 TCP 端口（1～65535）。");
            request["host"] = Host.Trim(); request["tcp_port"] = TcpPort;
        }
        else throw new ArgumentException("不支持的实时示波器链路类型。");
        return request;
    }
}

// Each BackendClient owns its own native runtime, transport handle and receive state.
// This controller is never passed MainWindow's common client or the symbol-only client.
public sealed class RealtimeScopeConnection : IAsyncDisposable
{
    private readonly SemaphoreSlim gate = new(1, 1);
    private BackendClient? client;
    private volatile bool closing;
    private Task? shutdown;
    private RealtimeScopeLinkSettings? settings;
    public bool HasSettings => settings != null;
    public JsonObject Snapshot() => closing || client == null
        ? new JsonObject { ["connected"] = false, ["rx_bytes"] = 0UL, ["tx_bytes"] = 0UL }
        : client.Snapshot();
    public async Task<string[]> PortsAsync()
    {
        await gate.WaitAsync().ConfigureAwait(false);
        try {
            ThrowIfClosing(); client ??= new BackendClient();
            var result = Check(await client.ExecuteAsync(new() { ["group"] = "serial", ["action"] = "ports" }).ConfigureAwait(false));
            return result?["data"]?.AsArray().Select(item => item is JsonObject entry ? entry["port"]?.ToString() ?? "" : item?.ToString() ?? "").Where(port => port.Length > 0).ToArray() ?? [];
        }
        finally { gate.Release(); }
    }
    public async Task ConnectAsync(RealtimeScopeLinkSettings settings)
    {
        var request = settings.Request();
        await gate.WaitAsync().ConfigureAwait(false);
        try {
            ThrowIfClosing(); client ??= new BackendClient();
            if (client.Snapshot()["connected"]?.GetValue<bool>() == true)
                Check(await client.ExecuteAsync(new() { ["group"] = "disconnect" }).ConfigureAwait(false));
            Check(await client.ExecuteAsync(request).ConfigureAwait(false));
            this.settings = settings;
        }
        finally { gate.Release(); }
    }
    public async Task ReconnectAsync()
    {
        var saved = settings ?? throw new InvalidOperationException("请先连接示波器数据链路。");
        for (int attempt = 0; ; ++attempt) {
            try { await ConnectAsync(saved).ConfigureAwait(false); return; }
            catch when (attempt < 2 && !closing) { await Task.Delay(100).ConfigureAwait(false); }
        }
    }
    public static async Task<JsonObject> DiscoverAsync(CancellationToken token)
    {
        await using var discovery = new BackendClient();
        return await discovery.ExecuteAsync(new() { ["group"] = "ethernet", ["action"] = "discover", ["scan_ms"] = 800, ["timeout"] = 3000 }, token);
    }
    public async Task DisconnectAsync()
    {
        await gate.WaitAsync().ConfigureAwait(false);
        try {
            ThrowIfClosing();
            if (client?.Snapshot()["connected"]?.GetValue<bool>() == true)
                Check(await client.ExecuteAsync(new() { ["group"] = "disconnect" }).ConfigureAwait(false));
        }
        finally { gate.Release(); }
    }
    public async Task<JsonObject> CommandAsync(string action, JsonObject? arguments = null)
    {
        await gate.WaitAsync().ConfigureAwait(false);
        try {
            ThrowIfClosing();
            if (client == null || client.Snapshot()["connected"]?.GetValue<bool>() != true) throw new InvalidOperationException("请先连接示波器数据链路。");
            var request = arguments ?? new JsonObject(); request["group"] = "realtime-scope"; request["action"] = action;
            request["response_timeout"] = 5000;
            return Check(await client.ExecuteAsync(request).ConfigureAwait(false))["data"]!.AsObject();
        }
        finally { gate.Release(); }
    }
    private void ThrowIfClosing() { if (closing) throw new ObjectDisposedException(nameof(RealtimeScopeConnection)); }
    private static JsonObject Check(JsonObject result)
    {
        if (result["ok"]?.GetValue<bool>() != true) throw new InvalidOperationException(result["error"]?.ToString() ?? "实时示波器独立链路操作失败。");
        return result;
    }
    public ValueTask DisposeAsync() => new(shutdown ??= CloseAsync());
    private async Task CloseAsync()
    {
        closing = true;
        await gate.WaitAsync().ConfigureAwait(false);
        try { if (client != null) await client.DisposeAsync().ConfigureAwait(false); }
        finally { gate.Release(); }
    }
}
