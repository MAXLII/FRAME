using System.Collections;
using System.Reflection;
using System.Text.Json.Nodes;
using Frame.Client;
using Frame.Desktop;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Threading;

internal static class SerialMonitorTests
{
    public static async Task RunAsync(MainWindow window)
    {
        const BindingFlags flags=BindingFlags.Instance|BindingFlags.Static|BindingFlags.NonPublic;
        var type=typeof(MainWindow);
        var page=((IDictionary)type.GetField("pages",flags)!.GetValue(window)!)["serial"]!;
        var records=(List<JsonObject>)page.GetType().GetProperty("SerialMonitor")!.GetValue(page)!;
        var client=(BackendClient)type.GetField("client",flags)!.GetValue(window)!;
        ulong epoch=client.Snapshot()["epoch"]!.GetValue<ulong>();
        var clear=type.GetMethod("ClearSerialMonitor",flags)!;
        var append=type.GetMethod("AppendSerialMonitor",flags)!;
        var advance=type.GetMethod("AdvanceSerialMonitorEpoch",flags)!;
        var receive=type.GetMethod("OnSerialMonitor",flags)!;
        clear.Invoke(null,[page]);
        receive.Invoke(window,[new JsonObject{["epoch"]=epoch,["records"]=new JsonArray(new JsonObject{["kind"]="rx",["hex"]="41"})}]);
        advance.Invoke(window,[epoch]);
        if(epoch>0)advance.Invoke(window,[epoch-1]);
        if(records.Count!=1||records[0]["hex"]?.ToString()!="41")throw new Exception("A snapshot must retain events already received for its epoch");
        if(epoch>0)
        {
            receive.Invoke(window,[new JsonObject{["epoch"]=epoch-1,["records"]=new JsonArray(new JsonObject{["hex"]="42"})}]);
            if(records.Count!=1)throw new Exception("Stale monitor events must be ignored");
        }
        clear.Invoke(null,[page]);
        var large=new JsonObject{["kind"]="rx",["hex"]=new string('A',200000),["bytes"]=100000};
        append.Invoke(null,[page,large]);
        if(records.Count!=1||records[0]["hex"]!.ToString().Length!=131072||large["hex"]!.ToString().Length!=200000)
            throw new Exception("Large blocks must retain only a bounded display tail without changing source data");
        for(int i=0;i<513;i++)append.Invoke(null,[page,new JsonObject{["hex"]="42"}]);
        if(records.Count!=512||records.Sum(r=>r["bytes"]!.GetValue<int>())>65536)
            throw new Exception("Both record and byte budgets must hold for the shared live/history path");
        clear.Invoke(null,[page]);
        var log=(RichTextBox)page.GetType().GetProperty("ReceiveLog")!.GetValue(page)!;
        var showProtocol=(CheckBox)page.GetType().GetProperty("ShowProtocolTraffic")!.GetValue(page)!;
        var follow=page.GetType().GetField("SerialFollowLatest")!;
        var render=type.GetMethod("RenderSerial",flags)!;
        var connection=type.GetMethod("UpdateSerialConnection",flags)!;
        for(int i=0;i<200;i++)append.Invoke(null,[page,new JsonObject{["kind"]="user_tx",["hex"]="4142"}]);
        render.Invoke(null,[page,true]);
        await Dispatcher.Yield(DispatcherPriority.Background);
        log.UpdateLayout();
        if(log.ExtentHeight<=log.ViewportHeight)throw new Exception("Monitor scrolling fixture must overflow its viewport");
        log.ScrollToVerticalOffset(log.ExtentHeight/3);log.UpdateLayout();
        await Dispatcher.Yield(DispatcherPriority.Background);
        if((bool)follow.GetValue(page)!)throw new Exception("Scrolling upward must pause follow");
        var document=log.Document;double offset=log.VerticalOffset;
        append.Invoke(null,[page,new JsonObject{["kind"]="rx",["hex"]="4344"}]);
        render.Invoke(null,[page,false]);
        if(!ReferenceEquals(document,log.Document)||Math.Abs(log.VerticalOffset-offset)>1)
            throw new Exception("New traffic must preserve the document and viewport while browsing history");
        int retained=records.Count;
        connection.Invoke(window,[false,epoch]);
        if(records.Count!=retained||!ReferenceEquals(document,log.Document))throw new Exception("Disconnect must retain history and viewport");
        log.ScrollToEnd();log.UpdateLayout();
        await Dispatcher.Yield(DispatcherPriority.Background);
        if(!(bool)follow.GetValue(page)!||ReferenceEquals(document,log.Document)||log.VerticalOffset+log.ViewportHeight<log.ExtentHeight-2)
            throw new Exception("Returning to the bottom must resume follow and display pending traffic");
        log.ScrollToHome();log.UpdateLayout();
        await Dispatcher.Yield(DispatcherPriority.Background);
        connection.Invoke(window,[true,epoch]);
        await Dispatcher.Yield(DispatcherPriority.Background);
        if(!(bool)follow.GetValue(page)!||records.Count!=retained||log.VerticalOffset+log.ViewportHeight<log.ExtentHeight-2)
            throw new Exception("Reconnect must preserve history and resume at the latest data");
        clear.Invoke(null,[page]);
        showProtocol.IsChecked=false;
        JsonObject traffic()=>new(){["epoch"]=epoch,["records"]=new JsonArray(
            new JsonObject{["kind"]="protocol_tx",["source"]="protocol",["hex"]="50524F544F"},
            new JsonObject{["kind"]="rx",["source"]="protocol",["hex"]="50524F544F"},
            new JsonObject{["kind"]="rx",["source"]="serial",["hex"]="55534552"})};
        receive.Invoke(window,[traffic()]);
        if(records.Count!=1)throw new Exception("Other-page TX and RX must both be suppressed when disabled");
        showProtocol.IsChecked=true;
        receive.Invoke(window,[traffic()]);
        if(records.Count!=4)throw new Exception("Other-page TX and RX must both be retained when enabled");
        showProtocol.IsChecked=false;
        if(new TextRange(log.Document.ContentStart,log.Document.ContentEnd).Text.Contains("PROTO"))
            throw new Exception("Disabling protocol display must hide existing protocol records");
        clear.Invoke(null,[page]);
        Console.WriteLine("PASS: monitor quotas, disconnect retention, paused scrolling, resume at bottom/reconnect and protocol TX/RX toggle.");
    }
}
