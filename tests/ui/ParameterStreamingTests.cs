using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json.Nodes;
using Frame.Client;
using Frame.Desktop;

internal static class ParameterStreamingTests
{
    private static byte[] Packet(byte word,byte[] payload,bool ack=false)
    {
        var data=new List<byte>{0xe8,1,2,0,1,0,1,word,(byte)(ack?1:0),(byte)payload.Length,(byte)(payload.Length>>8)};data.AddRange(payload);
        ushort crc=0xffff;foreach(byte value in data){crc^=(ushort)(value<<8);for(int i=0;i<8;i++)crc=(ushort)((crc&0x8000)!=0?(crc<<1)^0x1021:crc<<1);}
        data.Add((byte)crc);data.Add((byte)(crc>>8));data.Add(13);data.Add(10);return data.ToArray();
    }
    private static byte[] Batch(int total,int index,string name)
    {
        var data=new List<byte>();data.AddRange(BitConverter.GetBytes(total));data.AddRange(BitConverter.GetBytes(index));data.AddRange(new byte[]{1,0,(byte)name.Length,5});
        data.AddRange(BitConverter.GetBytes(42));data.AddRange(BitConverter.GetBytes(100));data.AddRange(BitConverter.GetBytes(0));data.Add(0);data.AddRange(Encoding.ASCII.GetBytes(name));
        return Packet(0x3f,data.ToArray());
    }
    public static async Task Run()
    {
        foreach(string mode in new[]{"complete","timeout","cancel"})
        {
            using var deadline=new CancellationTokenSource(TimeSpan.FromSeconds(5));
            using var cancelled=new CancellationTokenSource();
            using var listener=new TcpListener(IPAddress.Loopback,0);listener.Start();
            await using var client=new BackendClient();
            var accept=listener.AcceptTcpClientAsync(deadline.Token);
            await client.ExecuteAsync(new(){["group"]="connect",["transport"]="tcp",["host"]="127.0.0.1",["tcp_port"]=((IPEndPoint)listener.LocalEndpoint).Port});
            using var peer=await accept;var socket=peer.GetStream();
            string feedback="";
            var panel=new ParameterPanel(q=>client.ExecuteAsync(q),message=>feedback=message,(q,p)=>{q["response_timeout"]=mode=="timeout"?200:1500;return client.ExecuteAsync(q,cancelled.Token,p);});
            var reading=panel.RunAsync("list");
            await socket.ReadExactlyAsync(new byte[15],deadline.Token);
            await socket.WriteAsync(Packet(1,BitConverter.GetBytes(3),true),deadline.Token);
            await socket.WriteAsync(Batch(3,0,"FIRST"),deadline.Token);
            while(panel.Table.Items.Count<1){deadline.Token.ThrowIfCancellationRequested();await Task.Delay(10,deadline.Token);}
            if(reading.IsCompleted||panel.Table.Items.Count!=1)throw new Exception("First parameter must be visible before list completion");
            var first=panel.Table.Items[0];
            if(mode=="complete")
            {
                await socket.WriteAsync(Batch(3,2,"THIRD"),deadline.Token);await Task.Delay(60,deadline.Token);
                if(panel.Table.Items.Count!=1)throw new Exception("Out-of-order packet must not reorder displayed parameters");
                await socket.WriteAsync(Batch(3,1,"SECOND"),deadline.Token);
            }
            else if(mode=="cancel")cancelled.Cancel();
            await reading.WaitAsync(deadline.Token);
            if(mode=="complete")
            {
                if(!panel.Table.Items.Cast<ParameterRow>().Select(r=>r.Name).SequenceEqual(new[]{"FIRST","SECOND","THIRD"})||!ReferenceEquals(first,panel.Table.Items[0]))throw new Exception("Completion must preserve streamed rows and directory order");
            }
            else if(panel.Table.Items.Count!=1||!feedback.Contains("未完成"))throw new Exception("Interrupted list must preserve partial rows with an incomplete message");
        }
        Console.WriteLine("PASS: parameter rows visible before completion; ordered batches; no final rebuild; timeout/cancel retain partial rows.");
    }
}
