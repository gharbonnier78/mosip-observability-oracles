# OAEF document sources

1. `assemble.ps1` builds the full HTML of both documents from `spec.html`, `vts.html` and `data.ps1` (chapter 5 requirements, test cases and both traceability matrices are generated; it stops if a requirement has no test case). Output: `%TEMP%\oaef\spec.html`, `vts.html`.
2. Before conversion, replace `<p>[[TOC]]</p>` by `<p style="page-break-before:always;font-size:18pt;color:#003088;font-weight:bold">Contents</p><p>[[TOC]]</p>`.
3. `word2.ps1 -Html <html> -Docx <docx> -Title <title> -DocId <id>` converts with Microsoft Word (run it in `Start-Job`; keep paths short, Word does not accept paths over 260 characters).

Generated outputs: `../OAEF-SPEC-001_*.docx|pdf`, `../OAEF-VTS-001_*.docx|pdf`.
