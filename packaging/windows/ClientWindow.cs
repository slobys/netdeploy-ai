using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Net.Http;
using System.Runtime.InteropServices;
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

    [DllImport("user32.dll")]
    private static extern IntPtr GetWindowDpiAwarenessContext(IntPtr window);
    [DllImport("user32.dll")]
    private static extern bool AreDpiAwarenessContextsEqual(IntPtr first, IntPtr second);
    [DllImport("user32.dll")]
    private static extern uint GetDpiForWindow(IntPtr window);

    internal ClientWindow(bool mainWindow)
    {
        main = mainWindow;
        AutoScaleDimensions = new SizeF(96, 96);
        AutoScaleMode = AutoScaleMode.Dpi;
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

    private async Task<Dictionary<string, object>> VerifyDisplay()
    {
        if (!AreDpiAwarenessContextsEqual(GetWindowDpiAwarenessContext(Handle), new IntPtr(-4)))
            throw new Exception("Desktop window is not PerMonitorV2 DPI aware.");
        uint dpi = GetDpiForWindow(Handle);
        var display = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(
            await view.CoreWebView2.ExecuteScriptAsync(
                "({ratio:window.devicePixelRatio,width:window.innerWidth,height:window.innerHeight})"));
        double ratio = Convert.ToDouble(display["ratio"]);
        if (Math.Abs(ratio - dpi / 96.0) > 0.01 || DeviceDpi != dpi)
            throw new Exception("WebView raster scale does not match the window DPI.");
        if (Math.Abs(Convert.ToDouble(display["width"]) * ratio - view.ClientSize.Width) > 2 ||
            Math.Abs(Convert.ToDouble(display["height"]) * ratio - view.ClientSize.Height) > 2)
            throw new Exception("WebView content does not fill its physical pixel bounds.");
        return new Dictionary<string, object> {
            {"perMonitorV2", true}, {"windowDpi", dpi}, {"devicePixelRatio", ratio}
        };
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
            var mainDisplay = await VerifyDisplay();
            // Exercise the actual CSS cascade in both modes, including cases
            // where older component rules used pale colors intended for dark mode.
            string readable = await view.CoreWebView2.ExecuteScriptAsync(@"
                (() => {
                    const root=document.documentElement, original=root.getAttribute('data-appearance');
                    const rgb=hex=>hex.trim().replace('#','').match(/../g).map(v=>parseInt(v,16));
                    const lum=values=>values.map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4)
                        .reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
                    let checked=0;
                    try {
                        for(const mode of ['light','dark']) {
                            root.setAttribute('data-appearance',mode);
                            const tokens=getComputedStyle(root);
                            for(const [selector,token] of [['.section-heading p','--theme-secondary'],
                                ['.project p','--theme-secondary'],['.host-card-meta','--theme-secondary'],
                                ['.brand small','--theme-subtle']]) {
                                const element=document.querySelector(selector);
                                if(!element) continue;
                                const actual=getComputedStyle(element).color.match(/[\d.]+/g).slice(0,3).map(Number);
                                const expected=rgb(tokens.getPropertyValue(token));
                                if(actual.some((v,i)=>v!==expected[i])) return false;
                                for(const background of ['--theme-page','--theme-panel']) {
                                    const a=lum(actual), b=lum(rgb(tokens.getPropertyValue(background)));
                                    if((Math.max(a,b)+.05)/(Math.min(a,b)+.05)<4.5) return false;
                                }
                                checked++;
                            }
                        }
                        return checked>=4;
                    } finally {
                        if(original===null) root.removeAttribute('data-appearance');
                        else root.setAttribute('data-appearance',original);
                    }
                })()");
            if (readable != "true") throw new Exception("Light/dark supporting text does not use readable theme colors.");
            using (var capture = File.Create(Path.Combine(Launcher.Home, "desktop-ui-smoke.png")))
                await view.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png, capture);
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
            var popupDisplay = await children[0].VerifyDisplay();
            File.WriteAllText(Path.Combine(Launcher.Home, "desktop-ui-smoke.json"),
                new JavaScriptSerializer().Serialize(new Dictionary<string, object> {
                    {"embedded", true}, {"authenticated", true}, {"popup", true}, {"openerCleared", true}, {"themeText", true},
                    {"display", mainDisplay}, {"popupDisplay", popupDisplay}
                }));
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
