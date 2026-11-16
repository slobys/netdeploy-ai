using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Net.Http;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

internal sealed class ClientWindow : Form
{
    private readonly bool main;
    private readonly WebView2 view = new WebView2();
    private readonly Label message = new Label();
    private readonly List<ClientWindow> children = new List<ClientWindow>();
    private CoreWebView2Environment environment;
    private bool testing;

    internal ClientWindow(bool mainWindow)
    {
        main = mainWindow;
        Text = main ? "NetDeploy AI" : "NetDeploy AI · 管理面板";
        Icon = new Icon(Path.Combine(Launcher.Root, "netdeploy.ico"));
        Size = new Size(1440, 900);
        MinimumSize = new Size(900, 640);
        StartPosition = FormStartPosition.CenterScreen;
        view.Dock = DockStyle.Fill;
        message.Dock = DockStyle.Fill;
        message.TextAlign = ContentAlignment.MiddleCenter;
        message.Font = new Font("Segoe UI", 12);
        message.Text = "正在启动 NetDeploy AI…";
        Controls.Add(view);
        Controls.Add(message);
        if (main) Shown += async delegate { await Start(); };
        FormClosed += delegate {
            foreach (var child in children.ToArray()) if (!child.IsDisposed) child.Close();
            view.Dispose();
        };
    }

    internal void OnUi(Action action)
    {
        try { if (!IsDisposed && IsHandleCreated) BeginInvoke(action); }
        catch (InvalidOperationException) { }
    }

    private async Task Start()
    {
        try
        {
            using (var client = new HttpClient(new HttpClientHandler { UseProxy = false }))
            {
                client.Timeout = TimeSpan.FromSeconds(2);
                bool ready = false;
                for (int attempt = 0; attempt < 60 && !IsDisposed; attempt++)
                {
                    try
                    {
                        var health = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(
                            await client.GetStringAsync(new Uri(Launcher.Panel, "api/health")));
                        ready = health.ContainsKey("security") && (string)health["security"] == "local-only";
                        if (ready) break;
                    }
                    catch (HttpRequestException) { }
                    catch (TaskCanceledException) { }
                    await Task.Delay(250);
                }
                if (!ready) throw new Exception("面板启动未完成，请稍后重新打开客户端。");
            }
            if (IsDisposed) return;
            var env = await CoreWebView2Environment.CreateAsync(null, Path.Combine(Launcher.Home, "webview"));
            await Initialize(env);
            view.CoreWebView2.Navigate(Launcher.Panel.AbsoluteUri);
        }
        catch (Exception error) { Fail(error.Message); }
    }

    private async Task Initialize(CoreWebView2Environment env)
    {
        environment = env;
        await view.EnsureCoreWebView2Async(env);
        view.CoreWebView2.Settings.AreHostObjectsAllowed = false;
        view.CoreWebView2.Settings.IsWebMessageEnabled = false;
        view.CoreWebView2.NewWindowRequested += Popup;
        view.CoreWebView2.NavigationStarting += delegate(object sender, CoreWebView2NavigationStartingEventArgs args) {
            Uri uri;
            if (!Uri.TryCreate(args.Uri, UriKind.Absolute, out uri)) { args.Cancel = true; return; }
            if (uri.Scheme != "http" && uri.Scheme != "https") { args.Cancel = true; return; }
            if (Launcher.Authorization(uri)) { args.Cancel = true; Launcher.External(uri); return; }
            if (main && !Launcher.Local(uri)) {
                args.Cancel = true;
                OpenPage(uri);
            }
        };
        view.CoreWebView2.NavigationCompleted += async delegate(object sender, CoreWebView2NavigationCompletedEventArgs args) {
            if (!args.IsSuccess) { message.Text = "页面暂时无法打开，请按 F5 重试。"; message.Visible = true; return; }
            message.Visible = false;
            if (Launcher.Smoke && main && !testing) { testing = true; await VerifyWindow(); }
        };
    }

    private async void OpenPage(Uri uri)
    {
        var child = new ClientWindow(false);
        children.Add(child);
        child.Show();
        try { await child.Initialize(environment); child.view.CoreWebView2.Navigate(uri.AbsoluteUri); }
        catch (Exception error) { child.Fail(error.Message); }
    }

    private async void Popup(object sender, CoreWebView2NewWindowRequestedEventArgs args)
    {
        Uri uri;
        if (!Uri.TryCreate(args.Uri, UriKind.Absolute, out uri) || (uri.Scheme != "http" && uri.Scheme != "https"))
        { args.Handled = true; return; }
        if (Launcher.Authorization(uri)) { args.Handled = true; Launcher.External(uri); return; }
        var deferral = args.GetDeferral();
        var child = new ClientWindow(false);
        children.Add(child);
        child.Show();
        try
        {
            await child.Initialize(environment);
            args.NewWindow = child.view.CoreWebView2;
            args.Handled = true;
        }
        catch (Exception error) { args.Handled = true; child.Fail(error.Message); }
        finally { deferral.Complete(); }
    }

    private async Task VerifyWindow()
    {
        try
        {
            bool authenticated = false;
            for (int attempt = 0; attempt < 100; attempt++)
            {
                authenticated = await view.CoreWebView2.ExecuteScriptAsync(
                    "!!sessionStorage.getItem('nd_token') && document.querySelector('#login').classList.contains('hidden')") == "true";
                if (authenticated) break;
                await Task.Delay(100);
            }
            if (!authenticated) throw new Exception("Embedded panel did not authenticate.");
            await view.CoreWebView2.ExecuteScriptAsync(
                "window.open('/static/hiddify-launch.html#invalid','_blank');");
            bool popup = false;
            for (int attempt = 0; attempt < 100; attempt++)
            {
                if (children.Count == 1 && children[0].view.CoreWebView2 != null)
                {
                    popup = await children[0].view.CoreWebView2.ExecuteScriptAsync(
                        "!!sessionStorage.getItem('nd_token') && window.opener===null && document.querySelector('#launch-status')?.textContent.includes('任务编号无效')") == "true";
                    if (popup) break;
                }
                await Task.Delay(100);
            }
            if (!popup) throw new Exception("Embedded popup or session inheritance failed.");
            File.WriteAllText(Path.Combine(Launcher.Home, "desktop-ui-smoke.json"),
                "{\"embedded\":true,\"authenticated\":true,\"popup\":true,\"openerCleared\":true}");
            Close();
        }
        catch (Exception error) { Fail(error.Message); }
    }

    private void Fail(string text)
    {
        if (IsDisposed) return;
        message.Text = text;
        message.Visible = true;
        if (Launcher.Smoke)
        {
            Directory.CreateDirectory(Launcher.Home);
            File.WriteAllText(Path.Combine(Launcher.Home, "desktop-ui-smoke-error.txt"), text);
            Launcher.Result = 1;
            Close();
        }
    }
}
