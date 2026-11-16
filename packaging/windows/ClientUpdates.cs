using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using Microsoft.Web.WebView2.Core;

internal sealed partial class ClientWindow
{
    private DesktopRelease availableUpdate;
    private bool updateBusy;
    private bool installingUpdate;
    private bool updateAutoChecked;
    private CancellationTokenSource updateCancel;
    private Func<HttpMessageHandler> updateHandler;

    private async Task InitializeUpdates()
    {
        if (!main) return;
        view.CoreWebView2.Settings.IsWebMessageEnabled = true;
        await view.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(
            "Object.defineProperty(window,'netdeployDesktop',{value:true});");
        view.CoreWebView2.WebMessageReceived += UpdateMessage;
        FormClosed += delegate { if (updateCancel != null) updateCancel.Cancel(); };
    }

    private void UpdateEvent(string status, bool manual, object info = null)
    {
        Uri source;
        if (IsDisposed || view.CoreWebView2 == null ||
            !Uri.TryCreate(view.CoreWebView2.Source, UriKind.Absolute, out source) || !Launcher.Local(source)) return;
        view.CoreWebView2.PostWebMessageAsJson(new JavaScriptSerializer().Serialize(new {
            type = "netdeploy-update", status = status, manual = manual, info = info
        }));
    }

    private async void UpdateMessage(object sender, CoreWebView2WebMessageReceivedEventArgs args)
    {
        Uri source;
        if (!main || !Uri.TryCreate(args.Source, UriKind.Absolute, out source) ||
            !Launcher.Local(source) || source.AbsolutePath != "/") return;
        bool ownsOperation = false, manual = false, downloading = false;
        try
        {
            var data = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(args.WebMessageAsJson);
            if (data == null || !data.ContainsKey("type") || Convert.ToString(data["type"]) != "netdeploy-update") return;
            string action = data.ContainsKey("action") ? Convert.ToString(data["action"]) : "";
            manual = data.ContainsKey("manual") && Object.Equals(data["manual"], true);
            if (action == "cancel") { if (!installingUpdate && updateCancel != null) updateCancel.Cancel(); return; }
            if (updateBusy || installingUpdate) { UpdateEvent("busy", manual); return; }
            if (action != "check" && action != "install") return;
            if (action == "check" && !manual)
            {
                if (updateAutoChecked || Launcher.Smoke) return;
                updateAutoChecked = true;
            }
            updateBusy = true;
            ownsOperation = true;
            using (updateCancel = new CancellationTokenSource())
            using (var updates = new DesktopUpdates(updateHandler == null ? null : updateHandler()))
            {
                if (action == "check")
                {
                    // The installer smoke uses a deterministic release transport.
                    if (Launcher.Smoke && updateHandler == null) return;
                    updateCancel.CancelAfter(TimeSpan.FromSeconds(20));
                    UpdateEvent("checking", manual);
                    var version = Assembly.GetExecutingAssembly().GetName().Version;
                    availableUpdate = await updates.Check(version.Major + "." + version.Minor + "." + version.Build, updateCancel.Token);
                    UpdateEvent(availableUpdate == null ? "current" : "available", manual,
                        availableUpdate == null ? null : availableUpdate.PublicInfo());
                }
                else
                {
                    manual = true; downloading = true;
                    updateCancel.CancelAfter(TimeSpan.FromMinutes(15));
                    if (availableUpdate == null) throw new InvalidOperationException("请先重新检查更新。");
                    await CheckUpdateIdle();
                    UpdateEvent("downloading", true, new { received = 0, total = availableUpdate.Size });
                    string directory = Path.Combine(Launcher.Home, "updates", Guid.NewGuid().ToString("N"));
                    string installer = await updates.Download(availableUpdate, directory,
                        (received, total) => UpdateEvent("downloading", true, new { received, total }), updateCancel.Token);
                    await CheckUpdateIdle();
                    updateCancel.Token.ThrowIfCancellationRequested();
                    string helper = Path.Combine(directory, "NetDeployUpdater.exe");
                    File.Copy(Path.Combine(Launcher.Root, "NetDeployUpdater.exe"), helper, false);
                    string arguments = Launcher.Quote(Launcher.Root) + " " + Launcher.Quote(Launcher.Home) + " " +
                        Launcher.Panel.Port + " " + Launcher.WorkerPort + " " + Launcher.Quote(installer) + " " +
                        DesktopUpdates.Hash(installer) + " " + availableUpdate.Version;
                    UpdateEvent("installing", true);
                    installingUpdate = true;
                    var process = new Process { StartInfo = new ProcessStartInfo(helper, arguments) {
                        UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = directory }, EnableRaisingEvents = true };
                    process.Exited += delegate {
                        if (process.ExitCode != 0) OnUi(delegate {
                            installingUpdate = false;
                            UpdateEvent("error", true, new { message = "更新未完成。请查看更新提示，处理后重新检查。" });
                        });
                        process.Dispose();
                    };
                    try { process.Start(); } catch { installingUpdate = false; process.Dispose(); throw; }
                }
            }
        }
        catch (OperationCanceledException) {
            UpdateEvent(downloading ? "cancelled" : "error", manual,
                downloading ? null : new { message = "检查更新超时，请检查网络后重试。" });
        }
        catch (Exception error) { UpdateEvent("error", manual, new { message = error.Message }); }
        finally { if (ownsOperation) { updateBusy = false; updateCancel = null; } }
    }

