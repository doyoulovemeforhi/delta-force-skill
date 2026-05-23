param(
  [string]$Root = "D:\delta-force-skill-minimal",
  [int]$FallbackMinutes = 30,
  [int]$QuickRetrySeconds = 90,
  [int]$QuickRetryLimit = 2,
  [int]$BufferMinutes = 2,
  [ValidateSet("fixed", "profit")]
  [string]$ProductionMode = "fixed",
  [string[]]$FixedSpecs = @(
    "tech_center=AUG突击步枪",
    "workbench=5.45x39mm BS",
    "pharmacy_station=精密护甲维修包",
    "armor_bench=重型突击背心"
  ),
  [ValidateSet("hourlyProfit", "profit")]
  [string]$SwatMetric = "hourlyProfit",
  [switch]$AllowUnprofitable,
  [switch]$NotifyOnSuccess,
  [string[]]$NotifyProviders = @()
)

$ErrorActionPreference = "Continue"
Set-Location $Root

$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Convert-CommandOutputToJson {
  param($Output)
  $text = ($Output | Out-String).Trim()
  if (-not $text) { return $null }
  $start = $text.IndexOf("{")
  $end = $text.LastIndexOf("}")
  if ($start -lt 0 -or $end -le $start) { return $null }
  try { return $text.Substring($start, $end - $start + 1) | ConvertFrom-Json } catch { return $null }
}

function Resolve-CcConnectCommand {
  $local = Join-Path $Root "cc-connect.cmd"
  if (Test-Path -LiteralPath $local) { return $local }
  $cmd = Get-Command "cc-connect.cmd" -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $exe = Get-Command "cc-connect" -ErrorAction SilentlyContinue
  if ($exe) { return $exe.Source }
  return $null
}

function Format-ListOrNone {
  param($Items)
  $values = @($Items) | Where-Object { $_ }
  if ($values.Count -gt 0) { return ($values -join "、") }
  return "无"
}

function Get-StationDisplayName {
  param($Station)
  switch ([string]$Station) {
    "tech_center" { return "技术中心" }
    "workbench" { return "工作台" }
    "pharmacy_station" { return "制药台" }
    "armor_bench" { return "防具台" }
    default { return [string]$Station }
  }
}

function Get-ItemDisplayName {
  param($Station, $ItemName, $DisplayName)
  $raw = if ($DisplayName) { [string]$DisplayName } elseif ($ItemName) { [string]$ItemName } else { "" }
  if ($raw -match "4\\.6x30mm|4\\.6") { return "4.6x30mm" }
  if ($raw -match "5\\.45x39mm\\s*BS") { return "5.45x39mm BS" }
  if ($raw -match "762x51mm|M62") { return "7.62x51mm M62" }
  if ($raw -match "AUG") { return "AUG突击步枪" }
  if ($raw -match "重型突击背心") { return "重型突击背心" }
  switch ([string]$Station) {
    "tech_center" { return "AUG突击步枪" }
    "pharmacy_station" { return "精密护甲维修包" }
    "armor_bench" { return "重型突击背心" }
    default {
      if ($raw) { return $raw }
      return "未知物品"
    }
  }
}

function Get-ReasonDisplayName {
  param($Reason)
  switch ([string]$Reason) {
    "station_already_producing_until_next_collect" { return "正在生产中，未到收取时间" }
    "produce_button_not_found_after_fill" { return "一键补齐后未找到生产按钮" }
    "station_state_busy_or_not_ready" { return "正在生产或暂不可操作" }
    "station_state_complete_yellow" { return "已完成，等待收取后再生产" }
    "station_state_not_found" { return "未找到部门入口" }
    "item_not_selected" { return "未能选中生产物品" }
    "station_idle_slot_not_clicked" { return "未能点击空闲槽位" }
    "expected_profit_negative_after_fill_cost" { return "补齐后预期亏损，已跳过" }
    "expected_profit_negative" { return "预期亏损，已跳过" }
    "production_action_button_not_found" { return "未找到生产或补齐按钮" }
    "fill_confirm_not_clicked" { return "补齐确认未点击成功" }
    "one_click_fill_not_clicked" { return "一键补齐未点击成功" }
    "materials_not_ready" { return "材料未准备完成" }
    "game_unsafe_for_automation" { return "当前页面不适合自动化" }
    "game_window_not_ready" { return "游戏窗口不可用" }
    "station_item_mismatch" { return "物品与部门不匹配" }
    "unknown_station" { return "未知部门" }
    "not_complete_or_due" { return "未完成且未到收取时间" }
    "still_producing_no_yellow_badge" { return "未出现完成标记，判断仍在生产" }
    "due_without_yellow_cleared_idle" { return "到期但已空闲，可能已手动收取" }
    default {
      if ($Reason) { return [string]$Reason }
      return "未知原因"
    }
  }
}

