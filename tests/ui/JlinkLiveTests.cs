using System.Reflection;
using System.IO;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Frame.Client;
using Frame.Desktop;

// Explicit --jlink-live opt-in: reads the configured target; never writes RAM or firmware.
internal static class JlinkLiveTests
{
    public static async Task Run(string root)
    {
        var settings=DesktopSettings.Load(Path.Combine(root,"config/native-ui.json"));
        var saved=settings["fields"]?.AsObject()??throw new Exception("No saved diagnostic fields");
        await using var client=new BackendClient();var fields=new Dictionary<string,TextBox>();string feedback="";
        var page=new JlinkPage(client,fields,message=>feedback=message);
        foreach(var (name,field) in fields)if(saved["jlink."+name] is JsonValue value)field.Text=value.ToString();
        fields["search"].Text="section_shell_FAL_TEST";
        var host=new Window{Title="FRAME J-Link read-only verification",Content=page,Width=1350,Height=850};host.Show();host.UpdateLayout();
        try
        {
            await (Task)typeof(JlinkPage).GetMethod("LoadAsync",BindingFlags.NonPublic|BindingFlags.Instance)!.Invoke(page,null)!;
            var table=(DataGrid)typeof(JlinkPage).GetField("table",BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(page)!;
            async Task Expand(JlinkPage.Variable variable)
            {
                table.ScrollIntoView(variable);host.UpdateLayout();
                var row=(DataGridRow)table.ItemContainerGenerator.ContainerFromItem(variable);
                var button=DiagnosticPageTests.Visuals<Button>(row).Single(b=>Equals(b.Content,"▸"));
                button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                using var deadline=new CancellationTokenSource(TimeSpan.FromSeconds(15));
                var busy=typeof(DiagnosticPage).GetField("Busy",BindingFlags.NonPublic|BindingFlags.Instance)!;
                while((bool)busy.GetValue(page)!)await Task.Delay(20,deadline.Token);
                if(!variable.Expanded)throw new Exception(variable.Name+": "+variable.Status+" / "+feedback);
            }
            var node=table.Items.Cast<JlinkPage.Variable>().Single(r=>r.Name=="section_item_section_shell_FAL_TEST");
            await Expand(node);var next=node.Children.Single(r=>r.Expression=="p_next");await Expand(next);
            if(!next.Children.Any(r=>r.Expression=="p_next")||!next.Children.Any(r=>r.Expression=="p_obj"))throw new Exception("Missing actual target next-node members");
            var obj=node.Children.Single(r=>r.Expression=="p_obj");
            if(obj.Expanded||!obj.Status.Contains("shell_core_item")||!obj.Status.Contains("section_shell_FAL_TEST"))throw new Exception("Collapsed p_obj must already display its target type and symbol after reading");
            if(!next.Status.Contains("section_item_section_shell_"))throw new Exception("Typed p_next must identify its named target object, not just section_item");
            var nestedObj=next.Children.Single(r=>r.Expression=="p_obj");
            if(!nestedObj.Status.Contains("shell_core_item")||!nestedObj.Status.Contains("section_shell_"))throw new Exception("Nested collapsed pointer must resolve the next business object");
            await Expand(obj);
            if(obj.Data["resolved_symbol"]?.ToString()!="section_shell_FAL_TEST"||!obj.Children.Any(r=>r.Expression=="p_name_size"&&r.Status=="已读取"))throw new Exception("Actual void p_obj must resolve shell_core_item by address and read its members");
            await page.ExpandAsync(obj);
            host.UpdateLayout();var bitmap=new RenderTargetBitmap((int)host.ActualWidth,(int)host.ActualHeight,96,96,PixelFormats.Pbgra32);bitmap.Render(host);
            var encoder=new PngBitmapEncoder();encoder.Frames.Add(BitmapFrame.Create(bitmap));string path=Path.Combine(root,"build/ui-verification/jlink-live-next.png");Directory.CreateDirectory(Path.GetDirectoryName(path)!);using(var file=File.Create(path))encoder.Save(file);
            Console.WriteLine($"PASS: live J-Link arrow click with active search, p_obj={obj.Value} -> {obj.Data["resolved_symbol"]}, members={obj.Children.Count}, p_next={next.Value}; screenshot={path}");
        }
        finally{page.Shutdown();host.Close();}
    }
}
