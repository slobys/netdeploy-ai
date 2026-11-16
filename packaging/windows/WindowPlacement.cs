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
        window.WindowState = FormWindowState.Maximized;
        try
        {
            string file = FileName(main);
            if (!File.Exists(file)) return;
            var placement = new JavaScriptSerializer().Deserialize<Placement>(File.ReadAllText(file));
            var bounds = placement.NormalPosition;
            long width = (long)bounds.Right - bounds.Left, height = (long)bounds.Bottom - bounds.Top;
            if (width < 200 || height < 150 || width > 32768 || height > 32768 ||
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
