using System.Globalization;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Media;
using Frame.Client;
using Microsoft.Win32;

namespace Frame.Desktop;

// Presentation only: all target access and symbol interpretation use Frame.Client.
public abstract class DiagnosticPage : UserControl
{
    protected readonly BackendClient Client;
    protected readonly Dictionary<string, TextBox> Fields;
    protected readonly Action<string> Feedback;
    protected bool Busy, Closed;
    protected readonly TextBlock State = Label("就绪");
    protected DiagnosticPage(BackendClient client, Dictionary<string,TextBox> fields, Action<string> feedback)
    { Client=client;Fields=fields;Feedback=feedback; }
    public virtual Task TickAsync(JsonObject snapshot) => Task.CompletedTask;
    public virtual IEnumerable<BackendJob> ActiveJobs => Array.Empty<BackendJob>();
    public virtual void Shutdown() => Closed=true;
    public virtual void Apply(JsonNode? data) { }
    protected async Task<JsonNode?> Command(string group,string action,JsonObject? arguments=null,IProgress<JsonObject>? progress=null)
    {
        if(Closed)throw new OperationCanceledException();
        var request=arguments??new JsonObject();request["group"]=group;request["action"]=action;
        if(!request.ContainsKey("timeout"))request["timeout"]=10000;
        var result=await Client.ExecuteAsync(request,progress:progress);
        if(result["ok"]?.GetValue<bool>()!=true)throw new InvalidOperationException(result["error"]?.ToString()??"操作失败");
        return result["data"];
    }
    protected async Task Run(Func<Task> action)
    {
        if(Busy||Closed)return;Busy=true;
        try{await action();}catch(Exception error){Status(error.Message);}finally{Busy=false;}
    }
    protected void Status(string text){if(Closed)return;State.Text=text;Feedback(text);}
    protected static TextBlock Label(string text)=>new(){Text=text,VerticalAlignment=VerticalAlignment.Center,TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,0,8,8)};
    protected TextBox Input(string key,string value="",double width=150)
    {
        var input=new TextBox{Text=value,Width=width};Fields[key]=input;return input;
    }
    protected static Button Button(string text,Func<Task> action)
    {
        var button=new Button{Content=text,MinHeight=32};button.Click+=async(_,_)=>await action();return button;
    }
    protected Button ActionButton(string text,Func<Task> action)=>Button(text,()=>Run(action));
    protected static StackPanel Vertical(params UIElement[] elements){var panel=new StackPanel();foreach(var element in elements)panel.Children.Add(element);return panel;}
    protected static WrapPanel Toolbar(params UIElement[] elements){var panel=new WrapPanel();foreach(var element in elements)panel.Children.Add(element);return panel;}
    protected static Grid Split(UIElement left,UIElement right,double width=280)
    {
        var grid=new Grid();grid.ColumnDefinitions.Add(new(){Width=width>500?new GridLength(3,GridUnitType.Star):new GridLength(width),MinWidth=200});grid.ColumnDefinitions.Add(new(){Width=new GridLength(8)});grid.ColumnDefinitions.Add(new(){Width=new GridLength(width>500?2:1,GridUnitType.Star),MinWidth=220});
        grid.Children.Add(left);var splitter=new GridSplitter{Width=6,HorizontalAlignment=HorizontalAlignment.Center,VerticalAlignment=VerticalAlignment.Stretch};System.Windows.Controls.Grid.SetColumn(splitter,1);grid.Children.Add(splitter);System.Windows.Controls.Grid.SetColumn(right,2);grid.Children.Add(right);return grid;
    }
    protected static DockPanel Above(UIElement top,UIElement content)
    {var panel=new DockPanel();DockPanel.SetDock(top,Dock.Top);panel.Children.Add(top);panel.Children.Add(content);return panel;}
    protected static Border Card(string title,UIElement content)=>new(){Background=Brushes.White,BorderBrush=Brushes.LightSteelBlue,BorderThickness=new Thickness(1),Padding=new Thickness(12),Margin=new Thickness(0,0,8,8),Child=Vertical(Label(title),content)};
    protected static DataGrid Grid(params (string Header,string Property,double Width)[] columns)
    {
        var grid=new DataGrid{AutoGenerateColumns=false,IsReadOnly=true,SelectionUnit=DataGridSelectionUnit.CellOrRowHeader,ClipboardCopyMode=DataGridClipboardCopyMode.ExcludeHeader};
        foreach(var (header,property,width) in columns){
            var textStyle=new Style(typeof(TextBlock));textStyle.Setters.Add(new Setter(TextBlock.TextTrimmingProperty,TextTrimming.CharacterEllipsis));textStyle.Setters.Add(new Setter(ToolTipProperty,new Binding(property)));textStyle.Setters.Add(new Setter(MarginProperty,new Thickness(3,1,3,1)));
            grid.Columns.Add(new DataGridTextColumn{Header=header,Binding=new Binding(property),ElementStyle=textStyle,Width=width==0?new DataGridLength(1,DataGridLengthUnitType.Star):new DataGridLength(width)});
        }
        return grid;
    }
    protected static double Num(JsonNode? n,double fallback=0)=>double.TryParse(n?.ToString(),NumberStyles.Float,CultureInfo.InvariantCulture,out var value)?value:fallback;
    protected static string Hex(JsonNode? n)=>"0x"+((ulong)Num(n)).ToString("X8",CultureInfo.InvariantCulture);
    protected static string? ChooseFile(string filter)
    {var dialog=new OpenFileDialog{Filter=filter};return dialog.ShowDialog()==true?dialog.FileName:null;}
    protected static string? SaveFile(string filter,string name)
    {var dialog=new SaveFileDialog{Filter=filter,FileName=name};return dialog.ShowDialog()==true?dialog.FileName:null;}
}
