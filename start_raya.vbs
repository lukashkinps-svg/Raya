Option Explicit
Dim shell, fso, folder, launcher

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
launcher = folder & "\start_windows.bat"

If Not fso.FileExists(launcher) Then
    MsgBox "File start_windows.bat was not found beside this launcher.", vbCritical, "Raya Prime"
    WScript.Quit 1
End If

shell.CurrentDirectory = folder
' Run the setup/launcher invisibly. It starts the GUI Python process
' independently and exits; closing this script will not close Raya.
shell.Run Chr(34) & launcher & Chr(34) & " --hidden", 0, False
