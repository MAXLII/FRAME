using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Frame.Desktop;

public static class DesktopSettings
{
    public static string DataDirectory
    {
        get
        {
            string? configured=Environment.GetEnvironmentVariable("FRAME_DATA_DIR");
            if(!string.IsNullOrWhiteSpace(configured))return Path.GetFullPath(configured);
            string development=Path.GetFullPath(Path.Combine(AppContext.BaseDirectory,"../.."));
            return File.Exists(Path.Combine(development,"CMakeLists.txt"))&&Directory.Exists(Path.Combine(development,"frontend"))
                ?development:Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"FRAME");
        }
    }
    public static JsonObject Load(string path)
    {
        if(!File.Exists(path))return new();
        if(new FileInfo(path).Length>1024*1024)throw new InvalidDataException("界面设置文件过大");
        return JsonNode.Parse(File.ReadAllText(path))?.AsObject() ?? new();
    }
    public static void Save(string path,JsonObject settings)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        string temporary=path+"."+Guid.NewGuid().ToString("N")+".tmp";
        try
        {
            File.WriteAllText(temporary,settings.ToJsonString(new JsonSerializerOptions{WriteIndented=true}));
            File.Move(temporary,path,true);
        }
        finally{if(File.Exists(temporary))File.Delete(temporary);}
    }
}
