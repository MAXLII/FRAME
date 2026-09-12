using System.CommandLine;
using System.CommandLine.Parsing;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Frame.Client;

namespace Frame.Cli;

internal static class Program
{
    private static readonly Dictionary<string,string[]> Groups=new()
    {
        ["serial"]=["ports","connect","baud","send","raw"], ["param"]=["list","read","write","batch-read","batch-write","report"],
        ["wave"]=["capture","start","stop","status"], ["scope"]=["list","info","channels","start","trigger","stop","reset","pull"],
        ["sfra"]=["list","info","configure","start","stop","reset","points"], ["perf"]=["info","summary","dictionary","samples","start","stop","reset"],
        ["trace"]=["capture","start","stop","status"], ["section"]=["list","nodes"], ["jlink"]=["connect","disconnect","detect","load","symbols","expand","read","write"],
        ["data"]=["read","view","clear","export","release"], ["ethernet"]=["discover"], ["backend"]=["catalog"]
    };
    private static readonly string[] Numeric=["baud","dst","dynamic-dst","timeout","response-timeout","id","dataset","offset","limit","period","data-bits","stop-bits","count","revision","probe","tcp-port","scan-ms","discovery-port","speed"];
    private static readonly string[] Real=["duration","interval","start-hz","stop-hz","amplitude","seconds","left","right"];
    private static readonly string[] Strings=["port","replay","name","value","min","max","input","output","hex","text","parity","enable","elf","path","device","jlink-exe","filter","record","transport","host","map","interface","protocol"];
    private static readonly Dictionary<ulong,BackendJob> jobs=new();
    private static readonly Dictionary<ulong,JsonObject> completedJobs=new();
    private static BackendClient? client;
    private static BackendClient Client => client ??= new();
    private static CancellationTokenSource? foreground;
    private static bool inShell;
    private static bool exitRequested;

    public static async Task<int> Main(string[] args)
    {
        Console.OutputEncoding=new UTF8Encoding(false);
        Console.CancelKeyPress+=(_,e)=>{e.Cancel=true;foreground?.Cancel();};
        int code=0;
        try { code=await InvokeAsync(args); }
        catch(Exception error){Console.Error.WriteLine(error.Message);code=3;}
        finally
        {
            if(client!=null){await client.DisposeAsync();if(client.ShutdownError!=null){Console.Error.WriteLine(client.ShutdownError);if(code==0)code=8;}}
        }
        return code;
    }

    private static async Task<int> InvokeAsync(string[] args)
    {
        if(args.Length==2&&args.Contains("--json")&&args.Contains("--version")){Print(new JsonObject{["version"]=typeof(Program).Assembly.GetName().Version!.ToString(3)},true);return 0;}
        var root=Build();var parse=root.Parse(args);
        if(parse.Errors.Count>0)
        {
            string message=string.Join("; ",parse.Errors.Select(x=>x.Message));
            if(args.Contains("--json"))Print(new JsonObject{["ok"]=false,["code"]=2,["error"]=message},true);
            else Console.Error.WriteLine(message);
            return 2;
        }
        if(args.Any(a=>a is "--json" or "--ndjson")&&args.Any(a=>a is "--help" or "-h"))
        {
            var command=parse.CommandResult.Command;
            Print(new JsonObject{["command"]=command.Name,["description"]=command.Description,["subcommands"]=new JsonArray(command.Subcommands.Select(c=>(JsonNode?)JsonValue.Create(c.Name)).ToArray()),["options"]=new JsonArray(root.Options.Concat(command.Options).DistinctBy(o=>o.Name).Select(o=>(JsonNode)new JsonObject{["name"]=o.Name,["description"]=o.Description}).ToArray())},true);return 0;
        }
        return await parse.InvokeAsync();
    }

