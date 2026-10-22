using System.ComponentModel;
using System.Globalization;
using System.Text.Json.Nodes;

namespace Frame.Desktop;

// These models drive the explicitly labelled UI preview. Device acquisition stays in the native backend.
public sealed record RealtimeScopeSymbol(JsonObject Data, int Depth = 0)
{
    public string Name => Data["name"]?.ToString() ?? "?";
    public string Kind => Data["kind"]?.ToString() ?? "unknown";
    public string Type => Data["type_name"]?.ToString() ?? Kind;
    public ulong Address => ulong.TryParse(Data["address"]?.ToString(), out var value) ? value : 0;
    public string AddressText => $"0x{Address:X8}";
    public int Size => int.TryParse(Data["size"]?.ToString(), out var value) ? value : 0;
    public int Encoding => int.TryParse(Data["encoding"]?.ToString(), out var value) ? value : 0;
    public bool Expandable => Kind is "struct" or "union" or "array";
    public bool CanSample => Data["address"] != null && Kind == "scalar" &&
        Data["ambiguous"]?.GetValue<bool>() != true &&
        Data["bitfield"]?.GetValue<bool>() != true && Data["unsupported_location"]?.GetValue<bool>() != true &&
        (Encoding == 4 ? Size is 4 or 8 : Encoding is 2 or 5 or 6 or 7 or 8 && Size is 1 or 2 or 4 or 8);
    public string SamplingHint => CanSample ? "可加入通道" : Expandable ? "请展开并选择具体数值成员" :
        Data["ambiguous"]?.GetValue<bool>() == true ? "存在同名变量，无法唯一定位" :
        Data["bitfield"]?.GetValue<bool>() == true || Data["unsupported_location"]?.GetValue<bool>() == true ? "位域或成员位置表达式暂不支持" :
        Kind == "pointer" ? "指针暂不支持采样或自动解引用" :
        Data["address"] == null ? "没有可采样地址" : "此类型或数据宽度暂不支持";
    public string Arrow => Expandable ? Expanded ? "▾" : "▸" : "";
    public System.Windows.Thickness Indent => new(Depth * 14, 0, 0, 0);
    public bool Expanded { get; set; }
    public bool Loaded { get; set; }
    public List<RealtimeScopeSymbol> Children { get; } = new();
}

public sealed class RealtimeScopeDisplay : INotifyPropertyChanged
{
    private string unit = "";
    private double unitsPerDivision = 1, position, gain = 1, bias;
    private bool visible = true;
    public string Unit { get => unit; set { unit = value?.Trim() ?? ""; Changed(); } }
    public double UnitsPerDivision { get => unitsPerDivision; set { if (!double.IsFinite(value) || value <= 0) throw new ArgumentOutOfRangeException(nameof(value), "每格量程必须大于 0。"); unitsPerDivision = value; Changed(); } }
    public double Position { get => position; set { if (!double.IsFinite(value)) throw new ArgumentOutOfRangeException(nameof(value)); position = value; Changed(); } }
    public double Gain { get => gain; set { if (!double.IsFinite(value)) throw new ArgumentOutOfRangeException(nameof(value)); gain = value; Changed(); } }
    public double Bias { get => bias; set { if (!double.IsFinite(value)) throw new ArgumentOutOfRangeException(nameof(value)); bias = value; Changed(); } }
    public bool Visible { get => visible; set { visible = value; Changed(); } }
    public double Engineering(double raw) => raw * Gain + Bias;
    public double Divisions(double raw) => Engineering(raw) / UnitsPerDivision + Position;
    public string ScaleText => Unit.Length == 0 ? $"{UnitsPerDivision:G5}/div" : $"{UnitsPerDivision:G5} {Unit}/div";
    public event PropertyChangedEventHandler? PropertyChanged;
    private void Changed() => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(null));
}

public sealed class RealtimeScopeChannel(int number, RealtimeScopeDisplay display) : INotifyPropertyChanged
{
    public int Number { get; } = number;
    public string Label => $"CH{Number}";
    public RealtimeScopeDisplay Display { get; } = display;
    public RealtimeScopeSymbol? Symbol { get; private set; }
    public string Name => Symbol?.Name ?? "—";
    public string Type => Symbol?.Type ?? "—";
    public string Address => Symbol?.AddressText ?? "—";
    public bool Enabled => Symbol != null;
    public void Assign(RealtimeScopeSymbol? symbol) { Symbol = symbol; PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(null)); }
    public event PropertyChangedEventHandler? PropertyChanged;
}

