using System.Collections;
using System.IO;
using System.Reflection;
using System.Text.Json.Nodes;
using System.Windows.Controls;
using Frame.Desktop;

internal static class ParameterAddressTests
{
    private static ParameterPanel Panel(MainWindow window)
    {
        var pages=(IDictionary)typeof(MainWindow).GetField("pages",BindingFlags.Instance|BindingFlags.NonPublic)!.GetValue(window)!;
        return (ParameterPanel)pages["param"]!.GetType().GetField("Parameters")!.GetValue(pages["param"])!;
    }
    private static void Enter(MainWindow window,string address)
    {
        ((ComboBox)window.FindName("Address")).Text=address;
        typeof(MainWindow).GetMethod("CommitAddress",BindingFlags.Instance|BindingFlags.NonPublic)!.Invoke(window,[address]);
    }
    private static void Select(MainWindow window,string address)=>((ComboBox)window.FindName("Address")).SelectedItem=address;
    public static void Run(string root)
    {
        string settingsPath=Path.Combine(root,"build","ui-param-address-"+Guid.NewGuid().ToString("N"),"native-ui.json");
        var window=new MainWindow(settingsPath);
        var panel=Panel(window);
        var addresses=(ComboBox)window.FindName("Address");
        if(!addresses.IsEditable||!addresses.Items.Cast<string>().SequenceEqual(["2"]))throw new Exception("Dropdown must initially contain only the previously used address");
        if(((DockPanel)panel.Content).Children.OfType<WrapPanel>().Single().Children.OfType<Button>().Any(button=>button.Content?.ToString()=="保存参数数据"))throw new Exception("Parameter data must save automatically without a manual save button");
        panel.Apply(JsonNode.Parse("""[{"name":"GAIN","type":5,"value":3,"raw":3,"min":0,"min_raw":0,"max":10,"max_raw":10}]""")!);
        ((ParameterRow)panel.Table.Items[0]).Data="7";
        if(!File.Exists(Path.Combine(Path.GetDirectoryName(settingsPath)!,"parameters","2.json")))throw new Exception("Refreshed parameter data must be saved automatically");
        Enter(window,"3");
        if(addresses.Text!="3"||addresses.SelectedItem?.ToString()!="3"||!addresses.Items.Cast<string>().SequenceEqual(["2","3"])||panel.Table.Items.Count!=0)throw new Exception("A new address must appear in history and start with an empty table");
        Select(window,"2");
        if(panel.Table.Items.Count!=1||((ParameterRow)panel.Table.Items[0]).Data!="7"||!((ParameterRow)panel.Table.Items[0]).Dirty)throw new Exception("Switching back must restore saved parameter edits");
        Select(window,"3");
        panel.Apply(JsonNode.Parse("""[{"name":"OTHER","type":5,"value":9,"raw":9,"min":0,"min_raw":0,"max":10,"max_raw":10}]""")!);
        Select(window,"2");
        Select(window,"3");
        if(((ParameterRow)panel.Table.Items[0]).Name!="OTHER")throw new Exception("Address snapshots must remain independent");
        Enter(window,"4");
        if(panel.Table.Items.Count!=0)throw new Exception("An address without saved data must remain blank");
        Enter(window,"256");
        if(addresses.Text!="4"||addresses.SelectedItem?.ToString()!="4"||addresses.Items.Count!=3)throw new Exception("Invalid address must leave the active selection and history unchanged");
        typeof(MainWindow).GetMethod("SaveSettings",BindingFlags.Instance|BindingFlags.NonPublic)!.Invoke(window,null);
        var reopened=new MainWindow(settingsPath);
        var addressSelector=(ComboBox)reopened.FindName("Address");
        if(addressSelector.SelectedItem?.ToString()!="4"||addressSelector.Text!="4"||!addressSelector.Items.Cast<string>().SequenceEqual(["2","3","4"])||Panel(reopened).Table.Items.Count!=0)throw new Exception("Only used addresses and the blank selected address must survive restart");
        addressSelector.SelectedItem="3";
        if(((ParameterRow)Panel(reopened).Table.Items[0]).Name!="OTHER")throw new Exception("Saved address parameters must survive restart");
        addressSelector.SelectedItem="2";
        if(addressSelector.Text!="2"||((ParameterRow)Panel(reopened).Table.Items[0]).Data!="7")throw new Exception("Dropdown selection must display the selected address and reload its saved values");
        Panel(reopened).Apply(JsonNode.Parse("""[{"name":"REFRESHED","type":5,"value":8,"raw":8,"min":0,"min_raw":0,"max":10,"max_raw":10}]""")!);
        Select(reopened,"3");addressSelector.SelectedItem="2";
        if(Panel(reopened).Table.Items.Count!=1||((ParameterRow)Panel(reopened).Table.Items[0]).Name!="REFRESHED")throw new Exception("A fresh parameter list must replace only the current address snapshot");
        reopened.Close();
        window.Close();
        var legacySettings=DesktopSettings.Load(settingsPath);legacySettings.Remove("address_history");DesktopSettings.Save(settingsPath,legacySettings);
        var migrated=new MainWindow(settingsPath);
        if(!((ComboBox)migrated.FindName("Address")).Items.Cast<string>().SequenceEqual(["2","3","4"]))throw new Exception("Existing saved parameter files must repopulate address history after upgrade");
        migrated.Close();
        Console.WriteLine("PASS: used-address dropdown, typed new address, blank new table, automatic local save, and restart restore.");
    }
}
