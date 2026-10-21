namespace Frame.Desktop;

// Display-only monotone Hermite interpolation. Input samples and extrema are retained.
public static class RealtimeScopeCurve
{
    // Rebuild a bounded display envelope from the retained raw snapshot on every zoom.
    // Include the samples adjacent to the viewport so sub-sample zoom keeps its line segment.
    public static (double[] X, double[] Raw) Window(double[] raw, double origin, double interval, double left, double right, int pixels = 1000)
    {
        if (raw.Length == 0 || interval <= 0 || right < left) return ([], []);
        int first = (int)Math.Clamp(Math.Floor((left - origin) / interval) - 1, 0, raw.Length - 1);
        int last = (int)Math.Clamp(Math.Ceiling((right - origin) / interval) + 1, 0, raw.Length - 1);
        int stride = Math.Max(1, (last - first + 1 + pixels - 1) / pixels);
        var x = new List<double>(); var y = new List<double>();
        Span<int> selected = stackalloc int[6];
        for (int start = first; start <= last; start += stride) {
            int end = Math.Min(last, start + stride - 1), min = start, max = start, gapFirst = -1, gapLast = -1;
            if (stride == 1) { x.Add(origin + start * interval); y.Add(raw[start]); continue; }
            for (int i = start; i <= end; i++) {
                if (!double.IsFinite(raw[i])) { if (gapFirst < 0) gapFirst = i; gapLast = i; continue; }
                if (!double.IsFinite(raw[min]) || raw[i] < raw[min]) min = i;
                if (!double.IsFinite(raw[max]) || raw[i] > raw[max]) max = i;
            }
            selected[0] = start; selected[1] = min; selected[2] = max; selected[3] = gapFirst; selected[4] = gapLast; selected[5] = end;
            selected.Sort(); int previous = -1;
            foreach (int i in selected) {
                if (i < 0 || i == previous) continue;
                x.Add(origin + i * interval); y.Add(raw[i]); previous = i;
            }
        }
        return (x.ToArray(), y.ToArray());
    }
    public static (double[] X, double[] Y) Interpolate(double[] x, double[] y, int targetPoints = 12000)
    {
        if (x.Length != y.Length) throw new ArgumentException("Coordinate lengths differ.");
        if (x.Length < 3) return (x, y);
        var slopes = new double[x.Length - 1];
        for (int i = 0; i < slopes.Length; i++) slopes[i] = x[i + 1] > x[i] ? (y[i + 1] - y[i]) / (x[i + 1] - x[i]) : double.NaN;
        var tangent = new double[x.Length]; tangent[0] = slopes[0]; tangent[^1] = slopes[^1];
        for (int i = 1; i < tangent.Length - 1; i++) {
            double a = slopes[i - 1], b = slopes[i];
            if (!double.IsFinite(a) || !double.IsFinite(b) || a == 0 || b == 0 || Math.Sign(a) != Math.Sign(b)) continue;
            double left = x[i] - x[i - 1], right = x[i + 1] - x[i];
            double w1 = 2 * right + left, w2 = right + 2 * left;
            tangent[i] = (w1 + w2) / (w1 / a + w2 / b);
        }
        int steps = Math.Clamp(targetPoints / x.Length, 1, 6);
        var xx = new List<double>(x.Length * steps); var yy = new List<double>(x.Length * steps);
        for (int i = 0; i < x.Length - 1; i++) {
            xx.Add(x[i]); yy.Add(y[i]);
            double width = x[i + 1] - x[i];
            if (!double.IsFinite(slopes[i]) || !double.IsFinite(tangent[i]) || !double.IsFinite(tangent[i + 1]) || width <= 0) continue;
            for (int step = 1; step < steps; step++) {
                double t = (double)step / steps, t2 = t * t, t3 = t2 * t;
                double value = (2 * t3 - 3 * t2 + 1) * y[i] + (t3 - 2 * t2 + t) * width * tangent[i]
                    + (-2 * t3 + 3 * t2) * y[i + 1] + (t3 - t2) * width * tangent[i + 1];
                xx.Add(x[i] + t * width); yy.Add(Math.Clamp(value, Math.Min(y[i], y[i + 1]), Math.Max(y[i], y[i + 1])));
            }
        }
        xx.Add(x[^1]); yy.Add(y[^1]); return (xx.ToArray(), yy.ToArray());
    }
}
