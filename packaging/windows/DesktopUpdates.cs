using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

// Public release metadata only. No NetDeploy token, SSH secret or account data
// is sent to GitHub. The web page cannot supply a URL, filename or command.
internal sealed class DesktopRelease
{
    internal string Version, Notes, Page, Download, Checksums;
    internal long Size;
    internal Dictionary<string, object> PublicInfo() { return new Dictionary<string, object> {
        {"version", Version}, {"notes", Notes}, {"url", Page}, {"size", Size}
    }; }
}

internal sealed class DesktopUpdates : IDisposable
{
    internal const string Repository = "https://github.com/slobys/netdeploy-ai";
    internal const string Latest = "https://api.github.com/repos/slobys/netdeploy-ai/releases/latest";
    internal const long MaximumInstaller = 300L * 1024 * 1024;
    private readonly HttpClient client;

    internal DesktopUpdates(HttpMessageHandler handler = null)
    {
        ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
        client = new HttpClient(handler ?? new HttpClientHandler { AllowAutoRedirect = false });
        client.Timeout = TimeSpan.FromMinutes(15);
        client.DefaultRequestHeaders.UserAgent.ParseAdd("NetDeployAI-Desktop-Updater");
        client.DefaultRequestHeaders.Accept.ParseAdd("application/vnd.github+json");
    }

    internal static Version ParseVersion(string value)
    {
        if (!Regex.IsMatch(value ?? "", @"^\d{1,6}\.\d{1,6}\.\d{1,6}$"))
            throw new InvalidDataException("更新版本号无效，请稍后重试。");
        return new Version(value);
    }

    private static string Text(Dictionary<string, object> data, string key)
    { object value; return data.TryGetValue(key, out value) ? Convert.ToString(value) : ""; }

    private static bool DownloadHost(Uri uri)
    {
        return uri.Scheme == "https" && uri.IsDefaultPort && uri.UserInfo == "" &&
            (uri.Host == "github.com" || uri.Host == "api.github.com" ||
             uri.Host == "release-assets.githubusercontent.com" || uri.Host == "objects.githubusercontent.com");
    }

    private async Task<HttpResponseMessage> Get(string address, CancellationToken cancel)
    {
        var uri = new Uri(address);
        for (int redirect = 0; redirect <= 5; redirect++)
        {
            if (!DownloadHost(uri)) throw new InvalidDataException("更新下载地址未通过校验。");
            var response = await client.GetAsync(uri, HttpCompletionOption.ResponseHeadersRead, cancel);
            int status = (int)response.StatusCode;
            if (status >= 300 && status <= 399 && response.Headers.Location != null)
            {
                var next = new Uri(uri, response.Headers.Location);
                response.Dispose(); uri = next; continue;
            }
            if (status == 403 || status == 429) { response.Dispose(); throw new IOException("GitHub 暂时限制了请求，请稍后重新检查更新。"); }
            if (!response.IsSuccessStatusCode) { response.Dispose(); throw new IOException("暂时无法从 GitHub 获取更新，请检查网络后重试。"); }
            return response;
        }
        throw new IOException("更新下载重定向过多，请稍后重试。");
    }

    private async Task<string> ReadSmall(string address, int limit, CancellationToken cancel)
    {
        using (var response = await Get(address, cancel))
        using (cancel.Register(() => response.Dispose()))
        using (var stream = await response.Content.ReadAsStreamAsync())
        using (var output = new MemoryStream())
        {
            byte[] buffer = new byte[8192]; int count;
            while ((count = await stream.ReadAsync(buffer, 0, buffer.Length, cancel)) != 0)
            {
                if (output.Length + count > limit) throw new InvalidDataException("更新信息过大，已停止读取。");
                output.Write(buffer, 0, count);
            }
            return Encoding.UTF8.GetString(output.ToArray());
        }
    }

