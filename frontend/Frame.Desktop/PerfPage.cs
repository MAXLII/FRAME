using System.Collections.ObjectModel;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Media;
using Frame.Client;

namespace Frame.Desktop;

public sealed class PerfPage : DiagnosticPage
{
    public sealed record Record(int Id,int Kind,string Name,double? Time,double? Max,double? Period,double? Load,double? Peak)
    {public string Type=>Kind switch{1=>"Task",2=>"Interrupt",3=>"Code",_=>"?"};}
    private readonly ObservableCollection<Record> rows=new();
    private readonly TextBox search;
    private readonly DataGrid table;
    private readonly TextBlock info=Label("尚未读取设备信息"),detail=Label("选择记录查看执行时间和负载"),title=Label("未选择记录");
    private readonly TextBlock[] metrics=Enumerable.Range(0,4).Select(_=>Label("—")).ToArray();
    private readonly ProgressBar load=new(){Maximum=100,Height=18,Margin=new Thickness(0,8,0,8)},peak=new(){Maximum=100,Height=18,Foreground=Brushes.MediumPurple,Margin=new Thickness(0,8,0,8)};
    private readonly Button periodic;
    private int filter;
    private bool automatic;
    private long due;
    private long epoch=-1;
    public PerfPage(BackendClient client,Dictionary<string,TextBox> fields,Action<string> feedback):base(client,fields,feedback)
    {
        search=Input("search","",210);search.ToolTip="搜索记录名称";search.TextChanged+=(_,_)=>RefreshFilter();
        periodic=ActionButton("自动刷新 1s",async()=>{automatic=!automatic;periodic!.Content=automatic?"停止刷新":"自动刷新 1s";if(automatic)await RefreshAsync(filter);});
        var tools=Toolbar(Label("搜索"),search,ActionButton("拉取全部",()=>RefreshAsync(0)),ActionButton("Task",()=>RefreshAsync(1)),ActionButton("Interrupt",()=>RefreshAsync(2)),ActionButton("Code",()=>RefreshAsync(3)),periodic,ActionButton("导出 CSV",ExportAsync));
        var secondary=Toolbar(ActionButton("更新字典",async()=>{await Command("perf","dictionary",new(){["filter"]=0});await RefreshAsync(filter);}),ActionButton("Reset Peak",async()=>{await Command("perf","reset");await RefreshAsync(filter);}),info);
        var cards=new System.Windows.Controls.Primitives.UniformGrid{Columns=4};string[] labels={"任务总占用","任务峰值","中断总占用","中断峰值"};for(int i=0;i<4;i++){metrics[i].FontSize=22;cards.Children.Add(Card(labels[i],metrics[i]));}
        table=Grid(("Type","Type",85),("Name","Name",0),("Run Time (us)","Time",115),("Max Time (us)","Max",115),("Load (%)","Load",90),("Peak (%)","Peak",90));table.ItemsSource=rows;
        foreach(var column in table.Columns.OfType<DataGridTextColumn>().Skip(4))((Binding)column.Binding).StringFormat="F3";
        table.SelectionUnit=DataGridSelectionUnit.FullRow;table.SelectionMode=DataGridSelectionMode.Single;
        table.SelectionChanged+=(_,_)=>ShowDetails(table.SelectedItem as Record);
        table.PreviewKeyDown+=(_,e)=>{if(e.Key==System.Windows.Input.Key.C&&(System.Windows.Input.Keyboard.Modifiers&System.Windows.Input.ModifierKeys.Control)!=0&&table.SelectedItem is Record row){Clipboard.SetText(row.Name);e.Handled=true;}};
        var style=new Style(typeof(DataGridRow));foreach(var (kind,color) in new[]{(1,Brushes.Teal),(2,Brushes.DarkOrange),(3,Brushes.ForestGreen)}){var trigger=new DataTrigger{Binding=new Binding(nameof(Record.Kind)),Value=kind};trigger.Setters.Add(new Setter(ForegroundProperty,color));style.Triggers.Add(trigger);}table.RowStyle=style;
        Content=Above(Vertical(tools,secondary,cards),Split(table,Card("选中项详情",Vertical(title,detail,Label("当前占用 / 100%"),load,Label("峰值占用 / 100%"),peak)),740));
        RefreshFilter();
    }
    private void RefreshFilter()=>CollectionViewSource.GetDefaultView(rows).Filter=item=>item is Record r&&(filter==0||r.Kind==filter)&&r.Name.Contains(search.Text.Trim(),StringComparison.OrdinalIgnoreCase);
    public void SetRecords(JsonArray data,int typeFilter=0,bool complete=true)
    {
        int? selected=(table.SelectedItem as Record)?.Id;
        var incoming=data.OfType<JsonObject>().Select(r=>new Record((int)Num(r["record_id"]),(int)Num(r["type"]),r["name"]?.ToString()??"",r["time_us"]==null?null:Num(r["time_us"]),r["max_us"]==null?null:Num(r["max_us"]),r["period_us"]==null?null:Num(r["period_us"]),r["load"]==null?null:Num(r["load"]),r["peak"]==null?null:Num(r["peak"]))).ToArray();
        if(complete)foreach(var old in rows.Where(r=>(typeFilter==0||r.Kind==typeFilter)&&incoming.All(n=>n.Id!=r.Id)).ToArray())rows.Remove(old);
        foreach(var row in incoming){int index=rows.ToList().FindIndex(r=>r.Id==row.Id);if(index<0)rows.Add(row);else rows[index]=row;}
        table.SelectedItem=rows.FirstOrDefault(r=>r.Id==selected);RefreshFilter();
    }
    public override void Apply(JsonNode? data)
    {
        if(data is JsonArray records)SetRecords(records);
        else if(data is JsonObject obj&&obj.ContainsKey("task_load")){string[] keys={"task_load","task_peak","interrupt_load","interrupt_peak"};for(int i=0;i<4;i++)metrics[i].Text=$"{Num(obj[keys[i]]):F2}%";}
    }
    private void ShowDetails(Record? row)
    {
        if(row==null)return;title.Text=row.Name;title.FontSize=19;detail.Text=$"{row.Type} · ID {row.Id}\n运行 {row.Time:G8} us   最大 {row.Max:G8} us\n"+(row.Kind==1?$"周期 {row.Period:G8} us\n":"")+(row.Kind==3?"Code 记录不包含占用率":$"当前 {row.Load:F2}%   峰值 {row.Peak:F2}%");load.Value=row.Load??0;peak.Value=row.Peak??0;load.Visibility=peak.Visibility=row.Kind==3?Visibility.Collapsed:Visibility.Visible;
    }
    public async Task RefreshAsync(int type)
    {
        filter=type;Status("正在刷新 Perf…");var device=await Command("perf","info");info.Text=$"协议 {device?["version"]} · {device?["count"]} 条 · 单位 {device?["unit_us"]} us · {device?["count_per_tick"]} cnt/tick · 窗口 {device?["window_ms"]} ms";
        Apply(await Command("perf","summary"));
        var progress=new Progress<JsonObject>(part=>{if(Closed)return;SetRecords(part["items"]!.AsArray(),type,false);State.Text=$"已更新 {part["received"]}/{part["total"]} 条记录";});
        SetRecords((await Command("perf","samples",new(){["filter"]=type},progress))!.AsArray(),type);due=Environment.TickCount64+1000;Status($"Perf 刷新完成 · {rows.Count} 条缓存记录");
    }
    private async Task ExportAsync()
    {
        if(rows.Count==0)throw new InvalidOperationException("尚无 Perf 记录可导出");
        var path=SaveFile("CSV|*.csv","perf_records.csv");if(path==null)return;
        var data=new JsonArray(rows.Select(r=>(JsonNode)new JsonObject{["record_id"]=r.Id,["type"]=r.Type,["name"]=r.Name,["time_us"]=r.Time,["max_time_us"]=r.Max,["period_us"]=r.Period,["load_percent"]=r.Load,["peak_percent"]=r.Peak}).ToArray());
        await Command("data","save",new(){["records"]=data,["output"]=path});Status("已导出 "+path);
    }
    public override Task TickAsync(JsonObject snapshot)
    {
        long next=(long)Num(snapshot["epoch"]);if(epoch>=0&&next!=epoch){rows.Clear();foreach(var metric in metrics)metric.Text="—";info.Text="尚未读取设备信息";}epoch=next;
        if(!snapshot["connected"]!.GetValue<bool>()){automatic=false;periodic.Content="自动刷新 1s";return Task.CompletedTask;}
        if(automatic&&!Busy&&Environment.TickCount64>=due)_=Run(async()=>{try{await RefreshAsync(filter);}catch{automatic=false;periodic.Content="自动刷新 1s";throw;}});
        return Task.CompletedTask;
    }
}
