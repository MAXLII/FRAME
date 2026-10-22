using System.Text.Json.Nodes;

namespace Frame.Desktop;

// One receiver owns consumption of the dedicated data connection. Its bounded history
// is shared through synchronized snapshots; neither WPF nor the control client runs here.
public sealed class RealtimeScopeAcquisition
{
    private readonly object lifecycle = new();
    private readonly RealtimeScopeConnection connection;
    private readonly RealtimeScopePreview preview;
    private readonly int[] channels;
    private readonly CancellationTokenSource cancellation = new();
    private string fault = "";
    private long triggerRevision;
    private Task? receiver;
    private Task? stopping;
    public string Fault => Volatile.Read(ref fault);
    public long TriggerRevision => Interlocked.Read(ref triggerRevision);
    public RealtimeScopeAcquisition(RealtimeScopeConnection connection, RealtimeScopePreview preview, IEnumerable<int> channels)
    {
        this.connection = connection; this.preview = preview; this.channels = channels.ToArray();
    }
    public void Start()
    {
        lock (lifecycle) {
            if (receiver != null || stopping != null) throw new InvalidOperationException("采集接收器已经启动或停止。");
            receiver = Task.Run(ReceiveAsync);
        }
    }
    public Task StopAsync()
    {
        lock (lifecycle) return stopping ??= StopCoreAsync();
    }
    private async Task StopCoreAsync()
    {
        cancellation.Cancel();
        try { if (receiver != null) await receiver.ConfigureAwait(false); }
        finally { cancellation.Dispose(); }
    }
    private void OnTriggerCompleted() => Interlocked.Increment(ref triggerRevision);
    private async Task ReceiveAsync()
    {
        preview.TriggerCompleted += OnTriggerCompleted;
        try {
            var sample = channels.ToDictionary(channel => channel, _ => 0d);
            while (!cancellation.IsCancellationRequested) {
                var batch = await connection.CommandAsync("drain").ConfigureAwait(false);
                if (cancellation.IsCancellationRequested) return;
                lock (preview.SyncRoot) {
                    foreach (var row in batch["rows"]!.AsArray().OfType<JsonObject>()) {
                        if (preview.SingleCompleted) break;
                        var values = row["values"]!.AsArray();
                        for (int i = 0; i < channels.Length; i++) sample[channels[i]] = values[i]?.GetValue<double>() ?? double.NaN;
                        preview.Append(sample);
                    }
                }
                string error = batch["fault"]?.ToString() ?? "";
                if (error.Length > 0 || batch["running"]?.GetValue<bool>() != true) {
                    Volatile.Write(ref fault, error.Length > 0 ? error : "设备已停止采样。"); return;
                }
                // Catch up immediately when the decoder has a backlog. Otherwise yield
                // without tying acquisition cadence to the UI refresh rate.
                if ((batch["pending"]?.GetValue<int>() ?? 0) == 0)
                    await Task.Delay(2, cancellation.Token).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { }
        catch (Exception error) { if (!cancellation.IsCancellationRequested) Volatile.Write(ref fault, error.Message); }
        finally { preview.TriggerCompleted -= OnTriggerCompleted; }
    }
}
