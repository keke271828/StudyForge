param([Parameter(Mandatory=$true)][string]$DocumentPath,
      [Parameter(Mandatory=$true)][string]$OutputDirectory,
      [string]$WorkspaceRoot)
$ErrorActionPreference='Stop'
if(-not $WorkspaceRoot){$WorkspaceRoot=Split-Path $PSScriptRoot -Parent}
$sfWorkspace=[System.IO.Path]::GetFullPath($WorkspaceRoot)
if(-not (Test-Path -LiteralPath (Join-Path $sfWorkspace 'studyforge\exporters.py'))){
  throw 'WorkspaceRoot must point to the StudyForge source workspace'
}
$sfRoot=[System.IO.Path]::GetFullPath((Join-Path $sfWorkspace 'build'))
$sfDocument=(Get-Item -LiteralPath $DocumentPath).FullName
$sfOutput=[System.IO.Path]::GetFullPath($OutputDirectory)
$sfPrefix=$sfRoot.TrimEnd('\')+'\'
if(-not $sfDocument.StartsWith($sfPrefix,[StringComparison]::OrdinalIgnoreCase) -or
   [System.IO.Path]::GetExtension($sfDocument) -ne '.docx' -or
   -not $sfOutput.StartsWith($sfPrefix,[StringComparison]::OrdinalIgnoreCase)){
  throw '只读验收当前工作区 build 下的 DOCX，PDF 也只能写到 build 内'
}
$sfExistingWordIds=@(Get-Process -Name WINWORD -ErrorAction SilentlyContinue|ForEach-Object {$_.Id})
[System.IO.Directory]::CreateDirectory($sfOutput)|Out-Null
$sfWord=$null;$sfOpened=$null;$sfOwnInstance=$false
$sfPdf=Join-Path $sfOutput 'rendered.pdf'
try{
  $sfWord=New-Object -ComObject Word.Application
  $sfNewWord=@(Get-Process -Name WINWORD -ErrorAction SilentlyContinue|Where-Object {$sfExistingWordIds -notcontains $_.Id})
  if($sfNewWord.Count -ne 1 -or $sfWord.Documents.Count -ne 0){
    throw '未取得独立 Word 进程，已保留用户的 Word 状态'
  }
  $sfOwnInstance=$true
  @{owned_process=$sfNewWord[0].Id;created_at=$sfNewWord[0].StartTime;prior_processes=$sfExistingWordIds}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $sfOutput 'word-process.json') -Encoding UTF8
  $sfWord.Visible=$false;$sfWord.DisplayAlerts=0;$sfWord.AutomationSecurity=3
  $sfOpened=$sfWord.Documents.Open($sfDocument,$false,$true,$false)
  $sfOpened.Repaginate()
  $sfPages=$sfOpened.ComputeStatistics(2)
  $sfOpened.ExportAsFixedFormat($sfPdf,17)
  $sfResult=@{document=$sfDocument;pdf=$sfPdf;pages=$sfPages;read_only=$true;renderer='Microsoft Word'}
  $sfResult|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $sfOutput 'render.json') -Encoding UTF8
  $sfResult|ConvertTo-Json
}finally{
  if($sfOpened){$sfOpened.Close(0);[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($sfOpened)}
  if($sfWord){
    if($sfOwnInstance -and $sfWord.Documents.Count -eq 0){$sfWord.Quit(0)}
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($sfWord)
  }
}
