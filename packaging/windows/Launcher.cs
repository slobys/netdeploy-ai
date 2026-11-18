using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("NetDeploy AI")]
[assembly: AssemblyDescription("NetDeploy AI desktop client")]
[assembly: AssemblyCompany("NetDeploy AI")]
[assembly: AssemblyProduct("NetDeploy AI")]
[assembly: System.Runtime.Versioning.TargetFramework(".NETFramework,Version=v4.8")]
[assembly: AssemblyVersion("0.3.48.0")]
[assembly: AssemblyFileVersion("0.3.48.0")]

internal static class Launcher
{
    // Follow the Windows CommandLineToArgvW quoting rules, including trailing slashes.
    internal static string Root = AppDomain.CurrentDomain.BaseDirectory;
    internal static string Home;
    internal static Uri Panel;
    internal static int WorkerPort;
    internal static bool Smoke;
    internal static Uri SmokeExternal;
    internal static int Result;

    internal static string Quote(string value)
    {
        var text = new System.Text.StringBuilder("\"");
        int slashes = 0;
        foreach (char character in value)
        {
            if (character == '\\') { slashes++; continue; }
            if (character == '"')
                text.Append('\\', slashes * 2 + 1);
            else
                text.Append('\\', slashes);
            text.Append(character);
            slashes = 0;
        }
        text.Append('\\', slashes * 2);
        return text.Append('"').ToString();
    }

    private static string Option(string[] args, string key, string fallback)
    {
        int index = Array.IndexOf(args, key);
        return index >= 0 && index + 1 < args.Length ? args[index + 1] : fallback;
    }

    internal static bool Local(Uri uri)
    {
        return uri.Scheme == Panel.Scheme && uri.Host == Panel.Host && uri.Port == Panel.Port;
    }

    internal static bool Authorization(Uri uri)
    {
        return uri.Scheme == "https" && (uri.Host == "auth.openai.com" || uri.Host == "chatgpt.com");
    }

    internal static bool Documentation(Uri uri)
    {
        return uri.Scheme == "https" && uri.Host == "slobys.github.io" &&
            (uri.AbsolutePath == "/netdeploy-ai" || uri.AbsolutePath.StartsWith("/netdeploy-ai/", StringComparison.Ordinal));
    }

    internal static void External(Uri uri)
    {
        if (Smoke) { SmokeExternal = uri; return; }
        Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true });
    }

    private static void Signal(string name)
    {
        try { using (var signal = EventWaitHandle.OpenExisting(name)) signal.Set(); }
        catch (WaitHandleCannotBeOpenedException) { }
    }

    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            // Configure WinForms DPI handling before any window or WebView is created.
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Home = Path.GetFullPath(Option(args, "--home",
                Environment.GetEnvironmentVariable("NETDEPLOY_DESKTOP_HOME") ??
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "NetDeployAI", "desktop")));
            int port = int.Parse(Option(args, "--port",
                Environment.GetEnvironmentVariable("NETDEPLOY_DESKTOP_PORT") ?? "8787"));
            Panel = new Uri("http://127.0.0.1:" + port + "/");
            WorkerPort = int.Parse(Option(args, "--worker-port",
                Environment.GetEnvironmentVariable("NETDEPLOY_DESKTOP_WORKER_PORT") ?? "8789"));
            Smoke = Array.IndexOf(args, "--ui-smoke") >= 0;
            string key;
            using (var sha = SHA256.Create())
                key = BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(Home.ToUpperInvariant() + port))).Replace("-", "");
            string name = @"Local\NetDeployAI.Client." + key;
            string command = "-I " + Quote(Path.Combine(Root, "app", "desktop.py")) + " --no-browser";
            foreach (string argument in args)
                if (argument != "--ui-smoke") command += " " + Quote(argument);
            ProcessStartInfo start = new ProcessStartInfo(Path.Combine(Root, "runtime", "pythonw.exe"), command);
            start.WorkingDirectory = Root;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            using (Process process = Process.Start(start))
            {
                if (Array.IndexOf(args, "--stop") >= 0)
                {
                    if (!process.WaitForExit(20000)) return 1;
                    if (process.ExitCode == 0)
                    {
                        Signal(name + ".Exit");
                        try
                        {
                            using (var windowMutex = Mutex.OpenExisting(name))
                            {
                                if (!windowMutex.WaitOne(10000)) return 1;
                                windowMutex.ReleaseMutex();
                            }
                        }
                        catch (WaitHandleCannotBeOpenedException) { }
                        catch (AbandonedMutexException) { }
                    }
                    return process.ExitCode;
                }
            }
            if (Array.IndexOf(args, "--no-browser") >= 0) return 0;
            bool first;
            using (var mutex = new Mutex(true, name, out first))
            {
                if (!first) { Signal(name + ".Focus"); return 0; }
                using (var focus = new EventWaitHandle(false, EventResetMode.AutoReset, name + ".Focus"))
                using (var exit = new EventWaitHandle(false, EventResetMode.AutoReset, name + ".Exit"))
                using (var window = new ClientWindow(true))
                {
                    var focusWait = ThreadPool.RegisterWaitForSingleObject(focus, delegate {
                        window.OnUi(window.FocusWindow);
                    }, null, -1, false);
                    var exitWait = ThreadPool.RegisterWaitForSingleObject(exit, delegate {
                        window.OnUi(delegate { window.Close(); });
                    }, null, -1, false);
                    Application.Run(window);
                    focusWait.Unregister(null);
                    exitWait.Unregister(null);
                }
                mutex.ReleaseMutex();
            }
            return Result;
        }
        catch (Exception error)
        {
            if (Array.IndexOf(args, "--quiet") < 0)
                MessageBox.Show(error.Message, "NetDeploy AI", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
