using System.Collections.ObjectModel;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Media;
using Frame.Client;

namespace Frame.Desktop;

public sealed class TracePage : DiagnosticPage
{
    public sealed record Record(long Index,double Time,int Line);
    private readonly ObservableCollection<Record> rows=new();
    private readonly DataGrid table;
    private readonly TextBox highlight;
    private readonly TextBlock count=Label("0"),lastTime=Label("—"),lastLine=Label("—");
    private readonly Button toggle;
    private BackendJob? capture;
    private ulong dataset;
    private long dropped;
    private bool stopping;
    public override IEnumerable<BackendJob> ActiveJobs => capture==null?Array.Empty<BackendJob>():new[]{capture};
    public TracePage(BackendClient client,Dictionary<string,TextBox> fields,Action<string> feedback):base(client,fields,feedback)
    {
        highlight=Input("highlight","",200);highlight.ToolTip="匹配行号高亮，保留其他记录；支持十进制和 0x 十六进制";highlight.TextChanged+=(_,_)=>UpdateHighlights();
        toggle=ActionButton("开始上报",ToggleAsync);toggle.Width=220;
        var side=Vertical(Label("行号高亮"),highlight,toggle,State,Card("事件总数",count),Card("最后时间",lastTime),Card("最后行号",lastLine),ActionButton("导出…",ExportAsync));
        table=Grid(("#","Index",95),("Time (ms)","Time",0),("Line","Line",160));table.ItemsSource=rows;
        ((Binding)((DataGridTextColumn)table.Columns[1]).Binding).StringFormat="F3";
        Content=Split(side,table,255);
    }
    private async Task ToggleAsync()
    {
        if(capture!=null){stopping=true;toggle.Content="停止中";toggle.IsEnabled=false;try{await Command("trace","stop");}catch{Client.Cancel(capture.Id);throw;}return;}
        if(dataset!=0)await Command("data","release",new(){["dataset"]=dataset});
        rows.Clear();dropped=0;dataset=0;UpdateMetrics();
        capture=Client.Submit(new(){["group"]="trace",["action"]="capture",["duration"]=0});dataset=capture.Id;toggle.Content="停止上报";Status("正在开启上报…");
    }
    public void SetRecords(JsonArray data,long firstIndex=0,bool append=false)
    {
        if(!append)rows.Clear();
        foreach(var row in data.OfType<JsonObject>())rows.Add(new Record(++firstIndex,Num(row["time"])*1000,(int)Num(row["line"])));
        UpdateMetrics();if(rows.Count>0)table.ScrollIntoView(rows[^1]);
    }
    public override void Apply(JsonNode? data){if(data?["records"] is JsonArray records)SetRecords(records);}
    private void UpdateMetrics(){count.Text=(dropped+rows.Count).ToString("N0");lastTime.Text=rows.Count>0?$"{rows[^1].Time:F3} ms":"—";lastLine.Text=rows.Count>0?rows[^1].Line.ToString():"—";}
    private void UpdateHighlights()
    {
        if(table==null)return;var style=new Style(typeof(DataGridRow));try{
            string text=highlight.Text.Trim();int number=Convert.ToInt32(text,text.StartsWith("0x",StringComparison.OrdinalIgnoreCase)?16:10);
            var trigger=new DataTrigger{Binding=new Binding(nameof(Record.Line)),Value=number};trigger.Setters.Add(new Setter(BackgroundProperty,Brushes.LemonChiffon));trigger.Setters.Add(new Setter(ForegroundProperty,Brushes.DarkOrange));style.Triggers.Add(trigger);
        }catch(FormatException){}catch(OverflowException){}catch(ArgumentException){}
        table.RowStyle=style;
    }
    private async Task ExportAsync()
    {
        if(dataset==0)throw new InvalidOperationException("尚无采集数据");var path=SaveFile("FRAME JSON|*.json|CSV|*.csv","trace-records.json");if(path==null)return;
        await Command("data","export",new(){["dataset"]=dataset,["output"]=path});Status("已导出 "+path);
    }
    public override async Task TickAsync(JsonObject snapshot)
    {
        var set=snapshot["datasets"]!.AsArray().FirstOrDefault(d=>d!["id"]!.GetValue<ulong>()==dataset);
        if(set!=null){
            long lost=(long)Num(set["dropped"]);int total=(int)Num(set["count"]);
            if(lost!=dropped||rows.Count>total){rows.Clear();dropped=lost;}
            if(rows.Count<total){var part=await Command("data","read",new(){["dataset"]=dataset,["offset"]=rows.Count,["limit"]=10000});SetRecords(part!["records"]!.AsArray(),dropped+rows.Count,true);}
            if(capture!=null&&!stopping)State.Text=$"上报中{(lost>0?$" · 历史淘汰 {lost} 条":"")}";
        }
        if(capture?.Completion.IsCompleted==true){var result=await capture.Completion;capture=null;stopping=false;toggle.IsEnabled=true;toggle.Content="开始上报";Status(result["ok"]?.GetValue<bool>()==true?"已停止":$"上报结束：{result["error"]}");}
    }
}
