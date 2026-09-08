using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using ScottPlot.WPF;

namespace Frame.Desktop;

internal static class PlotWheelZoom
{
    public static void Attach(WpfPlot plot,Action? changed=null)
    {
        plot.PreviewMouseWheel+=(_,e)=>{
            var point=e.GetPosition(plot);var dpi=VisualTreeHelper.GetDpi(plot);
            var anchor=plot.Plot.GetCoordinates(new ScottPlot.Pixel((float)(point.X*dpi.DpiScaleX),(float)(point.Y*dpi.DpiScaleY)));
            var modifiers=Keyboard.Modifiers;
            Apply(plot,anchor,e.Delta,!modifiers.HasFlag(ModifierKeys.Control),!modifiers.HasFlag(ModifierKeys.Shift));
            e.Handled=true;changed?.Invoke();plot.Refresh();
        };
    }
    public static void Apply(WpfPlot plot,ScottPlot.Coordinates anchor,int delta,bool x,bool y)
    {
        var limits=plot.Plot.Axes.GetLimits();double factor=Math.Pow(0.85,delta/120.0);
        if(x)plot.Plot.Axes.SetLimitsX(anchor.X+(limits.Left-anchor.X)*factor,anchor.X+(limits.Right-anchor.X)*factor);
        if(y)plot.Plot.Axes.SetLimitsY(anchor.Y+(limits.Bottom-anchor.Y)*factor,anchor.Y+(limits.Top-anchor.Y)*factor);
    }
}
