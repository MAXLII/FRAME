using System.Text.Json.Nodes;
using Frame.Desktop;

internal static class ParameterTests
{
    public static async Task Run()
    {
        int calls=0;JsonObject? sent=null;bool reject=false;string feedback="";
        var panel=new ParameterPanel(q=>
        {
            calls++;sent=q;
            if(reject)return Task.FromResult(new JsonObject{["ok"]=false,["error"]="Device rejected reporting change"});
            var data=q["action"]!.GetValue<string>()=="report"?new JsonObject{["success"]=true}:new JsonObject{["name"]="GAIN",["type"]=6,["value"]=1.25,["verification"]="directory_readback",["verified"]=true,["ack_received"]=false};
            return Task.FromResult(new JsonObject{["ok"]=true,["data"]=data});
        },text=>feedback=text);
        panel.Apply(JsonNode.Parse("""
        [{"name":"GAIN","type":6,"value":1,"raw":1065353216,"min":0,"min_raw":0,"max":10,"max_raw":1092616192,"flags":0},
         {"name":"SIGNED","type":0,"value":-1,"raw":4294967295,"min":-128,"min_raw":4294967168,"max":127,"max_raw":127},
         {"name":"COMMAND","type":7,"value":0,"raw":0,"min_raw":0,"max_raw":0},
         {"name":"READONLY","type":5,"value":3,"raw":3,"min":3,"min_raw":3,"max":3,"max_raw":3}]
        """)!);
        var rows=panel.Table.Items.Cast<ParameterRow>().ToArray();
        if(panel.Table.Columns.Count!=6||rows[0].TypeName!="FP32"||rows[0].Data!="1.0"||rows[0].Hex!="/"||rows[1].Hex!="0xFF"||rows[2].Data!="/")throw new Exception("Legacy typed parameter columns failed");
        if(!ParameterPanel.Matches("DEMO_SHELL_GAIN","d s g")||ParameterPanel.Matches("GAIN","ng"))throw new Exception("Ordered fuzzy search failed");
        rows[0].BeginEdit();rows[0].Data="99";rows[0].CancelEdit();if(rows[0].Data!="1.0"||rows[0].Dirty)throw new Exception("Cancel editing must restore the draft");
        panel.Table.SelectedItem=rows[0];rows[0].Data="1.25";rows[0].Minimum="-1";rows[0].Maximum="20";
        if(calls!=0||!rows[0].Dirty)throw new Exception("Editing must remain local until Write");
        await panel.RunAsync("write");
        if(sent?["min"]?.ToString()!="-1"||sent?["max"]?.ToString()!="20"||rows[0].Dirty||panel.Table.Items.Count!=4)throw new Exception("Write/update must preserve the parameter list");
        reject=true;await panel.RunAsync("write");reject=false;
        if(!rows[0].Invalid)throw new Exception("Unconfirmed write must remain yellow");
        await panel.RunAsync("write");
        if(rows[0].Invalid||rows[0].Dirty||!feedback.Contains("ACK 未收到，已通过回读确认"))throw new Exception("Verified readback must clear old yellow state and explain missing ACK");
        await panel.RunAsync("report");if(!rows[0].Reporting)throw new Exception("Reporting state must follow ACK");
        IReadOnlyList<string> waveNames=Array.Empty<string>();var series=new WaveSeriesPanel();
        panel.WaveSelectionChanged+=names=>{waveNames=names;series.SetSelectedParameters(names);};
        var host=new System.Windows.Window{Content=panel,Width=1100,Height=450};host.Show();host.UpdateLayout();
        System.Windows.Controls.DataGridCell NameCell(ParameterRow row)
        {
            panel.Table.ScrollIntoView(row);host.UpdateLayout();
            var container=(System.Windows.Controls.DataGridRow)panel.Table.ItemContainerGenerator.ContainerFromItem(row);
            System.Windows.Controls.DataGridCell? Find(System.Windows.DependencyObject parent)
            {
                if(parent is System.Windows.Controls.DataGridCell found&&found.Column.DisplayIndex==0)return found;
                for(int i=0;i<System.Windows.Media.VisualTreeHelper.GetChildrenCount(parent);i++)if(Find(System.Windows.Media.VisualTreeHelper.GetChild(parent,i)) is {} cell)return cell;
                return null;
            }
            return Find(container)??throw new Exception("Parameter name cell not rendered");
        }
        void DoubleClickName(ParameterRow row)
        {
            var cell=NameCell(row);
            panel.Table.RaiseEvent(new System.Windows.Input.MouseButtonEventArgs(System.Windows.Input.Mouse.PrimaryDevice,Environment.TickCount,System.Windows.Input.MouseButton.Left){RoutedEvent=System.Windows.Controls.Control.MouseDoubleClickEvent,Source=cell});
        }
        DoubleClickName(rows[0]);await Task.Yield();
        if(rows[0].Reporting||waveNames.Count!=0||series.IsSeriesVisible("GAIN"))throw new Exception("Double-click must remove the reported parameter from the wave selection");
        DoubleClickName(rows[0]);await Task.Yield();
        if(!rows[0].Reporting||!waveNames.SequenceEqual(new[]{"GAIN"})||!series.IsSeriesVisible("GAIN")||sent?["enable"]?.GetValue<bool>()!=true)throw new Exception("Double-click must enable reporting and populate wave selection");
        await host.Dispatcher.InvokeAsync(()=>{},System.Windows.Threading.DispatcherPriority.ApplicationIdle);
        if((NameCell(rows[0]).Background as System.Windows.Media.SolidColorBrush)?.Color!=System.Windows.Media.Brushes.Honeydew.Color)throw new Exception("Selected waveform parameter must remain visibly green");
        reject=true;DoubleClickName(rows[0]);await Task.Yield();reject=false;
        if(!rows[0].Reporting||!waveNames.SequenceEqual(new[]{"GAIN"}))throw new Exception("Rejected reporting change must retain acknowledged wave membership");
        DoubleClickName(rows[1]);await Task.Yield();
        if(!waveNames.SequenceEqual(new[]{"GAIN","SIGNED"}))throw new Exception("Wave membership must retain parameter read order");
        DoubleClickName(rows[0]);await Task.Yield();
        series.Update(new JsonArray(new JsonObject{["name"]="GAIN",["value"]=1.25}));
        if(series.IsSeriesVisible("GAIN"))throw new Exception("Retained acquisition history must not re-add a removed parameter");
        int commandCalls=calls;DoubleClickName(rows[2]);await Task.Yield();if(calls!=commandCalls)throw new Exception("Commands cannot join a waveform");
        panel.Table.SelectedItem=rows[3];int previous=calls;await panel.RunAsync("write");if(calls!=previous)throw new Exception("Read-only writes must be blocked");
        host.Close();
        Console.WriteLine("PASS: typed/FP32 columns, integer HEX, command/read-only behavior, fuzzy search, staged edits, bounds and in-place updates.");
    }
}
