using System.Buffers.Binary;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Text.Json.Nodes;
using System.Windows.Controls;
using Frame.Client;
using Frame.Desktop;

internal static class RealtimeScopeConcurrencyTests
{
    private const int Rate = 31250, Count = 64000, ChannelCount = 8;
    private static readonly BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    private static void Require(bool condition, string message) { if (!condition) throw new Exception(message); }
    private static void Set(object instance, string name, object value) => instance.GetType().GetField(name, Private)!.SetValue(instance, value);
    private static ushort Crc(byte[] data)
    {
        ushort crc = 0xFFFF;
        foreach (byte value in data) {
            crc ^= (ushort)(value << 8);
            for (int bit = 0; bit < 8; bit++) crc = unchecked((ushort)((crc & 0x8000) != 0 ? crc << 1 ^ 0x1021 : crc << 1));
        }
        return crc;
    }
    private static byte[] Reply(byte[] header, byte[] payload)
    {
        byte[] result = [0xE8, 1, header[4], header[5], header[2], header[3], 1, header[7], 1,
            (byte)payload.Length, (byte)(payload.Length >> 8), .. payload, 0, 0, 13, 10];
        BinaryPrimitives.WriteUInt16LittleEndian(result.AsSpan(result.Length - 4), Crc(result[..^4]));
        return result;
    }
    private static byte[] Samples(int first, int count)
    {
        const int payloadSize = ChannelCount * 4, frameSize = payloadSize + 5;
        var bytes = new byte[count * frameSize];
        for (int i = 0; i < count; i++) {
            int offset = i * frameSize, counter = first + i;
            bytes[offset] = 0xEA; bytes[offset + 1] = unchecked((byte)counter);
            for (int channel = 0; channel < ChannelCount; channel++)
                BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(offset + 2 + channel * 4), (uint)(counter + channel * 1000000));
            bytes[offset + 2 + payloadSize] = payloadSize;
            byte sum = 0; for (int j = 0; j < frameSize - 1; j++) sum = unchecked((byte)(sum + bytes[offset + j]));
            bytes[offset + frameSize - 1] = sum;
        }
        return bytes;
    }
    public static async Task Run()
    {
        using var publicServer = new TcpListener(IPAddress.Loopback, 0); publicServer.Start();
        using var dataServer = new TcpListener(IPAddress.Loopback, 0); dataServer.Start();
        using var cancel = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        var listStarted = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var releaseList = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        await using var common = new BackendClient();
        Require((await common.ExecuteAsync(new() { ["group"] = "connect", ["transport"] = "tcp", ["wire"] = "e8",
            ["host"] = "127.0.0.1", ["tcp_port"] = ((IPEndPoint)publicServer.LocalEndpoint).Port }))["ok"]!.GetValue<bool>(), "Common connection failed");
        using var publicPeer = await publicServer.AcceptTcpClientAsync();
        var fields = new Dictionary<string, TextBox>();
        var page = new RealtimeScopePage(common, fields, _ => { });
        await page.ScopeLink.ConnectAsync(new("tcp", "", 0, "127.0.0.1", ((IPEndPoint)dataServer.LocalEndpoint).Port));
        using var dataPeer = await dataServer.AcceptTcpClientAsync(); dataPeer.NoDelay = true;
        int statuses = 0, stops = 0, deviceOverflows = 0, rejectStatus = 0;
        var responder = Task.Run(async () => {
            try {
                var stream = publicPeer.GetStream();
                while (!cancel.IsCancellationRequested) {
                    var header = new byte[11]; await stream.ReadExactlyAsync(header, cancel.Token);
                    int size = BinaryPrimitives.ReadUInt16LittleEndian(header.AsSpan(9));
                    var body = new byte[size + 4]; await stream.ReadExactlyAsync(body, cancel.Token);
                    byte[] payload;
                    if (header[7] == 1) {
                        listStarted.TrySetResult();
                        await releaseList.Task.WaitAsync(cancel.Token);
                        payload = new byte[4]; // Valid empty directory; hold its reply while data keeps arriving.
                    }
                    else {
                        Require(header[7] == 0x3A, "Unexpected public command");
                        if (body[0] == 7) {
                            Interlocked.Increment(ref statuses);
                            var status = new byte[30]; status[0] = 1; status[17] = 1;
                            if (Volatile.Read(ref deviceOverflows) != 0) {
                                status[0] = 0; BinaryPrimitives.WriteUInt32LittleEndian(status.AsSpan(5), 1);
                            }
                            payload = [.. body[..3], 0, .. status];
                            if (Volatile.Read(ref rejectStatus) != 0) payload = [.. body[..3], 2];
                        }
                        else {
                            Require(body[0] == 2, "Only status and teardown STOP are expected");
                            Interlocked.Increment(ref stops); payload = [.. body[..3], 0];
                        }
                    }
                    await stream.WriteAsync(Reply(header, payload), cancel.Token);
                }
            }
            catch (Exception error) when (error is OperationCanceledException or EndOfStreamException or IOException or ObjectDisposedException) { }
        });
        Task? sender = null;
        try {
            var symbol = new RealtimeScopeSymbol(new JsonObject { ["name"] = "counter", ["address"] = 0x20001000UL,
                ["kind"] = "scalar", ["type_name"] = "uint32_t", ["size"] = 4, ["encoding"] = 7 });
            for (int channel = 1; channel <= ChannelCount; channel++) page.Workspace.Configuration.Add(symbol, channel);
            var preview = new RealtimeScopePreview(page.Workspace.Configuration, Rate, 4);
            preview.Configure(0.5, new(false, 1, 0, RealtimeScopeEdge.Rising, 0.5, false));
            Set(page, "preview", preview); Set(page, "previewRunning", true); Set(page, "deviceRunning", true);
            await page.ScopeLink.CommandAsync("configure", new() { ["channels"] = new JsonArray(Enumerable.Range(1, ChannelCount)
                .Select(channel => (JsonNode)new JsonObject { ["channel"] = channel, ["address"] = 0x20001000u + (uint)channel * 4, ["type"] = 6 }).ToArray()) });
            await page.ScopeLink.CommandAsync("start", new() { ["frequency"] = Rate });
            var acquisition = new RealtimeScopeAcquisition(page.ScopeLink, preview, Enumerable.Range(1, ChannelCount));
            Set(page, "deviceAcquisition", acquisition); acquisition.Start();
            string directoryFeedback = "";
            var panel = new ParameterPanel(request => { request["response_timeout"] = 10000; return common.ExecuteAsync(request); }, message => directoryFeedback = message,
                (request, progress) => { request["response_timeout"] = 10000; return common.ExecuteAsync(request, progress: progress); });
            Task refresh = panel.RunAsync("list");
            await listStarted.Task.WaitAsync(TimeSpan.FromSeconds(3));
            sender = Task.Run(async () => {
                for (int first = 0; first < Count; first += 1000) {
                    await dataPeer.GetStream().WriteAsync(Samples(first, 1000), cancel.Token);
                    await Task.Delay(32, cancel.Token);
                }
            });
            var refreshDisplay = typeof(RealtimeScopePage).GetMethod("RefreshDevice", Private)!;
            refreshDisplay.Invoke(page, null);
            await Task.Delay(50, cancel.Token);
            // Deliberately block the WPF thread longer than the native queue can hold.
            // Neither a public request nor rendering can be a prerequisite for reception.
            long beforeUiBlock = preview.NextSample;
            var blocked = System.Diagnostics.Stopwatch.StartNew();
            while (preview.NextSample - beforeUiBlock < 40000 && blocked.Elapsed < TimeSpan.FromSeconds(4)) Thread.Sleep(20);
            long receivedWhileUiBlocked = preview.NextSample - beforeUiBlock;
            while (!sender.IsCompleted && page.PreviewRunning) {
                refreshDisplay.Invoke(page, null);
                await Task.Delay(10, cancel.Token);
            }
            await sender;
            long receivedWhileListing = preview.NextSample;
            releaseList.TrySetResult();
            await refresh.WaitAsync(TimeSpan.FromSeconds(5));
            for (int retry = 0; retry < 100 && preview.NextSample < Count && page.PreviewRunning; retry++) {
                refreshDisplay.Invoke(page, null); await Task.Delay(10, cancel.Token);
            }
            Require(receivedWhileUiBlocked > 32768, $"WPF blocked reception: only {receivedWhileUiBlocked} samples reached history during the UI stall");
            Require(receivedWhileListing > 32768, $"Parameter refresh blocked reception: only {receivedWhileListing}/{Count} samples were consumed before its reply");
            Require(page.PreviewRunning && page.LastDeviceFault == "" && preview.NextSample == Count,
                $"Acquisition stopped or lost data during parameter refresh: {page.LastDeviceFault}; {preview.NextSample}/{Count}");
            Require(preview.Samples(1, 0, Count - 1).Select((value, index) => value == index).All(value => value), "Sample values/order changed while refreshing parameters");
            Require(!panel.IsBusy && directoryFeedback.Contains("已读取 0"), "Parameter refresh must itself complete successfully");
            for (int retry = 0; retry < 100 && Volatile.Read(ref statuses) == 0; retry++) {
                refreshDisplay.Invoke(page, null); await Task.Delay(10, cancel.Token);
            }
            Require(Volatile.Read(ref statuses) > 0 && Volatile.Read(ref stops) == 0, "Status polling must resume without stopping the device");
            Console.WriteLine($"PASS: UI blocked while {receivedWhileUiBlocked} samples reached history; parameter refresh held while {receivedWhileListing} arrived; all {Count} counter samples received in order, no queue overflow or STOP, status polling resumed.");
            Interlocked.Exchange(ref rejectStatus, 1); Set(page, "nextDeviceStatus", 0L);
            for (int retry = 0; retry < 150 && page.LastDeviceStatusError == ""; retry++) {
                refreshDisplay.Invoke(page, null); await Task.Delay(10, cancel.Token);
            }
            await dataPeer.GetStream().WriteAsync(Samples(Count, 5000), cancel.Token);
            for (int retry = 0; retry < 100 && preview.NextSample < Count + 5000; retry++) await Task.Delay(10, cancel.Token);
            Require(page.PreviewRunning && page.LastDeviceFault == "" && page.LastDeviceStatusError != "" && preview.NextSample == Count + 5000,
                "A failed public status request must not terminate a healthy independent data stream");
            Interlocked.Exchange(ref rejectStatus, 0); Set(page, "nextDeviceStatus", 0L);
            for (int retry = 0; retry < 150 && page.LastDeviceStatusError != ""; retry++) {
                refreshDisplay.Invoke(page, null); await Task.Delay(10, cancel.Token);
            }
            Require(page.LastDeviceStatusError == "", "Status polling must recover after a transient public-link error");
            preview.PauseDisplay(); var frozen = preview.CaptureHistory();
            await dataPeer.GetStream().WriteAsync(Samples(Count + 5000, 1000), cancel.Token);
            for (int retry = 0; retry < 100 && preview.NextSample < Count + 6000; retry++) await Task.Delay(10, cancel.Token);
            Require(preview.NextSample == Count + 6000 && ReferenceEquals(frozen, preview.CaptureHistory()) && frozen.Values[1][^1] == Count + 4999,
                "Background reception must keep progressing without rewriting the frozen history");
            foreach (int channel in Enumerable.Range(1, ChannelCount))
                Require(preview.Samples(channel, 0, Count + 5999).Select((value, index) => value == index + (channel - 1) * 1000000).All(value => value),
                    "Control failures and display freezes must preserve every counter sample in every channel");
            preview.Rearm();
            Console.WriteLine($"PASS: public status failure/recovery does not stop data reception; frozen history stays stable; {ChannelCount} channels x {Count + 6000} counter values match exactly.");
            Interlocked.Exchange(ref deviceOverflows, 1);
            Set(page, "nextDeviceStatus", 0L);
            for (int retry = 0; retry < 150 && page.PreviewRunning; retry++) {
                refreshDisplay.Invoke(page, null); await Task.Delay(10, cancel.Token);
            }
            Require(!page.PreviewRunning && page.LastDeviceFault.Contains("设备采样缓存溢出"),
                "Decoupled status polling must still stop on a real device fault");
            Console.WriteLine("PASS: a subsequent device overflow still stops acquisition and preserves its fault reason.");
        }
        finally {
            releaseList.TrySetResult();
            page.Shutdown(); await page.ShutdownCompletion;
            cancel.Cancel(); publicPeer.Dispose();
            await responder;
            if (sender != null) { try { await sender; } catch (OperationCanceledException) { } }
        }
    }
}
