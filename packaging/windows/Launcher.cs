using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("NetDeploy AI")]
[assembly: AssemblyDescription("NetDeploy AI Windows launcher")]
[assembly: AssemblyCompany("NetDeploy AI")]
[assembly: AssemblyProduct("NetDeploy AI")]
[assembly: AssemblyVersion("0.3.32.0")]
[assembly: AssemblyFileVersion("0.3.32.0")]

internal static class Launcher
{
    // Follow the Windows CommandLineToArgvW quoting rules, including trailing slashes.
    private static string Quote(string value)
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

    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string python = Path.Combine(root, "runtime", "pythonw.exe");
            string command = "-I " + Quote(Path.Combine(root, "app", "desktop.py"));
            foreach (string argument in args) command += " " + Quote(argument);
            ProcessStartInfo start = new ProcessStartInfo(python, command);
            start.WorkingDirectory = root;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            Process process = Process.Start(start);
            if (Array.IndexOf(args, "--stop") >= 0)
            {
                if (!process.WaitForExit(20000)) return 1;
                return process.ExitCode;
            }
            return 0;
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "NetDeploy AI", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
