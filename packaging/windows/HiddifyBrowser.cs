using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

internal static class HiddifyBrowser
{
    internal static bool IsLauncher(Uri uri)
    {
        return Launcher.Local(uri) && uri.AbsolutePath == "/static/hiddify-launch.html";
    }

    internal static async Task<Uri> ReadLink(Uri launch, string token, HttpMessageHandler handler = null)
    {
        string job = launch.Fragment.Length == 0 ? "" : launch.Fragment.Substring(1);
        if (!IsLauncher(launch) || !Regex.IsMatch(job, "\\A[a-f0-9]{16}\\z"))
            throw new InvalidOperationException("任务编号无效，请从部署任务重新打开管理面板。");
        if (String.IsNullOrEmpty(token))
            throw new InvalidOperationException("请登录 NetDeploy 后再打开管理面板。");
        // Never send the NetDeploy token through a browser URL or a redirect.
        using (var client = new HttpClient(handler ?? new HttpClientHandler {
            UseProxy = false, AllowAutoRedirect = false
        }))
        {
            client.Timeout = TimeSpan.FromSeconds(75);
            using (var request = new HttpRequestMessage(HttpMethod.Get,
                new Uri(Launcher.Panel, "api/jobs/" + job + "/hiddify-admin")))
            {
                request.Headers.Add("X-Admin-Token", token);
                request.Headers.CacheControl = new System.Net.Http.Headers.CacheControlHeaderValue { NoCache = true };
                using (var response = await client.SendAsync(request))
                {
                    if (!response.IsSuccessStatusCode)
                        throw new InvalidOperationException("无法读取 Hiddify 管理链接（HTTP " +
                            (int)response.StatusCode + "），请检查任务和 SSH 连接后重试。");
                    Dictionary<string, object> result;
                    try { result = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(
                        await response.Content.ReadAsStringAsync()); }
                    catch (ArgumentException) { throw new InvalidOperationException("Hiddify 管理链接响应无效，请重试。"); }
                    object value;
                    Uri url;
                    if (result == null || !result.TryGetValue("url", out value) || !(value is string) ||
                        !Uri.TryCreate((string)value, UriKind.Absolute, out url) ||
                        url.Scheme != "https" || !String.IsNullOrEmpty(url.UserInfo))
                        throw new InvalidOperationException("Hiddify 管理链接格式无效，未打开外部页面。");
                    return url;
                }
            }
        }
    }
}
