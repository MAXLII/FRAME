using System.Collections.Concurrent;
using System.Text;
using System.Text.Json.Nodes;
using Frame.Interop;

namespace Frame.Client;

public sealed record BackendJob(ulong Id, Task<JsonObject> Completion);
public sealed class BackendException(int code,string message) : Exception(message)
{
    public int Code { get; } = code;
}

public sealed class BackendClient : IAsyncDisposable
{
    private readonly BackendHandle handle;
    private readonly ConcurrentDictionary<ulong, TaskCompletionSource<JsonObject>> pending = new();
    private readonly ConcurrentDictionary<ulong,IProgress<JsonObject>> progressHandlers=new();
    private readonly object submissionGate=new();
    private ulong eventCursor;
    private readonly CancellationTokenSource lifetime = new();
    private readonly Task pump;
    private bool closing;
    public string? ShutdownError { get; private set; }

    public BackendClient()
    {
        if ((Native.Version() >> 16) != 1) throw new InvalidOperationException("Incompatible native ABI");
        handle = Native.Create();
        if (handle.IsInvalid) throw new InvalidOperationException("Cannot create backend");
        pump = Task.Run(PumpAsync);
    }

    public BackendJob Submit(JsonObject command) => Submit(command,null);
    private BackendJob Submit(JsonObject command,IProgress<JsonObject>? progress)
    {
        lock(submissionGate)
        {
        if (closing) throw new ObjectDisposedException(nameof(BackendClient));
        byte[] bytes = Encoding.UTF8.GetBytes(command.ToJsonString());
        int code = Native.Submit(handle, bytes, (uint)bytes.Length, out ulong id);
        if (code != 0) throw new BackendException(Math.Abs(code),$"Backend rejected submission ({code})");
        var completion = new TaskCompletionSource<JsonObject>(TaskCreationOptions.RunContinuationsAsynchronously);
        pending[id] = completion;
        if(progress!=null)progressHandlers[id]=progress;
        return new BackendJob(id, completion.Task);
        }
    }

    public async Task<JsonObject> ExecuteAsync(JsonObject command, CancellationToken cancellationToken = default,IProgress<JsonObject>? progress=null)
    {
        var job = Submit(command,progress);
        using var registration = cancellationToken.Register(() => Cancel(job.Id));
        return await job.Completion.ConfigureAwait(false);
    }

    public bool Cancel(ulong id) => !handle.IsClosed && Native.Cancel(handle, id)==0;

    public JsonObject Snapshot()
    {
        for (int retry=0;retry<4;retry++)
        {
            Native.Snapshot(handle,null,0,out uint length);
            if(length>16*1024*1024) throw new InvalidOperationException("Snapshot exceeds capacity");
            byte[] bytes=new byte[length];
            int code=Native.Snapshot(handle,bytes,length,out uint actual);
            if(code==2) continue;
            if(code!=0) throw new InvalidOperationException("Snapshot failed");
            return JsonNode.Parse(bytes.AsSpan(0,(int)actual))!.AsObject();
        }
        throw new InvalidOperationException("Snapshot changed repeatedly");
    }

    private async Task PumpAsync()
    {
        try
        {
            while(!lifetime.IsCancellationRequested)
            {
                ReadProgress();
                foreach(var pair in pending)
                {
                    int code=Native.Result(handle,pair.Key,null,0,out uint size);
                    if(code==1) continue;
                    if(code!=2 && code!=0) { if(pending.TryRemove(pair.Key,out var t))t.TrySetException(new InvalidOperationException("Result unavailable")); continue; }
                    if(size>64*1024*1024) { Native.Release(handle,pair.Key); if(pending.TryRemove(pair.Key,out var t))t.TrySetException(new InvalidOperationException("Result too large; use paging")); continue; }
                    byte[] bytes=new byte[size];
                    code=Native.Result(handle,pair.Key,bytes,size,out uint actual);
                    if(code!=0) continue;
                    var result=JsonNode.Parse(bytes.AsSpan(0,(int)actual))!.AsObject();
                    // Drain events published just before completion before
                    // posting the final result to the caller's UI context.
                    ReadProgress();
                    progressHandlers.TryRemove(pair.Key,out _);
                    Native.Release(handle,pair.Key);
                    if(pending.TryRemove(pair.Key,out var completion))completion.TrySetResult(result);
                }
                await Task.Delay(20,lifetime.Token).ConfigureAwait(false);
            }
        }
        catch(OperationCanceledException) { }
        catch(Exception error) { foreach(var entry in pending.Values) entry.TrySetException(error); }
    }

    private void ReadProgress()
    {
        lock(submissionGate)
        {
            for(int batch=0;batch<8;batch++)
            {
                int code=Native.Events(handle,eventCursor,128,null,0,out uint size);
                if(code!=0&&code!=2)return;
                if(size>16*1024*1024)throw new InvalidOperationException("Progress batch exceeds capacity");
                byte[] buffer=new byte[size];
                code=Native.Events(handle,eventCursor,128,buffer,size,out uint actual);
                if(code==2)continue;
                if(code!=0)return;
                var events=JsonNode.Parse(buffer.AsSpan(0,(int)actual))!["events"]!.AsArray();
                foreach(var entry in events)
                {
                    eventCursor=entry!["sequence"]!.GetValue<ulong>();
                    if(entry["kind"]?.ToString() is "parameter_directory" or "section_nodes" or "perf_samples"&&progressHandlers.TryGetValue(entry["operation_id"]!.GetValue<ulong>(),out var handler))handler.Report(entry["data"]!.AsObject());
                }
                if(events.Count<128)return;
            }
        }
    }

    public async ValueTask DisposeAsync()
    {
        if(closing)return; closing=true;
        foreach(ulong id in pending.Keys)Cancel(id);
        var tasks=pending.Values.Select(x=>x.Task).ToArray();
        try
        {
            var results=await Task.WhenAll(tasks).WaitAsync(TimeSpan.FromSeconds(5)).ConfigureAwait(false);
            var errors=results.Where(r=>r["code"]!.GetValue<int>() is not (0 or 130)).Select(r=>$"job {r["operation_id"]}: {r["error"]}").ToArray();
            if(errors.Length>0)ShutdownError=string.Join("; ",errors);
        }
        catch(Exception error) { ShutdownError="Shutdown did not complete cleanly: "+error.Message; }
        lifetime.Cancel(); await pump.ConfigureAwait(false);
        await Task.Run(handle.Dispose).ConfigureAwait(false);
        foreach(var entry in pending.Values)entry.TrySetCanceled();
        lifetime.Dispose();
    }
}