function Format-NumberOrUnknown {
  param($Value)
  if ($null -eq $Value) { return "未知" }
  try {
    return ([double]$Value).ToString("N0")
  } catch {
    return [string]$Value
  }
}

function Format-TimeOrUnknown {
  param($Value)
  if ($null -eq $Value -or -not $Value) { return "未知" }
  try {
    return ([datetime]::Parse([string]$Value)).ToString("yyyy-MM-dd HH:mm:ss")
  } catch {
    return [string]$Value
  }
}

function Format-ProductionReports {
  param($Reports)
  $items = @($Reports) | Where-Object { $_ }
  if ($items.Count -eq 0) { return "无新增生产" }
  $lines = @()
  foreach ($report in $items) {
    $station = Get-StationDisplayName $report.station
    $name = Get-ItemDisplayName $report.station $report.itemName $report.displayName
    $cost = Format-NumberOrUnknown $report.estimatedCost
    $revenue = Format-NumberOrUnknown $report.expectedRevenue
    $profit = Format-NumberOrUnknown $report.expectedProfit
    $duration = if ($report.durationText) { $report.durationText } else { "未知" }
    $finishAt = Format-TimeOrUnknown $report.nextCollectAt
    $lines += "• $station"
    $lines += "  生产：$name"
    $lines += "  补齐花费：$cost"
    $lines += "  预期收入：$revenue"
    $lines += "  预期利润：$profit"
    $lines += "  生产耗时：$duration"
    $lines += "  预计完成：$finishAt"
  }
  return ($lines -join "`n")
}

function Format-SkippedReasons {
  param($Skipped, $Reasons)
  $items = @($Skipped) | Where-Object { $_ }
  if ($items.Count -eq 0) { return "无" }
  $lines = @()
  foreach ($item in $items) {
    $reason = $null
    if ($Reasons -and $Reasons.PSObject.Properties.Name -contains [string]$item) {
      $reason = $Reasons.([string]$item)
    }
    $label = Get-StationDisplayName $item
    if ($reason) {
      $lines += "$label($(Get-ReasonDisplayName $reason))"
    } else {
      $lines += [string]$label
    }
  }
  return ($lines -join "、")
}

function Format-SyncedTimes {
  param($UpdatedStations)
  $items = @($UpdatedStations) | Where-Object { $_ }
  if ($items.Count -eq 0) { return "无" }
  $lines = @()
  foreach ($item in $items) {
    $text = if ($item.text) { $item.text } else { "未知" }
    $finishAt = Format-TimeOrUnknown $item.nextCollectAt
    $label = Get-StationDisplayName $item.station
    $lines += "$label：剩余 $text，预计 $finishAt"
  }
  return ($lines -join "`n")
}

function Get-ProduceCommandArgs {
  if ($ProductionMode -eq "profit") {
    return @(
      "main.py",
      "produce_swat_products",
      "--metric",
      $SwatMetric
    )
  }

  return @(
    "main.py",
    "produce_station_items"
  ) + @($FixedSpecs | Where-Object { $_ })
}