    private static RootCommand Build()
    {
        var root=new RootCommand("FRAME native device diagnostics. Use frame shell for a persistent session.");
        var textOptions=new Dictionary<string,Option<string>>();
        foreach(string name in Numeric.Concat(Real).Concat(Strings).Distinct())
        {
            var option=new Option<string>("--"+name){Description=name.Replace('-',' '),Recursive=true};root.Options.Add(option);textOptions[name]=option;
        }
        var jsonOption=new Option<bool>("--json"){Description="Machine-readable JSON on stdout",Recursive=true};
        var backgroundOption=new Option<bool>("--background"){Description="Start a background Shell job",Recursive=true};
        var ndjsonOption=new Option<bool>("--ndjson"){Description="Stream dataset records as NDJSON followed by a final result",Recursive=true};
        root.Options.Add(jsonOption);root.Options.Add(backgroundOption);root.Options.Add(ndjsonOption);
        void Bind(Command c,string group,string action)
        {
            c.SetAction(async (ParseResult parse,CancellationToken token)=>
            {
                bool json=parse.GetValue(jsonOption)||parse.GetValue(ndjsonOption);
                try
                {
                    JsonObject request=new(){["group"]=group,["action"]=action};
                    foreach(var pair in textOptions)
                    {
                        var val=parse.GetValue(pair.Value);if(val==null)continue;string key=pair.Key.Replace('-','_');
                        if(Numeric.Contains(pair.Key))request[key]=val.StartsWith("0x",StringComparison.OrdinalIgnoreCase)?Convert.ToInt64(val[2..],16):long.Parse(val,System.Globalization.CultureInfo.InvariantCulture);
                        else if(Real.Contains(pair.Key))request[key]=double.Parse(val,System.Globalization.CultureInfo.InvariantCulture);
                        else if(pair.Key=="filter"&&group=="perf")request[key]=int.Parse(val);
                        else if(pair.Key=="enable")request[key]=val.ToLowerInvariant() switch {"true" or "on" or "1"=>true,"false" or "off" or "0"=>false,_=>throw new ArgumentException("--enable expects on/off")};
                        else request[key]=val;
                    }
                    if(group=="status"||group=="jobs"){var snapshot=Client.Snapshot();if(group=="jobs")snapshot["completed"]=new JsonArray(completedJobs.Values.Select(x=>x.DeepClone()).ToArray());Print(snapshot,json);return 0;}
                    if(group=="cancel"){if(request["id"]==null)throw new ArgumentException("--id required");if(!Client.Cancel(checked((ulong)request["id"]!.GetValue<long>())))throw new ArgumentException("Unknown or completed job");Print(new JsonObject{["ok"]=true,["cancel_requested"]=true},json);return 0;}
                    if(group=="shell")return await ShellAsync(json);
                    if(group=="exit"){exitRequested=true;return 0;}
                    if(parse.GetValue(backgroundOption))
                    {
                        if(!inShell)throw new ArgumentException("--background requires frame shell");
                        var job=Client.Submit(request);jobs[job.Id]=job;Print(new JsonObject{["job_id"]=job.Id},json);return 0;
                    }
                    using var cancellation=CancellationTokenSource.CreateLinkedTokenSource(token);foreground=cancellation;
                    JsonObject result;
                    if(parse.GetValue(ndjsonOption))
                    {
                        if(group is not ("wave" or "trace")||action is not ("capture" or "start"))throw new ArgumentException("--ndjson requires wave/trace capture or start");
                        result=await StreamAsync(request,cancellation.Token);
                    }
                    else result=await Client.ExecuteAsync(request,cancellation.Token);
                    foreground=null;Print(result,json);return result["code"]!.GetValue<int>();
                }
                catch(Exception error){foreground=null;int code=error is BackendException be?be.Code:error is DllNotFoundException or BadImageFormatException?3:2;if(json)Print(new JsonObject{["ok"]=false,["code"]=code,["error"]=error.Message},true);else Console.Error.WriteLine(error.Message);return code;}
            });
        }
        foreach(var group in Groups){var parent=new Command(group.Key);root.Subcommands.Add(parent);foreach(string action in group.Value){var c=new Command(action);parent.Subcommands.Add(c);Bind(c,group.Key,action);}}
        foreach(string name in new[]{"connect","disconnect","status","jobs","cancel","shell","exit"}){var c=new Command(name);root.Subcommands.Add(c);Bind(c,name,"");}
        return root;
    }

    private static async Task<JsonObject> StreamAsync(JsonObject request,CancellationToken token)
    {
        var job=Client.Submit(request);using var registration=token.Register(()=>Client.Cancel(job.Id));
        long cursor=0;ulong generation=0;
        while(true)
        {
            bool done=job.Completion.IsCompleted;
            var set=Client.Snapshot()["datasets"]!.AsArray().FirstOrDefault(x=>x!["id"]!.GetValue<ulong>()==job.Id);
            if(set!=null)
            {
                ulong currentGeneration=set["generation"]?.GetValue<ulong>()??0;
                if(currentGeneration!=generation){generation=currentGeneration;cursor=0;Print(new JsonObject{["kind"]="reset",["dataset_id"]=job.Id,["generation"]=generation},true);}
                long dropped=set["dropped"]!.GetValue<long>();
                if(cursor<dropped){Print(new JsonObject{["kind"]="gap",["dataset_id"]=job.Id,["lost"]=dropped-cursor},true);cursor=dropped;}
                var page=await Client.ExecuteAsync(new JsonObject{["group"]="data",["action"]="read",["dataset"]=job.Id,["offset"]=cursor-dropped,["limit"]=10000});
                if(page["ok"]!.GetValue<bool>() || (page["code"]!.GetValue<int>()==6 && page["data"] is JsonObject))
                {
                    var data=page["data"]!;long actualDropped=data["dropped"]?.GetValue<long>()??0;
                    if((data["generation"]?.GetValue<ulong>()??0)!=generation)continue;
                    if(actualDropped!=dropped)continue;
                    foreach(var row in data["records"]!.AsArray()){Print(new JsonObject{["kind"]="record",["dataset_id"]=job.Id,["index"]=cursor++,["data"]=row!.DeepClone()},true);}
                    if(done&&cursor<actualDropped+data["total"]!.GetValue<long>())continue;
                }
            }
            if(done)return await job.Completion;
            await Task.Delay(100);
        }
    }

