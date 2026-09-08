using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Text;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using Frame.Client;
using Frame.Desktop;

internal static class SectionRefreshTests
{
    private static byte[] Packet(byte word,byte[] payload)
    {
        var bytes=new List<byte>{0xe8,1,2,0,1,0,1,word,1,(byte)payload.Length,(byte)(payload.Length>>8)};bytes.AddRange(payload);
        ushort crc=0xffff;foreach(byte value in bytes){crc^=(ushort)(value<<8);for(int i=0;i<8;i++)crc=(ushort)((crc&0x8000)!=0?(crc<<1)^0x1021:crc<<1);}
        bytes.Add((byte)crc);bytes.Add((byte)(crc>>8));bytes.Add(13);bytes.Add(10);return bytes.ToArray();
    }
    private static byte[] Directory(ushort index,ushort id,string name)
    {
        var bytes=new List<byte>{1,0};bytes.AddRange(BitConverter.GetBytes(index));bytes.AddRange(BitConverter.GetBytes((ushort)2));bytes.AddRange(BitConverter.GetBytes(id));bytes.AddRange(BitConverter.GetBytes(2u));bytes.Add((byte)name.Length);bytes.AddRange(Encoding.ASCII.GetBytes(name));return Packet(0x38,bytes.ToArray());
    }
    private static byte[] Node(uint index,uint count=2,byte status=0)
    {
        var bytes=new List<byte>{1,status};bytes.AddRange(BitConverter.GetBytes((ushort)7));bytes.AddRange(BitConverter.GetBytes(index));bytes.AddRange(BitConverter.GetBytes(count));bytes.AddRange(BitConverter.GetBytes(0x20000000u+index*16));return Packet(0x39,bytes.ToArray());
    }
    private static async Task<byte[]> Request(NetworkStream stream,byte word,CancellationToken token)
    {
        var header=new byte[11];await stream.ReadExactlyAsync(header,token);var tail=new byte[BitConverter.ToUInt16(header,9)+4];await stream.ReadExactlyAsync(tail,token);
        if(header[7]!=word)throw new Exception($"Unexpected section command {header[7]:X2}");return tail;
    }
    public static async Task Run()
    {
        using var deadline=new CancellationTokenSource(TimeSpan.FromSeconds(12));var token=deadline.Token;
        using var listener=new TcpListener(IPAddress.Loopback,0);listener.Start();await using var client=new BackendClient();
        var accept=listener.AcceptTcpClientAsync(token);await client.ExecuteAsync(new(){["group"]="connect",["transport"]="tcp",["host"]="127.0.0.1",["tcp_port"]=((IPEndPoint)listener.LocalEndpoint).Port});
        using var peer=await accept;var stream=peer.GetStream();string feedback="";
        var page=new SectionPage(client,new(),message=>feedback=message);var host=new Window{Content=page,Width=1100,Height=650,ShowInTaskbar=false};host.Show();host.UpdateLayout();
        DataGrid Grid(string name)=>(DataGrid)typeof(SectionPage).GetField(name,BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(page)!;
        void Click(string label)=>DiagnosticPageTests.Visuals<Button>(page).Single(b=>Equals(b.Content,label)).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        async Task Until(Func<bool> check){while(!check())await Task.Delay(10,token);}
        var lists=Grid("lists");var nodes=Grid("nodes");
        try
        {
            Click("刷新所选链表");if(!feedback.Contains("请选择")&&!feedback.Contains("选择链表"))throw new Exception("Missing selection must report an actionable message");
            Click("刷新链表列表");
            for(ushort i=0;i<2;i++){var request=await Request(stream,0x38,token);if(BitConverter.ToUInt16(request)!=i)throw new Exception("Directory request order");await stream.WriteAsync(Directory(i,(ushort)(i==0?3:7),i==0?"Task":"Interrupt"),token);}
            await Until(()=>lists.Items.Count==2);DiagnosticPageTests.ClickCell(lists,1);
            Click("刷新所选链表");
            for(uint i=0;i<2;i++)
            {
                var request=await Request(stream,0x39,token);if(BitConverter.ToUInt16(request)!=7||BitConverter.ToUInt32(request,2)!=i)throw new Exception("Refresh must request the clicked list and sequential node index");
                if(i==1){await Until(()=>nodes.Items.Count==1);if(feedback.Contains("Interrupt 已刷新"))throw new Exception("Partial nodes must be visible before operation completion");}
                await stream.WriteAsync(Node(i),token);
            }
            await Until(()=>feedback.Contains("Interrupt 已刷新"));
            if(nodes.Items.Count!=2||((SectionPage.NodeItem)nodes.Items[1]).Address!="0x20000010")throw new Exception("Section refresh must render native results in order");
            DiagnosticPageTests.ClickCell(lists,0);if(nodes.Items.Count!=0)throw new Exception("Unfetched list must not show another list's nodes");
            DiagnosticPageTests.ClickCell(lists,1);if(nodes.Items.Count!=2)throw new Exception("Switching lists must preserve the refreshed cache");
            feedback="";Click("刷新所选链表");await Request(stream,0x39,token);await stream.WriteAsync(Node(0,0,4),token);
            await Until(()=>feedback.Contains("Interrupt 已刷新"));if(nodes.Items.Count!=0)throw new Exception("Refreshing an empty list must clear stale nodes");
            Console.WriteLine("PASS: Section button-to-TCP directory/selected-list refresh, incremental nodes, per-list cache and empty-list refresh.");
        }
        finally{page.Shutdown();host.Close();}
    }
}
