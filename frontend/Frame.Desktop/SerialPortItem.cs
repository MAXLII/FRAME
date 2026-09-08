namespace Frame.Desktop;

public sealed record SerialPortItem(string Port, string Description)
{
    public string Display => string.IsNullOrWhiteSpace(Description) ? Port : $"{Port} — {Description}";
    public override string ToString() => Display;
}
