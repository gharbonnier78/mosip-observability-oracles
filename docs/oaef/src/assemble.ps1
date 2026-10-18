param([string]$OutDir)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
. (Join-Path $here 'data.ps1')
function HtmlEnc([string]$s) { [System.Net.WebUtility]::HtmlEncode($s) }

# ---------- requirement -> test cases map ----------
$cover = @{}
foreach ($tc in $TCs) { foreach ($r in ($tc.Reqs -split ',\s*')) { if (-not $cover[$r]) { $cover[$r] = @() }; $cover[$r] += $tc.Id } }
$missing = $Reqs | Where-Object { -not $cover[$_.Id] } | ForEach-Object { $_.Id }
if ($missing) { throw "Requirements without test case: $($missing -join ', ')" }

# ---------- spec chapter 5 ----------
$sb = New-Object System.Text.StringBuilder
foreach ($d in $Domains.Keys) {
  [void]$sb.AppendLine("<h2>$(HtmlEnc $Domains[$d])</h2>")
  [void]$sb.AppendLine('<table><tr><th style="width:9%">ID</th><th style="width:40%">Requirement</th><th style="width:5%">Pri</th><th style="width:6%">Ver.</th><th style="width:30%">Acceptance criterion</th><th>Closes</th></tr>')
  foreach ($r in ($Reqs | Where-Object { $_.Id -like "$d-*" })) {
    [void]$sb.AppendLine("<tr><td>OAEF-$($r.Id)</td><td>$(HtmlEnc $r.Text)</td><td>$($r.Pri)</td><td>$($r.Ver)</td><td>$(HtmlEnc $r.Acc)</td><td>$(HtmlEnc $r.Closes)</td></tr>")
  }
  [void]$sb.AppendLine('</table>')
}
[void]$sb.AppendLine('<h2>5.7 Gap closure</h2><table><tr><th style="width:12%">Gap</th><th style="width:52%">Problem</th><th>Closed by</th></tr>')
foreach ($g in $Gaps) { [void]$sb.AppendLine("<tr><td>$($g[0])</td><td>$(HtmlEnc $g[1])</td><td>$(($g[2] -split ',\s*' | % { "OAEF-$_" }) -join ', ')</td></tr>") }
[void]$sb.AppendLine('</table>')
$reqHtml = $sb.ToString()

# ---------- RTM (requirement -> VT) ----------
$sb = New-Object System.Text.StringBuilder
[void]$sb.AppendLine('<table><tr><th style="width:16%">Requirement</th><th style="width:6%">Pri</th><th style="width:8%">Ver.</th><th>Validation test cases (OAEF-VTS-001)</th></tr>')
foreach ($r in $Reqs) { [void]$sb.AppendLine("<tr><td>OAEF-$($r.Id)</td><td>$($r.Pri)</td><td>$($r.Ver)</td><td>$(($cover[$r.Id] | Select-Object -Unique) -join ', ')</td></tr>") }
[void]$sb.AppendLine('</table>')
$rtmHtml = $sb.ToString()

# ---------- VTS test cases ----------
$groups = [ordered]@{ 'VT-INF' = '6.1 Infrastructure (FS-1)'; 'VT-PIPE' = '6.2 Pipeline (FS-2)'; 'VT-SW' = '6.3 Instrumentation (FS-3)'; 'VT-SEC' = '6.4 Security (FS-4)'; 'VT-DQ' = '6.5 Data quality (FS-5)'; 'VT-QUAL' = '6.6 Qualification layer (FS-6)'; 'VT-E2E' = '6.7 End to end (FS-7)'; 'VT-OPS' = '6.8 Operations (FS-8)' }
$modeName = @{ S = 'S — Simulation'; F = 'F — Full (NIN-001 on MOSIP)'; I = 'I — Inspection'; D = 'D — Demonstration' }
$sb = New-Object System.Text.StringBuilder
[void]$sb.AppendLine('<h2>6.0 Test case summary</h2><table><tr><th style="width:14%">ID</th><th style="width:48%">Title</th><th style="width:8%">Mode</th><th>Requirements</th></tr>')
foreach ($tc in $TCs) { [void]$sb.AppendLine("<tr><td>$($tc.Id)</td><td>$(HtmlEnc $tc.Title)</td><td>$($tc.Mode)</td><td>$(($tc.Reqs -split ',\s*' | % { "OAEF-$_" }) -join ', ')</td></tr>") }
[void]$sb.AppendLine('</table>')
foreach ($g in $groups.Keys) {
  [void]$sb.AppendLine("<h2>$(HtmlEnc $groups[$g])</h2>")
  foreach ($tc in ($TCs | Where-Object { $_.Id -like "$g-*" })) {
    $steps = ($tc.Steps | % { "<li>$(HtmlEnc $_)</li>" }) -join ''
    [void]$sb.AppendLine("<h3>$($tc.Id) $(HtmlEnc $tc.Title)</h3>")
    [void]$sb.AppendLine('<table>')
    [void]$sb.AppendLine("<tr><td style=`"width:22%`"><b>Requirements</b></td><td>$(($tc.Reqs -split ',\s*' | % { "OAEF-$_" }) -join ', ')</td></tr>")
    [void]$sb.AppendLine("<tr><td><b>Mode</b></td><td>$($modeName[$tc.Mode])</td></tr>")
    [void]$sb.AppendLine("<tr><td><b>Preconditions</b></td><td>$(HtmlEnc $tc.Pre)</td></tr>")
    [void]$sb.AppendLine("<tr><td><b>Steps</b></td><td><ol>$steps</ol></td></tr>")
    [void]$sb.AppendLine("<tr><td><b>Expected result</b></td><td>$(HtmlEnc $tc.Exp)</td></tr>")
    [void]$sb.AppendLine("<tr><td><b>Evidence to retain</b></td><td>$(HtmlEnc $tc.Ev)</td></tr>")
    [void]$sb.AppendLine('<tr><td><b>Result</b></td><td>[ ] Pass &nbsp; [ ] Fail &nbsp; [ ] Blocked &nbsp;&nbsp; Executed by: [ ] &nbsp; Date: [ ] &nbsp; Defect: [ ]</td></tr>')
    [void]$sb.AppendLine('</table>')
  }
}
$tcHtml = $sb.ToString()

# ---------- assemble HTML ----------
$spec = [IO.File]::ReadAllText((Join-Path $here 'spec.html')).Replace('<!--REQS-->', $reqHtml).Replace('<!--RTM-->', $rtmHtml).Replace('<!--TOC-->', '<p>[[TOC]]</p>')
$vts = [IO.File]::ReadAllText((Join-Path $here 'vts.html')).Replace('<!--TCS-->', $tcHtml).Replace('<!--RTM-->', $rtmHtml).Replace('<!--TOC-->', '<p>[[TOC]]</p>')
$work = Join-Path $env:TEMP 'oaef'; New-Item -ItemType Directory -Force $work | Out-Null; $specHtml = Join-Path $work 'spec.html'; $vtsHtml = Join-Path $work 'vts.html'
[IO.File]::WriteAllText($specHtml, $spec, (New-Object Text.UTF8Encoding $true))
[IO.File]::WriteAllText($vtsHtml, $vts, (New-Object Text.UTF8Encoding $true))
"requirements: $($Reqs.Count), test cases: $($TCs.Count), all requirements covered"

