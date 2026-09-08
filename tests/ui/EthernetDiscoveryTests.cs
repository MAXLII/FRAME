using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json.Nodes;
using Frame.Client;
using Frame.Desktop;

internal static class EthernetDiscoveryTests
{
    public static async Task RunAsync()
    {
        using var udp=new UdpClient(new IPEndPoint(IPAddress.Loopback,0));
        int port=((IPEndPoint)udp.Client.LocalEndPoint!).Port;
        using var stop=new CancellationTokenSource();
        const string reply="FRAME_DEVICE_V1;name=E507;ip=192.168.1.101;tcp_port=5000;mac=02-12-34-56-78-9a;fw_version=1.0;protocol_version=1";
        int requests=0;
        var responder=Task.Run(async ()=>{
            try{
                while(true){
                    var received=await udp.ReceiveAsync(stop.Token);
                    if(Encoding.ASCII.GetString(received.Buffer)!="FRAME_DISCOVER_V1")throw new Exception("Discovery request differs from legacy protocol");
                    Interlocked.Increment(ref requests);
                    foreach(var message in new[]{reply,reply,"unrelated",reply+";name=duplicate",reply.Replace("tcp_port=5000","tcp_port=65536"),reply.Replace("02-12","01-12"),reply.Replace("ip=192.168.1.101","ip=0.0.0.0")})
                        await udp.SendAsync(Encoding.ASCII.GetBytes(message),received.RemoteEndPoint);
                }
            }catch(OperationCanceledException){}
        });
        await using var client=new BackendClient();
        var result=await client.ExecuteAsync(new(){["group"]="ethernet",["action"]="discover",["host"]="127.0.0.1",["discovery_port"]=port,["scan_ms"]=350});
        stop.Cancel();await responder;
        var devices=result["data"]?["devices"]?.AsArray();
        if(result["ok"]?.GetValue<bool>()!=true||devices?.Count!=1||requests<2)throw new Exception("Discovery retry/deduplication/invalid-response filtering failed: "+result);
        var device=EthernetDevice.FromJson(devices[0]!);
        if(device.Ip!="127.0.0.1"||device.Port!=5000||device.Mac!="02:12:34:56:78:9A"||devices[0]!["advertised_ip"]!.ToString()!="192.168.1.101")throw new Exception("Discovery must connect to source IP and advertised TCP port");
        var empty=await client.ExecuteAsync(new(){["group"]="ethernet",["action"]="discover",["host"]="127.0.0.1",["discovery_port"]=port,["scan_ms"]=50});
        if(empty["ok"]?.GetValue<bool>()!=true||empty["data"]!["devices"]!.AsArray().Count!=0)throw new Exception("Empty discovery must complete with no stale devices");
        using var cancel=new CancellationTokenSource(80);
        try{
            var cancelled=await client.ExecuteAsync(new(){["group"]="ethernet",["action"]="discover",["host"]="127.0.0.1",["discovery_port"]=port,["scan_ms"]=10000},cancel.Token);
            if(cancelled["code"]?.GetValue<int>()!=130)throw new Exception("Discovery cancellation did not reach backend");
        }catch(OperationCanceledException){}
        var status=await client.ExecuteAsync(new(){["group"]="status"});
        if(status["ok"]?.GetValue<bool>()!=true)throw new Exception("Discovery cancellation left backend unavailable");
        Console.WriteLine("PASS: native UDP discovery, retry, MAC deduplication, invalid datagrams, source IP, empty scan, cancellation and device mapping.");
    }
}
