using System.Globalization;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Input;
using System.Windows.Media;

namespace Frame.Desktop;

public sealed partial class RealtimeScopePage
{
    private readonly ComboBox triggerMode = Choice("realtime_trigger_mode", "自动", "普通");
    private RealtimeScopeTriggerMode shortMode = RealtimeScopeTriggerMode.Auto;
    private bool rollMode = true, singleArmed;
    private bool modeInitialized;
    private readonly ComboBox measureSource = new() { DisplayMemberPath = "Label", SelectedValuePath = "Number", Width = 80, Height = 28, Margin = new Thickness(0, 0, 6, 4) };
    private readonly Dictionary<int, int> divisionWheelRemainders = new();
    private int timeWheelRemainder;
    private readonly TextBox pretrigger = new() { Text = "50", Width = 46, Height = 28, Padding = new Thickness(6, 2, 6, 2), Margin = new Thickness(0, 0, 6, 4) };
    private readonly TextBlock timebase = Text("10 ms/div · 10 div"), cursorValues = Text("等待波形"), measurements = Text("等待完整采样窗口");
    private readonly CheckBox xCursors = new() { Content = "X1 / X2 时间", IsChecked = false }, yCursors = new() { Content = "Y1 / Y2 幅值", IsChecked = false };
    private readonly Dictionary<int, double[]> rawSnapshot = new();
    private readonly double[] cursorPositions = [0.25, 0.75, -1, 1];
    private int draggedCursor = -1;
    private Point? waveformDragOrigin;
    private double waveformDragLeft, waveformDragRight, waveformDragWidth, waveformDragHeight, waveformDragPosition;
    private RealtimeScopeChannel? draggedWaveform;