    private static void Print(JsonNode result,bool json)
    {
        Console.WriteLine(result.ToJsonString(new JsonSerializerOptions{WriteIndented=!json}));
    }

    private static async Task<int> ShellAsync(bool json)
    {
        if(inShell)throw new ArgumentException("Already in Shell");inShell=true;
        var history=new List<string>();bool interactive=!Console.IsInputRedirected;
        if(interactive)Console.Error.WriteLine("FRAME Shell — help, status, jobs, cancel --id N, exit");
        while(true)
        {
            foreach(var pair in jobs.Where(x=>x.Value.Completion.IsCompleted).ToArray())
            {
                var result=await pair.Value.Completion;Console.Error.WriteLine($"job {pair.Key}: code={result["code"]} {result["error"]}");jobs.Remove(pair.Key);completedJobs[pair.Key]=result;if(completedJobs.Count>128)completedJobs.Remove(completedJobs.Keys.First());
            }
            string? line=interactive?ReadLine(history):Console.ReadLine();if(line==null||line.Trim()=="exit")break;
            if(string.IsNullOrWhiteSpace(line))continue;history.Add(line);
            if(line.Trim()=="help")line="--help";
            int code;
            try{var args=Tokenize(line);if(json&&!args.Contains("--json"))args=[..args,"--json"];code=await InvokeAsync(args);}
            catch(Exception error){if(json)Print(new JsonObject{["ok"]=false,["code"]=2,["error"]=error.Message},true);else Console.Error.WriteLine(error.Message);code=2;}
            if(!interactive&&code!=0)return code;
            if(exitRequested)break;
        }
        return 0;
    }

    internal static string[] Tokenize(string line)
    {
        var result=new List<string>();var word=new StringBuilder();char quote='\0';bool started=false;
        foreach(char c in line)
        {
            if(quote!='\0'){if(c==quote)quote='\0';else word.Append(c);started=true;}
            else if(c=='"'||c=='\''){quote=c;started=true;}
            else if(char.IsWhiteSpace(c)){if(started){result.Add(word.ToString());word.Clear();started=false;}}
            else {word.Append(c);started=true;}
        }
        if(quote!='\0')throw new ArgumentException("Unclosed quote");if(started)result.Add(word.ToString());return result.ToArray();
    }

    private static string ReadLine(List<string> history)
    {
        Console.Error.Write("frame> ");var line=new StringBuilder();int cursor=history.Count;
        void Replace(string text){Console.Error.Write("\rframe> "+new string(' ',line.Length)+"\rframe> "+text);line.Clear();line.Append(text);}
        while(true)
        {
            var key=Console.ReadKey(true);
            if(key.Key==ConsoleKey.Enter){Console.Error.WriteLine();return line.ToString();}
            if(key.Key==ConsoleKey.Backspace){if(line.Length>0){line.Length--;Console.Error.Write("\b \b");}continue;}
            if(key.Key==ConsoleKey.UpArrow){if(cursor>0)Replace(history[--cursor]);continue;}
            if(key.Key==ConsoleKey.DownArrow){if(cursor<history.Count-1)Replace(history[++cursor]);else{cursor=history.Count;Replace("");}continue;}
            if(key.Key==ConsoleKey.Tab){string prefix=line.ToString();var choices=Groups.SelectMany(g=>g.Value.Select(a=>g.Key+" "+a)).Concat(new[]{"connect","disconnect","status","jobs","cancel","exit"}).Where(x=>x.StartsWith(prefix)).ToArray();if(choices.Length==1)Replace(choices[0]+" ");continue;}
            if(!char.IsControl(key.KeyChar)){line.Append(key.KeyChar);Console.Error.Write(key.KeyChar);}
        }
    }
}
