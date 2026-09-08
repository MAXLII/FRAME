using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Globalization;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Input;
using System.Windows.Media;
using Frame.Client;

namespace Frame.Desktop;

public sealed class JlinkPage : DiagnosticPage
{
    public sealed class Variable : INotifyPropertyChanged, IEditableObject
    {
        private string? draft;
        public JsonObject Data {get;private set;}
        public int Depth {get;}
        public Variable? Parent {get;}
        public List<Variable> Children {get;}=new();
        public bool Expanded {get;set;}
        public bool Loaded {get;set;}
        public ulong? ExpandedAddress {get;set;}
        public string? ExpandedType {get;set;}
        public string Name=>Data["name"]?.ToString()??"?";
        public string Expression=>Depth==0?Name:Name[(Math.Max(Name.LastIndexOf('.'),Name.LastIndexOf('>'))+1)..];
        public string Value=>Data["kind"]?.ToString()=="pointer"&&Data["raw"]!=null?Hex(Data["raw"]):Data["value"]==null?"—":Num(Data["encoding"])==4?Num(Data["value"]).ToString(Num(Data["size"])==8?"G15":"G7",CultureInfo.InvariantCulture):Data["value"]!.ToString();
        public string EditValue {get=>draft??Value;set=>draft=value;}
        public void BeginEdit()=>draft=null;
        public void CancelEdit(){draft=null;Changed();}
        public void EndEdit(){draft=null;Changed();}
        public string Type=>Data["type_name"]?.ToString() is {Length:>0} type?type:Data["kind"]?.ToString()??"";
        public string Address=>Hex(Data["address"]);
        public string Raw=>Data["hex"]?.ToString()??"";
        public string Status {get;private set;}="未读取";
        public bool Expandable=>Data["kind"]?.ToString() is "struct" or "union" or "array" or "pointer";
        public string Arrow=>Expandable?(Expanded?"▾":"▸"):"";
        public Thickness Indent=>new(Depth*16,0,0,0);
        public event PropertyChangedEventHandler? PropertyChanged;
        public Variable(JsonObject data,int depth=0,Variable? parent=null){Data=(JsonObject)data.DeepClone();Depth=depth;Parent=parent;}
        public void Update(JsonObject data)
        {
            draft=null;Data=(JsonObject)data.DeepClone();
            string type=Data["resolved_type"]?.ToString()??"",symbol=Data["resolved_symbol"]?.ToString()??"";
            Status=type.Length>0?"已解析："+type+(symbol.Length>0?"\n"+symbol:""):symbol.Length>0?"已解析 → "+symbol:"已读取";Changed();
        }
        public void Error(string message){draft=null;Status=message;Changed();}
        public void Changed()=>PropertyChanged?.Invoke(this,new PropertyChangedEventArgs(null));
    }
    private readonly List<Variable> roots=new();
    private readonly ObservableCollection<Variable> visible=new();
    private readonly DataGrid table;
    private readonly TextBox device,elf,map,speed,search,history;
    private readonly ComboBox deviceCombo,transport;
    private readonly TextBlock count=Label("0 个变量");
    private bool rebuilding;
    private bool writeRequested;
    public JlinkPage(BackendClient client,Dictionary<string,TextBox> fields,Action<string> feedback):base(client,fields,feedback)
    {
        device=Input("device","GD32E507ZE",220);history=Input("device_history","GD32E507ZE;Cortex-M4",220);
        deviceCombo=new ComboBox{IsEditable=true,MinHeight=32,Margin=new Thickness(0,3,8,10)};
        deviceCombo.SetBinding(ComboBox.TextProperty,new Binding(nameof(TextBox.Text)){Source=device,Mode=BindingMode.TwoWay,UpdateSourceTrigger=UpdateSourceTrigger.PropertyChanged});
        deviceCombo.DropDownOpened+=(_,_)=>deviceCombo.ItemsSource=history.Text.Split(';',StringSplitOptions.RemoveEmptyEntries).Distinct().ToArray();
        transport=new ComboBox{ItemsSource=new[]{"SWD","JTAG"},SelectedIndex=0,MinHeight=32,Margin=new Thickness(0,3,8,10)};
        var interfaceField=Input("interface","SWD");transport.SetBinding(ComboBox.SelectedItemProperty,new Binding(nameof(TextBox.Text)){Source=interfaceField,Mode=BindingMode.TwoWay});
        speed=Input("speed","1000",220);elf=Input("elf","",175);map=Input("map","",175);
        var probe=Input("probe","",220);probe.ToolTip="留空使用唯一可用探针";
        var executable=Input("jlink_exe","",220);executable.ToolTip="可选，自定义 JLink.exe 路径";
        search=Input("search","",260);search.TextChanged+=(_,_)=>Rebuild();
        var side=Vertical(Label("Target / Device"),deviceCombo,Label("Interface"),transport,Label("Speed kHz"),speed,
            ActionButton("Connect",async()=>{var result=await Command("jlink","connect",Settings());RememberDevice();Status($"已连接 {result?["device"]} · {transport.SelectedItem} · {speed.Text} kHz");}),
            ActionButton("Disconnect",async()=>{await Command("jlink","disconnect");Status("探针已断开");}),
            Label("ELF / AXF"),Toolbar(elf,ActionButton("ELF",async()=>{var path=ChooseFile("ELF / AXF|*.elf;*.axf|所有文件|*.*");if(path!=null){elf.Text=path;await DetectDeviceAsync();}})),
            Label("MAP"),Toolbar(map,ActionButton("MAP",()=>{var path=ChooseFile("GNU MAP|*.map|所有文件|*.*");if(path!=null)map.Text=path;return Task.CompletedTask;})),
            ActionButton("Load",LoadAsync),ActionButton("Refresh",RefreshAsync),
            new Expander{Header="探针设置",Content=Vertical(Label("探针序列号"),probe,Label("JLink.exe（可选）"),executable)});
        table=Grid(("Value","Value",135),("Type","Type",120),("Address","Address",115),("Raw","Raw",180),("Status","Status",240));table.ItemsSource=visible;
        var statusColumn=(DataGridTextColumn)table.Columns[^1];var statusStyle=new Style(typeof(TextBlock),statusColumn.ElementStyle);
        statusStyle.Setters.Add(new Setter(TextBlock.TextWrappingProperty,TextWrapping.Wrap));statusStyle.Setters.Add(new Setter(TextBlock.TextTrimmingProperty,TextTrimming.None));statusColumn.ElementStyle=statusStyle;
        var template=new FrameworkElementFactory(typeof(StackPanel));template.SetValue(StackPanel.OrientationProperty,Orientation.Horizontal);template.SetBinding(MarginProperty,new Binding(nameof(Variable.Indent)));
        var expander=new FrameworkElementFactory(typeof(Button));expander.SetValue(WidthProperty,24d);expander.SetValue(HeightProperty,24d);expander.SetValue(MarginProperty,new Thickness(0));expander.SetValue(Control.PaddingProperty,new Thickness(0));expander.SetValue(Control.BorderThicknessProperty,new Thickness(0));expander.SetValue(Control.BackgroundProperty,Brushes.Transparent);expander.SetBinding(ContentControl.ContentProperty,new Binding(nameof(Variable.Arrow)));expander.AddHandler(System.Windows.Controls.Primitives.ButtonBase.ClickEvent,new RoutedEventHandler(async(sender,e)=>{e.Handled=true;if((sender as FrameworkElement)?.DataContext is Variable row)await Run(()=>ExpandAsync(row));}));template.AppendChild(expander);
        var expression=new FrameworkElementFactory(typeof(TextBlock));expression.SetBinding(TextBlock.TextProperty,new Binding(nameof(Variable.Expression)));expression.SetValue(VerticalAlignmentProperty,VerticalAlignment.Center);template.AppendChild(expression);
        table.Columns.Insert(0,new DataGridTemplateColumn{Header="Expression",CellTemplate=new DataTemplate{VisualTree=template},Width=new DataGridLength(1,DataGridLengthUnitType.Star),MinWidth=220});
        table.IsReadOnly=false;for(int i=0;i<table.Columns.Count;i++){table.Columns[i].DisplayIndex=i;table.Columns[i].IsReadOnly=i!=1;}
        ((DataGridTextColumn)table.Columns[1]).Binding=new Binding(nameof(Variable.EditValue)){Mode=BindingMode.TwoWay,UpdateSourceTrigger=UpdateSourceTrigger.PropertyChanged};
        table.BeginningEdit+=(_,e)=>{if(Busy||Closed||e.Column.DisplayIndex!=1||e.Row.Item is not Variable row||row.Data["kind"]?.ToString()!="scalar")e.Cancel=true;};
        table.PreviewKeyDown+=(_,e)=>{if(e.OriginalSource is TextBox){if(e.Key==Key.Enter)writeRequested=true;else if(e.Key==Key.Escape)writeRequested=false;}};
        table.CellEditEnding+=async(_,e)=>{
            bool commit=writeRequested;writeRequested=false;
            if(!commit||e.EditAction!=DataGridEditAction.Commit||e.Row.Item is not Variable row||e.EditingElement is not TextBox editor)return;
            string text=editor.Text.Trim();if(text==row.Value)return;
            await Run(async()=>{try{var args=Settings();args["name"]=row.Name;args["value"]=text;row.Update((await Command("jlink","write",args))!.AsObject());Status(row.Name+" 已写入并回读确认");}catch(Exception error){row.Error(error.Message);throw;}});
        };
        var menu=new ContextMenu();foreach(var label in new[]{"Copy Cell","Copy Row","Copy Expression","Copy Value","刷新所选变量"}){var item=new MenuItem{Header=label};item.Click+=async(_,_)=>{if(table.CurrentItem is not Variable row)return;if(label=="刷新所选变量"){await Run(()=>ReadAsync(row));return;}string text=label switch{"Copy Row"=>string.Join('\t',row.Name,row.Value,row.Type,row.Address,row.Raw,row.Status),"Copy Expression"=>row.Name,"Copy Value"=>row.Value,_=>CellText(row,table.CurrentColumn?.DisplayIndex??0)};Clipboard.SetText(text);};menu.Items.Add(item);}table.ContextMenu=menu;
        table.PreviewKeyDown+=(_,e)=>{if(e.Key==Key.C&&(Keyboard.Modifiers&ModifierKeys.Control)!=0&&table.CurrentItem is Variable row){Clipboard.SetText(CellText(row,table.CurrentColumn?.DisplayIndex??0));e.Handled=true;}};
        var tools=Toolbar(Label("J-Link Variables"),Label("Search"),search,count);
        Content=Split(new ScrollViewer{Content=side,VerticalScrollBarVisibility=ScrollBarVisibility.Auto},Above(tools,table),270);
    }
    private static string CellText(Variable row,int column)=>column switch{0=>row.Name,1=>row.Value,2=>row.Type,3=>row.Address,4=>row.Raw,_=>row.Status};
    private JsonObject Settings()
    {
        if(!int.TryParse(speed.Text,out int khz)||khz<1||khz>50000)throw new ArgumentException("Speed 必须为 1–50000 kHz");
        var q=new JsonObject{["device"]=device.Text.Trim(),["interface"]=transport.SelectedItem?.ToString()??"SWD",["speed"]=khz};
        if(!string.IsNullOrWhiteSpace(Fields["probe"].Text)){if(!uint.TryParse(Fields["probe"].Text,out uint serial))throw new ArgumentException("探针序列号无效");q["probe"]=serial;}else q["probe"]=0;
        if(!string.IsNullOrWhiteSpace(Fields["jlink_exe"].Text))q["jlink_exe"]=Fields["jlink_exe"].Text.Trim();return q;
    }
    private void RememberDevice()=>history.Text=string.Join(';',new[]{device.Text.Trim()}.Concat(history.Text.Split(';',StringSplitOptions.RemoveEmptyEntries)).Distinct().Take(20));
    private async Task DetectDeviceAsync(){var data=await Command("jlink","detect",new(){["path"]=elf.Text.Trim()});if(data?["device"] is JsonValue found){device.Text=found.ToString();Status("从工程配置识别目标："+device.Text);}}
    public override void Apply(JsonNode? data)
    {
        if(data is JsonArray list){roots.Clear();roots.AddRange(list.OfType<JsonObject>().Select(r=>new Variable(r)));Rebuild();}
    }
    private async Task LoadAsync()
    {
        string path=elf.Text.Trim().Length>0?elf.Text.Trim():map.Text.Trim();if(path.Length==0)throw new ArgumentException("请选择 ELF / AXF 或 MAP");
        var args=new JsonObject{["path"]=path};if(map.Text.Trim().Length>0&&map.Text.Trim()!=path)args["map"]=map.Text.Trim();
        await Command("jlink","load",args);roots.Clear();Rebuild();
        for(int offset=0;;){var part=(await Command("jlink","symbols",new(){["offset"]=offset,["limit"]=4096,["variables_only"]=true}))!.AsArray();roots.AddRange(part.OfType<JsonObject>().Select(r=>new Variable(r)));offset+=part.Count;if(part.Count<4096)break;}
        Rebuild();RememberDevice();Status($"已加载 {roots.Count} 个变量；Refresh 读取当前展开的变量");
    }
    private void Rebuild()
    {
        if(rebuilding)return;rebuilding=true;try{
            var selected=table?.SelectedItem as Variable;visible.Clear();string query=search.Text.Trim();
            bool Matches(Variable row)=>row.Name.Contains(query,StringComparison.OrdinalIgnoreCase)||row.Children.Any(Matches);
            void Add(Variable row){if(query.Length>0&&!Matches(row))return;visible.Add(row);if(row.Expanded)foreach(var child in row.Children)Add(child);}
            foreach(var row in roots)Add(row);if(table!=null)table.SelectedItem=selected;count.Text=$"{roots.Count} 个变量 · 显示 {visible.Count}";
        }finally{rebuilding=false;}
    }
    public async Task ExpandAsync(Variable row)
    {
        if(!row.Expandable)return;if(row.Expanded){row.Expanded=false;row.Changed();Rebuild();return;}
        if(row.Depth>=64){row.Error("达到 64 层展开限制");return;}
        if(!row.Loaded||row.Data["kind"]?.ToString()=="pointer"){
            var children=new List<Variable>();try{
                string expression=row.Name;
                if(row.Data["kind"]?.ToString()=="pointer"){
                    await ReadAsync(row);
                    if(Num(row.Data["raw"])==0){row.Error("NULL · 链表结束");return;}
                    var pointerArgs=Settings();pointerArgs["name"]=row.Name;
                    var target=(await Command("jlink","expand",pointerArgs))!.AsArray().OfType<JsonObject>().Single();
                    ulong address=(ulong)Num(target["address"]);string type=target["type_name"]?.ToString()??"";
                    // The second backend read may observe a newer pointer value.
                    var pointerData=(JsonObject)row.Data.DeepClone();pointerData["raw"]=address;pointerData["value"]=address;pointerData.Remove("hex");pointerData["resolved_type"]=type.Length>0?type:target["kind"]?.ToString();pointerData.Remove("resolved_symbol");if(target["resolved_symbol"] is JsonValue resolved)pointerData["resolved_symbol"]=resolved.DeepClone();row.Update(pointerData);
                    for(var ancestor=row.Parent;ancestor!=null;ancestor=ancestor.Parent){
                        ulong? ancestorAddress=ancestor.ExpandedAddress??(ancestor.Data["kind"]?.ToString() is "struct" or "union"?(ulong)Num(ancestor.Data["address"]):null);
                        string ancestorType=ancestor.ExpandedType??ancestor.Data["type_name"]?.ToString()??"";
                        if(ancestorAddress==address&&ancestorType==type){row.Children.Clear();row.Loaded=false;row.Error("循环引用 → "+ancestor.Name);Rebuild();return;}
                    }
                    row.ExpandedAddress=address;row.ExpandedType=type;
                    if(target["kind"]?.ToString() is "struct" or "union")expression=target["name"]!.ToString();
                    else children.Add(new Variable(target,row.Depth+1,row));
                }
                if(children.Count==0)for(int offset=0;;){var args=Settings();args["name"]=expression;args["offset"]=offset;args["limit"]=4096;var part=(await Command("jlink","expand",args))!.AsArray();children.AddRange(part.OfType<JsonObject>().Select(r=>new Variable(r,row.Depth+1,row)));offset+=part.Count;if(part.Count<4096)break;}
                row.Children.Clear();row.Children.AddRange(children);row.Loaded=true;
            }catch(Exception error){row.Children.Clear();row.Loaded=false;row.ExpandedAddress=null;row.Error(error.Message);Rebuild();throw;}
        }
        if(row.Data["kind"]?.ToString() is "struct" or "union"){var data=(JsonObject)row.Data.DeepClone();data["resolved_type"]=row.Type;row.Update(data);}
        row.Expanded=true;row.Changed();Rebuild();
        var readable=row.Children.Where(child=>child.Data["kind"]?.ToString() is "scalar" or "pointer").ToArray();
        foreach(var child in readable.Take(256)){
            if(Closed)return;
            try{await ReadAsync(child);}catch{ /* Keep the individual member error visible. */ }
        }
        if(readable.Length>256)Status("已读取前 256 个成员，其余可选择后刷新");
    }
    private async Task ReadAsync(Variable row)
    {
        try{var args=Settings();args["name"]=row.Name;var result=(await Command("jlink","read",args))!.AsObject();bool moved=row.Data["kind"]?.ToString()=="pointer"&&row.Data["raw"]?.ToString()!=result["raw"]?.ToString();row.Update(result);if(moved){row.Children.Clear();row.Loaded=false;row.Expanded=false;row.ExpandedAddress=null;row.ExpandedType=null;Rebuild();}}
        catch(Exception error){if(row.Data["kind"]?.ToString()=="pointer"){row.Children.Clear();row.Loaded=false;row.Expanded=false;row.ExpandedAddress=null;row.ExpandedType=null;Rebuild();}row.Error(error.Message);throw;}
    }
    private async Task RefreshAsync()
    {
        int ok=0,failed=0;
        foreach(var row in visible.ToArray().Where(r=>r.Data["kind"]?.ToString() is "scalar" or "pointer")){
            if(Closed)break;
            // A pointer refresh can invalidate descendants that were in the snapshot.
            if(!visible.Contains(row))continue;
            try{await ReadAsync(row);ok++;}catch{failed++;}
        }
        Status($"刷新完成 · 成功 {ok} · 失败 {failed}（详见 Status 列）");
    }
}
