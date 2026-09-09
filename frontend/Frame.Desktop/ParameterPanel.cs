using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Globalization;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Input;
using System.Windows.Media;

namespace Frame.Desktop;

// Presentation and pending edits only; decoding, validation and writes use Frame.Client.
public sealed class ParameterRow : INotifyPropertyChanged, IEditableObject
{
    private readonly JsonObject source = new();
    private string data="", minimum="", maximum="";
    private (string Data,string Minimum,string Maximum,bool Dirty,bool Invalid)? editBackup;
    public string Name => source["name"]!.GetValue<string>();
    public int Type => source["type"]!.GetValue<int>();
    public string TypeName => Type is >=0 and <=7 ? new[]{"INT8","UINT8","INT16","UINT16","INT32","UINT32","FP32","CMD"}[Type] : Type.ToString();
    public bool IsCommand => Type==7;
    public bool IsReadOnly => !IsCommand && source["min_raw"]!=null && source["min_raw"]!.ToJsonString()==source["max_raw"]?.ToJsonString();
    public bool Reporting => ((source["flags"]?.GetValue<int>()??0)&1)!=0 && !IsCommand;
    public bool Dirty { get; private set; }
    public bool Busy { get; private set; }
    public bool Invalid { get; private set; }
    public string Data { get=>data; set {data=value;Edited();} }
    public string Minimum { get=>minimum; set {minimum=value;Edited();} }
    public string Maximum { get=>maximum; set {maximum=value;Edited();} }
    public string Hex
    {
        get
        {
            if(Type is <0 or >5)return "/";
            uint raw=source["raw"]?.GetValue<uint>()??0;
            int digits=Type<2?2:Type<4?4:8;
            uint mask=digits==2?0xffu:digits==4?0xffffu:uint.MaxValue;
            return "0x"+(raw&mask).ToString("X"+digits,CultureInfo.InvariantCulture);
        }
    }
    public event PropertyChangedEventHandler? PropertyChanged;
    public ParameterRow(JsonObject row) => Apply(row);
    public void BeginEdit()=>editBackup??=(data,minimum,maximum,Dirty,Invalid);
    public void EndEdit()=>editBackup=null;
    public void CancelEdit()
    {
        if(editBackup is {} saved){data=saved.Data;minimum=saved.Minimum;maximum=saved.Maximum;Dirty=saved.Dirty;Invalid=saved.Invalid;editBackup=null;Changed();}
    }
    private void Changed()=>PropertyChanged?.Invoke(this,new PropertyChangedEventArgs(""));
    private void Edited(){Dirty=true;Invalid=false;Changed();}
    public void MarkBusy(bool value){Busy=value;if(value)Invalid=false;Changed();}
    public void MarkInvalid(){Invalid=true;Changed();}
    public void SetReporting(bool enabled){source["flags"]=((source["flags"]?.GetValue<int>()??0)&~1)|(enabled?1:0);Changed();}
    public void Apply(JsonObject row)
    {
        foreach(var field in row)source[field.Key]=field.Value?.DeepClone();
        data=IsCommand?"/":Format(source["value"],Type);
        minimum=IsCommand?"/":Format(source["min"],Type);
        maximum=IsCommand?"/":Format(source["max"],Type);
        Dirty=false;Invalid=false;Changed();
    }
    public void ApplyReported(JsonObject row)
    {
        if(Dirty||Busy)return;
        Apply(row);
    }
    public static string Format(JsonNode? value,int type)
    {
        if(value==null)return "/";
        if(type!=6)return value.ToString();
        double number=value.GetValue<double>();
        if(!double.IsFinite(number))return number.ToString(CultureInfo.InvariantCulture);
        if(number!=0 && (Math.Abs(number)<0.000001 || Math.Abs(number)>=1e9))return number.ToString("G9",CultureInfo.InvariantCulture);
        return number.ToString("0.0######",CultureInfo.InvariantCulture);
    }
}