    private async Task CheckUpdateIdle()
    {
        string token = new JavaScriptSerializer().Deserialize<string>(
            await view.CoreWebView2.ExecuteScriptAsync("sessionStorage.getItem('nd_token')"));
        if (String.IsNullOrEmpty(token)) throw new InvalidOperationException("请先登录 NetDeploy，再进行更新。");
        using (var client = new HttpClient(new HttpClientHandler { UseProxy = false, AllowAutoRedirect = false }))
        {
            client.Timeout = TimeSpan.FromSeconds(5);
            client.DefaultRequestHeaders.Add("X-Admin-Token", token);
            var jobs = new JavaScriptSerializer().Deserialize<List<Dictionary<string, object>>>(
                await client.GetStringAsync(new Uri(Launcher.Panel, "api/jobs")));
            foreach (var job in jobs)
                if (Convert.ToString(job["status"]) == "running" || Convert.ToString(job["status"]) == "queued")
                    throw new InvalidOperationException("有部署任务正在执行，请等待任务结束后再更新。");
        }
    }

    private async Task VerifyDesktopUpdates(string panelSource)
    {
        string version = "999.1.0", prefix = DesktopUpdates.Repository + "/releases/download/v999.1.0/";
        int statusCode = 200;
        updateHandler = delegate { return new SmokeBackend(request => {
            if (request.Headers.Contains("X-Admin-Token")) throw new Exception("Local token leaked to GitHub.");
            string body = new JavaScriptSerializer().Serialize(new {
                tag_name = "v" + version, draft = false, prerelease = false, body = "客户端更新测试（模拟版本，不安装）",
                assets = new [] {
                    new { name="NetDeployAI-999.1.0-Setup-x64.exe", browser_download_url=prefix+"NetDeployAI-999.1.0-Setup-x64.exe", size=3, state="uploaded" },
                    new { name="SHA256SUMS.txt", browser_download_url=prefix+"SHA256SUMS.txt", size=90, state="uploaded" }
                }
            });
            return new HttpResponseMessage((System.Net.HttpStatusCode)statusCode) { Content = new StringContent(body) };
        }); };
        try
        {
            await view.CoreWebView2.ExecuteScriptAsync("document.querySelector('#desktop-version').click()");
            for (int attempt=0; attempt<50 && availableUpdate==null; attempt++) await Task.Delay(20);
            await Task.Delay(100);
            if (availableUpdate==null || await view.CoreWebView2.ExecuteScriptAsync(
                "document.querySelector('#desktop-update-panel')?.textContent.includes('下载并更新')") != "true")
                throw new Exception("Desktop version button did not check and display the native update.");
            await view.CoreWebView2.ExecuteScriptAsync("document.querySelector('[data-update-action=later]').click()");
            if (view.CoreWebView2.Source != panelSource || children.Count != 0)
                throw new Exception("Update prompt changed the NetDeploy page.");
            availableUpdate=null; statusCode=429;
            await view.CoreWebView2.ExecuteScriptAsync("document.querySelector('#desktop-version').click(); window.chrome.webview.postMessage({type:'netdeploy-update',action:'check',manual:true})");
            await Task.Delay(200);
            if (await view.CoreWebView2.ExecuteScriptAsync(
                "document.querySelector('#desktop-update-panel')?.textContent.includes('重新检查')") != "true")
                throw new Exception("Update failure did not offer retry.");
        }
        finally { updateHandler=null; availableUpdate=null; }
        await view.CoreWebView2.ExecuteScriptAsync("closeDialog()");
    }
}
