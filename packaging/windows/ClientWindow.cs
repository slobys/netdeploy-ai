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
    private bool openingHiddify;
    private Func<HttpMessageHandler> hiddifyHandler;
    private FormWindowState visibleState = FormWindowState.Normal;

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
        Size = new Size(1500, 1000);
        MinimumSize = new Size(900, 640);
        StartPosition = FormStartPosition.CenterScreen;
        WindowState = FormWindowState.Normal;
        view.Dock = DockStyle.Fill;
        message.Dock = DockStyle.Fill;
        message.TextAlign = ContentAlignment.MiddleCenter;
        message.Font = new Font("Segoe UI", 12);
        message.Text = "正在启动 NetDeploy AI…";
        Controls.Add(view);
        Controls.Add(message);
        Load += delegate { WindowPlacement.Restore(this, main); };
        Resize += delegate {
            if (WindowState != FormWindowState.Minimized) visibleState = WindowState;
        };
        FormClosing += delegate { WindowPlacement.Save(this, main, visibleState); };
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

    internal void FocusWindow()
    {
        Show();
        if (WindowState == FormWindowState.Minimized) WindowState = visibleState;
        Activate();
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
        view.CoreWebView2.NavigationStarting += async delegate(object sender, CoreWebView2NavigationStartingEventArgs args) {
            Uri uri;
            if (!Uri.TryCreate(args.Uri, UriKind.Absolute, out uri)) { args.Cancel = true; return; }
            if (uri.Scheme != "http" && uri.Scheme != "https") { args.Cancel = true; return; }
            if (HiddifyBrowser.IsLauncher(uri))
            { args.Cancel = true; await OpenHiddify(uri); return; }
            if (Launcher.Authorization(uri) || Launcher.Documentation(uri))
            { args.Cancel = true; Launcher.External(uri); return; }
            if (!Launcher.Local(uri)) {
                args.Cancel = true;
                Launcher.External(uri);
            }
        };
        view.CoreWebView2.NavigationCompleted += async delegate(object sender, CoreWebView2NavigationCompletedEventArgs args) {
            if (!args.IsSuccess && args.WebErrorStatus == CoreWebView2WebErrorStatus.OperationCanceled) return;
            if (!args.IsSuccess) { message.Text = "页面暂时无法打开，请按 F5 重试。"; message.Visible = true; return; }
            message.Visible = false;
            if (Launcher.Smoke && main && !testing) { testing = true; await VerifyWindow(); }
        };
    }

    private async Task Notify(string text, bool bad = false)
    {
        if (!IsDisposed && view.CoreWebView2 != null)
            await view.CoreWebView2.ExecuteScriptAsync("typeof toast==='function' && toast(" +
                new JavaScriptSerializer().Serialize(text) + "," + (bad ? "true" : "false") + ")");
    }

    private async Task OpenHiddify(Uri launch)
    {
        if (openingHiddify) return;
        openingHiddify = true;
        try
        {
            string failure = null;
            try
            {
                Uri source;
                if (!Uri.TryCreate(view.CoreWebView2.Source, UriKind.Absolute, out source) || !Launcher.Local(source))
                    throw new InvalidOperationException("请从 NetDeploy 的部署任务打开管理面板。");
                await Notify("正在读取 Hiddify 管理链接…");
                string token = new JavaScriptSerializer().Deserialize<string>(
                    await view.CoreWebView2.ExecuteScriptAsync("sessionStorage.getItem('nd_token')"));
                Uri url = await HiddifyBrowser.ReadLink(launch, token,
                    hiddifyHandler == null ? null : hiddifyHandler());
                if (IsDisposed) return;
                Launcher.External(url);
                await Notify("已交给默认浏览器打开 Hiddify 管理面板");
            }
            catch (TaskCanceledException) { failure = "读取 Hiddify 管理链接超时，请检查 SSH 连接后重试。"; }
            catch (Exception error) { failure = error.Message; }
            if (failure != null) await Notify(failure, true);
        }
        finally { openingHiddify = false; }
    }

    private async void Popup(object sender, CoreWebView2NewWindowRequestedEventArgs args)
    {
        Uri uri;
        if (!Uri.TryCreate(args.Uri, UriKind.Absolute, out uri) || (uri.Scheme != "http" && uri.Scheme != "https"))
        { args.Handled = true; return; }
        if (HiddifyBrowser.IsLauncher(uri))
        { args.Handled = true; await OpenHiddify(uri); return; }
        if (!Launcher.Local(uri))
        { args.Handled = true; Launcher.External(uri); return; }
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
            FormWindowState initialState = WindowState;
            FocusWindow();
            if (WindowState != initialState) throw new Exception("Activating the client changed its window state.");
            WindowState = FormWindowState.Minimized;
            FocusWindow();
            await Task.Delay(150);
            if (WindowState != initialState) throw new Exception("Minimized client did not restore its previous state.");
            Rectangle visibleBounds = Rectangle.Intersect(Bounds, Screen.FromControl(this).WorkingArea);
            if (visibleBounds.Width < 100 || visibleBounds.Height < 100)
                throw new Exception("Restored window is outside the available displays.");
            var mainDisplay = await VerifyDisplay();
            string panelSource = view.CoreWebView2.Source;
            await view.CoreWebView2.ExecuteScriptAsync("document.querySelector('.topbar-doc-link').click()");
            for (int attempt = 0; attempt < 40 && Launcher.SmokeExternal == null; attempt++) await Task.Delay(50);
            if (Launcher.SmokeExternal == null || !Launcher.Documentation(Launcher.SmokeExternal) ||
                children.Count != 0 || view.CoreWebView2.Source != panelSource)
                throw new Exception("Documentation did not route to the system browser while retaining the panel.");
            foreach (var externalPanel in new[] {
                new Uri("https://panel.example.invalid:8443/panel"),
                new Uri("https://sui.example.invalid:2095/app/"),
                new Uri("https://[2001:db8::1]:2095/app/")
            })
            {
                string target = new JavaScriptSerializer().Serialize(externalPanel.AbsoluteUri);
                foreach (string navigation in new[] {
                    "window.open(" + target + ",'_blank','noopener,noreferrer')",
                    "window.location.href=" + target
                })
                {
                    Launcher.SmokeExternal = null;
                    await view.CoreWebView2.ExecuteScriptAsync(navigation);
                    for (int attempt = 0; attempt < 40 && Launcher.SmokeExternal == null; attempt++) await Task.Delay(50);
                    await Task.Delay(150);
                    if (Launcher.SmokeExternal != externalPanel || children.Count != 0 ||
                        view.CoreWebView2.Source != panelSource || message.Visible)
                        throw new Exception("External management link did not open in the system browser while retaining the client.");
                }
            }
            await VerifyHiddifyLinks(panelSource);
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
            File.WriteAllText(Path.Combine(Launcher.Home, "desktop-ui-smoke.json"),
                new JavaScriptSerializer().Serialize(new Dictionary<string, object> {
                    {"embedded", true}, {"authenticated", true}, {"themeText", true},
                    {"display", mainDisplay}, {"hiddifyExternal", true}, {"hiddifyErrorsSafe", true}, {"suiExternal", true},
                    {"windowState", initialState.ToString()}, {"activationPreservesState", true}, {"documentationExternal", true},
                    {"managementLinksExternal", true}
                }));
            Close();
        }
        catch (Exception error) { Fail(error.Message); }
    }

    private sealed class SmokeBackend : HttpMessageHandler
    {
        private readonly Func<HttpRequestMessage, HttpResponseMessage> respond;
        internal SmokeBackend(Func<HttpRequestMessage, HttpResponseMessage> response) { respond = response; }
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request,
            System.Threading.CancellationToken cancellation) { return Task.FromResult(respond(request)); }
    }

    private async Task VerifyHiddifyLinks(string panelSource)
    {
        string token = new JavaScriptSerializer().Deserialize<string>(
            await view.CoreWebView2.ExecuteScriptAsync("sessionStorage.getItem('nd_token')"));
        var destination = new Uri("https://hiddify.example.invalid/admin/v2/quick-setup");
        string body = "{\"url\":\"" + destination.AbsoluteUri + "\",\"tls_verified\":true}";
        int status = 200, requests = 0;
        hiddifyHandler = delegate { return new SmokeBackend(request => {
            if (request.Method != HttpMethod.Get || request.RequestUri != new Uri(Launcher.Panel,
                "api/jobs/a1b2c3d4e5f6a7b8/hiddify-admin") ||
                String.Join("", request.Headers.GetValues("X-Admin-Token")) != token)
                throw new Exception("Hiddify lookup must use authenticated localhost GET only.");
            requests++;
            return new HttpResponseMessage((System.Net.HttpStatusCode)status) { Content = new StringContent(body) };
        }); };
        try
        {
            await view.CoreWebView2.ExecuteScriptAsync(
                "dialog(modalHead('Hiddify · 导航验证')+hiddifyAdminLink('a1b2c3d4e5f6a7b8'))");
            string click = "document.querySelector('a[href^=\"/static/hiddify-launch.html#\"]').click()";
            foreach (string action in new[] { click + ";" + click,
                "window.location.href='/static/hiddify-launch.html#a1b2c3d4e5f6a7b8'" })
            {
                Launcher.SmokeExternal = null;
                await view.CoreWebView2.ExecuteScriptAsync(action);
                for (int attempt = 0; attempt < 100 && (Launcher.SmokeExternal == null || openingHiddify); attempt++)
                    await Task.Delay(50);
                if (Launcher.SmokeExternal != destination || view.CoreWebView2.Source != panelSource || children.Count != 0)
                    throw new Exception("Hiddify did not open externally while retaining the original page.");
            }
            if (requests != 2) throw new Exception("Hiddify authenticated lookup was not exercised.");
            foreach (string invalid in new[] { "http://hiddify.example.invalid/", "https://user:secret@hiddify.example.invalid/", "javascript:alert(1)", "" })
            {
                body = new JavaScriptSerializer().Serialize(new { url = invalid });
                Launcher.SmokeExternal = null;
                int before = requests;
                await view.CoreWebView2.ExecuteScriptAsync(click);
                for (int attempt = 0; attempt < 100 && (requests == before || openingHiddify); attempt++) await Task.Delay(50);
                if (requests != before + 1 || Launcher.SmokeExternal != null || children.Count != 0 ||
                    view.CoreWebView2.Source != panelSource || await view.CoreWebView2.ExecuteScriptAsync(
                        "document.querySelector('#toast').textContent.includes('格式无效')") != "true")
                    throw new Exception("Invalid Hiddify URL was not rejected safely in the original page.");
            }
            foreach (int denied in new[] { 401, 302 })
            {
                status = denied;
                int deniedBefore = requests;
                await view.CoreWebView2.ExecuteScriptAsync(click);
                for (int attempt = 0; attempt < 100 && (requests == deniedBefore || openingHiddify); attempt++) await Task.Delay(50);
                if (Launcher.SmokeExternal != null || children.Count != 0 || view.CoreWebView2.Source != panelSource ||
                    await view.CoreWebView2.ExecuteScriptAsync(
                        "document.querySelector('#toast').textContent.includes('HTTP " + denied + "')") != "true")
                    throw new Exception("Hiddify API failure did not remain visible in the original page.");
            }
            int invalidBefore = requests;
            await view.CoreWebView2.ExecuteScriptAsync("window.open('/static/hiddify-launch.html#invalid','_blank')");
            for (int attempt = 0; attempt < 100; attempt++)
            {
                if (await view.CoreWebView2.ExecuteScriptAsync(
                    "document.querySelector('#toast').textContent.includes('任务编号无效')") == "true" && !openingHiddify) break;
                await Task.Delay(50);
            }
            if (requests != invalidBefore || children.Count != 0 || Launcher.SmokeExternal != null ||
                await view.CoreWebView2.ExecuteScriptAsync("document.querySelector('#toast').textContent.includes('任务编号无效')") != "true")
                throw new Exception("Invalid Hiddify task must not make an authenticated lookup or open a window.");
            await view.CoreWebView2.ExecuteScriptAsync("closeDialog()");
        }
        finally { hiddifyHandler = null; }
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
