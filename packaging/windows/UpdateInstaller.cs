using System;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using System.Collections.Generic;

// Runs from the user's staging directory, never from files being overwritten.
internal static class UpdateInstaller
{
    internal static string Quote(string value)
    {
        var text = new System.Text.StringBuilder("\""); int slashes = 0;
        foreach (char c in value)
        {
            if (c == '\\') { slashes++; continue; }
            text.Append('\\', c == '"' ? slashes * 2 + 1 : slashes); text.Append(c); slashes = 0;
        }
        return text.Append('\\', slashes * 2).Append('"').ToString();
    }

    private static int Run(string file, string arguments, string root, int seconds)
    {
        using (var process = Process.Start(new ProcessStartInfo(file, arguments) {
            WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true }))
        {
            if (!process.WaitForExit(seconds * 1000)) throw new IOException("更新步骤尚未结束，请查看更新日志后再操作。");
            return process.ExitCode;
        }
    }

    [STAThread]
    private static int Main(string[] args)
    {
        string root = null, home = null, log = null; bool stopped = false;
        try
        {
            if (args.Length != 7) throw new ArgumentException("更新参数不完整。");
            root = Path.GetFullPath(args[0]); home = Path.GetFullPath(args[1]);
            int port = int.Parse(args[2]), worker = int.Parse(args[3]);
            string setup = Path.GetFullPath(args[4]), expected = args[5], version = args[6];
            DesktopUpdates.ParseVersion(version);
            if (port < 1 || port > 65535 || worker < 1 || worker > 65535 || port == worker ||
                !Regex.IsMatch(expected, "^[a-f0-9]{64}$") ||
                Path.GetFileName(setup) != "NetDeployAI-" + version + "-Setup-x64.exe")
                throw new ArgumentException("更新参数未通过校验。");
            string executable = Path.Combine(root, "NetDeployAI.exe");
            if (!File.Exists(executable) || DesktopUpdates.Hash(setup) != expected)
                throw new IOException("安装包校验失败，原程序未修改，请重新下载。");
            log = Path.Combine(Path.GetDirectoryName(setup), "install.log");
            Environment.SetEnvironmentVariable("NETDEPLOY_DESKTOP_HOME", home);
            Environment.SetEnvironmentVariable("NETDEPLOY_DESKTOP_PORT", port.ToString());
            Environment.SetEnvironmentVariable("NETDEPLOY_DESKTOP_WORKER_PORT", worker.ToString());
            string options = " --quiet --home " + Quote(home) + " --port " + port + " --worker-port " + worker;
            if (Run(executable, "--stop" + options, root, 40) != 0)
                throw new IOException("请先等待正在执行的部署任务结束，再点击版本号重试更新。");
            stopped = true;
            if (Run(Path.Combine(root, "runtime", "python.exe"), "-I " +
                Quote(Path.Combine(root, "app", "desktop_update.py")) + " --home " + Quote(home), root, 60) != 0)
                throw new IOException("更新前备份失败，尚未安装新版。请检查磁盘空间后重试。");
            // The package is checked again immediately before execution.
            if (DesktopUpdates.Hash(setup) != expected) throw new IOException("安装包已发生变化，已停止更新。");
            int code = Run(setup, "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /DIR=" + Quote(root) +
                " /LOG=" + Quote(log), root, 300);
            if (code != 0 && code != 3010) throw new IOException("安装未完成（代码 " + code + "）。请查看更新日志或手动覆盖安装。");
            Process.Start(new ProcessStartInfo(executable, options) { UseShellExecute = false, WorkingDirectory = root });
            stopped = false;
            using (var client = new HttpClient(new HttpClientHandler { UseProxy = false }))
            {
                client.Timeout = TimeSpan.FromSeconds(2);
                for (int attempt = 0; attempt < 60; attempt++)
                {
                    try
                    {
                        var health = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(
                            client.GetStringAsync("http://127.0.0.1:" + port + "/api/health").GetAwaiter().GetResult());
                        if (Convert.ToString(health["version"]) == version && Convert.ToString(health["security"]) == "local-only") return 0;
                    }
                    catch (Exception) { }
                    Thread.Sleep(500);
                }
            }
            throw new IOException("新版已安装，客户端启动尚未确认。请重新打开 NetDeploy AI。");
        }
        catch (Exception error)
        {
            if (stopped && root != null)
            {
                try { Process.Start(new ProcessStartInfo(Path.Combine(root, "NetDeployAI.exe")) {
                    WorkingDirectory = root, UseShellExecute = false }); } catch (Exception) { }
            }
            string text = error.Message + (log == null ? "" : "\n更新日志：" + log);
            if (log != null) File.WriteAllText(log + ".error.txt", text);
            MessageBox.Show(text, "NetDeploy AI · 更新未完成", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return 1;
        }
    }
}