    internal async Task<DesktopRelease> Check(string current, CancellationToken cancel)
    {
        var data = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(
            await ReadSmall(Latest, 1024 * 1024, cancel));
        if (data == null || !data.ContainsKey("draft") || !data.ContainsKey("prerelease") ||
            !Object.Equals(data["draft"], false) || !Object.Equals(data["prerelease"], false))
            throw new InvalidDataException("暂时没有可用的正式更新。");
        string tag = Text(data, "tag_name");
        string version = tag.StartsWith("v", StringComparison.Ordinal) ? tag.Substring(1) : "";
        if (ParseVersion(version) <= ParseVersion(current)) return null;
        string prefix = Repository + "/releases/download/" + tag + "/";
        string name = "NetDeployAI-" + version + "-Setup-x64.exe";
        var result = new DesktopRelease { Version = version, Notes = Text(data, "body"),
            Page = Repository + "/releases/tag/" + tag };
        object assets;
        if (!data.TryGetValue("assets", out assets) || !(assets is IEnumerable))
            throw new InvalidDataException("新版安装包还未发布完整，请稍后重试。");
        foreach (object item in (IEnumerable)assets)
        {
            var asset = item as Dictionary<string, object>;
            if (asset == null || Text(asset, "state") != "uploaded") continue;
            string assetName = Text(asset, "name"), url = Text(asset, "browser_download_url");
            if (assetName == name && url == prefix + name)
            { result.Download = url; result.Size = Convert.ToInt64(asset["size"]); }
            if (assetName == "SHA256SUMS.txt" && url == prefix + "SHA256SUMS.txt") result.Checksums = url;
        }
        if (result.Download == null || result.Checksums == null || result.Size <= 0 || result.Size > MaximumInstaller)
            throw new InvalidDataException("新版安装包还未发布完整，请稍后重试。");
        if (result.Notes.Length > 6000) result.Notes = result.Notes.Substring(0, 6000) + "…";
        return result;
    }

    internal static string Checksum(string text, string name)
    {
        string found = null;
        foreach (string line in text.Split('\n'))
        {
            var match = Regex.Match(line.Trim(), @"^([a-fA-F0-9]{64})\s+\*?(.+)$");
            if (match.Success && match.Groups[2].Value == name)
            {
                if (found != null) throw new InvalidDataException("安装包校验信息重复，已停止更新。");
                found = match.Groups[1].Value.ToLowerInvariant();
            }
        }
        if (found == null) throw new InvalidDataException("找不到安装包 SHA-256 校验值，已停止更新。");
        return found;
    }

    internal static string Hash(string path)
    {
        using (var sha = SHA256.Create()) using (var stream = File.OpenRead(path))
            return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
    }

    internal async Task<string> Download(DesktopRelease release, string folder,
        Action<long, long> progress, CancellationToken cancel)
    {
        string name = "NetDeployAI-" + release.Version + "-Setup-x64.exe";
        string expected = Checksum(await ReadSmall(release.Checksums, 65536, cancel), name);
        Directory.CreateDirectory(folder);
        string partial = Path.Combine(folder, name + ".part"), target = Path.Combine(folder, name);
        try
        {
            using (var response = await Get(release.Download, cancel))
            using (cancel.Register(() => response.Dispose()))
            using (var input = await response.Content.ReadAsStreamAsync())
            using (var output = new FileStream(partial, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                long total = 0; int count; byte[] buffer = new byte[65536];
                DateTime last = DateTime.MinValue;
                while ((count = await input.ReadAsync(buffer, 0, buffer.Length, cancel)) != 0)
                {
                    total += count;
                    if (total > release.Size || total > MaximumInstaller) throw new InvalidDataException("安装包大小与发布信息不符，已停止更新。");
                    await output.WriteAsync(buffer, 0, count, cancel);
                    if ((DateTime.UtcNow - last).TotalMilliseconds >= 200)
                    { progress(total, release.Size); last = DateTime.UtcNow; }
                }
                if (total != release.Size) throw new InvalidDataException("安装包下载不完整，请重试。");
                progress(total, release.Size);
            }
            cancel.ThrowIfCancellationRequested();
            if (Hash(partial) != expected) throw new InvalidDataException("安装包 SHA-256 校验失败，已停止更新，请重新下载。");
            File.Move(partial, target);
            return target;
        }
        catch (Exception) { cancel.ThrowIfCancellationRequested(); throw; }
        finally { if (File.Exists(partial)) File.Delete(partial); }
    }

    public void Dispose() { client.Dispose(); }
}
