# Cria a tarefa agendada da auditoria de completeness.
#
# Roda as 09:30, depois do refresh das bases em Projetos\dados (Power Automate)
# e da tarefa do reabastecimento, que roda as 09:00. Se o PC estiver desligado
# no horario, a tarefa executa assim que voce logar (StartWhenAvailable).
#
# Uso:  botao direito > "Executar com PowerShell"  (ou)  powershell -File setup_agendador.ps1

$ErrorActionPreference = "Stop"
$proj = Split-Path -Parent $MyInvocation.MyCommand.Path
$nome = "CompletenessSouqDiario"
$hora = "09:30"

# Caminho completo do python (o Agendador nao usa o PATH do usuario).
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $python) { throw "Python nao encontrado no PATH. Instale ou ajuste manualmente." }

$action = New-ScheduledTaskAction -Execute $python -Argument "tarefa_diaria.py" -WorkingDirectory $proj
$trigger = New-ScheduledTaskTrigger -Daily -At $hora
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $nome -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Tarefa '$nome' criada: todo dia as $hora (roda ao logar se perdida)." -ForegroundColor Green
Write-Host "Python:  $python"
Write-Host "Projeto: $proj"
Write-Host ""
Write-Host "Testar agora:  Start-ScheduledTask -TaskName $nome"
Write-Host "Ver log:       Get-Content '$proj\logs\completeness_*.log' -Tail 40"
Write-Host "Remover:       Unregister-ScheduledTask -TaskName $nome -Confirm:`$false"
