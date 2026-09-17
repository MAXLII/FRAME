using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Windows.Controls;
using Frame.Client;
using Frame.Desktop;

internal static class ConnectionSwitchTests
{
    public static async Task RunAsync(MainWindow window,string root)
    {
        const BindingFlags flags=BindingFlags.Instance|BindingFlags.NonPublic;
        var client=(BackendClient)typeof(MainWindow).GetField("client",flags)!.GetValue(window)!;
        var connect=typeof(MainWindow).GetMethod("ConnectDiscoveredAsync",flags)!;
        var type=(ComboBox)window.FindName("ConnectionType");
        type.SelectedIndex=1;await Task.Delay(100);
        using var first=new TcpListener(IPAddress.Loopback,0);first.Start();
        using var second=new TcpListener(IPAddress.Loopback,0);second.Start();
        EthernetDevice Device(TcpListener listener)=>new("loopback","127.0.0.1",((IPEndPoint)listener.LocalEndpoint).Port,"02:00:00:00:00:01","1","1","test");
        await (Task)connect.Invoke(window,[Device(first)])!;
        using var firstPeer=await first.AcceptTcpClientAsync().WaitAsync(TimeSpan.FromSeconds(2));
        var originalClosed=firstPeer.GetStream().ReadAsync(new byte[1]).AsTask();
        await (Task)connect.Invoke(window,[Device(second)])!;
        using var secondPeer=await second.AcceptTcpClientAsync().WaitAsync(TimeSpan.FromSeconds(2));
        if(await originalClosed.WaitAsync(TimeSpan.FromSeconds(2))!=0)throw new Exception("Switch must close old TCP session");
        if(client.Snapshot()["endpoint"]?.ToString()!=$"tcp://127.0.0.1:{Device(second).Port}")throw new Exception("Discovered device did not auto-connect to new endpoint: "+client.Snapshot()+"; "+((TextBlock)window.FindName("Feedback")).Text);
        var rejected=await client.ExecuteAsync(new(){["group"]="serial",["action"]="baud",["baud"]=9600});
        if(rejected["ok"]!.GetValue<bool>()||!client.Snapshot()["connected"]!.GetValue<bool>())throw new Exception("Baud changes must reject TCP without dropping connection");
        await VerifyTargetSwitch(window,client,secondPeer);
        type.SelectedIndex=0;
        await Task.Delay(200);
        if(client.Snapshot()["connected"]!.GetValue<bool>())throw new Exception("Changing transport must disconnect");
        await client.ExecuteAsync(new(){["group"]="connect",["replay"]=System.IO.Path.Combine(root,"tests/fixtures/wave-periodic.json")});
        var port=(ComboBox)window.FindName("Port");
        port.ItemsSource=new[]{new SerialPortItem("COM77","test"),new SerialPortItem("COM78","test")};port.SelectedIndex=1;
        await Task.Delay(200);
        if(client.Snapshot()["connected"]!.GetValue<bool>())throw new Exception("Selecting a different serial port must disconnect");
        Console.WriteLine("PASS: discovered TCP endpoint auto-connect/switch, old session close, transport/serial selection disconnect, TCP baud rejection.");
    }

    private static async Task VerifyTargetSwitch(MainWindow window,BackendClient client,TcpClient peer)
    {
        var address=(TextBox)window.FindName("Address");
        var dynamicAddress=(TextBox)window.FindName("DynamicAddress");
        var endpoint=client.Snapshot()["endpoint"]!.ToString();
        using var timeout=new CancellationTokenSource(TimeSpan.FromSeconds(8));
        static byte[] Reply(byte source,byte dynamicSource,uint count)
        {
            byte[] bytes=[0xe8,1,source,dynamicSource,1,0,1,1,1,4,0,(byte)count,(byte)(count>>8),(byte)(count>>16),(byte)(count>>24),0,0,13,10];
            ushort crc=0xffff;
            foreach(byte value in bytes.AsSpan(0,15))
            {
                crc^=(ushort)(value<<8);
                for(int bit=0;bit<8;bit++)crc=(ushort)((crc&0x8000)!=0?(crc<<1)^0x1021:crc<<1);
            }
            bytes[15]=(byte)crc;bytes[16]=(byte)(crc>>8);return bytes;
        }
        async Task Exchange(byte target,byte dynamicTarget,string? editWhilePending=null)
        {
            address.Text=target.ToString();dynamicAddress.Text=dynamicTarget.ToString();
            var request=new System.Text.Json.Nodes.JsonObject{["group"]="param",["action"]="list"};
            var job=client.Submit(request);
            if(request.ContainsKey("dst"))throw new Exception("Submission must not mutate caller command");
            if(editWhilePending!=null)address.Text=editWhilePending;
            byte[] sent=new byte[15];
            await peer.GetStream().ReadExactlyAsync(sent,timeout.Token);
            if(sent[4]!=target||sent[5]!=dynamicTarget||sent[7]!=1)throw new Exception("Live target not reflected in transmitted FRAME header");
            // An ACK from another node must not satisfy the pending transaction.
            await peer.GetStream().WriteAsync(Reply((byte)(target==2?3:2),dynamicTarget,100001),timeout.Token);
            await peer.GetStream().WriteAsync(Reply(target,dynamicTarget,0),timeout.Token);
            var result=await job.Completion.WaitAsync(timeout.Token);
            if(!result["ok"]!.GetValue<bool>()||result["data"]!.AsArray().Count!=0)throw new Exception("Target reply mismatch: "+result);
            if(!client.Snapshot()["connected"]!.GetValue<bool>()||client.Snapshot()["endpoint"]!.ToString()!=endpoint)throw new Exception("Target change must retain TCP connection");
        }
        await Exchange(2,0,"3");
        await Exchange(3,0);
        await Exchange(2,7);
        foreach(string invalid in new[]{"","256","-1","abc"})
        {
            address.Text=invalid;
            try{client.Submit(new(){["group"]="param",["action"]="list"});throw new Exception("Invalid target was accepted");}
            catch(InvalidOperationException error) when(error.Message.Contains("0–255")) { }
        }
        await Exchange(2,0);
        Console.WriteLine("PASS: same TCP connection routes 2 -> 3 -> 2, dynamic address, in-flight target snapshot, foreign ACK rejection and invalid input.");
    }
}
