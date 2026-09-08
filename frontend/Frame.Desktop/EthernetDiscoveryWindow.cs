using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;

namespace Frame.Desktop;

public sealed record EthernetDevice(string Name,string Ip,int Port,string Mac,string Firmware,string Protocol,string Adapter)
{
    public static EthernetDevice FromJson(JsonNode data)=>new(data["name"]!.ToString(),data["ip"]!.ToString(),data["tcp_port"]!.GetValue<int>(),data["mac"]!.ToString(),data["fw_version"]!.ToString(),data["protocol_version"]!.ToString(),data["interface"]?["name"]?.ToString()??"");
}

public sealed class EthernetDiscoveryWindow : Window
{
    private readonly Func<CancellationToken,Task<JsonObject>> discover;
    private CancellationTokenSource? scan;
    private readonly DataGrid devices=new(){AutoGenerateColumns=false,IsReadOnly=true,SelectionMode=DataGridSelectionMode.Single,CanUserAddRows=false};
    private readonly TextBlock status=new(){Text="准备搜索…",Margin=new Thickness(0,8,0,8),TextWrapping=TextWrapping.Wrap};
    private readonly Button search=new(){Content="重新搜索"};
    private readonly Button use=new(){Content="连接选中设备",IsEnabled=false};
    public EthernetDevice? SelectedDevice { get; private set; }
    public EthernetDiscoveryWindow(Func<CancellationToken,Task<JsonObject>> discover)
    {
        this.discover=discover;Title="搜索以太网设备";Width=980;Height=420;MinWidth=720;MinHeight=320;WindowStartupLocation=WindowStartupLocation.CenterOwner;
        var layout=new DockPanel{Margin=new Thickness(16)};Content=layout;
        var buttons=new StackPanel{Orientation=Orientation.Horizontal};DockPanel.SetDock(buttons,Dock.Bottom);layout.Children.Add(buttons);
        var cancel=new Button{Content="取消搜索"};cancel.Click+=(_,_)=>scan?.Cancel();
        var close=new Button{Content="关闭"};close.Click+=(_,_)=>Close();
        buttons.Children.Add(search);buttons.Children.Add(cancel);buttons.Children.Add(use);buttons.Children.Add(close);
        DockPanel.SetDock(status,Dock.Top);layout.Children.Add(status);
        foreach(var (title,path) in new[]{("设备名称","Name"),("IP 地址","Ip"),("TCP 端口","Port"),("MAC","Mac"),("固件版本","Firmware"),("协议版本","Protocol"),("网卡","Adapter")})
            devices.Columns.Add(new DataGridTextColumn{Header=title,Binding=new Binding(path),Width=DataGridLength.SizeToCells,MinWidth=75});
        layout.Children.Add(devices);
        devices.SelectionChanged+=(_,_)=>use.IsEnabled=devices.SelectedItem is EthernetDevice;
        use.Click+=(_,_)=>Choose();devices.MouseDoubleClick+=(_,e)=>{if(e.OriginalSource is DependencyObject source&&ItemsControl.ContainerFromElement(devices,source) is DataGridRow row&&row.Item is EthernetDevice){devices.SelectedItem=row.Item;Choose();}};
        search.Click+=async (_,_)=>await SearchAsync();Loaded+=async (_,_)=>await SearchAsync();Closed+=(_,_)=>scan?.Cancel();
    }
    private void Choose(){if(devices.SelectedItem is EthernetDevice device){SelectedDevice=device;DialogResult=true;}}
    private async Task SearchAsync()
    {
        if(scan!=null)return;
        using var cancellation=new CancellationTokenSource();scan=cancellation;search.IsEnabled=false;use.IsEnabled=false;devices.ItemsSource=null;
        status.Text="正在搜索各 IPv4 网卡上的 FRAME 设备…";
        try{
            var result=await discover(cancellation.Token);
            if(cancellation.IsCancellationRequested){status.Text="搜索已取消";return;}
            if(result["ok"]?.GetValue<bool>()!=true)throw new InvalidOperationException(result["error"]?.ToString()??"搜索失败");
            var data=result["data"]!;var found=data["devices"]!.AsArray().Select(d=>EthernetDevice.FromJson(d!)).ToArray();devices.ItemsSource=found;
            if(found.Length>0)devices.SelectedIndex=0;
            int count=data["interfaces"]!.AsArray().Count;
            status.Text=found.Length>0?$"发现 {found.Length} 台设备（搜索了 {count} 个 IPv4 接口）。双击设备自动连接；已有连接会先断开。":$"未发现设备（搜索了 {count} 个 IPv4 接口）。请确认设备已连接网线并支持 FRAME 发现协议，可重新搜索或关闭后手动输入 IP。";
            var errors=data["send_errors"]?.AsArray();if(errors?.Count>0)status.Text+="\n部分接口搜索失败："+string.Join("；",errors.Select(e=>e?.ToString()));
        }catch(OperationCanceledException){status.Text="搜索已取消";}
        catch(Exception error){status.Text="搜索失败："+error.Message;}
        finally{scan=null;search.IsEnabled=true;}
    }
}
