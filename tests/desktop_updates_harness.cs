using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

internal static class UpdateTests
{
    private sealed class Transport : HttpMessageHandler
    {
        internal Func<HttpRequestMessage, HttpResponseMessage> Respond;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token)
        { token.ThrowIfCancellationRequested(); return Task.FromResult(Respond(request)); }
    }
    private static void Assert(bool condition, string message) { if (!condition) throw new Exception(message); }
    private static HttpResponseMessage Reply(string text) { return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(text) }; }
    private static Dictionary<string, object> Release(string version)
    {
        string prefix = DesktopUpdates.Repository + "/releases/download/v" + version + "/";
        return new Dictionary<string, object> {
            {"tag_name", "v" + version}, {"draft",false}, {"prerelease",false}, {"body","更新说明"},
            {"assets", new object[] {
                new Dictionary<string,object> { {"name","NetDeployAI-"+version+"-Setup-x64.exe"},
                    {"browser_download_url",prefix+"NetDeployAI-"+version+"-Setup-x64.exe"}, {"size",3}, {"state","uploaded"} },
                new Dictionary<string,object> { {"name","SHA256SUMS.txt"}, {"browser_download_url",prefix+"SHA256SUMS.txt"}, {"state","uploaded"} }
            }}
        };
    }
    private static async Task Reject(Func<Task> action, string message)
    {
        try { await action(); } catch (InvalidDataException) { return; } catch (IOException) { return; } catch (InvalidOperationException) { return; }
        throw new Exception(message);
    }
    private static async Task Tests(string folder)
    {
        Assert(DesktopUpdates.ParseVersion("0.3.10") > DesktopUpdates.ParseVersion("0.3.9"), "numeric ordering");
        var release = Release("0.3.42");
        var transport = new Transport { Respond = request => Reply(new JavaScriptSerializer().Serialize(release)) };
        using (var client = new DesktopUpdates(transport))
        {
            Assert(await client.Check("0.3.42", CancellationToken.None) == null, "same version prompted");
            Assert(await client.Check("0.3.43", CancellationToken.None) == null, "downgrade offered");
            var latest = await client.Check("0.3.41", CancellationToken.None);
            Assert(latest.Version == "0.3.42" && latest.Size == 3, "valid release not offered");
            release["prerelease"] = true;
            await Reject(async () => { await client.Check("0.3.41", CancellationToken.None); }, "prerelease accepted");
            release["prerelease"] = false;
            var assets = (object[])release["assets"];
            var installer = (Dictionary<string,object>)assets[0];
            string good = (string)installer["browser_download_url"];
            installer["browser_download_url"] = "https://evil.example/install.exe";
            await Reject(async () => { await client.Check("0.3.41", CancellationToken.None); }, "arbitrary URL accepted");
            installer["browser_download_url"] = good;
            string name = "NetDeployAI-0.3.42-Setup-x64.exe";
            string input = Path.Combine(folder, "expected"); File.WriteAllText(input, "abc");
            string hash = DesktopUpdates.Hash(input);
            string checksum = hash + "  " + name;
            transport.Respond = request => request.RequestUri.AbsolutePath.EndsWith("SHA256SUMS.txt")
                ? Reply(checksum) : Reply("abc");
            string output = await client.Download(latest, Path.Combine(folder,"valid"), (x,y)=>{}, CancellationToken.None);
            Assert(DesktopUpdates.Hash(output) == hash, "download mismatch");
            checksum = new string('0',64) + "  " + name;
            await Reject(async () => { await client.Download(latest, Path.Combine(folder,"bad"), (x,y)=>{}, CancellationToken.None); }, "bad hash accepted");
            Assert(Directory.GetFiles(Path.Combine(folder,"bad")).Length == 0, "bad installer remained executable");
            checksum = hash + "  other.exe";
            await Reject(async () => { await client.Download(latest, Path.Combine(folder,"missing"), (x,y)=>{}, CancellationToken.None); }, "missing checksum accepted");
            checksum = hash + "  " + name;
            latest.Size = 4;
            await Reject(async () => { await client.Download(latest, Path.Combine(folder,"short"), (x,y)=>{}, CancellationToken.None); }, "truncated installer accepted");
            latest.Size = 3;
            var cancellation = new CancellationTokenSource();
            cancellation.Cancel();
            try { await client.Download(latest, Path.Combine(folder,"cancel"), (x,y)=>{}, cancellation.Token); throw new Exception("cancel ignored"); }
            catch (OperationCanceledException) { }
            transport.Respond = request => new HttpResponseMessage(HttpStatusCode.Redirect) {
                Headers = { Location = new Uri("http://evil.example/payload") }
            };
            await Reject(async () => { await client.Check("0.3.41", CancellationToken.None); }, "unsafe redirect accepted");
            transport.Respond = request => new HttpResponseMessage((HttpStatusCode)429);
            await Reject(async () => { await client.Check("0.3.41", CancellationToken.None); }, "rate limit ignored");
        }
        Console.WriteLine("PASS: version ordering, downgrade, release URL, SHA256, truncation, cancellation, redirect, network errors");
    }
    private static int Main(string[] args)
    { try { Tests(args[0]).GetAwaiter().GetResult(); return 0; } catch(Exception error) { Console.Error.WriteLine(error); return 1; } }
}
