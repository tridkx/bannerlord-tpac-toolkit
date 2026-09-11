param(
  [int]$x = -1,
  [int]$y = -1,
  [string]$out = ".\shot_ui.png",
  [int]$wait = 2500,
  [int]$foreground = 0
)
Add-Type @"
using System;
using System.Drawing;
using System.Runtime.InteropServices;
public class U {
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern IntPtr PostMessage(IntPtr h, uint msg, IntPtr wp, IntPtr lp);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  public struct RECT { public int L, T, R, B; }
}
"@ -ReferencedAssemblies System.Drawing,System.Windows.Forms

$name = if ($env:CAP_PROC) { $env:CAP_PROC } else { "Bannerlord" }
$p = Get-Process $name -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { "$name window not found"; exit 1 }
$h = $p.MainWindowHandle
$r = New-Object U+RECT
[U]::GetWindowRect($h, [ref]$r) | Out-Null

if ($x -ge 0) {
  if ($foreground -eq 1) {
    # unlock the foreground lock with a synthetic ALT press, then focus the game
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.SendKeys]::SendWait("%")
    Start-Sleep -Milliseconds 200
    [U]::ShowWindow($h, 9) | Out-Null
    [U]::SetForegroundWindow($h) | Out-Null
    Start-Sleep -Milliseconds 900
    [U]::SetCursorPos($r.L + $x, $r.T + $y) | Out-Null
    Start-Sleep -Milliseconds 250
    [U]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero)   # LEFTDOWN
    Start-Sleep -Milliseconds 110
    [U]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero)   # LEFTUP
    "real click at $($r.L+$x),$($r.T+$y) focused=" + ([U]::GetForegroundWindow() -eq $h)
  } else {
    $lp = [IntPtr](($y -shl 16) -bor ($x -band 0xFFFF))
    [U]::PostMessage($h, 0x0200, [IntPtr]0, $lp) | Out-Null
    Start-Sleep -Milliseconds 150
    [U]::PostMessage($h, 0x0201, [IntPtr]1, $lp) | Out-Null
    Start-Sleep -Milliseconds 90
    [U]::PostMessage($h, 0x0202, [IntPtr]0, $lp) | Out-Null
    "posted click at $x,$y"
  }
  Start-Sleep -Milliseconds $wait
}

$w = $r.R - $r.L; $ht = $r.B - $r.T
$bmp = New-Object System.Drawing.Bitmap $w, $ht
$g = [System.Drawing.Graphics]::FromImage($bmp)
$dc = $g.GetHdc()
[U]::PrintWindow($h, $dc, 2) | Out-Null
$g.ReleaseHdc($dc)
$bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
"saved $out"
