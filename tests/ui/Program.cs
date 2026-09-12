using System.Collections;
using System.IO;
using System.Reflection;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media.Imaging;
using System.Xml.Linq;
using Frame.Desktop;

internal static class UiTests
{
    [STAThread]
    public static int Main(string[] args)
    {
        string root=Path.GetFullPath(args.Length>0?args[0]:".");
        if(args.Contains("--wave-viewport")){new Application();WaveViewportTests.Run();return 0;}
        var gapRows=new[]{0d,0.01,0.02,2d,2.01}.Select(t=>new JsonObject{["time"]=t,["value"]=1d,["segment"]=0}).ToArray();
        if(!WavePlotPanel.CurvePoints(gapRows).Y.Any(double.IsNaN))throw new Exception("Long sampling gaps must break curves");
        gapRows[1]["segment"]=1;if(!WavePlotPanel.CurvePoints(gapRows.Take(2).ToArray()).Y.Any(double.IsNaN))throw new Exception("Restart boundary must break curve even with adjacent timestamps");
        if(WavePlotPanel.FormatTime(0,false)!="0"||WavePlotPanel.FormatTime(1.2345,false)!="1.2345"||WavePlotPanel.FormatTime(1704067200.125,true)!="08:00:00.125")throw new Exception("MCU Beijing time / PLECS simulation time formatting failed");
        string settingsPath=Path.Combine(root,"build/test-native-ui.json");
        DesktopSettings.Save(settingsPath,new(){["port"]="COM77",["host"]="192.168.1.20",["label"]="中文设备"});
        var settings=DesktopSettings.Load(settingsPath);
        if(settings["port"]?.ToString()!="COM77"||settings["label"]?.ToString()!="中文设备")throw new Exception("Settings UTF-8 round trip failed");
        var app=new Application();
        XNamespace presentation="http://schemas.microsoft.com/winfx/2006/xaml/presentation";
        var xaml=XDocument.Load(Path.Combine(root,"frontend/Frame.Desktop/App.xaml"));
        var resources=xaml.Root!.Element(presentation+"Application.Resources")!;
        var dictionary=new XElement(presentation+"ResourceDictionary",new XAttribute(XNamespace.Xmlns+"x","http://schemas.microsoft.com/winfx/2006/xaml"),resources.Elements());
        app.Resources=(ResourceDictionary)System.Windows.Markup.XamlReader.Parse(dictionary.ToString());
        var window=new MainWindow(settingsPath);
        window.Loaded+=async (_,_)=>
        {
            try
            {
                if(args.Contains("--jlink-live")){await JlinkLiveTests.Run(root);window.Close();return;}
                if(args.Contains("--plecs-live")){await PlecsWaveRefreshTests.Run(window,root,args[Array.IndexOf(args,"--plecs-live")+1]);window.Close();return;}
                await EthernetDiscoveryTests.RunAsync();
                await ParameterStreamingTests.Run();
                await ParameterTests.Run();
                await DiagnosticPageTests.Run();
                await SectionRefreshTests.Run();
                await JlinkSymbolTests.Run(root);
                if(((ComboBox)window.FindName("Port")).Text!="COM77"||((TextBox)window.FindName("TcpHost")).Text!="192.168.1.20")throw new Exception("Connection settings were not restored");
                var toggle=(Button)window.FindName("SidebarToggle");
                var sidebar=(ColumnDefinition)window.FindName("SidebarColumn");
                toggle.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                if(sidebar.Width.Value!=60||!window.SidebarCollapsed)throw new Exception("Sidebar icon rail collapse failed");
                toggle.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                if(sidebar.Width.Value!=185)throw new Exception("Sidebar restore failed");
                var connectionType=(ComboBox)window.FindName("ConnectionType");
                connectionType.SelectedIndex=1;
                if(((FrameworkElement)window.FindName("TcpSettings")).Visibility!=Visibility.Visible||((FrameworkElement)window.FindName("SerialSettings")).Visibility!=Visibility.Collapsed)throw new Exception("Ethernet settings selection failed");
                var connection=(JsonObject)typeof(MainWindow).GetMethod("ConnectionRequest",BindingFlags.Instance|BindingFlags.NonPublic)!.Invoke(window,null)!;
                if(connection["transport"]?.ToString()!="tcp"||connection["tcp_port"]?.GetValue<int>()!=9000)throw new Exception("UI TCP request mapping failed");
                connectionType.SelectedIndex=0;
                var serialPort=(ComboBox)window.FindName("Port");
                serialPort.ItemsSource=new[]{new SerialPortItem("COM6","USB-SERIAL CH340 (COM6)")};
                serialPort.SelectedIndex=0;
                window.UpdateLayout();
                connection=(JsonObject)typeof(MainWindow).GetMethod("ConnectionRequest",BindingFlags.Instance|BindingFlags.NonPublic)!.Invoke(window,null)!;
                if(!serialPort.Text.Contains("CH340")||connection["port"]?.ToString()!="COM6")throw new Exception("Friendly serial name must display without changing the COM endpoint");
                serialPort.Text="COM77";
                connection=(JsonObject)typeof(MainWindow).GetMethod("ConnectionRequest",BindingFlags.Instance|BindingFlags.NonPublic)!.Invoke(window,null)!;
                if(connection["port"]?.ToString()!="COM77")throw new Exception("Manual COM endpoint must remain editable");
                var updateConnection=typeof(MainWindow).GetMethod("UpdateConnectionDisplay",BindingFlags.Instance|BindingFlags.NonPublic)!;
                updateConnection.Invoke(window,[true,"COM6"]);
                if(!connectionType.IsEnabled||!serialPort.IsEnabled||serialPort.Visibility!=Visibility.Visible||!serialPort.ToolTip.ToString()!.Contains("COM6"))throw new Exception("Connected serial selector must remain editable and identify actual connection");
                updateConnection.Invoke(window,[false,""]);
                if(serialPort.Text!="COM77")throw new Exception("Connection status must not overwrite a pending serial selection");
                var baudSelector=(ComboBox)window.FindName("Baud");
                if(!baudSelector.Items.Contains("1000000")||!baudSelector.Items.Contains("自定义…"))throw new Exception("Baud presets/custom option missing");
                await ConnectionSwitchTests.RunAsync(window,root);
                await PageDockingTests.Run(window,args.Contains("--mouse"));
                var flags=BindingFlags.Instance|BindingFlags.NonPublic;
                var pages=(IDictionary)typeof(MainWindow).GetField("pages",flags)!.GetValue(window)!;
                var show=typeof(MainWindow).GetMethod("ShowData",flags)!;
                var nav=(ListBox)window.FindName("Navigation");
                Directory.CreateDirectory(Path.Combine(root,"build/ui-verification"));
                int index=0;
                foreach(DictionaryEntry entry in pages)
                {
                    string group=(string)entry.Key;nav.SelectedIndex=index++;
                    if(group=="param")connectionType.SelectedIndex=1;
                    string path=Path.Combine(root,"build/e507-"+group+".json");
                    if(File.Exists(path))
                    {
                        var data=JsonNode.Parse(await File.ReadAllTextAsync(path));
                        if(data is JsonObject envelope&&envelope["operation_id"]!=null)data=envelope["data"]?.DeepClone();
                        show.Invoke(window,[entry.Value,data]);
                    }
                    await Task.Delay(150);window.UpdateLayout();
                    if(group=="sfra"){
                        var sfraFields=(Dictionary<string,TextBox>)entry.Value!.GetType().GetProperty("Fields")!.GetValue(entry.Value)!;
                        if(new[]{"start_hz","stop_hz","amplitude","count"}.Any(key=>sfraFields[key].Text!=""||sfraFields[key].IsEnabled))throw new Exception("SFRA must not use host defaults before reading device configuration");
                        typeof(MainWindow).GetMethod("ApplySfraConfig",BindingFlags.NonPublic|BindingFlags.Static)!.Invoke(null,[entry.Value,new JsonObject{["start_hz"]=25d,["stop_hz"]=2500d,["amplitude"]=0.125d,["count"]=128,["table_length"]=7}]);
                        if(sfraFields["start_hz"].Text!="25"||sfraFields["stop_hz"].Text!="2500"||sfraFields["amplitude"].Text!="0.125")throw new Exception("SFRA configuration must display device values");
                        if(sfraFields["count"].Text!="128"||!sfraFields["count"].IsReadOnly||!sfraFields["count"].IsEnabled)throw new Exception("SFRA must show device sweep point count, not received table length or a writable host default");
                        var sfraView=(SfraPlotView)entry.Value!.GetType().GetField("SfraView")!.GetValue(entry.Value)!;
                        var sfraPlots=(ScottPlot.WPF.WpfPlot[])typeof(SfraPlotView).GetField("plots",BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(sfraView)!;
                        sfraView.Render(new JsonArray(new JsonObject{["frequency"]=10d,["db"]=0d,["phase"]=-20d},new JsonObject{["frequency"]=100d,["db"]=-6d,["phase"]=-80d}),true);
                        sfraView.ShowCursor(1.8);window.UpdateLayout();await Task.Delay(100);
                        if(Math.Abs(sfraPlots[0].ActualHeight-sfraPlots[1].ActualHeight)>1)throw new Exception("SFRA magnitude and phase plots must have equal heights");
                        if(sfraPlots.Any(chart=>chart.Plot.GetPlottables<ScottPlot.Plottables.VerticalLine>().Single().X!=2||chart.Plot.GetPlottables<ScottPlot.Plottables.Marker>().Count()!=1))throw new Exception("SFRA cursor must share a real frequency point with labels and markers");
                    }
                    if(group=="scope"){
                        var scopePage=entry.Value!;
                        var scopeBody=(Grid)scopePage.GetType().GetProperty("Body")!.GetValue(scopePage)!;
                        if(scopeBody.Children.Count!=1||scopeBody.Children[0] is not ScopePlotView)throw new Exception("Scope plot body must not contain live waveform toolbar");
                        if(((FrameworkElement)window.FindName("PageHeading")).Visibility!=Visibility.Collapsed||((DataGrid)scopePage.GetType().GetProperty("Table")!.GetValue(scopePage)!).Parent!=null)throw new Exception("Scope heading and lower table must be removed");
                        var applyObjects=typeof(MainWindow).GetMethod("ApplyScopeObjects",BindingFlags.NonPublic|BindingFlags.Static)!;
                        var objects=new JsonArray(new JsonObject{["id"]=3,["name"]="scope_A"},new JsonObject{["id"]=7,["name"]="scope_B"});
                        applyObjects.Invoke(null,[scopePage,objects]);
                        var choice=(ComboBox)scopePage.GetType().GetField("ScopeObjects")!.GetValue(scopePage)!;choice.SelectedIndex=1;
                        var scopeFields=(Dictionary<string,TextBox>)scopePage.GetType().GetProperty("Fields")!.GetValue(scopePage)!;
                        if(scopeFields["id"].Text!="7")throw new Exception("Scope commands must use selected object's actual ID");
                        applyObjects.Invoke(null,[scopePage,objects]);if((int)choice.SelectedValue!=7)throw new Exception("Object refresh should retain selection");
                        applyObjects.Invoke(null,[scopePage,new JsonArray()]);if(choice.SelectedItem!=null)throw new Exception("Empty directory must clear obsolete object selection");
                        applyObjects.Invoke(null,[scopePage,objects]);window.UpdateLayout();
                        var captures=(IList)scopePage.GetType().GetField("ScopeCaptures")!.GetValue(scopePage)!;
                        var captureType=typeof(MainWindow).GetNestedType("ScopeCapture",BindingFlags.NonPublic)!;
                        foreach(var fixture in new[]{(3,101UL,1d),(7,102UL,2d),(3,103UL,3d)}){
                            var capturedRows=new JsonArray(new JsonObject{["time"]=0d,["values"]=new JsonArray(JsonValue.Create(fixture.Item3))});
                            captures.Add(Activator.CreateInstance(captureType,fixture.Item1,fixture.Item2,capturedRows,"缓存 "+fixture.Item2)!);
                        }
                        choice.SelectedIndex=0;typeof(MainWindow).GetMethod("RefreshScopeHistory",BindingFlags.NonPublic|BindingFlags.Static)!.Invoke(null,[scopePage]);
                        var history=(ComboBox)scopePage.GetType().GetField("ScopeHistory")!.GetValue(scopePage)!;
                        if(history.Items.Count!=2||(ulong)scopePage.GetType().GetField("Dataset")!.GetValue(scopePage)!=103UL)throw new Exception("Scope must retain multiple captures per object");
                        history.SelectedIndex=0;choice.SelectedIndex=1;
                        if(history.Items.Count!=1||(ulong)scopePage.GetType().GetField("Dataset")!.GetValue(scopePage)!=102UL)throw new Exception("Scope object switch must restore its own dataset");
                        choice.SelectedIndex=0;history.SelectedIndex=0;
                        if((ulong)scopePage.GetType().GetField("Dataset")!.GetValue(scopePage)!=101UL)throw new Exception("Older recording must remain selectable after object switch");
                        var scopeView=(ScopePlotView)scopePage.GetType().GetField("ScopeView")!.GetValue(scopePage)!;
                        scopeView.SetChannels(3,new JsonArray(new JsonObject{["index"]=0,["name"]="Voltage"}));
                        var scopeLegend=(WrapPanel)typeof(ScopePlotView).GetField("legend",BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(scopeView)!;
                        var channelButton=(Button)scopeLegend.Children[0];if(!channelButton.Content.ToString()!.Contains("Voltage"))throw new Exception("Scope legend must use channel variable names");
                        channelButton.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                        if(((Button)scopeLegend.Children[0]).Foreground!=System.Windows.Media.Brushes.Gray)throw new Exception("Hidden channel legend must turn gray");
                        ((Button)scopeLegend.Children[0]).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));scopeView.ShowCursor(0);
                        var scopeChart=(ScottPlot.WPF.WpfPlot)scopePage.GetType().GetField("Plot")!.GetValue(scopePage)!;
                        if(scopeChart.Plot.GetPlottables<ScottPlot.Plottables.HorizontalLine>().Any()||scopeChart.Plot.GetPlottables<ScottPlot.Plottables.VerticalLine>().Count()!=1)throw new Exception("Scope cursor must be vertical only");
                        var scopeValues=(TextBlock)typeof(ScopePlotView).GetField("values",BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(scopeView)!;
                        if(!scopeValues.Text.Contains("Voltage = 1"))throw new Exception("Scope cursor must display named sample values");
                        scopeView.TriggerMetadata=new JsonObject{["trigger_display_index"]=1d,["period_us"]=1000000d,["count"]=3d};
                        scopeView.Render(new JsonArray(new JsonObject{["time"]=0d,["values"]=new JsonArray(JsonValue.Create(1d))},new JsonObject{["time"]=1d,["values"]=new JsonArray(JsonValue.Create(2d))},new JsonObject{["time"]=2d,["values"]=new JsonArray(JsonValue.Create(3d))}),3,true);
                        scopeView.ShowCursor(0.7);
                        if(scopeChart.Plot.GetPlottables<ScottPlot.Plottables.VerticalLine>().Count()!=2||scopeChart.Plot.GetPlottables<ScottPlot.Plottables.VerticalLine>().Any(line=>line.X!=1))throw new Exception("Cursor must snap to actual sample and trigger must use display index");
                        if(scopeChart.Plot.GetPlottables<ScottPlot.Plottables.Marker>().Count()!=1||scopeChart.Plot.GetPlottables<ScottPlot.Plottables.Text>().Count()!=1||scopeValues.Parent!=null)throw new Exception("Sample marker and value label must be inside plot only");
                        scopeView.ShowCursor(1.8);if(scopeChart.Plot.GetPlottables<ScottPlot.Plottables.Marker>().Count()!=1)throw new Exception("Moving cursor must replace highlighted point");
                        window.UpdateLayout();
                    }
                    if(entry.Value!.GetType().GetField("Diagnostic")!.GetValue(entry.Value) is DiagnosticPage diagnostic)DiagnosticPageTests.Populate(diagnostic);
                    if(group=="wave"){
                        if(((FrameworkElement)window.FindName("PageHeading")).Visibility!=System.Windows.Visibility.Collapsed)throw new Exception("Wave heading must not reserve vertical space");
                        var wavePlots=(WavePlotPanel)entry.Value!.GetType().GetField("WavePlots")!.GetValue(entry.Value)!;
                        var table=(DataGrid)entry.Value.GetType().GetProperty("Table")!.GetValue(entry.Value)!;
                        if(table.Parent!=null)throw new Exception("Raw waveform table must be removed from layout");
                        foreach(string flag in new[]{"Pause","Follow"})if(((CheckBox)entry.Value.GetType().GetProperty(flag)!.GetValue(entry.Value)!).Parent!=null)throw new Exception("Wave pause/follow controls must not appear in toolbar");
                        int first=wavePlots.PlotIds[0],second=wavePlots.AddPlot();
                        wavePlots.Assign("TEST_SERIES",second);
                        if(wavePlots.PlotIds.Count!=2||wavePlots.PlotFor("TEST_SERIES")!=second)throw new Exception("Wave pane assignment failed");
                        wavePlots.RemovePlot(second);
                        if(wavePlots.PlotIds.Count!=1||wavePlots.PlotFor("TEST_SERIES")!=first)throw new Exception("Closing wave pane must preserve parameter assignment");
                        wavePlots.RemovePlot(first);if(wavePlots.PlotIds.Count!=1)throw new Exception("Final waveform pane must remain usable");
                        int other=wavePlots.AddPlot();wavePlots.Assign("LAYOUT_B",other);
                        var selection=(WaveSeriesPanel)entry.Value.GetType().GetField("Series")!.GetValue(entry.Value)!;
                        selection.SetSelectedParameters(new[]{"LAYOUT_A","LAYOUT_B"});
                        selection.Select("LAYOUT_A");
                        var valueTest=new WaveSeriesPanel();valueTest.SetSelectedParameters(new[]{"A"});
                        var valueRows=new JsonArray(new JsonObject{["name"]="A",["time"]=1d,["value"]=10d},new JsonObject{["name"]="A",["time"]=2d,["value"]=20d});
                        var valueLatest=new JsonArray(new JsonObject{["name"]="A",["time"]=100d,["value"]=99d});
                        valueTest.Update(valueRows,valueLatest);valueTest.SetHoverTime(1.2);
                        var valueEntries=(IDictionary)typeof(WaveSeriesPanel).GetField("series",BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(valueTest)!;
                        var valueLabel=(TextBlock)((System.Runtime.CompilerServices.ITuple)valueEntries["A"]!)[1]!;
                        if(valueLabel.Text!="10.0")throw new Exception("Cursor must select nearest sample value");
                        valueTest.Update(valueRows,valueLatest);if(valueLabel.Text!="10.0")throw new Exception("Incoming refresh must preserve cursor values");
                        valueTest.SetHoverTime(null);if(valueLabel.Text!="99.0")throw new Exception("Mouse leave must restore latest dataset values, not historical viewport values");
                        selection.SetSeriesVisible("LAYOUT_B",false);wavePlots.Assign("LAYOUT_B",other);
                        if(!selection.IsSeriesVisible("LAYOUT_B")||wavePlots.PlotFor("LAYOUT_B")!=other)throw new Exception("Dropping hidden series must select and display it in target pane");
                        var preview=new JsonArray();for(int sample=0;sample<100;sample++){preview.Add(new JsonObject{["name"]="LAYOUT_A",["time"]=sample*0.1,["value"]=Math.Sin(sample*0.1)});preview.Add(new JsonObject{["name"]="LAYOUT_B",["time"]=sample*0.1,["value"]=100*Math.Cos(sample*0.1)});}
                        show.Invoke(window,[entry.Value,new JsonObject{["records"]=preview}]);
                        window.UpdateLayout();
                        var panes=(IEnumerable)typeof(WavePlotPanel).GetField("panes",BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(wavePlots)!;
                        var charts=panes.Cast<object>().Select(pane=>(ScottPlot.WPF.WpfPlot)pane.GetType().GetProperty("Plot")!.GetValue(pane)!).ToArray();
                        var legendPanel=(StackPanel)panes.Cast<object>().First().GetType().GetProperty("Legend")!.GetValue(panes.Cast<object>().First())!;
                        var legendItem=legendPanel.Children[0];show.Invoke(window,[entry.Value,new JsonObject{["records"]=preview.DeepClone()}]);
                        if(!ReferenceEquals(legendItem,legendPanel.Children[0]))throw new Exception("Sampling refresh must reuse existing legend elements");
                        charts[0].Plot.Axes.SetLimitsX(2,5);
                        typeof(WavePlotPanel).GetMethod("SynchronizeTime",BindingFlags.NonPublic|BindingFlags.Instance)!.Invoke(wavePlots,[charts[0]]);
                        if(charts.Any(chart=>chart.Plot.Axes.GetLimits().Left!=2||chart.Plot.Axes.GetLimits().Right!=5))throw new Exception("Wave time axes must synchronize without acquisition polling");
                        var leftPixels=charts.Select(chart=>chart.Plot.GetPixel(new ScottPlot.Coordinates(2,0)).X).ToArray();
                        if(leftPixels.Max()-leftPixels.Min()>1)throw new Exception("Wave data rectangles must align despite different Y labels");
                        show.Invoke(window,[entry.Value,new JsonObject{["records"]=preview.DeepClone()}]);
                        var cursorMethod=typeof(WavePlotPanel).GetMethod("UpdateCursor",BindingFlags.NonPublic|BindingFlags.Instance)!;
                        cursorMethod.Invoke(wavePlots,[charts[0],new ScottPlot.Coordinates(3,0.25)]);
                        cursorMethod.Invoke(wavePlots,[charts[1],new ScottPlot.Coordinates(4,20)]);
                        if(charts.Any(chart=>chart.Plot.GetPlottables<ScottPlot.Plottables.VerticalLine>().Single().X!=4||chart.Plot.GetPlottables<ScottPlot.Plottables.VerticalLine>().Single().LineWidth>1||chart.Plot.GetPlottables<ScottPlot.Plottables.HorizontalLine>().Any()))throw new Exception("Wave hover cursor must be a thin synchronized vertical line only");
                        show.Invoke(window,[entry.Value,new JsonObject{["records"]=preview.DeepClone()}]);
                        if(charts.Any(chart=>chart.Plot.GetPlottables<ScottPlot.Plottables.VerticalLine>().Count()!=1))throw new Exception("Rendering must preserve shared cursors without duplicates");
                        string measurementText="";wavePlots.MeasurementChanged+=text=>measurementText=text;
                        var measurementBody=(Grid)entry.Value.GetType().GetProperty("Body")!.GetValue(entry.Value)!;
                        var measurementButton=measurementBody.Children.OfType<WrapPanel>().SelectMany(bar=>bar.Children.OfType<Button>()).Single(button=>button.Content?.ToString()=="测量时间差");
                        measurementButton.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                        cursorMethod.Invoke(wavePlots,[charts[0],new ScottPlot.Coordinates(4,0.25)]);
                        if(charts.Any(chart=>chart.Plot.GetPlottables<ScottPlot.Plottables.VerticalLine>().Single().X!=4))throw new Exception("Measurement must show a moving vertical guide before the first click");
                        wavePlots.PlaceTimeMarker(charts[0],new ScottPlot.Coordinates(4,0.25));
                        if(charts.Any(chart=>chart.Plot.GetPlottables<ScottPlot.Plottables.VerticalLine>().Single().X!=4))throw new Exception("First measurement click must align across panes");
                        if(!charts[0].Plot.GetPlottables<ScottPlot.Plottables.Text>().Single().LabelText.Contains("T1 = 4 s"))throw new Exception("First marker must show its simulation time");
                        cursorMethod.Invoke(wavePlots,[charts[1],new ScottPlot.Coordinates(3.75,20)]);
                        if(charts.Any(chart=>chart.Plot.GetPlottables<ScottPlot.Plottables.VerticalLine>().Count()!=2))throw new Exception("Second point selection must show the fixed first line and moving guide");
                        wavePlots.PlaceTimeMarker(charts[1],new ScottPlot.Coordinates(3.75,20));
                        if(measurementText!="Δt = 250 ms"||charts[0].Plot.GetPlottables<ScottPlot.Plottables.Text>().Single().Location.X!=4||charts[1].Plot.GetPlottables<ScottPlot.Plottables.Text>().Single().Location.X!=3.75)throw new Exception("First time and delta time must stay beside their own markers");
                        show.Invoke(window,[entry.Value,new JsonObject{["records"]=preview.DeepClone()}]);
                        cursorMethod.Invoke(wavePlots,[charts[0],new ScottPlot.Coordinates(5,0)]);
                        if(charts.Any(chart=>chart.Plot.GetPlottables<ScottPlot.Plottables.VerticalLine>().Count()!=2)||charts[1].Plot.GetPlottables<ScottPlot.Plottables.Text>().Count()!=1)throw new Exception("Data refresh and hover must preserve exactly two measurement lines");
                        if(WavePlotPanel.FormatInterval(0)!="Δt = 0 s"||WavePlotPanel.FormatInterval(0.000025)!="Δt = 25 μs"||WavePlotPanel.FormatInterval(2)!="Δt = 2 s")throw new Exception("Time measurement unit formatting failed");
                        measurementButton.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                        wavePlots.PlaceTimeMarker(charts[0],new ScottPlot.Coordinates(2,0));
                        var clearMeasurementButton=measurementBody.Children.OfType<WrapPanel>().SelectMany(bar=>bar.Children.OfType<Button>()).Single(button=>System.Windows.Automation.AutomationProperties.GetAutomationId(button)=="wave_clear_measurement");
                        clearMeasurementButton.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                        if(charts.Any(chart=>chart.Plot.GetPlottables<ScottPlot.Plottables.VerticalLine>().Any()||chart.Plot.GetPlottables<ScottPlot.Plottables.Text>().Any()))throw new Exception("Restart/cancel measurement must remove previous markers");
                        window.UpdateLayout();await Task.Delay(100);
                        wavePlots.ResetView();var initial=wavePlots.PrepareView(100,30);var filling=wavePlots.PrepareView(105,30);
                        if(initial!=filling||initial.Right!=106)throw new Exception("Live samples must fill the existing window without scrolling");
                        var advanced=wavePlots.PrepareView(131,30);
                        if(advanced.Right<=131||Math.Abs(advanced.Right-advanced.Left-30)>0.001)throw new Exception("Boundary crossing must scroll with headroom and preserve span");
                        var nextScroll=wavePlots.PrepareView(132,30);
                        if(Math.Abs(nextScroll.Right-advanced.Right-1)>0.001||Math.Abs(nextScroll.Right-132-6)>0.001)throw new Exception("Scrolling must advance continuously with stable headroom");
                        var zoom=typeof(WavePlotPanel).GetMethod("Zoom",BindingFlags.NonPublic|BindingFlags.Instance)!;
                        var beforeZoom=charts[0].Plot.Axes.GetLimits();zoom.Invoke(wavePlots,[charts[0],new ScottPlot.Coordinates(120,0),120,false,true]);
                        var afterZoom=charts[0].Plot.Axes.GetLimits();if(afterZoom.Left!=beforeZoom.Left||afterZoom.Right!=beforeZoom.Right||afterZoom.Top==beforeZoom.Top)throw new Exception("Ctrl wheel must change Y only");
                        zoom.Invoke(wavePlots,[charts[0],new ScottPlot.Coordinates(120,0),120,true,false]);
                        if(charts[0].Plot.Axes.GetLimits().Top!=afterZoom.Top||charts[1].Plot.Axes.GetLimits().Left!=charts[0].Plot.Axes.GetLimits().Left)throw new Exception("Shift wheel must change shared X only");
                        charts[0].Plot.Axes.SetLimitsX(10,20);typeof(WavePlotPanel).GetMethod("RememberView",BindingFlags.NonPublic|BindingFlags.Instance)!.Invoke(wavePlots,[charts[0]]);
                        if(wavePlots.PrepareView(140,30)!=(10d,20d))throw new Exception("History viewport must survive incoming samples");
                        var latestButton=((Grid)entry.Value.GetType().GetProperty("Body")!.GetValue(entry.Value)!).Children.OfType<WrapPanel>().SelectMany(bar=>bar.Children.OfType<Button>()).Single(button=>System.Windows.Automation.AutomationProperties.GetAutomationId(button)=="wave_latest");
                        var latestY=charts[0].Plot.Axes.GetLimits();
                        latestButton.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                        var latestRange=wavePlots.PrepareView(1000,30);
                        if(Math.Abs(latestRange.Right-latestRange.Left-10)>0.001||latestRange.Left>=1000||latestRange.Right<=1000)throw new Exception("Latest button must leave history and preserve zoomed time span");
                        if(charts[0].Plot.Axes.GetLimits().Bottom!=latestY.Bottom||charts[0].Plot.Axes.GetLimits().Top!=latestY.Top)throw new Exception("Latest button must preserve Y zoom");
                        if(wavePlots.PrepareView(1001,30).Right<=latestRange.Right)throw new Exception("Latest button must resume continuous following");
                        wavePlots.ResetView();show.Invoke(window,[entry.Value,new JsonObject{["records"]=preview.DeepClone()}]);window.UpdateLayout();await Task.Delay(100);
                        var currentChart=(ScottPlot.WPF.WpfPlot)entry.Value.GetType().GetField("Plot")!.GetValue(entry.Value)!;
                        var beforeFit=currentChart.Plot.Axes.GetLimits();currentChart.Plot.Axes.SetLimitsY(-10000,10000);wavePlots.FitY();
                        var afterFit=currentChart.Plot.Axes.GetLimits();
                        if(afterFit.Left!=beforeFit.Left||afterFit.Right!=beforeFit.Right||afterFit.Top>=10000)throw new Exception("Fit Y must preserve time viewport and fit signal values");
                    }
                    var content=(FrameworkElement)window.Content;
                    window.UpdateLayout();await window.Dispatcher.InvokeAsync(()=>{},System.Windows.Threading.DispatcherPriority.Render);
                    if(content is Panel panel)panel.Background=window.Background;
                    var image=new RenderTargetBitmap((int)content.ActualWidth,(int)content.ActualHeight,96,96,System.Windows.Media.PixelFormats.Pbgra32);
                    image.Render(content);
                    var png=new PngBitmapEncoder();png.Frames.Add(BitmapFrame.Create(image));
                    using(var output=File.Create(Path.Combine(root,"build/ui-verification/"+group+".png")))png.Save(output);
                    if(group=="param")connectionType.SelectedIndex=0;
                    if(window.ActualWidth<1000||window.ActualHeight<600)throw new Exception("Unexpected layout dimensions");
                }
                if(index!=9)throw new Exception("Nine pages required");
                var client=(Frame.Client.BackendClient)typeof(MainWindow).GetField("client",flags)!.GetValue(window)!;
                var serialPage=pages["serial"]!;var serialType=serialPage.GetType();
                var serialFields=(Dictionary<string,TextBox>)serialType.GetProperty("Fields")!.GetValue(serialPage)!;
                serialFields["text"].Text=" 你好 ";serialFields["hex"].Text="FF";serialFields["duration"].Text="0.1";
                ((CheckBox)serialType.GetProperty("SendText")!.GetValue(serialPage)!).IsChecked=true;
                ((CheckBox)serialType.GetProperty("SendNewline")!.GetValue(serialPage)!).IsChecked=true;
                ((CheckBox)serialType.GetProperty("ReceiveText")!.GetValue(serialPage)!).IsChecked=true;
                string serialReplay=Path.Combine(root,"build/serial-text-replay.json");
                File.WriteAllText(serialReplay,new JsonArray(new JsonObject{["tx"]=Convert.ToHexString(System.Text.Encoding.UTF8.GetBytes(" 你好 \r\n")),["rx"]=new JsonArray("E4BD","A0E5A5BD")}).ToJsonString());
                await client.ExecuteAsync(new(){["group"]="connect",["replay"]=serialReplay});
                nav.SelectedIndex=0;
                var runSerial=typeof(MainWindow).GetMethod("RunPageAsync",flags)!;
                await (Task)runSerial.Invoke(window,[serialPage,"send"])!;await Task.Delay(600);
                var receiveLog=(TextBox)serialType.GetProperty("ReceiveLog")!.GetValue(serialPage)!;
                if(receiveLog.Text!="你好")throw new Exception("Serial text send/CRLF/fragmented UTF-8 receive failed: "+receiveLog.Text);
                await (Task)runSerial.Invoke(window,[serialPage,"clear-view"])!;
                if(receiveLog.Text!=""||!client.Snapshot()["datasets"]!.AsArray().Any(d=>d!["group"]?.ToString()=="serial"&&d["count"]!.GetValue<int>()==2))throw new Exception("Clearing serial display must retain exportable data");
                var replay=Path.Combine(root,"tests/fixtures/wave-periodic.json");
                var connected=await client.ExecuteAsync(new(){["group"]="connect",["replay"]=replay});
                if(!connected["ok"]!.GetValue<bool>())throw new Exception("WPF client replay connection failed");
                var wave=pages["wave"]!;
                var fields=(Dictionary<string,TextBox>)wave.GetType().GetProperty("Fields")!.GetValue(wave)!;
                var run=typeof(MainWindow).GetMethod("RunPageAsync",flags)!;
                if(fields.ContainsKey("duration"))throw new Exception("Wave UI must not expose a capture duration");
                fields["window"].Text="0.1";
                nav.SelectedIndex=2;
                var pause=(CheckBox)wave.GetType().GetProperty("Pause")!.GetValue(wave)!;
                var previousRecords=wave.GetType().GetProperty("Records")!.GetValue(wave);
                var captureButton=(Button)wave.GetType().GetField("CaptureButton")!.GetValue(wave)!;
                captureButton.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                if(captureButton.Content?.ToString()!="停止")throw new Exception("Combined button must switch to stop after capture submission");
                pause.IsChecked=true;
                await Task.Delay(500);
                if(!ReferenceEquals(previousRecords,wave.GetType().GetProperty("Records")!.GetValue(wave)))throw new Exception("Paused view must retain displayed records");
                if(!client.Snapshot()["datasets"]!.AsArray().Any(d=>d!["count"]!.GetValue<int>()>0))throw new Exception("Pausing display must not stop backend ingestion");
                pause.IsChecked=false;
                await Task.Delay(400);
                if(ReferenceEquals(previousRecords,wave.GetType().GetProperty("Records")!.GetValue(wave)))throw new Exception("Resume must display newly acquired records");
                var series=(WaveSeriesPanel)wave.GetType().GetField("Series")!.GetValue(wave)!;
                var records=(JsonArray)wave.GetType().GetProperty("Records")!.GetValue(wave)!;
                var times=records.Select(r=>r!["time"]!.GetValue<double>()).ToArray();
                if(times.Max()-times.Min()>0.101)throw new Exception("Wave viewport must represent seconds rather than last 10000 records");
                string seriesName=records[0]!["name"]!.ToString();int recordCount=records.Count;
                series.SetSeriesVisible(seriesName,false);
                if(series.IsSeriesVisible(seriesName)||records.Count!=recordCount)throw new Exception("Hiding a curve must preserve acquired records");
                series.SetSeriesVisible(seriesName,true);
                nav.SelectedIndex=4;
                await Task.Delay(800);
                var datasets=client.Snapshot()["datasets"]!.AsArray();
                if(!datasets.Any(d=>d!["count"]!.GetValue<int>()>0&&d["state"]?.ToString()=="running"))throw new Exception("Display window must not stop continuous acquisition or page navigation");
                await PageDockingTests.VerifyLiveWave(window,wave);
                var waveButtons=((Grid)wave.GetType().GetProperty("Body")!.GetValue(wave)!).Children.OfType<WrapPanel>().SelectMany(bar=>bar.Children.OfType<Button>()).ToArray();
                if(waveButtons.Any(b=>b.Content?.ToString()=="全图")||fields["window"].Parent!=null)throw new Exception("Wave toolbar must omit full plot and window controls");
                waveButtons.Single(b=>b.Content?.ToString()=="最新数据").RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                await Task.Delay(400);
                var afterFull=wave.GetType().GetProperty("Records")!.GetValue(wave);
                await Task.Delay(400);
                if(pause.IsChecked==true||ReferenceEquals(afterFull,wave.GetType().GetProperty("Records")!.GetValue(wave)))throw new Exception("Latest-data action must continue refreshing instead of entering a hidden pause state");
                captureButton.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                for(int attempt=0;attempt<20&&captureButton.Content?.ToString()!="开始";attempt++)await Task.Delay(100);
                if(captureButton.Content?.ToString()!="开始"||!captureButton.IsEnabled)throw new Exception("Combined button must return to start after stop completion");
                var waveBody=(Grid)wave.GetType().GetProperty("Body")!.GetValue(wave)!;
                var clearWave=waveBody.Children.OfType<WrapPanel>().SelectMany(bar=>bar.Children.OfType<Button>()).Single(button=>button.Content?.ToString()=="清除波形");
                var visibleBeforeClear=series.VisibleNames.ToArray();
                clearWave.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                for(int attempt=0;attempt<20&&!clearWave.IsEnabled;attempt++)await Task.Delay(50);
                if(((JsonArray)wave.GetType().GetProperty("Records")!.GetValue(wave)!).Count!=0||!visibleBeforeClear.SequenceEqual(series.VisibleNames))throw new Exception("Clear button must empty the plot and preserve curve selection");
                ulong waveDataset=(ulong)wave.GetType().GetField("Dataset")!.GetValue(wave)!;
                var clearedWave=await client.ExecuteAsync(new(){["group"]="data",["action"]="read",["dataset"]=waveDataset});
                if(clearedWave["data"]!["total"]!.GetValue<int>()!=0)throw new Exception("Clear button must clear exportable backend history");
                await client.ExecuteAsync(new(){["group"]="connect",["replay"]=replay});
                fields["output"].Text=Path.Combine(root,"build/ui-close-wave.json");
                await (Task)run.Invoke(window,[wave,"capture"])!;
                await Task.Delay(100);
                Console.WriteLine("PASS: nine WPF pages rendered; shared Client acquisition survives navigation. Mouse/keyboard acceptance remains separate.");
                var closingFloat=(Window)typeof(MainWindow).GetMethod("DetachPage",flags)!.Invoke(window,["perf",window.PointToScreen(new Point(300,180))])!;
                window.Closed+=(_,_)=>{if(closingFloat.IsVisible)throw new Exception("Main window shutdown must close detached pages");};
                window.Close();
            }
            catch(Exception e){Console.Error.WriteLine(e);app.Shutdown(1);}
        };
        int code=app.Run(window);
        if(code==0&&!args.Contains("--plecs-live"))
        {
            var closed=JsonNode.Parse(File.ReadAllText(Path.Combine(root,"build/ui-close-wave.json")))!;
            if(closed["stop_confirmed"]?.GetValue<bool>()!=true||closed["state"]?.GetValue<string>()!="cancelled")return 1;
            if(closed["generation"]?.GetValue<int>()<2||closed["records"]!.AsArray().Select(r=>r!["segment"]!.GetValue<int>()).Distinct().Count()!=1)throw new Exception("New PLECS connection must export only the current simulation after clear");
            Console.WriteLine("PASS: WPF close cancels active acquisition, confirms device stop and flushes partial export.");
        }
        return code;
    }
}
