param(
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$Config,
    [string]$TaskName = "QwenPaw"
)
$ErrorActionPreference = "Stop"
$taskPython = (Resolve-Path -LiteralPath $Python).Path
$taskConfig = (Resolve-Path -LiteralPath $Config).Path
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    throw "任务已存在，请使用任务计划程序检查后再修改。"
}
$taskAction = New-ScheduledTaskAction -Execute $taskPython -Argument "-m qwenpaw service --config `"$taskConfig`" run" -WorkingDirectory (Split-Path $taskPython)
$taskTrigger = New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
$taskSettings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $taskAction -Trigger $taskTrigger -Settings $taskSettings -Description "QwenPaw 用户登录后运行；配置必须使用绝对路径" | Out-Null
Write-Output "已登记登录自启动任务 $TaskName。无用户登录的开机启动请在任务计划程序中配置运行账户与启动触发器。"
