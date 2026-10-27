Option Explicit
Dim launcherShell, launcherFiles, launcherRoot, launcherElectron
Set launcherShell = CreateObject("WScript.Shell")
Set launcherFiles = CreateObject("Scripting.FileSystemObject")
launcherRoot = launcherFiles.GetParentFolderName(WScript.ScriptFullName)
launcherElectron = launcherFiles.BuildPath(launcherRoot, "node_modules\electron\dist\electron.exe")
If Not launcherFiles.FileExists(launcherElectron) Then
  MsgBox "Electron is missing. Run setup_studyforge.cmd in this folder first.", 16, "StudyForge"
  WScript.Quit 1
End If
launcherShell.CurrentDirectory = launcherRoot
launcherShell.Run Chr(34) & launcherElectron & Chr(34) & " " & Chr(34) & launcherRoot & Chr(34), 1, False