    private void InitializeInstrument()
    {
        sourceChoice.SelectionChanged += (_, _) => {
            StopPreview(); preview = null; snapshot.Clear(); rawSnapshot.Clear(); retainedHistory = false; snapshotSource = null; snapshotOriginMs = 0;
            sourceBadge.Text = sourceChoice.SelectedIndex == 1 ? "模拟源" : "设备";
            frequency.IsReadOnly = sourceChoice.SelectedIndex == 0; verifiedDeviceBindings = null;
            frequency.Text = sourceChoice.SelectedIndex == 0 ? "待同步" : "30000";
            RenderSnapshot(); UpdateSummary();
        };
        frequency.IsReadOnly = sourceChoice.SelectedIndex == 0;
        if (frequency.IsReadOnly) frequency.Text = "待同步";
        AutomationProperties.SetAutomationId(pretrigger, "realtime_pretrigger");
        AutomationProperties.SetAutomationId(measureSource, "realtime_measure_source");
        AutomationProperties.SetAutomationId(cursorValues, "realtime_cursor_values");
        AutomationProperties.SetAutomationId(measurements, "realtime_measurements");
        AutomationProperties.SetAutomationId(xCursors, "realtime_x_cursors");
        AutomationProperties.SetAutomationId(yCursors, "realtime_y_cursors");
        foreach (var box in new[] { xCursors, yCursors }) {
            box.Checked += (_, _) => RenderSnapshot(); box.Unchecked += (_, _) => RenderSnapshot();
        }
        measureSource.SelectionChanged += (_, _) => { if (!refreshing) UpdateReadouts(); };
        triggerMode.SelectionChanged += (_, _) => {
            if (refreshing || rollMode) return;
            shortMode = triggerMode.SelectedIndex == 1 ? RealtimeScopeTriggerMode.Normal : RealtimeScopeTriggerMode.Auto;
            singleArmed = false; ConfigurePreview();
        };
        pretrigger.LostKeyboardFocus += (_, _) => ConfigurePreview();
        pretrigger.KeyDown += (_, e) => { if (e.Key == Key.Enter) ConfigurePreview(); };
    }
    private void ChangeChannelDivision(object sender, MouseWheelEventArgs e)
    {
        e.Handled = true;
        if (sender is not TextBox box || box.DataContext is not RealtimeScopeChannel channel) return;
        box.GetBindingExpression(TextBox.TextProperty)?.UpdateSource();
        if (Validation.GetHasError(box)) return;
        long accumulated = Math.Clamp((long)divisionWheelRemainders.GetValueOrDefault(channel.Number) + e.Delta, -3840, 3840);
        int steps = (int)(accumulated / Mouse.MouseWheelDeltaForOneLine);
        divisionWheelRemainders[channel.Number] = (int)(accumulated % Mouse.MouseWheelDeltaForOneLine);
        for (int i = 0; i < Math.Abs(steps); i++) channel.Display.UnitsPerDivision = StepDivision(channel.Display.UnitsPerDivision, Math.Sign(steps));
    }
    private static double StepDivision(double value, int direction)
    {
        double power = Math.Pow(10, Math.Floor(Math.Log10(value)));
        if (power == 0) power = double.Epsilon;
        var candidates = new[] { 0.1, 0.2, 0.5, 1, 2, 5, 10 }.Select(step => step * power)
            .Where(step => double.IsFinite(step) && step > 0);
        return direction > 0 ? candidates.FirstOrDefault(step => step > value * (1 + 1e-12), value)
            : candidates.LastOrDefault(step => step < value * (1 - 1e-12), value);
    }
    private UIElement BuildReadouts()
    {
        var panel = new StackPanel { Margin = new Thickness(7) };
        measureSource.HorizontalAlignment = HorizontalAlignment.Left;
        panel.Children.Add(Toolbar(measureSource, Click("复位游标", "realtime_cursor_reset", () => { cursorPositions[0] = 0.25; cursorPositions[1] = 0.75; cursorPositions[2] = -1; cursorPositions[3] = 1; RenderSnapshot(); })));
        var title = Text("游标"); title.FontWeight = FontWeights.SemiBold; panel.Children.Add(title);
        xCursors.Margin = new Thickness(0, 0, 12, 4); yCursors.Margin = new Thickness(0, 0, 0, 4);
        panel.Children.Add(Toolbar(xCursors, yCursors));
        cursorValues.FontFamily = new FontFamily("Consolas, Microsoft YaHei UI"); cursorValues.LineHeight = 19; cursorValues.FontSize = 12; cursorValues.TextWrapping = TextWrapping.NoWrap; panel.Children.Add(cursorValues);
        var auto = Text("测量"); auto.FontWeight = FontWeights.SemiBold; auto.Margin = new Thickness(0, 6, 0, 4); panel.Children.Add(auto);
        measurements.FontFamily = new FontFamily("Consolas, Microsoft YaHei UI"); measurements.LineHeight = 19; measurements.FontSize = 12; measurements.TextWrapping = TextWrapping.NoWrap; panel.Children.Add(measurements);
        return new ScrollViewer { Content = panel, VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
    }
    private double CursorX(int index)
    {
        var limits = plot.Plot.Axes.GetLimits(); return limits.Left + cursorPositions[index] * (limits.Right - limits.Left);
    }
    private void RenderCursors()
    {
        for (int i = 0; i < 4; i++) {
            if (i < 2 ? xCursors.IsChecked != true : yCursors.IsChecked != true) continue;
            var color = ScottPlot.Color.FromHex(i < 2 ? "#6D28D9" : "#0F766E");
            string name = i < 2 ? $"X{i + 1}" : $"Y{i - 1}";
            if (i < 2) { var line = plot.Plot.Add.VerticalLine(CursorX(i)); line.Color = color; line.LineWidth = 1; line.Text = name; }
            else { var line = plot.Plot.Add.HorizontalLine(cursorPositions[i]); line.Color = color; line.LineWidth = 1; line.Text = name; }
        }
    }
    private ScottPlot.Coordinates MouseCoordinates(MouseEventArgs e)
    {
        return PlotCoordinates(e.GetPosition(plot));
    }
    private ScottPlot.Coordinates PlotCoordinates(Point at)
    {
        var dpi = VisualTreeHelper.GetDpi(plot);
        return plot.Plot.GetCoordinates(new ScottPlot.Pixel((float)(at.X * dpi.DpiScaleX), (float)(at.Y * dpi.DpiScaleY)));
    }
    internal bool BeginWaveformDrag(Point at)
    {
        if (preview == null || snapshot.Count == 0) return false;
        var point = PlotCoordinates(at); var limits = plot.Plot.Axes.GetLimits();
        if (point.X < limits.Left || point.X > limits.Right || point.Y < limits.Bottom || point.Y > limits.Top) return false;
        var dpi = VisualTreeHelper.GetDpi(plot);
        var first = plot.Plot.GetPixel(new ScottPlot.Coordinates(limits.Left, limits.Bottom));
        var last = plot.Plot.GetPixel(new ScottPlot.Coordinates(limits.Right, limits.Top));
        waveformDragWidth = (last.X - first.X) / dpi.DpiScaleX;
        waveformDragHeight = (first.Y - last.Y) / dpi.DpiScaleY;
        if (waveformDragWidth <= 0 || waveformDragHeight <= 0) return false;
        waveformDragOrigin = at; waveformDragLeft = limits.Left; waveformDragRight = limits.Right;
        draggedWaveform = null; double nearest = 12;
        foreach (var channel in workspace.Configuration.Enabled.Where(channel => channel.Display.Visible)) {
            if (!rawSnapshot.TryGetValue(channel.Number, out var raw) || raw.Length == 0) continue;
            double sample = (point.X + snapshotOriginMs - snapshotFirst) * preview.SampleRate / 1000;
            if (sample < 0 || sample > raw.Length - 1) continue;
            int index = (int)Math.Floor(sample), next = Math.Min(index + 1, raw.Length - 1);
            double value = raw[index] + (raw[next] - raw[index]) * (sample - index);
            var pixel = plot.Plot.GetPixel(new ScottPlot.Coordinates(point.X, channel.Display.Divisions(value)));
            double distance = Math.Abs(pixel.Y / dpi.DpiScaleY - at.Y);
            if (distance < nearest) { nearest = distance; draggedWaveform = channel; }
        }
        if (draggedWaveform != null) {
            waveformDragPosition = draggedWaveform.Display.Position;
            channelTable.SelectedItem = draggedWaveform;
        }
        return true;
    }
    internal void MoveWaveformDrag(Point at)
    {
        if (waveformDragOrigin is not Point origin || preview == null) return;
        double dx = at.X - origin.X, dy = at.Y - origin.Y;
        if (draggedWaveform != null) {
            if (Math.Abs(dy) < 2) return;
            draggedWaveform.Display.Position = waveformDragPosition - dy / waveformDragHeight * 8;
        }
        else {
            if (Math.Abs(dx) < 2) return;
            follow = false;
            double span = waveformDragRight - waveformDragLeft;
            double first = retainedHistory ? snapshotFirst : preview.Oldest * 1000.0 / preview.SampleRate;
            double last = retainedHistory ? snapshotLast : (preview.NextSample - 1) * 1000.0 / preview.SampleRate;
            double padding = Math.Min(span / 2, 1000.0 / preview.SampleRate);
            double left = waveformDragLeft - dx / waveformDragWidth * span;
            left = Math.Clamp(left, first - span + padding - snapshotOriginMs, last - padding - snapshotOriginMs);
            plot.Plot.Axes.SetLimitsX(left, left + span);
        }
        if (previewRunning && !preview.DisplayPaused) CaptureSnapshot();
        RenderSnapshot();
    }
    internal void EndWaveformDrag()
    {
        waveformDragOrigin = null; draggedWaveform = null;
    }
    private bool TriggerCoordinates(out ScottPlot.Coordinates point)
    {
        point = default;
        if (triggerSource.SelectedItem is not RealtimeScopeChannel channel ||
            !double.TryParse(level.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out double threshold) || !double.IsFinite(threshold) ||
            !double.TryParse(pretrigger.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out double percent) || !double.IsFinite(percent)) return false;
        var limits = plot.Plot.Axes.GetLimits();
        point = new(limits.Left + Math.Clamp(percent, 0, 100) / 100 * (limits.Right - limits.Left),
            threshold / channel.Display.UnitsPerDivision + channel.Display.Position);
        return double.IsFinite(point.Y);
    }
    private void RenderTrigger()
    {
        if (!TriggerCoordinates(out var point) || triggerSource.SelectedItem is not RealtimeScopeChannel channel) return;
        var color = ScottPlot.Color.FromHex(Colors[(channel.Number - 1) % Colors.Length]);
        var limits = plot.Plot.Axes.GetLimits();
        if (draggedCursor == 5) {
            var line = plot.Plot.Add.HorizontalLine(point.Y);
            line.Color = color; line.LineWidth = 1; line.LinePattern = ScottPlot.LinePattern.Dashed;
            line.Text = $"T {channel.Label} {level.Text} {channel.Display.Unit}".TrimEnd();
        }
        var levelAt = TriggerLevelHandle(point);
        // Rotate a downward triangle 90 degrees clockwise in pixel space, independent of axis scales.
        var center = plot.Plot.GetPixel(levelAt);
        const double angle = Math.PI / 2;
        var corners = new[] { (X: -12d, Y: -7d), (X: 12d, Y: -7d), (X: 0d, Y: 14d) };
        var vertices = corners.Select(p => plot.Plot.GetCoordinates(new ScottPlot.Pixel(
            (float)(center.X + p.X * Math.Cos(angle) - p.Y * Math.Sin(angle)),
            (float)(center.Y + p.X * Math.Sin(angle) + p.Y * Math.Cos(angle))))).ToArray();
        var levelMarker = plot.Plot.Add.Polygon(vertices); levelMarker.FillColor = color; levelMarker.LineWidth = 0;
        var label = plot.Plot.Add.Text("T", levelAt.X, levelAt.Y);
        label.LabelAlignment = ScottPlot.Alignment.MiddleCenter; label.LabelFontColor = ScottPlot.Colors.White; label.LabelFontSize = 10; label.LabelBold = true;
        var marker = plot.Plot.Add.Marker(point.X, limits.Top - (limits.Top - limits.Bottom) * 0.025);
        marker.Shape = ScottPlot.MarkerShape.FilledTriangleDown; marker.Size = 12; marker.Color = color;
    }
    private ScottPlot.Coordinates TriggerLevelHandle(ScottPlot.Coordinates point)
    {
        var limits = plot.Plot.Axes.GetLimits();
        var right = plot.Plot.GetPixel(new ScottPlot.Coordinates(limits.Right, Math.Clamp(point.Y, limits.Bottom + 0.15, limits.Top - 0.15)));
        // The rotated triangle's vertical base is seven pixels right of its center.
        return plot.Plot.GetCoordinates(new ScottPlot.Pixel(right.X - 7, right.Y));
    }
    private void BeginCursorDrag(object sender, MouseButtonEventArgs e)
    {
        if (e.ChangedButton != MouseButton.Left) { follow = false; return; }
        var at = e.GetPosition(plot); var dpi = VisualTreeHelper.GetDpi(plot);
        var coordinates = MouseCoordinates(e); var limits = plot.Plot.Axes.GetLimits();
        if (coordinates.X < limits.Left || coordinates.X > limits.Right || coordinates.Y < limits.Bottom || coordinates.Y > limits.Top) return;
        double nearest = 9;
        if (TriggerCoordinates(out var trigger)) {
            var top = plot.Plot.GetPixel(new ScottPlot.Coordinates(trigger.X, limits.Top - (limits.Top - limits.Bottom) * 0.025));
            var levelPixel = plot.Plot.GetPixel(TriggerLevelHandle(trigger));
            double dx = Math.Abs(top.X / dpi.DpiScaleX - at.X), dy = Math.Abs(top.Y / dpi.DpiScaleY - at.Y);
            if (dx < 12 && dy < 12) { draggedCursor = 4; plot.CaptureMouse(); e.Handled = true; return; }
            if (Math.Abs(levelPixel.X / dpi.DpiScaleX - at.X) < 16 && Math.Abs(levelPixel.Y / dpi.DpiScaleY - at.Y) < 16) {
                draggedCursor = 5; plot.CaptureMouse(); RenderSnapshot(); e.Handled = true; return;
            }
        }
        for (int i = 0; i < 4; i++) {
            if (i < 2 ? xCursors.IsChecked != true : yCursors.IsChecked != true) continue;
            var pixel = plot.Plot.GetPixel(i < 2 ? new ScottPlot.Coordinates(CursorX(i), 0) : new ScottPlot.Coordinates(0, cursorPositions[i]));
            double distance = i < 2 ? Math.Abs(pixel.X / dpi.DpiScaleX - at.X) : Math.Abs(pixel.Y / dpi.DpiScaleY - at.Y);
            if (distance < nearest) { nearest = distance; draggedCursor = i; }
        }
        if (draggedCursor >= 0) { plot.CaptureMouse(); e.Handled = true; }
        else if (BeginWaveformDrag(at)) { plot.CaptureMouse(); e.Handled = true; }
    }
    private void MoveCursor(object sender, MouseEventArgs e)
    {
        if (waveformDragOrigin != null) { MoveWaveformDrag(e.GetPosition(plot)); e.Handled = true; return; }
        if (draggedCursor < 0) return;
        var at = MouseCoordinates(e); var limits = plot.Plot.Axes.GetLimits();
        if (draggedCursor >= 4) {
            SetTriggerFromPlot(draggedCursor == 4, at.X, at.Y); e.Handled = true; return;
        }
        if (draggedCursor < 2) cursorPositions[draggedCursor] = Math.Clamp((at.X - limits.Left) / (limits.Right - limits.Left), 0, 1);
        else cursorPositions[draggedCursor] = Math.Clamp(at.Y, limits.Bottom, limits.Top);
        RenderSnapshot(); e.Handled = true;
    }
    internal void SetTriggerFromPlot(bool timePosition, double x, double y)
    {
        if (triggerSource.SelectedItem is not RealtimeScopeChannel channel || !double.IsFinite(x) || !double.IsFinite(y)) return;
        var limits = plot.Plot.Axes.GetLimits();
        if (timePosition) pretrigger.Text = (Math.Clamp((x - limits.Left) / (limits.Right - limits.Left), 0, 1) * 100).ToString("G9", CultureInfo.InvariantCulture);
        else level.Text = ((Math.Clamp(y, limits.Bottom, limits.Top) - channel.Display.Position) * channel.Display.UnitsPerDivision).ToString("G9", CultureInfo.InvariantCulture);
        ConfigurePreview();
    }
    private void EndCursorDrag(object sender, MouseButtonEventArgs e)
    {
        if (waveformDragOrigin != null) {
            EndWaveformDrag(); plot.ReleaseMouseCapture(); RenderSnapshot(); e.Handled = true; return;
        }
        if (draggedCursor < 0) return;
        draggedCursor = -1; plot.ReleaseMouseCapture(); RenderSnapshot(); e.Handled = true;
    }
    private void UpdateReadouts()
    {
        var channel = measureSource.SelectedItem as RealtimeScopeChannel;
        if (channel == null || preview == null || !rawSnapshot.TryGetValue(channel.Number, out var samples) || samples.Length == 0) {
            cursorValues.Text = "等待波形"; measurements.Text = "等待完整采样窗口"; return;
        }
        var display = channel.Display; string unit = display.Unit.Length > 0 ? " " + display.Unit : "";
        string Value(double value) => value.ToString("G6", CultureInfo.InvariantCulture) + unit;
        string Sample(double x) {
            x += snapshotOriginMs;
            if (x < snapshotFirst || x > snapshotLast) return "超出快照";
            int index = Math.Clamp((int)Math.Round((x - snapshotFirst) * preview.SampleRate / 1000), 0, samples.Length - 1);
            return Value(display.Engineering(samples[index]));
        }
        double x1 = CursorX(0), x2 = CursorX(1), delta = x2 - x1;
        var lines = new List<string>();
        if (xCursors.IsChecked == true) {
            lines.Add($"X1 = {x1:G6} ms  {Sample(x1)}");
            lines.Add($"X2 = {x2:G6} ms  {Sample(x2)}");
            lines.Add($"ΔX = {delta:G7} ms\n1/|ΔX| = {(Math.Abs(delta) > 1e-12 ? (1000 / Math.Abs(delta)).ToString("G6", CultureInfo.InvariantCulture) + " Hz" : "—")}");
        }
        if (yCursors.IsChecked == true) {
            double y1 = (cursorPositions[2] - display.Position) * display.UnitsPerDivision;
            double y2 = (cursorPositions[3] - display.Position) * display.UnitsPerDivision;
            lines.Add($"Y1 = {Value(y1)}\nY2 = {Value(y2)}\nΔY = {Value(y2 - y1)}");
        }
        cursorValues.Text = string.Join("\n", lines);
        var view = plot.Plot.Axes.GetLimits();
        int first = (int)Math.Clamp(Math.Ceiling((view.Left + snapshotOriginMs - snapshotFirst) * preview.SampleRate / 1000), 0, samples.Length);
        int end = (int)Math.Clamp(Math.Floor((view.Right + snapshotOriginMs - snapshotFirst) * preview.SampleRate / 1000) + 1, first, samples.Length);
        var visibleSamples = first == 0 && end == samples.Length ? samples : samples[first..end];
        var m = RealtimeScopeMeasurements.Calculate(visibleSamples, display, preview.SampleRate);
        measurements.Text = m == null ? "无有效测量（含非有限值）" :
            $"最大    {Value(m.Maximum)}\n最小    {Value(m.Minimum)}\n峰峰值  {Value(m.PeakToPeak)}\n均值    {Value(m.Mean)}\nRMS     {Value(m.Rms)}\n频率    {(m.Frequency is double hz ? $"{hz:G6} Hz" : "—")}" +
            $"\n周期    {(m.Period is double period ? $"{period * 1000:G6} ms" : "—")}\n占空比  {(m.Duty is double duty ? $"{duty:G5} %" : "—")}\n样本数  {visibleSamples.Length}";
    }
    private void AutoSet() => Try(() => {
        if (preview == null) return;
        var measured = workspace.Configuration.Enabled.Where(channel => channel.Display.Visible)
            .Select(channel => (Channel: channel, Measurement: RealtimeScopeMeasurements.Calculate(
                retainedHistory && ReferenceEquals(snapshotSource, preview) && rawSnapshot.TryGetValue(channel.Number, out var held)
                    ? held : preview.Samples(channel.Number, preview.Oldest, preview.NextSample - 1), channel.Display, preview.SampleRate)))
            .Where(item => item.Measurement != null).ToArray();
        if (measured.Length == 0) return;
        foreach (var (channel, measurement) in measured) {
            var m = measurement!;
            double span = m.PeakToPeak > Math.Max(1e-12, Math.Max(Math.Abs(m.Maximum), Math.Abs(m.Minimum)) * 1e-9)
                ? m.PeakToPeak / 6 : Math.Max(Math.Abs(m.Mean) / 3, 1e-6);
            channel.Display.UnitsPerDivision = NiceScale(span);
            channel.Display.Position = -(m.Maximum / 2 + m.Minimum / 2) / channel.Display.UnitsPerDivision;
        }
        var periodic = measured.Where(item => item.Measurement!.Period is > 0)
            .OrderByDescending(item => item.Measurement!.Period).ToArray();
        var source = periodic.Length > 0 ? periodic[0] : measured[0];
        triggerSource.SelectedValue = source.Channel.Number;
        level.Text = (source.Measurement!.Maximum / 2 + source.Measurement.Minimum / 2).ToString("G9", CultureInfo.InvariantCulture);
        if (periodic.Length > 0)
            windowMs.Text = Math.Clamp(periodic[0].Measurement!.Period!.Value * 3000,
                Math.Min(Read(history, "历史容量") * 1000, Math.Max(0.01, 10000.0 / preview.SampleRate)),
                Read(history, "历史容量") * 1000).ToString("G9", CultureInfo.InvariantCulture);
        shortMode = RealtimeScopeTriggerMode.Auto; singleArmed = false; ConfigurePreviewCore(); follow = true;
        CaptureSnapshot(); RenderSnapshot();
    });
    private static double NiceScale(double value)
    {
        double power = Math.Pow(10, Math.Floor(Math.Log10(value))); double fraction = value / power;
        return (fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10) * power;
    }
}