public sealed class ParameterPanel : UserControl
{
    private readonly Func<JsonObject,Task<JsonObject>> execute;
    private readonly Action<string> feedback;
    private readonly Func<JsonObject,IProgress<JsonObject>,Task<JsonObject>>? executeProgress;
    private readonly ObservableCollection<ParameterRow> rows=new();
    private readonly ICollectionView view;
    private readonly TextBox search=new(){Width=240,ToolTip="按字符顺序模糊匹配，忽略大小写和空格"};
    private readonly TextBlock count=new(){VerticalAlignment=VerticalAlignment.Center,Margin=new Thickness(6,0,16,8)};
    private readonly Button read=new(){Content="读取"},write=new(){Content="写入"};
    private bool busy;
    private bool listing;
    private int listGeneration,expectedCount;
    public event Action<IReadOnlyList<string>>? WaveSelectionChanged;
    public event Action<string>? WaveParameterEnabled;
    public DataGrid Table { get; }=new(){AutoGenerateColumns=false,IsReadOnly=false,SelectionMode=DataGridSelectionMode.Single,SelectionUnit=DataGridSelectionUnit.FullRow,CanUserSortColumns=false,CanUserReorderColumns=false};
    public ParameterPanel(Func<JsonObject,Task<JsonObject>> execute,Action<string> feedback,Func<JsonObject,IProgress<JsonObject>,Task<JsonObject>>? executeProgress=null)
    {
        this.execute=execute;this.feedback=feedback;this.executeProgress=executeProgress;
        var root=new DockPanel();Content=root;
        var toolbar=new WrapPanel();DockPanel.SetDock(toolbar,Dock.Top);root.Children.Add(toolbar);
        Button Add(string text,Func<Task> action){var button=new Button{Content=text};button.Click+=async(_,_)=>await action();toolbar.Children.Add(button);return button;}
        Add("读取参数列表",()=>RunAsync("list"));toolbar.Children.Add(count);
        toolbar.Children.Add(new TextBlock{Text="参数搜索",VerticalAlignment=VerticalAlignment.Center,Margin=new Thickness(0,0,8,8)});toolbar.Children.Add(search);
        toolbar.Children.Add(read);toolbar.Children.Add(write);
        read.Click+=async(_,_)=>await RunAsync("read");write.Click+=async(_,_)=>await RunAsync("write");
        view=CollectionViewSource.GetDefaultView(rows);view.Filter=item=>Matches(((ParameterRow)item).Name,search.Text);
        Table.ItemsSource=view;root.Children.Add(Table);
        foreach(var column in new[]{("参数名称","Name",260d,true),("类型","TypeName",90d,true),("数据","Data",140d,false),("HEX","Hex",120d,true),("最小值","Minimum",130d,false),("最大值","Maximum",130d,false)})
            Table.Columns.Add(new DataGridTextColumn{Header=column.Item1,Binding=new Binding(column.Item2){Mode=column.Item4?BindingMode.OneWay:BindingMode.TwoWay,UpdateSourceTrigger=UpdateSourceTrigger.LostFocus},Width=new DataGridLength(column.Item3),IsReadOnly=column.Item4});
        var style=new Style(typeof(DataGridRow));
        void Trigger(string property,DependencyProperty target,object color){var trigger=new DataTrigger{Binding=new Binding(property),Value=true};trigger.Setters.Add(new Setter(target,color));style.Triggers.Add(trigger);}
        Trigger(nameof(ParameterRow.Reporting),DataGridRow.BackgroundProperty,Brushes.Honeydew);
        Trigger(nameof(ParameterRow.Dirty),DataGridRow.ForegroundProperty,Brushes.Firebrick);
        Trigger(nameof(ParameterRow.Invalid),DataGridRow.BackgroundProperty,Brushes.LemonChiffon);
        Trigger(nameof(ParameterRow.Busy),DataGridRow.BackgroundProperty,Brushes.MistyRose);
        Table.RowStyle=style;
        var cellStyle=new Style(typeof(DataGridCell));
        foreach(var state in new[]{(nameof(ParameterRow.Reporting),Brushes.Honeydew),(nameof(ParameterRow.Invalid),Brushes.LemonChiffon),(nameof(ParameterRow.Busy),Brushes.MistyRose)})
        {
            var trigger=new DataTrigger{Binding=new Binding(state.Item1),Value=true};
            trigger.Setters.Add(new Setter(DataGridCell.BackgroundProperty,state.Item2));
            trigger.Setters.Add(new Setter(DataGridCell.ForegroundProperty,new Binding("Foreground"){RelativeSource=new RelativeSource(RelativeSourceMode.FindAncestor,typeof(DataGridRow),1)}));
            cellStyle.Triggers.Add(trigger);
        }
        Table.CellStyle=cellStyle;
        Table.ToolTip="双击参数名称加入或移出波形；绿色表示已加入。双击数据或上下限编辑。";
        Table.SelectionChanged+=(_,_)=>UpdateActions();
        Table.BeginningEdit+=(_,e)=>{if(busy||e.Row.Item is not ParameterRow row||row.IsCommand||(e.Column.DisplayIndex==2&&row.IsReadOnly))e.Cancel=true;};
        Table.MouseDoubleClick+=async(_,e)=>
        {
            DependencyObject? element=e.OriginalSource as DependencyObject;
            while(element!=null && element is not DataGridCell)element=element is FrameworkContentElement content?content.Parent:VisualTreeHelper.GetParent(element);
            if(element is DataGridCell cell && cell.Column.DisplayIndex==0 && cell.DataContext is ParameterRow row){Table.SelectedItem=row;await RunAsync("report");e.Handled=true;}
        };
        Table.PreviewKeyDown+=(_,e)=>{if(e.Key==Key.C&&Keyboard.Modifiers==ModifierKeys.Control&&Table.SelectedItem is ParameterRow row){try{Clipboard.SetText(row.Name);feedback("已复制参数名称: "+row.Name);}catch(Exception error){feedback(error.Message);}e.Handled=true;}};
        search.TextChanged+=(_,_)=>{CommitEdit();view.Refresh();UpdateActions();};
        UpdateActions();
    }
    public static bool Matches(string name,string query)
    {
        int index=0;
        foreach(char c in query.Where(c=>!char.IsWhiteSpace(c))){index=name.IndexOf(c.ToString(),index,StringComparison.OrdinalIgnoreCase);if(index<0)return false;index++;}
        return true;
    }
    private void CommitEdit(){Table.CommitEdit(DataGridEditingUnit.Cell,true);Table.CommitEdit(DataGridEditingUnit.Row,true);}
    private void UpdateActions()
    {
        var row=Table.SelectedItem as ParameterRow;
        read.IsEnabled=!busy&&row!=null;write.IsEnabled=!busy&&row!=null&&!row.IsReadOnly;
        write.Content=row?.IsReadOnly==true?"只读":row?.IsCommand==true?"执行":"写入";
        count.Text=listing?$"{rows.Count}/{(expectedCount<0?"?":expectedCount.ToString())}":$"{view.Cast<object>().Count()}/{rows.Count}";
    }
    public void Apply(JsonNode data)
    {
        string? selected=(Table.SelectedItem as ParameterRow)?.Name;
        if(data is JsonArray list)
        {
            rows.Clear();foreach(var row in list.OfType<JsonObject>())if(row["name"]!=null&&row["type"]!=null)rows.Add(new(row));
        }
        else if(data is JsonObject item&&item["name"]!=null)
        {
            var row=rows.FirstOrDefault(r=>r.Name==item["name"]!.GetValue<string>());
            if(row!=null)row.Apply(item);else if(item["type"]!=null)rows.Add(new(item));
        }
        view.Refresh();Table.SelectedItem=rows.FirstOrDefault(r=>r.Name==selected);UpdateActions();NotifyWaveSelection();
    }
    public void ApplyReported(JsonArray records)
    {
        if(Table.IsKeyboardFocusWithin && Keyboard.FocusedElement is TextBox)return;
        foreach(var item in records.OfType<JsonObject>().Where(r=>r["name"]!=null).GroupBy(r=>r["name"]!.GetValue<string>()).Select(g=>g.Last()))rows.FirstOrDefault(r=>r.Name==item["name"]!.GetValue<string>())?.ApplyReported(item);
    }
    public async Task RunAsync(string action)
    {
        if(busy)return;CommitEdit();var row=Table.SelectedItem as ParameterRow;
        if(action!="list"&&row==null)return;
        if(action=="write"&&row!.IsReadOnly||action=="report"&&row!.IsCommand)return;
        busy=true;row?.MarkBusy(true);UpdateActions();
        int generation=++listGeneration;
        if(action=="list"){listing=true;expectedCount=-1;rows.Clear();UpdateActions();feedback("正在读取参数列表…");}
        try
        {
            JsonObject request=new(){["group"]="param",["action"]=action};
            if(action!="list")request["name"]=row!.Name;
            if(action=="write")
            {
                request["value"]=row!.IsCommand?"0":row.Data;
                if(!row.IsCommand){request["min"]=row.Minimum;request["max"]=row.Maximum;}
            }
            bool enabled=row?.Reporting!=true;
            if(action=="report")request["enable"]=enabled;
            var result=action=="list"&&executeProgress!=null
                ?await executeProgress(request,new Progress<JsonObject>(update=>{if(listing&&generation==listGeneration)ApplyListProgress(update);}))
                :await execute(request);
            if(!result["ok"]!.GetValue<bool>())throw new InvalidOperationException(result["error"]?.ToString()??"操作失败");
            if(action=="report"){row!.SetReporting(enabled);NotifyWaveSelection();if(enabled)WaveParameterEnabled?.Invoke(row.Name);}
            else if(action=="list"&&result["data"] is JsonArray completed&&rows.Select(r=>r.Name).SequenceEqual(completed.Select(r=>r!["name"]!.ToString())))NotifyWaveSelection();
            else if(result["data"]!=null)Apply(result["data"]!);
            feedback(action=="list"?$"已读取 {rows.Count} 个参数":action=="report"?$"{row!.Name}：{(enabled?"已加入参数波形":"已移出参数波形")}":$"{row!.Name}：{(action=="write"&&row.IsCommand?"执行":action)} 完成");
            if(action=="write"&&!row!.IsCommand)feedback($"{row.Name}：写入成功，"+(result["data"]?["verification"]?.ToString()=="directory_readback"?"ACK 未收到，已通过回读确认":"已通过 ACK 确认"));
        }
        catch(Exception error){row?.MarkInvalid();feedback(action=="list"?$"参数列表未完成，已收到 {rows.Count}/{(expectedCount<0?"?":expectedCount.ToString())}：{error.Message}":error.Message);}
        finally{listing=false;busy=false;row?.MarkBusy(false);UpdateActions();}
    }
    private void ApplyListProgress(JsonObject update)
    {
        expectedCount=update["total"]!.GetValue<int>();
        var items=update["items"]!.AsArray();int received=update["received"]!.GetValue<int>();
        if(received==rows.Count+items.Count)foreach(var item in items.OfType<JsonObject>())rows.Add(new ParameterRow(item));
        UpdateActions();feedback($"正在读取参数列表：{rows.Count}/{expectedCount}");
    }
    private void NotifyWaveSelection()=>WaveSelectionChanged?.Invoke(rows.Where(r=>r.Reporting).Select(r=>r.Name).ToArray());
    public void RefreshWaveSelection(){if(rows.Count>0)NotifyWaveSelection();}
}
