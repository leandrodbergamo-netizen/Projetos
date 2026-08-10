# Cria a tarefa agendada que atualiza as planilhas todo dia às 09:00.
# Se o computador estiver desligado/deslogado no horario, a tarefa roda
# assim que voce logar (StartWhenAvailable + execucao apenas com usuario logado).
#
# Uso:  botao direito > "Executar com PowerShell"  (ou)  powershell -File setup_agendador.ps1

$ErrorActionPreference = "Stop"
$proj = Split-Path -Parent $MyInvocation.MyCommand.Path
$nome = "RemanejamentoRefreshBases"

# Caminho completo do python (Task Scheduler nao usa o PATH do usuario).
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $python) { throw "Python nao encontrado no PATH. Instale ou ajuste manualmente." }

$action = New-ScheduledTaskAction -Execute $python -Argument "refresh_bases.py" -WorkingDirectory $proj
$trigger = New-ScheduledTaskTrigger -Daily -At 9:00AM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $nome -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Tarefa '$nome' criada: todo dia 09:00 (roda ao logar se perdida)." -ForegroundColor Green
Write-Host "Python: $python"
Write-Host "Projeto: $proj"
Write-Host "Para testar agora:  Start-ScheduledTask -TaskName $nome"
Write-Host "Para remover:       Unregister-ScheduledTask -TaskName $nome -Confirm:`$false"
