param([string]$Html, [string]$Docx, [string]$Title, [string]$DocId, [switch]$NoNormalFont)
# Converts one HTML source into a formatted .docx + .pdf with Word. Run inside Start-Job (hidden Word).
$ErrorActionPreference = 'Stop'
$log = Join-Path (Split-Path $Docx) 'build.log'
function L($m) { Add-Content $log "$(Get-Date -f HH:mm:ss) $DocId $m" }
$navy = 0x883000
$w = New-Object -ComObject Word.Application; $w.Visible = $false; $w.DisplayAlerts = 0
try {
  $d = $w.Documents.Open($Html, $false, $false, $false); L 'open'
  try { $d.Windows.Item(1).View.Type = 3 } catch {}
  $ps = $d.PageSetup; $ps.PaperSize = 7; $ps.TopMargin = 56.7; $ps.BottomMargin = 56.7; $ps.LeftMargin = 56.7; $ps.RightMargin = 56.7
  if (-not $NoNormalFont) { $n = $d.Styles.Item(-1); $n.Font.Name = 'Arial'; $n.Font.Size = [single]10 }
  foreach ($lv in 1..4) {
    $st = $d.Styles.Item(-1 - $lv)
    $st.Font.Name = 'Arial'; $st.Font.Color = $navy; $st.Font.Bold = $true; $st.Font.Size = [single](@(0, 18, 14, 12, 10.5)[$lv])
    $st.ParagraphFormat.SpaceBefore = [single](@(0, 18, 12, 10, 8)[$lv]); $st.ParagraphFormat.SpaceAfter = [single]6; $st.ParagraphFormat.KeepWithNext = $true
  }
  $d.Styles.Item(-2).ParagraphFormat.PageBreakBefore = $true
  L 'styles'
  $p1 = $d.Paragraphs.Item(1).Range; $p1.Font.Size = [single]26; $p1.Font.Bold = $true; $p1.Font.Color = $navy; $p1.ParagraphFormat.SpaceBefore = [single]120; $p1.ParagraphFormat.SpaceAfter = [single]18
  $p2 = $d.Paragraphs.Item(2).Range; $p2.Font.Size = [single]13; $p2.ParagraphFormat.SpaceAfter = [single]36
  L 'cover'
  foreach ($t in $d.Tables) {
    $first = ''; try { $first = $t.Cell(1, 1).Range.Text } catch {}
    if ($first -like 'Requirements*') { try { $pv = $t.Range.Previous(4, 1); $pv.ParagraphFormat.KeepWithNext = $true; $pv2 = $t.Range.Previous(4, 2); $pv2.ParagraphFormat.KeepWithNext = $true } catch {}; try { $t.Rows.AllowBreakAcrossPages = $false; $t.Range.ParagraphFormat.KeepWithNext = $true; $t.Rows.Item($t.Rows.Count).Range.ParagraphFormat.KeepWithNext = $false; $t.PreferredWidthType = 2; $t.PreferredWidth = [single]100; $t.Columns.Item(1).PreferredWidthType = 2; $t.Columns.Item(1).PreferredWidth = [single]20 } catch {} }
    else { try { $t.Rows.Item(1).HeadingFormat = -1 } catch {}; try { $t.Rows.AllowBreakAcrossPages = $true } catch {} }
  }
  foreach ($para in $d.Paragraphs) { if ($para.OutlineLevel -le 4) { $para.KeepWithNext = $true } }
  L 'tables'
  $f = $d.Content
  if ($f.Find.Execute('[[TOC]]')) {
    $f.Text = ''
    $f.InsertParagraphAfter()
    $r2 = $d.Range($f.End, $f.End)
    $d.TablesOfContents.Add($r2, $true, 1, 3) | Out-Null
  }
  L 'toc'
  $sec = $d.Sections.Item(1); $sec.PageSetup.DifferentFirstPageHeaderFooter = -1
  $hdr = $sec.Headers.Item(1).Range; $hdr.Text = "$Title  |  $DocId v0.1 Draft"; $hdr.Font.Size = [single]8
  $ftr = $sec.Footers.Item(1).Range; $ftr.Text = '[Classification]  |  Page PGX of PGY'; $ftr.Font.Size = [single]8
  foreach ($pair in @(@('PGX', 33), @('PGY', 26))) { $fr = $sec.Footers.Item(1).Range; if ($fr.Find.Execute($pair[0])) { $fr.Text = ''; $d.Fields.Add($fr, $pair[1]) | Out-Null } }
  L 'header-footer'
  $d.Fields.Update() | Out-Null; foreach ($t in $d.TablesOfContents) { $t.Update() }
  L 'update'
  $d.SaveAs2($Docx, 16); L 'saved'
  $d.ExportAsFixedFormat(($Docx -replace '\.docx$', '.pdf'), 17); L 'pdf'
  "$Docx : $($d.ComputeStatistics(2)) pages"
  $d.Close($false)
} finally { $w.Quit() }
