namespace Frame.Desktop;

// Measurements use retained samples, never the drawing envelope.
public sealed record RealtimeScopeMeasurements(double Minimum, double Maximum, double Mean, double Rms, double? Frequency, double? Duty)
{
    public double PeakToPeak => Maximum - Minimum;
    public double? Period => Frequency is > 0 ? 1 / Frequency : null;
    public static RealtimeScopeMeasurements? Calculate(double[] raw, RealtimeScopeDisplay display, int sampleRate)
    {
        if (raw.Length == 0 || sampleRate <= 0) return null;
        double min = double.PositiveInfinity, max = double.NegativeInfinity, mean = 0, scale = 0, squares = 0;
        for (int i = 0; i < raw.Length; i++) {
            double value = display.Engineering(raw[i]); if (!double.IsFinite(value)) return null;
            min = Math.Min(min, value); max = Math.Max(max, value); mean += (value - mean) / (i + 1);
            double magnitude = Math.Abs(value);
            if (magnitude > scale) { squares = scale == 0 ? 1 : 1 + squares * (scale / magnitude) * (scale / magnitude); scale = magnitude; }
            else if (scale > 0) squares += (magnitude / scale) * (magnitude / scale);
        }
        double threshold = min / 2 + max / 2;
        double? first = null, last = null; int periods = 0;
        double high = 0, highAtFirst = 0, highAtLast = 0;
        if (max - min > Math.Max(1e-12, Math.Max(Math.Abs(min), Math.Abs(max)) * 1e-9)) {
            for (int i = 1; i < raw.Length; i++) {
                double a = display.Engineering(raw[i - 1]), b = display.Engineering(raw[i]);
                bool rising = a < threshold && b >= threshold;
                bool falling = a >= threshold && b < threshold;
                double fraction = rising || falling ? Math.Clamp((threshold - a) / (b - a), 0, 1) : 0;
                if (rising) {
                    double at = i - 1 + fraction;
                    if (first == null) { first = at; highAtFirst = high; }
                    else { periods++; last = at; highAtLast = high; }
                    high += 1 - fraction;
                }
                else if (falling) high += fraction;
                else if (a >= threshold) high++;
            }
        }
        double? frequency = periods > 0 && last > first ? periods * sampleRate / (last - first) : null;
        double? duty = frequency != null ? 100 * (highAtLast - highAtFirst) / (last - first) : null;
        return new(min, max, mean, scale * Math.Sqrt(squares / raw.Length), frequency, duty);
    }
}