public sealed class RealtimeScopeConfiguration
{
    public string Storage { get; }
    public RealtimeScopeChannel[] Channels { get; }
    public IEnumerable<RealtimeScopeChannel> Enabled => Channels.Where(channel => channel.Enabled);
    public int ByteCount => Enabled.Sum(channel => channel.Symbol!.Size);
    public RealtimeScopeConfiguration(string storage, RealtimeScopeDisplay[] displays)
    {
        Storage = storage;
        Channels = displays.Select((display, index) => new RealtimeScopeChannel(index + 1, display)).ToArray();
    }
    public bool Add(RealtimeScopeSymbol symbol, int? number = null)
    {
        if (!symbol.CanSample) throw new ArgumentException("请选择具有地址和受支持标量类型的参数；结构体请先展开到具体成员。");
        if (number is < 1 or > 32) throw new ArgumentOutOfRangeException(nameof(number), "通道号必须为 1～32。");
        var channel = number.HasValue ? Channels[number.Value - 1] : Channels.FirstOrDefault(channel => !channel.Enabled);
        if (channel == null) return false;
        channel.Assign(symbol);
        return true;
    }
}

public sealed class RealtimeScopeWorkspace
{
    public RealtimeScopeDisplay[] Displays { get; } = Enumerable.Range(0, 32).Select(_ => new RealtimeScopeDisplay()).ToArray();
    public RealtimeScopeConfiguration Configuration { get; }
    public RealtimeScopeWorkspace() { Configuration = new("通道", Displays); }
}

public enum RealtimeScopeEdge { Rising, Falling }
public enum RealtimeScopeTriggerMode { Auto, Normal, Single, Roll }
public sealed record RealtimeScopeTrigger(bool Enabled, int Channel, double Level, RealtimeScopeEdge Edge, double Pretrigger, bool PauseOnTrigger,
    RealtimeScopeTriggerMode Mode = RealtimeScopeTriggerMode.Auto);

