param(
    [Parameter(Mandatory = $true)]
    [string]$RetroArch,
    [Parameter(Mandatory = $true)]
    [string]$Core,
    [Parameter(Mandatory = $true)]
    [string]$Content,
    [Parameter(Mandatory = $true)]
    [string]$Config,
    [Parameter(Mandatory = $true)]
    [string]$CapturePath
)

Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;

public static class RetroInput {
    [StructLayout(LayoutKind.Sequential)]
    public struct INPUT {
        public uint type;
        public InputUnion data;
    }

    [StructLayout(LayoutKind.Explicit)]
    public struct InputUnion {
        [FieldOffset(0)] public KEYBDINPUT keyboard;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct KEYBDINPUT {
        public ushort virtualKey;
        public ushort scanCode;
        public uint flags;
        public uint time;
        public IntPtr extraInfo;
    }

    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr window);

    [DllImport("user32.dll")]
    public static extern bool ShowWindowAsync(IntPtr window, int command);

    [DllImport("user32.dll")]
    public static extern bool BringWindowToTop(IntPtr window);

    [DllImport("user32.dll")]
    public static extern bool IsIconic(IntPtr window);

    [DllImport("user32.dll")]
    public static extern bool SetWindowPos(
        IntPtr window,
        IntPtr insertAfter,
        int x,
        int y,
        int width,
        int height,
        uint flags
    );

    [DllImport("user32.dll")]
    public static extern void SwitchToThisWindow(IntPtr window, bool altTab);

    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT {
        public int left;
        public int top;
        public int right;
        public int bottom;
    }

    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr window, out RECT rectangle);

    [DllImport("user32.dll")]
    public static extern uint SendInput(uint count, INPUT[] inputs, int size);

    public static void Scan(ushort scanCode) {
        INPUT[] inputs = new INPUT[1];
        inputs[0].type = 1;
        inputs[0].data.keyboard.scanCode = scanCode;
        inputs[0].data.keyboard.flags = 0x0008;
        SendInput(1, inputs, Marshal.SizeOf(typeof(INPUT)));
        System.Threading.Thread.Sleep(250);
        inputs[0].data.keyboard.flags = 0x0008 | 0x0002;
        SendInput(1, inputs, Marshal.SizeOf(typeof(INPUT)));
    }
}
"@

$argumentLine = '-L "{0}" --config "{1}" -M noload-nosave "{2}"' -f (
    $Core,
    $Config,
    $Content
)
$process = Start-Process -FilePath $RetroArch -ArgumentList $argumentLine -WindowStyle Normal -PassThru
$deadline = (Get-Date).AddSeconds(15)
do {
    Start-Sleep -Milliseconds 250
    $process.Refresh()
    if ($process.HasExited) {
        throw "RetroArch exited before creating a test window (exit code $($process.ExitCode))."
    }
} while (($null -eq $process.MainWindowHandle -or $process.MainWindowHandle -eq [IntPtr]::Zero) -and (Get-Date) -lt $deadline)

$window = [IntPtr]$process.MainWindowHandle
if ($window -eq [IntPtr]::Zero) {
    throw "RetroArch did not create a test window."
}

for ($attempt = 0; $attempt -lt 20; $attempt++) {
    $process.Refresh()
    if ($process.HasExited) {
        throw "RetroArch exited while waiting for foreground focus (exit code $($process.ExitCode))."
    }

    if ($process.MainWindowHandle -ne [IntPtr]::Zero) {
        $window = [IntPtr]$process.MainWindowHandle
    }

    # RetroArch can briefly minimize itself while the core/content window is
    # being initialized. Restore it on every attempt, then force it to the top.
    [RetroInput]::ShowWindowAsync($window, 9) | Out-Null
    [RetroInput]::ShowWindowAsync($window, 5) | Out-Null
    [RetroInput]::SetWindowPos($window, [IntPtr]::Zero, 0, 0, 0, 0, 0x0043) | Out-Null
    [RetroInput]::BringWindowToTop($window) | Out-Null
    [RetroInput]::SetForegroundWindow($window) | Out-Null

    if ([RetroInput]::GetForegroundWindow() -eq $window -and -not [RetroInput]::IsIconic($window)) {
        break
    }

    if ($attempt -eq 4 -or $attempt -eq 9 -or $attempt -eq 14) {
        [RetroInput]::SwitchToThisWindow($window, $true)
    }
    Start-Sleep -Milliseconds 250
}

if ([RetroInput]::GetForegroundWindow() -ne $window -or [RetroInput]::IsIconic($window)) {
    throw "RetroArch remained minimized or did not receive foreground focus; no test input was sent."
}

[RetroInput]::SetForegroundWindow($window) | Out-Null
Start-Sleep -Milliseconds 250
[RetroInput]::Scan(0x2D)
Start-Sleep -Seconds 6
$rectangle = New-Object RetroInput+RECT
if (-not [RetroInput]::GetWindowRect($window, [ref]$rectangle)) {
    throw "Could not read the RetroArch window bounds."
}
$width = $rectangle.right - $rectangle.left
$height = $rectangle.bottom - $rectangle.top
$bitmap = New-Object System.Drawing.Bitmap($width, $height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($rectangle.left, $rectangle.top, 0, 0, $bitmap.Size)
$bitmap.Save($CapturePath, [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()
$process.CloseMainWindow() | Out-Null
if (-not $process.WaitForExit(5000)) {
    $process.Kill()
    $process.WaitForExit()
}
