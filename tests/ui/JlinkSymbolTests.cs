using System.Text.Json.Nodes;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Reflection;
using Frame.Desktop;
using Frame.Client;

internal static class JlinkSymbolTests
{
    public static async Task Run(string root)
    {
        string elf=Path.Combine(root,"build/symbol-fixture.elf");
        if(!File.Exists(elf))throw new Exception("Build tests/native/symbol_fixture.cpp into build/symbol-fixture.elf before UI verification");
        await using var client=new BackendClient();
        async Task<JsonNode?> Call(string action,JsonObject? args=null){var q=args??new();q["group"]="jlink";q["action"]=action;var r=await client.ExecuteAsync(q);if(r["ok"]?.GetValue<bool>()!=true)throw new Exception(r.ToJsonString());return r["data"];}
        await Call("load",new(){["path"]=elf});
        var symbols=(await Call("symbols",new(){["limit"]=4096,["variables_only"]=true}))!.AsArray();
        if(symbols.Any(s=>s?["name"]?.ToString()=="fixture_entry")||!symbols.Any(s=>s?["name"]?.ToString()=="gain"))throw new Exception("Variables-only symbol table must omit functions");
        var children=(await Call("expand",new(){["name"]="controller"}))!.AsArray();if(children.Count!=2||children[0]?["name"]?.ToString()!="controller.gain")throw new Exception("Struct DWARF members missing");
        var array=(await Call("expand",new(){["name"]="samples",["offset"]=1,["limit"]=1}))!.AsArray();if(array.Count!=1||array[0]?["name"]?.ToString()!="samples[1]")throw new Exception("Array paging");
        await Call("connect",new(){["jlink_exe"]=Path.Combine(root,"build/native/Release/frame_fake_commander.exe"),["device"]="TESTMEM",["interface"]="JTAG",["speed"]=4000});
        var pointer=(await Call("expand",new(){["name"]="active"}))!.AsArray();if(pointer.Count!=1||pointer[0]?["address"]?.GetValue<ulong>()!=0x20001000)throw new Exception("Pointer expansion must read current target memory");
        var pointee=(await Call("expand",new(){["name"]="(*active)"}))!.AsArray();if(pointee[0]?["address"]?.GetValue<ulong>()!=0x20001000||pointee[1]?["address"]?.GetValue<ulong>()!=0x20001004)throw new Exception("Pointee member addresses");
        var scalar=await Call("read",new(){["name"]="controller.count"});if(scalar?["raw"]?.GetValue<ulong>()!=0x20001000)throw new Exception("Typed variable read with selected Commander session");
        var write=await Call("write",new(){["name"]="gain",["value"]="1.5"});if(write?["value"]?.GetValue<double>()!=1.5)throw new Exception("Float write and readback");
        var precision=await Call("write",new(){["name"]="precision_value",["value"]="1.23456789"});if(precision?["value"]?.GetValue<double>()!=1.23456789)throw new Exception("Double write and readback");
        var fields=new Dictionary<string,TextBox>();var page=new JlinkPage(client,fields,_=>{});fields["device"].Text="TESTMEM";fields["jlink_exe"].Text=Path.Combine(root,"build/native/Release/frame_fake_commander.exe");page.Apply(symbols);
        var host=new Window{Content=page,Width=1300,Height=650};host.Show();host.UpdateLayout();
        var table=(DataGrid)typeof(JlinkPage).GetField("table",BindingFlags.Instance|BindingFlags.NonPublic)!.GetValue(page)!;
        var unreadTarget=(await Call("read",new(){["name"]="opaque_object"}))!.AsObject();
        if(unreadTarget["resolved_type"]?.ToString()!="Controller"||unreadTarget["resolved_symbol"]?.ToString()!="resolved_controller")throw new Exception("Pointer read must resolve its target before any expansion");
        fields["search"].Text="opaque_object";
        var opaque=table.Items.Cast<JlinkPage.Variable>().Single();await page.ExpandAsync(opaque);
        if(opaque.Children.Count!=2||opaque.Children[0].Type!="float"||opaque.Children[1].Address!="0x20001004"||opaque.Children[1].Status!="已读取"||!opaque.Status.Contains("resolved_controller"))throw new Exception("void pointer must resolve its exact ELF object and read real struct members");
        fields["search"].Clear();var bytePointer=table.Items.Cast<JlinkPage.Variable>().Single(r=>r.Name=="byte_object");await page.ExpandAsync(bytePointer);
        if(bytePointer.Children.Count!=2||bytePointer.Children[1].Expression!="count")throw new Exception("Byte pointer must resolve a known object at the pointed-to address");
        var registry=table.Items.Cast<JlinkPage.Variable>().Single(r=>r.Name=="registry");await page.ExpandAsync(registry);await page.ExpandAsync(registry.Children.Single());
        if(registry.Children[0].Children.Count!=2)throw new Exception("A void pointer member must expand the registered object's DWARF layout");
        await (Task)typeof(JlinkPage).GetMethod("RefreshAsync",BindingFlags.NonPublic|BindingFlags.Instance)!.Invoke(page,null)!;
        if(!opaque.Status.Contains("Controller")||!opaque.Status.Contains("resolved_controller")||!opaque.Expanded)throw new Exception("Refresh must retain resolved type, symbol and expanded members");
        fields["device"].Text="LISTMOVE";await page.ExpandAsync(opaque);await page.ExpandAsync(opaque);
        if(opaque.Children[0].Expression!="value"||opaque.Children[0].Value!="202"||!opaque.Status.Contains("resolved_node"))throw new Exception("Changed void pointer must resolve the new object's type and data");
        fields["device"].Text="UNMAPPED";await page.ExpandAsync(opaque);
        try{await page.ExpandAsync(opaque);throw new Exception("Unknown address unexpectedly expanded");}catch(InvalidOperationException error){if(!error.Message.Contains("No DWARF target type"))throw;}
        if(opaque.Children.Count!=0||opaque.Expanded)throw new Exception("Unresolved address must not retain previous struct data");
        fields["device"].Text="TESTMEM";fields["search"].Clear();
        Console.WriteLine("PASS: void/byte pointers and nested registry member resolve exact ELF objects, read values, change target type and reject unknown addresses.");
        var gain=table.Items.Cast<JlinkPage.Variable>().Single(r=>r.Name=="gain");table.SelectedItem=gain;table.CurrentCell=new DataGridCellInfo(gain,table.Columns[1]);table.Focus();host.UpdateLayout();
        if(!table.BeginEdit())throw new Exception($"J-Link Value must support inline edit; tableReadonly={table.IsReadOnly}, columnReadonly={table.Columns[1].IsReadOnly}, display={table.Columns[1].DisplayIndex}, current={table.CurrentColumn?.Header}, kind={gain.Data["kind"]}");host.UpdateLayout();var editor=(TextBox)table.Columns[1].GetCellContent(gain);editor.Text="2.75";
        editor.RaiseEvent(new KeyEventArgs(Keyboard.PrimaryDevice,PresentationSource.FromVisual(host)!,Environment.TickCount,Key.Enter){RoutedEvent=Keyboard.PreviewKeyDownEvent,Source=editor});table.CommitEdit(DataGridEditingUnit.Cell,true);
        for(int i=0;i<150&&gain.Value!="2.75";i++)await Task.Delay(20);
        if(gain.Value!="2.75")throw new Exception("J-Link inline Enter must commit and show readback: "+gain.Status);
        table.CurrentCell=new DataGridCellInfo(gain,table.Columns[1]);table.BeginEdit();host.UpdateLayout();((TextBox)table.Columns[1].GetCellContent(gain)).Text="99";table.CancelEdit(DataGridEditingUnit.Cell);await Task.Delay(30);
        if((await Call("read",new(){["name"]="gain"}))?["value"]?.GetValue<double>()!=2.75)throw new Exception("Cancelled inline edits must not write RAM");
        fields["device"].Text="LIST";page.Apply(symbols);
        var head=table.Items.Cast<JlinkPage.Variable>().Single(r=>r.Name=="list_head");await page.ExpandAsync(head);
        if(head.Children.Single(r=>r.Expression=="value").Value!="101")throw new Exception("Linked-list first node values must be read on expansion");
        var next=head.Children.Single(r=>r.Expression=="next");await page.ExpandAsync(next);
        if(next.Children.Single(r=>r.Expression=="value").Value!="202")throw new Exception("next must expand the pointed-to struct and read its values");
        await (Task)typeof(JlinkPage).GetMethod("RefreshAsync",BindingFlags.Instance|BindingFlags.NonPublic)!.Invoke(page,null)!;
        if(!head.Expanded||!next.Expanded)throw new Exception("Refreshing unchanged list pointers must preserve expanded nodes");
        var tail=next.Children.Single(r=>r.Expression=="next");await page.ExpandAsync(tail);
        if(!tail.Status.Contains("NULL")||tail.Children.Count!=0)throw new Exception("Null list tail must stop traversal");
        fields["device"].Text="LISTMOVE";
        await (Task)typeof(JlinkPage).GetMethod("RefreshAsync",BindingFlags.Instance|BindingFlags.NonPublic)!.Invoke(page,null)!;
        if(head.Expanded||head.Children.Count!=0)throw new Exception("Relinked head must discard old descendant values");
        await page.ExpandAsync(head);if(head.Children.Single(r=>r.Expression=="value").Value!="202")throw new Exception("Relinked head must use the new struct address");
        fields["device"].Text="LISTRING";page.Apply(symbols);head=table.Items.Cast<JlinkPage.Variable>().Single(r=>r.Name=="list_head");await page.ExpandAsync(head);next=head.Children.Single(r=>r.Expression=="next");await page.ExpandAsync(next);tail=next.Children.Single(r=>r.Expression=="next");await page.ExpandAsync(tail);
        if(!tail.Status.Contains("循环引用")||tail.Children.Count!=0)throw new Exception("Ring list must identify the ancestor instead of growing without limit");
        Console.WriteLine("PASS: J-Link two-node struct chain, automatic values, NULL tail, ring detection, unchanged refresh and relink invalidation.");
        page.Shutdown();host.Close();
        await Call("connect",new(){["device"]="ZERO"});var nullPointer=await client.ExecuteAsync(new(){["group"]="jlink",["action"]="expand",["name"]="active"});if(nullPointer["ok"]?.GetValue<bool>()==true||!nullPointer["error"]!.ToString().Contains("Null pointer"))throw new Exception("Null pointers must not expose fabricated children");
        Console.WriteLine("PASS: ARM ELF/DWARF variable filtering, struct/array paging, current/null pointers, Commander memory read, FP32/FP64 writes and readback.");
    }
}