// Bounded sample history and trigger engine, shared by device and demonstration sources.
public sealed class RealtimeScopePreview
{
    public const double RollThresholdSeconds = 0.5;
    private readonly Dictionary<int, double[]> values;
    private long? pendingTrigger;
    private long captureEnd;
    private long armedAt, lastCapture;
    private double viewSeconds = 0.1;
    private RealtimeScopeTrigger trigger = new(false, 1, 0, RealtimeScopeEdge.Rising, 0.5, true);
    public int SampleRate { get; }
    public int Capacity { get; }
    public long NextSample { get; private set; }
    public long Oldest => Math.Max(0, NextSample - Capacity);
    public long? CompletedTrigger { get; private set; }
    public bool DisplayPaused { get; private set; }
    public bool SingleCompleted { get; private set; }
    public bool IsRolling => viewSeconds >= RollThresholdSeconds;
    public bool TriggerEnabled => trigger.Enabled;
    public bool AutoFallback => trigger.Mode == RealtimeScopeTriggerMode.Auto && NextSample - lastCapture >= Math.Max(SampleRate / 10, viewSeconds * SampleRate);
    public bool CanDisplay => !trigger.Enabled || CompletedTrigger != null || AutoFallback;
    public event Action? TriggerCompleted;
    public bool AutoPauseEligible => !IsRolling && trigger.Enabled && trigger.PauseOnTrigger;
    public IReadOnlyCollection<int> Channels => values.Keys;
    public RealtimeScopePreview(RealtimeScopeConfiguration configuration, int sampleRate, double historySeconds)
    {
        Capacity = Validate(configuration, sampleRate, historySeconds);
        SampleRate = sampleRate;
        values = configuration.Enabled.ToDictionary(channel => channel.Number, _ => new double[Capacity]);
    }
    public static int Validate(RealtimeScopeConfiguration configuration, int sampleRate, double historySeconds)
    {
        if (sampleRate is < 1 or > 200_000 || !double.IsFinite(historySeconds) || historySeconds is < 0.1 or > 60)
            throw new ArgumentException("预览采样频率范围为 1～200000 Hz，历史容量范围为 0.1～60 s。");
        int count = configuration.Enabled.Count();
        if (count == 0) throw new ArgumentException("通道为空，请先选择参数。");
        double samples = Math.Ceiling(sampleRate * historySeconds);
        if (samples * count > 16_000_000) throw new ArgumentException("预览数据超过 128 MB 数值缓存预算，请降低频率、通道数或历史容量。");
        return checked((int)samples);
    }
    public void Configure(double seconds, RealtimeScopeTrigger settings)
    {
        if (!double.IsFinite(seconds) || seconds <= 0 || seconds * SampleRate > Capacity)
            throw new ArgumentException("显示时长必须大于 0 且不超过历史容量。");
        if (seconds >= RollThresholdSeconds) settings = settings with { Enabled = false, Mode = RealtimeScopeTriggerMode.Roll, PauseOnTrigger = false, Level = 0, Pretrigger = 0.5 };
        else if (settings.Mode == RealtimeScopeTriggerMode.Roll) settings = settings with { Mode = RealtimeScopeTriggerMode.Auto };
        if (!double.IsFinite(settings.Level) || !double.IsFinite(settings.Pretrigger) || settings.Pretrigger < 0 || settings.Pretrigger > 1)
            throw new ArgumentException("触发电平或预触发比例无效。");
        if (settings.Enabled && !values.ContainsKey(settings.Channel)) throw new ArgumentException("触发源必须是已配置通道。");
        if (seconds != viewSeconds || settings != trigger) {
            bool paused = DisplayPaused, completed = SingleCompleted;
            Rearm();
            DisplayPaused = paused;
            SingleCompleted = completed;
        }
        viewSeconds = seconds;
        trigger = settings;
    }
    public void Rearm() { DisplayPaused = false; SingleCompleted = false; pendingTrigger = null; CompletedTrigger = null; armedAt = lastCapture = NextSample; }
    public void PauseDisplay() => DisplayPaused = true;
    public void ForceTrigger()
    {
        if (!trigger.Enabled || SingleCompleted || pendingTrigger != null) return;
        long size = Math.Max(2, (long)Math.Ceiling(viewSeconds * SampleRate));
        long before = (long)Math.Floor((size - 1) * trigger.Pretrigger);
        long at = NextSample - 1;
        if (at < before || at - before < Oldest) return;
        pendingTrigger = at; captureEnd = at + size - before - 1;
        DisplayPaused = false;
    }
    public static bool Crosses(double previous, double current, double level, RealtimeScopeEdge edge) =>
        edge == RealtimeScopeEdge.Rising ? previous < level && current >= level : previous > level && current <= level;
    public static double Signal(int channel, long sample, int sampleRate) =>
        Math.Sin(2 * Math.PI * 50 * sample / sampleRate + (channel - 1) * Math.PI / 3) * (1 + (channel - 1) % 3 * 0.5);
    public void Advance(int count)
    {
        if (count < 0) throw new ArgumentOutOfRangeException(nameof(count));
        for (int i = 0; i < count && !SingleCompleted; i++)
            Append(values.Keys.ToDictionary(channel => channel, channel => Signal(channel, NextSample, SampleRate)));
    }
    public void Append(IReadOnlyDictionary<int, double> sample)
    {
        if (SingleCompleted) return;
        if (values.Keys.Any(channel => !sample.ContainsKey(channel))) throw new ArgumentException("采样通道布局不完整。");
        long window = Math.Max(2, (long)Math.Ceiling(viewSeconds * SampleRate));
        long before = (long)Math.Floor((window - 1) * trigger.Pretrigger);
        long after = window - before - 1;
            long n = NextSample;
            double previous = n > 0 && values.TryGetValue(trigger.Channel, out var source) ? source[(n - 1) % Capacity] : double.NaN;
            foreach (var channel in values) channel.Value[n % Capacity] = sample[channel.Key];
            NextSample++;
            // Reception continues even while the displayed snapshot is paused.
            if (!trigger.Enabled || DisplayPaused) return;
            if (pendingTrigger == null && n >= before && n >= armedAt && n > 0 &&
                Crosses(previous, sample[trigger.Channel], trigger.Level, trigger.Edge))
            {
                pendingTrigger = n;
                captureEnd = n + after;
            }
            if (pendingTrigger != null && n >= captureEnd)
            {
                CompletedTrigger = pendingTrigger;
                pendingTrigger = null;
                lastCapture = NextSample;
                SingleCompleted = trigger.Mode == RealtimeScopeTriggerMode.Single;
                if (AutoPauseEligible || SingleCompleted) DisplayPaused = true;
                TriggerCompleted?.Invoke();
            }
    }
    public (long First, long Last) Window()
    {
        long size = Math.Max(2, (long)Math.Ceiling(viewSeconds * SampleRate));
        long last = NextSample - 1;
        if (trigger.Enabled && !AutoFallback && CompletedTrigger is long at)
            last = at + size - (long)Math.Floor((size - 1) * trigger.Pretrigger) - 1;
        return (Math.Max(Oldest, last - size + 1), Math.Min(last, NextSample - 1));
    }
    public double[] Samples(int channel, long first, long last)
    {
        first = Math.Max(first, Oldest); last = Math.Min(last, NextSample - 1);
        if (last < first || !values.TryGetValue(channel, out var buffer)) return [];
        var result = new double[checked((int)(last - first + 1))];
        for (int i = 0; i < result.Length; i++) result[i] = buffer[(first + i) % Capacity];
        return result;
    }
    public (double[] X, double[] Y) Points(int channel, long first, long last, RealtimeScopeDisplay display, int pixels = 1000)
    {
        first = Math.Max(first, Oldest);
        last = Math.Min(last, NextSample - 1);
        if (last < first || !values.TryGetValue(channel, out var buffer)) return ([], []);
        var x = new List<double>();
        var y = new List<double>();
        long stride = Math.Max(1, (last - first + 1 + pixels - 1) / pixels);
        void Add(long n) { x.Add(n * 1000.0 / SampleRate); y.Add(display.Divisions(buffer[n % Capacity])); }
        for (long n = first; n <= last; n += stride)
        {
            long min = n, max = n, end = Math.Min(last, n + stride - 1);
            for (long j = n + 1; j <= end; j++)
            {
                if (buffer[j % Capacity] < buffer[min % Capacity]) min = j;
                if (buffer[j % Capacity] > buffer[max % Capacity]) max = j;
            }
            Add(Math.Min(min, max));
            if (min != max) Add(Math.Max(min, max));
        }
        return (x.ToArray(), y.ToArray());
    }
}
