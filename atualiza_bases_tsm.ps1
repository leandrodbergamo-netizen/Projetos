$ErrorActionPreference = "Stop"
$arquivo = "C:\Users\LeandroDias\Projetos\dados\Bases_TSM.xlsx"
$logDir  = "C:\Users\LeandroDias\Projetos\dados\logs"
if (!(Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir ("atualiza_{0:yyyyMMdd}.log" -f (Get-Date))
function Log($m){ "{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m | Out-File $log -Append -Encoding utf8 }

Log "=== Inicio ==="
$excel = $null
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $wb = $excel.Workbooks.Open($arquivo)
    foreach ($c in $wb.Connections) {
        try { $c.OLEDBConnection.BackgroundQuery = $false } catch {}
    }
    $wb.RefreshAll()
    $excel.CalculateUntilAsyncQueriesDone()
    $wb.Save()
    $wb.Close($false)
    Log "Atualizacao concluida com sucesso"
}
catch {
    Log ("ERRO: " + $_.Exception.Message)
    throw
}
finally {
    if ($excel) { $excel.Quit(); [Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null }
    [GC]::Collect(); [GC]::WaitForPendingFinalizers()
    Log "=== Fim ==="
}
