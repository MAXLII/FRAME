using System.Buffers.Binary;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text.Json.Nodes;
using Frame.Client;
using Frame.Desktop;

internal static class RealtimeScopeDeviceTests
{
    private static void Require(bool condition, string message) { if (!condition) throw new Exception(message); }
    private static ushort Crc(byte[] data) {
        ushort crc = 0xFFFF;
        foreach (byte value in data) {
            crc ^= (ushort)(value << 8);
            for (int i = 0; i < 8; ++i) crc = unchecked((ushort)((crc & 0x8000) != 0 ? (crc << 1) ^ 0x1021 : crc << 1));
        }
        return crc;
    }
    private static byte[] Reply(byte[] request, byte[] payload) {
        byte[] frame = [0xE8, 1, request[4], request[5], request[2], request[3], 1, 0x3A, 1, (byte)payload.Length, 0, .. payload, 0, 0, 13, 10];
        BinaryPrimitives.WriteUInt16LittleEndian(frame.AsSpan(frame.Length - 4), Crc(frame[..^4])); return frame;
    }
    private static byte[] Sample(byte index) {
        byte[] frame = [0xEA, index, 0xEA, 0xEB, 0x34, 0x12, 0x85, 0xFF, 6, 0, 0];
        frame[^1] = unchecked((byte)frame[..^1].Sum(value => value)); return frame;
    }
    public static async Task Run()
    {
        using var publicServer = new TcpListener(IPAddress.Loopback, 0); publicServer.Start();
        using var dataServer = new TcpListener(IPAddress.Loopback, 0); dataServer.Start();
        await using var common = new BackendClient(); await using var data = new RealtimeScopeConnection();
        Require((await common.ExecuteAsync(new() { ["group"] = "connect", ["transport"] = "tcp", ["wire"] = "e8", ["host"] = "127.0.0.1", ["tcp_port"] = ((IPEndPoint)publicServer.LocalEndpoint).Port }))["ok"]!.GetValue<bool>(), "Public connection failed");
        using var publicPeer = await publicServer.AcceptTcpClientAsync();
        await data.ConnectAsync(new("tcp", "", 0, "127.0.0.1", ((IPEndPoint)dataServer.LocalEndpoint).Port));
        TcpClient? dataPeer = await dataServer.AcceptTcpClientAsync(); dataPeer.NoDelay = true;
        var commands = new List<byte>(); bool overflow = false;
        using var cancel = new CancellationTokenSource(TimeSpan.FromSeconds(25));
        var responder = Task.Run(async () => {
            try {
                var stream = publicPeer.GetStream();
                while (!cancel.IsCancellationRequested) {
                    var head = new byte[11]; await stream.ReadExactlyAsync(head, cancel.Token);
                    Require(head[0] == 0xE8 && head[6] == 1 && head[7] == 0x3A && head[8] == 0, "Controls must use public E8 command 01/3A");
                    int length = BinaryPrimitives.ReadUInt16LittleEndian(head.AsSpan(9));
                    var tail = new byte[length + 4]; await stream.ReadExactlyAsync(tail, cancel.Token);
                    Require(Crc([.. head, .. tail[..length]]) == BinaryPrimitives.ReadUInt16LittleEndian(tail.AsSpan(length)), "Public control CRC mismatch");
                    byte word = tail[0]; commands.Add(word); byte[] result = [];
                    if (word == 1) {
                        result = new byte[46]; result[0] = 1; result[1] = 32;
                        BinaryPrimitives.WriteUInt32LittleEndian(result.AsSpan(2), 50000);
                        BinaryPrimitives.WriteUInt32LittleEndian(result.AsSpan(6), 1000000);
                        BinaryPrimitives.WriteUInt32LittleEndian(result.AsSpan(42), 30000);
                    }
                    if (word == 2 && dataPeer != null) { Require(dataPeer.Available == 0, "Data socket must never carry commands"); dataPeer.Dispose(); dataPeer = null; }
                    if (word is 3 or 4) { result = new byte[4]; BinaryPrimitives.WriteUInt32LittleEndian(result, 30000); }
                    if (word == 4) Require(tail[3] is 1 or 32, "Sparse slot mapping lost");
                    if (word == 5) { result = [6, 0, 0, 0, 0, 0]; BinaryPrimitives.WriteUInt32LittleEndian(result.AsSpan(2), 30000); }
                    if (word == 6) { Require(length == 3, "START must not set the MCU sampling rate"); result = new byte[4]; BinaryPrimitives.WriteUInt32LittleEndian(result, 30000); }
                    if (word == 7) { result = new byte[18]; result[0] = 1; result[17] = dataPeer != null ? (byte)1 : (byte)0; if (overflow) result[5] = 1; }
                    var response = Reply(head, [.. tail[..3], 0, .. result]);
                    await stream.WriteAsync(response.AsMemory(0, 3), cancel.Token); await stream.WriteAsync(response.AsMemory(3), cancel.Token);
                    if (word == 6) {
                        for (int i = 0; i < 300; i++) {
                            var sample = Sample(unchecked((byte)i));
                            await dataPeer!.GetStream().WriteAsync(sample.AsMemory(0, 4), cancel.Token);
                            await dataPeer.GetStream().WriteAsync(sample.AsMemory(4), cancel.Token);
                        }
                    }
                }
            }
            catch (Exception error) when (error is OperationCanceledException or EndOfStreamException or IOException or ObjectDisposedException) { }
        });
        async Task<JsonObject> Control(string action, JsonObject? args = null) {
            args ??= new(); args["group"] = "realtime-scope-control"; args["action"] = action; args["response_timeout"] = 3000;
            var response = await common.ExecuteAsync(args); Require(response["ok"]?.GetValue<bool>() == true, response["error"]?.ToString() ?? "Control failed");
            return response["data"]!.AsObject();
        }
        try {
            Require((await Control("capabilities"))["channels"]!.GetValue<int>() == 32, "Capabilities failed");
            var invalidRate = await common.ExecuteAsync(new() { ["group"] = "realtime-scope-control", ["action"] = "start", ["frequency"] = 30000 });
            Require(invalidRate["ok"]?.GetValue<bool>() == false && !commands.Contains(6), "Host frequency setting must be rejected before starting the MCU");
            var layout = new JsonArray(new JsonObject { ["channel"] = 32, ["address"] = 0x40800104u, ["type"] = 3 }, new JsonObject { ["channel"] = 1, ["address"] = 0x40800100u, ["type"] = 6 });
            await data.CommandAsync("configure", new() { ["channels"] = layout.DeepClone() });
            await dataPeer!.GetStream().WriteAsync(Sample(99).AsMemory(0, 4));
            Require((await Control("configure", new() { ["channels"] = layout.DeepClone() }))["sample_frequency"]!.GetValue<int>() == 30000,
                "Full synchronization must return the rate from its configuration ACK");
            int beforeUpdate = commands.Count;
            Require((await Control("set-channel", new() { ["channel"] = 32, ["channels"] = layout.DeepClone() }))["sample_frequency"]!.GetValue<int>() == 30000,
                "Incremental channel ACK must return the sampling rate");
            Require(commands.Skip(beforeUpdate).SequenceEqual(new byte[] { 4 }) && !commands.Contains(5), "Channel updates must stage one slot without swapping the active bank");
            await data.ReconnectAsync(); dataPeer = await dataServer.AcceptTcpClientAsync(); dataPeer.NoDelay = true;
            Require((await Control("status"))["data_connected"]!.GetValue<bool>(), "Data readiness missing");
            await data.CommandAsync("configure", new() { ["channels"] = layout });
            await data.CommandAsync("start", new() { ["frequency"] = 30000 });
            Require((await Control("start"))["frequency"]!.GetValue<int>() == 30000, "START must report the board's fixed rate");
            int received = 0;
            for (int i = 0; i < 100 && received < 300; i++) {
                var batch = await data.CommandAsync("drain");
                foreach (var row in batch["rows"]!.AsArray().OfType<JsonObject>()) {
                    Require(row["index"]!.GetValue<int>() == received++, "Sample counter must start fresh and survive wrap");
                    var values = row["values"]!.AsArray();
                    Require(values[0]!.GetValue<double>() == 0x1234EBEA && values[1]!.GetValue<double>() == -123, "Sparse native type decoding failed");
                }
                Require(batch["fault"]!.ToString() == "" && batch["missing"]!.GetValue<int>() == 0, "Valid data marked corrupt");
                if (received < 300) await Task.Delay(10);
            }
            Require(received == 300, "Missing acquisition samples");
            Require(data.Snapshot()["tx_bytes"]!.GetValue<long>() == 0 && dataPeer.Available == 0, "Data link must transmit zero application bytes");
            overflow = true; Require((await Control("status"))["fault"]!.ToString().Contains("溢出"), "Overflow must be reported over common control");
            await Control("stop"); Require(commands.Take(9).SequenceEqual(new byte[] { 1, 2, 3, 4, 4, 4, 7, 5, 6 }), "Configure must stage channels; START must activate them");
        }
        finally { cancel.Cancel(); dataPeer?.Dispose(); await responder; }
        Console.WriteLine("PASS: separate public E8 control and receive-only EA TCP, zero data-link TX, fresh session boundary, 300 sparse typed samples, wrap and overflow status.");
    }
}