function Get-ProduceSummary {
  param($ProduceJson)
  if (-not $ProduceJson) {
    return [pscustomobject]@{
      produced = @()
      productionReports = @()
      skipped = @()
      skippedReasons = $null
      planSummary = $null
      mode = $ProductionMode
    }
  }

  if ($ProduceJson.action -eq "produce_swat_products" -and $ProduceJson.execution) {
    $planSummary = $null
    if ($ProduceJson.plan -and $ProduceJson.plan.selected) {
      $planLines = @()
      foreach ($item in @($ProduceJson.plan.selected)) {
        $station = Get-StationDisplayName $item.station
        $name = if ($item.remoteItemName) { [string]$item.remoteItemName } else { Get-ItemDisplayName $item.station $item.localItemName $item.localItemName }
        $metricValue = Format-NumberOrUnknown $item.metricValue
        $metricLabel = if ($ProduceJson.metric -eq "profit") { "总利润" } else { "小时利润" }
        $planLines += "$station：$name（$metricLabel $metricValue）"
      }
      $planSummary = $planLines -join "`n"
    }
    return [pscustomobject]@{
      produced = if ($ProduceJson.execution.produced) { @($ProduceJson.execution.produced) } else { @() }
      productionReports = if ($ProduceJson.execution.productionReports) { @($ProduceJson.execution.productionReports) } else { @() }
      skipped = if ($ProduceJson.execution.skipped) { @($ProduceJson.execution.skipped) } else { @() }
      skippedReasons = if ($ProduceJson.execution.skippedReasons) { $ProduceJson.execution.skippedReasons } else { $null }
      planSummary = $planSummary
      mode = "profit"
    }
  }

  return [pscustomobject]@{
    produced = if ($ProduceJson.produced) { @($ProduceJson.produced) } else { @() }
    productionReports = if ($ProduceJson.productionReports) { @($ProduceJson.productionReports) } else { @() }
    skipped = if ($ProduceJson.skipped) { @($ProduceJson.skipped) } else { @() }
    skippedReasons = if ($ProduceJson.skippedReasons) { $ProduceJson.skippedReasons } else { $null }
    planSummary = $null
    mode = "fixed"
  }
}

function Send-CcConnectMessage {
  param([string]$Message, [string]$LogPath)
  $cc = Resolve-CcConnectCommand
  if ($cc) {
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $Message | & $cc send --data-dir "C:\Users\Administrator\.cc-connect" -p "delta-force-skill-minimal_deaac76e" --stdin
  } else {
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] cc-connect command not found; notification skipped" | Tee-Object -FilePath $LogPath -Append
  }
}

function Invoke-Round {
  $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
  $roundLog = Join-Path $LogDir "scheduled_collect_produce_$timestamp.log"
  "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] scheduled collect/produce started" | Tee-Object -FilePath $roundLog -Append

  $cleanup = & python main.py cleanup_artifacts 2>&1
  $cleanup | Tee-Object -FilePath $roundLog -Append | Out-Null

  $collect = & python main.py collect_completed 2>&1
  $collect | Tee-Object -FilePath $roundLog -Append | Out-Null

  $produceArgs = Get-ProduceCommandArgs
  $produce = & python @produceArgs 2>&1
  $produce | Tee-Object -FilePath $roundLog -Append | Out-Null

  $shot = & python main.py desktop_screenshot 2>&1
  $shot | Tee-Object -FilePath $roundLog -Append | Out-Null

  $sync = & python main.py sync_overview_remaining_times 2>&1
  $sync | Tee-Object -FilePath $roundLog -Append | Out-Null

  $collectJson = Convert-CommandOutputToJson $collect
  $produceJson = Convert-CommandOutputToJson $produce
  $syncJson = Convert-CommandOutputToJson $sync
  $produceSummary = Get-ProduceSummary $produceJson
  $collected = if ($collectJson -and $collectJson.collected) { @($collectJson.collected) } else { @() }
  $produced = @($produceSummary.produced)
  $collectSkipped = if ($collectJson -and $collectJson.skipped) { @($collectJson.skipped) } else { @() }
  $produceSkipped = @($produceSummary.skipped)
  $productionReports = @($produceSummary.productionReports)
  $syncUpdated = if ($syncJson -and $syncJson.updatedStations) { @($syncJson.updatedStations) } else { @() }
  $produceReasons = $produceSummary.skippedReasons
  $modeText = if ($produceSummary.mode -eq "profit") { "利润最优模式" } else { "固定物品模式" }
  $planBlock = if ($produceSummary.planSummary) { "利润计划：`n$($produceSummary.planSummary)`n`n" } else { "" }

  if ($NotifyOnSuccess) {
    $message = @"
三角洲行动特勤处自动任务已执行一轮。
$modeText
$planBlock收取：$(Format-ListOrNone @($collected | ForEach-Object { Get-StationDisplayName $_ }))

生产：
$(Format-ProductionReports $productionReports)

剩余时间：
$(Format-SyncedTimes $syncUpdated)

未收取：$(Format-ListOrNone @($collectSkipped | ForEach-Object { Get-StationDisplayName $_ }))
未生产：$(Format-SkippedReasons $produceSkipped $produceReasons)。

日志：$roundLog
"@
    Send-CcConnectMessage -Message $message -LogPath $roundLog
  }

  "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] scheduled collect/produce finished" | Tee-Object -FilePath $roundLog -Append
  return [pscustomobject]@{
    logPath = $roundLog
    collected = $collected
    produced = $produced
    productionReports = $productionReports
    synced = $syncUpdated
  }
}

