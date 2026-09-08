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
}
