using System.Reflection;
using System.Text.Json.Nodes;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using Frame.Client;
using Frame.Desktop;

internal static class DiagnosticPageTests
{
    private static T Field<T>(object instance,string name)=>(T)instance.GetType().GetField(name,BindingFlags.Instance|BindingFlags.NonPublic)!.GetValue(instance)!;
    private static void Require(bool value,string message){if(!value)throw new Exception(message);}
    internal static IEnumerable<T> Visuals<T>(DependencyObject root) where T:DependencyObject
    {
        for(int i=0;i<VisualTreeHelper.GetChildrenCount(root);i++){var child=VisualTreeHelper.GetChild(root,i);if(child is T match)yield return match;foreach(var nested in Visuals<T>(child))yield return nested;}
    }
    internal static void ClickCell(DataGrid grid,int index)
    {
        grid.ScrollIntoView(grid.Items[index]);grid.UpdateLayout();
        var row=(DataGridRow)grid.ItemContainerGenerator.ContainerFromIndex(index);
        var cell=Visuals<DataGridCell>(row).First();
        cell.RaiseEvent(new MouseButtonEventArgs(Mouse.PrimaryDevice,Environment.TickCount,MouseButton.Left){RoutedEvent=UIElement.MouseLeftButtonDownEvent});
        Require(Equals(grid.SelectedItem,grid.Items[index]),"Single cell click must select the corresponding row");
    }
    public static async Task Run()
    {
        await using var client=new BackendClient();
        var fields=new Dictionary<string,TextBox>();var perf=new PerfPage(client,fields,_=>{});
        perf.SetRecords(JsonNode.Parse("""[{"record_id":1,"type":1,"name":"task","time_us":2,"max_us":100,"load":1.25,"peak":5},{"record_id":2,"type":3,"name":"code","time_us":100,"max_us":120}]""")!.AsArray());
        var table=Field<DataGrid>(perf,"table");
        Require(table.Columns.Select(c=>c.Header.ToString()).SequenceEqual(new[]{"Type","Name","Run Time (us)","Max Time (us)","Load (%)","Peak (%)"}),"Perf column parity");
        perf.SetRecords(JsonNode.Parse("""[{"record_id":1,"type":1,"name":"task","time_us":9,"max_us":100,"load":2.5,"peak":6}]""")!.AsArray(),1);
        Require(table.Items.Count==2&&table.Items.Cast<PerfPage.Record>().Single(r=>r.Id==1).Time==9,"Perf filtered pulls retain other record kinds");
        fields["search"].Text="CODE";Require(table.Items.Count==1&&((PerfPage.Record)table.Items[0]).Name=="code","Perf local case-insensitive search");fields["search"].Clear();
        var view=CollectionViewSource.GetDefaultView(table.ItemsSource);view.SortDescriptions.Add(new(nameof(PerfPage.Record.Time),System.ComponentModel.ListSortDirection.Descending));Require(((PerfPage.Record)table.Items[0]).Time==100,"Perf numeric sort must not compare formatted text");
        var host=new Window{Content=perf,Width=1200,Height=700,ShowInTaskbar=false};host.Show();host.UpdateLayout();
        ClickCell(table,0);Require(Field<TextBlock>(perf,"detail").Text.Contains("Code 记录不包含占用率"),"Code details must open on cell click and not invent load");
        var traceFields=new Dictionary<string,TextBox>();var trace=new TracePage(client,traceFields,_=>{});
        trace.SetRecords(JsonNode.Parse("""[{"time":1.2345,"line":35},{"time":1.5,"line":40}]""")!.AsArray());traceFields["highlight"].Text="0x23";
        var traces=Field<DataGrid>(trace,"table");Require(traces.Items.Count==2&&((TracePage.Record)traces.Items[0]).Time==1234.5,"Trace milliseconds and highlight without dropping other lines");
        Require(traces.RowStyle.Triggers.OfType<System.Windows.DataTrigger>().Single().Value.Equals(35),"Trace hex line highlighting");
        trace.SetRecords(JsonNode.Parse("""[{"time":2,"line":35}]""")!.AsArray(),2,true);Require(traces.Items.Count==3&&((TracePage.Record)traces.Items[2]).Index==3,"Trace append numbering");
        var section=new SectionPage(client,new(),_=>{});
        section.SetDirectory(JsonNode.Parse("""[{"list_id":1,"name":"Task","node_count":2},{"list_id":2,"name":"Interrupt","node_count":1}]""")!.AsArray());
        section.SetNodes(1,JsonNode.Parse("""[{"index":0,"address":536870912,"name":"run"},{"index":1,"address":536870916,"name":"stop"}]""")!.AsArray());
        section.SetNodes(2,JsonNode.Parse("""[{"index":0,"address":536870920,"name":"irq"}]""")!.AsArray());
        host.Content=section;host.UpdateLayout();
        var lists=Field<DataGrid>(section,"lists");var nodes=Field<DataGrid>(section,"nodes");ClickCell(lists,1);Require(((SectionPage.NodeItem)nodes.Items[0]).Name=="irq","Section object switch uses the correct cache");ClickCell(lists,0);Require(nodes.Items.Count==2&&((SectionPage.NodeItem)nodes.Items[1]).Index==1,"Section restores nodes in device traversal order");
        var jlinkFields=new Dictionary<string,TextBox>();var jlink=new JlinkPage(client,jlinkFields,_=>{});jlink.Apply(JsonNode.Parse("""[{"name":"gain","kind":"scalar","type_name":"float","size":4,"address":536870912},{"name":"controller","kind":"struct","size":16,"address":536870916}]"""));
        var variables=Field<DataGrid>(jlink,"table");Require(variables.Columns.Select(c=>c.Header.ToString()).SequenceEqual(new[]{"Expression","Value","Type","Address","Raw","Status"}),"J-Link tree table columns");
        jlinkFields["search"].Text="GAIN";Require(variables.Items.Count==1,"J-Link local search");var gain=(JlinkPage.Variable)variables.Items[0];gain.Update(JsonNode.Parse("""{"name":"gain","kind":"scalar","type_name":"float","size":4,"address":536870912,"value":1.25,"hex":"00 00 A0 3F"}""")!.AsObject());Require(gain.Value=="1.25"&&gain.Address=="0x20000000"&&gain.Status=="已读取","J-Link value/address/status in same row");
        foreach(var page in new DiagnosticPage[]{perf,trace,section,jlink})page.Shutdown();
        host.Close();
        Console.WriteLine("PASS: Perf filtered cache/numeric sorting/details; Trace highlight and append; Section per-list cache/order; J-Link variable table/search/value updates.");
    }
    public static void Populate(DiagnosticPage page)
    {
        if(page is PerfPage perf){perf.Apply(JsonNode.Parse("""{"task_load":26.25,"task_peak":42.75,"interrupt_load":4.5,"interrupt_peak":8.25}"""));var table=Field<DataGrid>(perf,"table");if(table.Items.Count>0)table.SelectedIndex=0;}
        if(page is SectionPage section){section.SetDirectory(JsonNode.Parse("""[{"list_id":1,"name":"Task","node_count":2},{"list_id":2,"name":"Interrupt","node_count":1}]""")!.AsArray());section.SetNodes(1,JsonNode.Parse("""[{"index":0,"name":"heartbeat_task","address":536870912},{"index":1,"name":"control_task","address":536870928}]""")!.AsArray());}
        if(page is JlinkPage jlink)jlink.Apply(JsonNode.Parse("""[{"name":"gain","kind":"scalar","type_name":"float","size":4,"address":536870912,"value":1.25,"hex":"00 00 A0 3F"},{"name":"controller","kind":"struct","type_name":"Controller","size":16,"address":536870916},{"name":"samples","kind":"array","type_name":"float[16]","size":64,"address":536870932},{"name":"active","kind":"pointer","type_name":"Controller*","size":4,"address":536870996}]"""));
    }
}