function Send-AgentHelpRequest {
  param(
    [int]$FailureCount,
    [string]$LastLogPath,
    $ActionState
  )

  $due = if ($ActionState -and $ActionState.dueStations) { @($ActionState.dueStations) -join "、" } else { "无" }
  $idle = if ($ActionState -and $ActionState.idleStations) { @($ActionState.idleStations) -join "、" } else { "无" }
  $unknown = if ($ActionState -and $ActionState.unknownStations) { @($ActionState.unknownStations) -join "、" } else { "无" }
  $message = @"
三角洲行动特勤处自动循环连续 $FailureCount 轮未能解除待处理状态，需要人工协助。
当前仍待处理：$due
当前空闲：$idle
状态未知：$unknown
最后一轮日志：$LastLogPath
请检查游戏画面是否被弹窗遮挡、是否不在特勤处页面、黄色完成态/空闲中识别是否异常，或是否需要手动介入。
"@

  $cc = Resolve-CcConnectCommand
  Send-CcConnectMessage -Message $message -LogPath $LastLogPath
}

function Get-NextActionState {
  $output = & python main.py next_action 2>&1
  return Convert-CommandOutputToJson $output
}

function Get-NextSleepSeconds {
  $json = Get-NextActionState
  if (-not $json) { return $FallbackMinutes * 60 }
  if ($json.needAction) { return 0 }
  if ($json.nextSuggestedRun) {
    try {
      $next = [datetime]::Parse($json.nextSuggestedRun)
      return [Math]::Max(10, [int](($next - (Get-Date)).TotalSeconds) + ($BufferMinutes * 60))
    } catch {
      return $FallbackMinutes * 60
    }
  }
  return $FallbackMinutes * 60
}

Write-Output "Delta Force dynamic collect/produce loop started."
$consecutiveFailures = 0
$lastHelpAt = $null
while ($true) {
  $sleep = Get-NextSleepSeconds
  if ($sleep -gt 0) {
    $wake = (Get-Date).AddSeconds($sleep)
    Write-Output "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] not due; next wake $($wake.ToString('yyyy-MM-dd HH:mm:ss'))"
    Start-Sleep -Seconds $sleep
    continue
  }
  Write-Output "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] action due; running round"
  $round = Invoke-Round
  $postState = Get-NextActionState
  $postSleep = if ($postState -and $postState.needAction) { 0 } elseif ($postState -and $postState.nextSuggestedRun) {
    try {
      [Math]::Max(10, [int](([datetime]::Parse($postState.nextSuggestedRun) - (Get-Date)).TotalSeconds) + ($BufferMinutes * 60))
    } catch {
      $FallbackMinutes * 60
    }
  } else {
    $FallbackMinutes * 60
  }
  if ($postSleep -le 0) {
    $consecutiveFailures++
    if ($consecutiveFailures -le $QuickRetryLimit) {
      $postSleep = $QuickRetrySeconds
      $wake = (Get-Date).AddSeconds($postSleep)
      Write-Output "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] action still due after round (#$consecutiveFailures); quick retry at $($wake.ToString('yyyy-MM-dd HH:mm:ss'))"
    } else {
      $shouldNotify = $true
      if ($lastHelpAt) {
        $shouldNotify = ((Get-Date) - $lastHelpAt).TotalMinutes -ge $FallbackMinutes
      }
      if ($shouldNotify) {
        Send-AgentHelpRequest -FailureCount $consecutiveFailures -LastLogPath $round.logPath -ActionState $postState
        $lastHelpAt = Get-Date
      }
      $postSleep = $FallbackMinutes * 60
      Write-Output "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] action still due after round (#$consecutiveFailures); backing off ${FallbackMinutes}min"
    }
  } else {
    $consecutiveFailures = 0
  }
  Start-Sleep -Seconds $postSleep
}




