param([string]$Title,[string]$ScreenshotOut)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class StudyForgeToastMouse {
 [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
 [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT point);
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
 [DllImport("user32.dll")] public static extern void mouse_event(uint flag,uint x,uint y,uint data,UIntPtr extra);
}
'@
$sfFound=$null
$sfDeadline=[DateTime]::UtcNow.AddSeconds(4)
$sfCondition=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,$Title)
while([DateTime]::UtcNow -lt $sfDeadline){
  $sfElements=[System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Descendants,$sfCondition)
  foreach($sfElement in $sfElements){if(-not $sfElement.Current.IsOffscreen -and $sfElement.Current.BoundingRectangle.Width -gt 10){$sfFound=$sfElement;break}}
  if(-not $sfFound){
    $sfTexts=[System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
    foreach($sfElement in $sfTexts){
      try{if($sfElement.Current.Name -like '*Windows 桌面通知测试*' -and -not $sfElement.Current.IsOffscreen -and $sfElement.Current.BoundingRectangle.Width -gt 50){$sfFound=$sfElement;break}}catch{}
    }
  }
  if($sfFound){break}
  Start-Sleep -Milliseconds 100
}
if(-not $sfFound){@{clicked=$false;reason='Windows banner not found; notification may be in the notification center or suppressed by system settings.'}|ConvertTo-Json -Compress;exit 0}
$sfBounds=$sfFound.Current.BoundingRectangle
if($ScreenshotOut){
  $sfCapture=$sfFound
  $sfWalker=[System.Windows.Automation.TreeWalker]::ControlViewWalker
  for($sfIndex=0;$sfIndex -lt 4;$sfIndex++){
    $sfParent=$sfWalker.GetParent($sfCapture);if(-not $sfParent){break}
    $sfArea=$sfParent.Current.BoundingRectangle
    if($sfArea.Width -gt 700 -or $sfArea.Height -gt 700 -or $sfArea.Width -lt 10){break}
    $sfCapture=$sfParent
  }
  $sfArea=$sfCapture.Current.BoundingRectangle
  $sfBitmap=New-Object System.Drawing.Bitmap([int]$sfArea.Width,[int]$sfArea.Height)
  $sfGraphics=[System.Drawing.Graphics]::FromImage($sfBitmap)
  try{$sfGraphics.CopyFromScreen([int]$sfArea.X,[int]$sfArea.Y,0,0,$sfBitmap.Size);$sfBitmap.Save($ScreenshotOut,[System.Drawing.Imaging.ImageFormat]::Png)}
  finally{$sfGraphics.Dispose();$sfBitmap.Dispose()}
}
$sfCursor=New-Object StudyForgeToastMouse+POINT
$null=[StudyForgeToastMouse]::GetCursorPos([ref]$sfCursor)
try{
  $null=[StudyForgeToastMouse]::SetCursorPos([int]($sfBounds.X+$sfBounds.Width/2),[int]($sfBounds.Y+$sfBounds.Height/2))
  [StudyForgeToastMouse]::mouse_event(2,0,0,0,[UIntPtr]::Zero)
  [StudyForgeToastMouse]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
}finally{$null=[StudyForgeToastMouse]::SetCursorPos($sfCursor.X,$sfCursor.Y)}
@{clicked=$true;title=$Title}|ConvertTo-Json -Compress
