using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal static class WindowPlacement
{
    [StructLayout(LayoutKind.Sequential)]
    public struct Point { public int X, Y; }
    [StructLayout(LayoutKind.Sequential)]
    public struct Rect { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)]
    public struct Placement
    {
        public int Length, Flags, ShowCommand;
        public Point MinimumPosition, MaximumPosition;
        public Rect NormalPosition;
    }

    [DllImport("user32.dll")]
    private static extern bool GetWindowPlacement(IntPtr window, ref Placement placement);
    [DllImport("user32.dll")]
    private static extern bool SetWindowPlacement(IntPtr window, ref Placement placement);

    private static string FileName(bool main)
    {
        return Path.Combine(Launcher.Home, main ? "window-main.json" : "window-panel.json");
    }

    internal static void Restore(Form window, bool main)
    {
        window.WindowState = FormWindowState.Normal;
        var area = Screen.FromControl(window).WorkingArea;
        double scale = window.DeviceDpi / 96.0;
        window.MinimumSize = new System.Drawing.Size(Math.Min((int)(900 * scale), (int)(area.Width * .92)),
            Math.Min((int)(640 * scale), (int)(area.Height * .92)));
        int width = Math.Min((int)(1440 * scale), (int)(area.Width * .92));
        int height = Math.Min((int)(1000 * scale), (int)(area.Height * .92));
        window.StartPosition = FormStartPosition.Manual;
        window.Bounds = new System.Drawing.Rectangle(area.Left + (area.Width - width) / 2,
            area.Top + (area.Height - height) / 2, width, height);
        try
        {
            string file = FileName(main);
            if (!File.Exists(file)) return;
            var placement = new JavaScriptSerializer().Deserialize<Placement>(File.ReadAllText(file));
            var bounds = placement.NormalPosition;
            long savedWidth = (long)bounds.Right - bounds.Left, savedHeight = (long)bounds.Bottom - bounds.Top;
            if (savedWidth < 200 || savedHeight < 150 || savedWidth > 32768 || savedHeight > 32768 ||
                (placement.ShowCommand != 1 && placement.ShowCommand != 3)) return;
            placement.Length = Marshal.SizeOf(typeof(Placement));
            placement.Flags = 0;
            window.StartPosition = FormStartPosition.Manual;
            // Keep workspace coordinates together with SetWindowPlacement; Windows
            // also brings completely off-screen positions back onto a display.
            SetWindowPlacement(window.Handle, ref placement);
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
        catch (ArgumentException) { }
        catch (InvalidOperationException) { }
    }

    internal static void Save(Form window, bool main, FormWindowState visibleState)
    {
        if (!window.IsHandleCreated) return;
        try
        {
            var placement = new Placement { Length = Marshal.SizeOf(typeof(Placement)) };
            if (!GetWindowPlacement(window.Handle, ref placement)) return;
            // Closing while minimized should reopen in the last visible state.
            placement.ShowCommand = visibleState == FormWindowState.Maximized ? 3 : 1;
            placement.Flags = 0;
            Directory.CreateDirectory(Launcher.Home);
            string file = FileName(main), temporary = file + ".tmp";
            File.WriteAllText(temporary, new JavaScriptSerializer().Serialize(placement));
            if (File.Exists(file)) File.Replace(temporary, file, null);
            else File.Move(temporary, file);
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }
}
