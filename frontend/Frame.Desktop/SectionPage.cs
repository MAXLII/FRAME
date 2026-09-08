using System.Collections.ObjectModel;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using Frame.Client;

namespace Frame.Desktop;

public sealed class SectionPage : DiagnosticPage
{
    public sealed record DirectoryItem(int Id,string Name,int Count,string Cache);
    public sealed record NodeItem(int Index,string Name,string Address);
    private readonly ObservableCollection<DirectoryItem> directory=new();
    private readonly Dictionary<int,JsonArray> cache=new();
    private readonly Dictionary<int,JsonArray> partial=new();
    private readonly DataGrid lists,nodes;
    private readonly TextBox map;
    private readonly TextBlock total=Label("尚未读取"),selection=Label("请选择链表");
    private long epoch=-1;
    public SectionPage(BackendClient client,Dictionary<string,TextBox> fields,Action<string> feedback):base(client,fields,feedback)
    {
        map=Input("map","",360);map.ToolTip="GNU MAP 文件，注册对象地址由后端解析";
        var tools=Toolbar(Label("MAP"),map,ActionButton("选择 MAP",async()=>{var path=ChooseFile("GNU MAP|*.map|所有文件|*.*");if(path!=null){map.Text=path;await ResolveCachedAsync();}}),ActionButton("加载 MAP",ResolveCachedAsync),ActionButton("刷新链表列表",RefreshDirectoryAsync));
        lists=Grid(("链表","Name",0),("节点","Count",55),("状态","Cache",72));lists.ItemsSource=directory;
        lists.SelectionUnit=DataGridSelectionUnit.FullRow;lists.SelectionMode=DataGridSelectionMode.Single;
        lists.SelectionChanged+=(_,_)=>RenderSelected();
        nodes=Grid(("顺序","Index",65),("对象名称","Name",0),("地址","Address",140));
        var sidebar=Above(Vertical(total,ActionButton("刷新所选链表",RefreshSelectedAsync)),lists);
        Content=Above(tools,Split(sidebar,Above(selection,nodes),300));
        var menu=new ContextMenu();var copy=new MenuItem{Header="复制单元格"};copy.Click+=(_,_)=>System.Windows.Input.ApplicationCommands.Copy.Execute(null,nodes);menu.Items.Add(copy);nodes.ContextMenu=menu;
    }
    public void SetDirectory(JsonArray data)
    {
        int? selected=(lists.SelectedItem as DirectoryItem)?.Id;directory.Clear();
        foreach(var row in data.OfType<JsonObject>().Where(r=>r["list_id"]!=null)){int id=(int)Num(row["list_id"]);directory.Add(new(id,row["name"]?.ToString()??"",(int)Num(row["node_count"]),cache.ContainsKey(id)?"已缓存":"未读取"));}
        foreach(var id in cache.Keys.Where(id=>directory.All(d=>d.Id!=id)).ToArray())cache.Remove(id);
        lists.SelectedItem=directory.FirstOrDefault(d=>d.Id==selected)??directory.FirstOrDefault();UpdateCount();
    }
    public void SetNodes(int id,JsonArray records)
    {
        partial.Remove(id);cache[id]=(JsonArray)records.DeepClone();int index=directory.ToList().FindIndex(d=>d.Id==id);if(index>=0){bool selected=(lists.SelectedItem as DirectoryItem)?.Id==id;directory[index]=directory[index] with{Cache="已缓存",Count=records.Count};if(selected)lists.SelectedIndex=index;}UpdateCount();RenderSelected();
    }
    public override void Apply(JsonNode? data){if(data is JsonArray rows){if(rows.FirstOrDefault()?["node_count"]!=null)SetDirectory(rows);else if(rows.FirstOrDefault()?["list_id"]!=null)SetNodes((int)Num(rows[0]!["list_id"]),rows);}}
    private void UpdateCount()=>total.Text=$"{directory.Count} 条链表 · {cache.Count} 条已缓存";
    private void RenderSelected()
    {
        var item=lists.SelectedItem as DirectoryItem;selection.Text=item==null?"请选择链表":$"{item.Name} · {item.Count} 个节点";
        JsonArray? data=null;if(item!=null){if(!partial.TryGetValue(item.Id,out data))cache.TryGetValue(item.Id,out data);}
        nodes.ItemsSource=data?.OfType<JsonObject>().Select(r=>new NodeItem((int)Num(r["index"]),r["name"]?.ToString() is {Length:>0} name?name:"未解析",Hex(r["address"]))).ToArray()??Array.Empty<NodeItem>();
    }
    private async Task RefreshDirectoryAsync(){SetDirectory((await Command("section","list"))!.AsArray());Status("链表目录已更新");}
    private async Task RefreshSelectedAsync()
    {
        if(lists.SelectedItem is not DirectoryItem item)throw new InvalidOperationException("请先刷新链表列表并选择链表");var args=new JsonObject{["id"]=item.Id};if(map.Text.Trim().Length>0)args["map"]=map.Text.Trim();
        partial[item.Id]=new JsonArray();
        var progress=new Progress<JsonObject>(part=>{
            if(Closed||!partial.TryGetValue(item.Id,out var buffer))return;foreach(var row in part["items"]!.AsArray())buffer.Add(row!.DeepClone());
            int index=directory.ToList().FindIndex(d=>d.Id==item.Id);if(index>=0){bool selected=(lists.SelectedItem as DirectoryItem)?.Id==item.Id;directory[index]=directory[index] with{Cache=$"{part["received"]}/{part["total"]}"};if(selected)lists.SelectedIndex=index;}RenderSelected();
        });
        try{SetNodes(item.Id,(await Command("section","nodes",args,progress))!.AsArray());Status($"{item.Name} 已刷新");}
        catch{Status($"{item.Name} 未完成 · 保留 {partial[item.Id].Count} 个已接收节点");throw;}
    }
    private async Task ResolveCachedAsync()
    {
        if(string.IsNullOrWhiteSpace(map.Text))throw new ArgumentException("请选择 MAP 文件");
        foreach(var (id,data) in cache.ToArray())SetNodes(id,(await Command("section","resolve",new(){["map"]=map.Text.Trim(),["records"]=data.DeepClone()}))!.AsArray());Status("MAP 名称解析已更新");
    }
    public override Task TickAsync(JsonObject snapshot)
    {
        long next=(long)Num(snapshot["epoch"]);if(epoch>=0&&next!=epoch){cache.Clear();partial.Clear();directory.Clear();nodes.ItemsSource=null;UpdateCount();}epoch=next;return Task.CompletedTask;
    }
}
