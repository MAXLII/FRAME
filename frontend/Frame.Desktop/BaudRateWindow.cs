using System.Windows;
using System.Windows.Controls;
namespace Frame.Desktop;
public sealed class BaudRateWindow : Window
{
    private readonly TextBox input=new(){Margin=new Thickness(0,8,0,8)};
    public string Value=>input.Text.Trim();
    public BaudRateWindow(string current)
    {
        Title="自定义波特率";Width=330;Height=190;ResizeMode=ResizeMode.NoResize;WindowStartupLocation=WindowStartupLocation.CenterOwner;
        var layout=new StackPanel{Margin=new Thickness(16)};Content=layout;
        layout.Children.Add(new TextBlock{Text="输入波特率（1～12000000）"});input.Text=current;layout.Children.Add(input);
        var error=new TextBlock{Foreground=System.Windows.Media.Brushes.Firebrick};layout.Children.Add(error);
        var apply=new Button{Content="确定",IsDefault=true};apply.Click+=(_,_)=>{if(!int.TryParse(Value,out int baud)||baud<1||baud>12000000){error.Text="请输入有效的整数波特率";return;}DialogResult=true;};layout.Children.Add(apply);
        Loaded+=(_,_)=>{input.Focus();input.SelectAll();};
    }
}
