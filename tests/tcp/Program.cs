using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Text.Json.Nodes;
using Frame.Client;

static void Require(bool condition,string message){if(!condition)throw new Exception(message);}
string root=Path.GetFullPath(args.Length>0?args[0]:".");
string exe=Path.GetFullPath(args.Length>1?args[1]:Path.Combine(root,"build/app/frame.exe"));
var fixture=JsonNode.Parse(await File.ReadAllTextAsync(Path.Combine(root,"tests/fixtures/parameter-session.json")))!.AsArray();
using var timeout=new CancellationTokenSource(TimeSpan.FromSeconds(20));
var listener=new TcpListener(IPAddress.Loopback,0);listener.Start();
int port=((IPEndPoint)listener.LocalEndpoint).Port;
try
{
    async Task Serve()
    {
        using var peer=await listener.AcceptTcpClientAsync(timeout.Token);peer.NoDelay=true;
        using var stream=peer.GetStream();
        foreach(var step in fixture)
        {
            byte[] expected=Convert.FromHexString(step!["tx"]!.GetValue<string>());
            byte[] received=new byte[expected.Length];await stream.ReadExactlyAsync(received,timeout.Token);
            Require(received.SequenceEqual(expected),"TCP protocol TX differs from serial golden fixture");
            foreach(var chunk in step["rx"]!.AsArray())
            {
                byte[] bytes=Convert.FromHexString(chunk!.GetValue<string>());
                await stream.WriteAsync(bytes.AsMemory(0,1),timeout.Token);
                await Task.Delay(2,timeout.Token);
                await stream.WriteAsync(bytes.AsMemory(1),timeout.Token);
            }
        }
        Require(await stream.ReadAsync(new byte[1],timeout.Token)==0,"Shell disconnect must close TCP peer");
    }
    var server=Serve();
    var start=new ProcessStartInfo(exe){UseShellExecute=false,CreateNoWindow=true,RedirectStandardInput=true,RedirectStandardOutput=true,RedirectStandardError=true,WorkingDirectory=root};
    start.ArgumentList.Add("shell");start.ArgumentList.Add("--json");
    using var process=Process.Start(start)!;
    var output=process.StandardOutput.ReadToEndAsync(timeout.Token);var error=process.StandardError.ReadToEndAsync(timeout.Token);
    await process.StandardInput.WriteLineAsync($"connect --transport tcp --host 127.0.0.1 --tcp-port {port}");
    await process.StandardInput.WriteLineAsync("param list");
    await process.StandardInput.WriteLineAsync("param read --name TEST_COUNTER");
    await process.StandardInput.WriteLineAsync("disconnect");
    await process.StandardInput.WriteLineAsync("exit");process.StandardInput.Close();
    await process.WaitForExitAsync(timeout.Token);await server;
    var results=(await output).Split('\n',StringSplitOptions.RemoveEmptyEntries).Select(line=>JsonNode.Parse(line)!).ToArray();
    Require(process.ExitCode==0&&results.Length==4&&results.All(r=>r["ok"]!.GetValue<bool>()),"TCP Shell JSON failed: "+await error);
    Require(results[2]["data"]!["value"]!.GetValue<int>()==42,"TCP parameter result mismatch");
    Console.WriteLine("PASS: CLI/Shell persistent TCP, fragmented FRAME protocol, parameter read, JSON and disconnect.");
    async Task FailureCase(bool cancel,bool close)
    {
        await using var client=new BackendClient();
        var accepted=listener.AcceptTcpClientAsync(timeout.Token);
        var job=client.Submit(new(){["group"]="param",["action"]="list",["transport"]="tcp",["host"]="127.0.0.1",["tcp_port"]=port,["response_timeout"]=cancel?1000:50});
        using var peer=await accepted;
        byte[] bytes=new byte[32];int received=await peer.GetStream().ReadAsync(bytes,timeout.Token);Require(received>0,"Expected a TCP request before failure injection");
        if(cancel)client.Cancel(job.Id);
        if(close)peer.Close();
        var result=await job.Completion.WaitAsync(timeout.Token);
        Require(result["code"]!.GetValue<int>()==(cancel?130:close?3:4),"TCP failure classification mismatch: "+result);
    }
    await FailureCase(false,false);await FailureCase(true,false);await FailureCase(false,true);
    listener.Stop();
    await using(var client=new BackendClient())
    {
        var result=await client.ExecuteAsync(new(){["group"]="connect",["transport"]="tcp",["host"]="127.0.0.1",["tcp_port"]=port});
        Require(result["code"]!.GetValue<int>()==3,"TCP connection refusal classification");
        var invalid=await client.ExecuteAsync(new(){["group"]="connect",["transport"]="tcp",["host"]="not-an-IP",["tcp_port"]=9000});
        Require(invalid["code"]!.GetValue<int>()==2,"TCP address validation");
    }
    Console.WriteLine("PASS: TCP timeout, cancel, remote close, refusal and invalid address.");
}
finally{listener.Stop();}
