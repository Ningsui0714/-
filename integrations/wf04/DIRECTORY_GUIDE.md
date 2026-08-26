# Project directory guide

- frontend: web pages, styles, UI logic, and static assets.
- backend: API service, configuration, database, and backend tests.
- workflows/current: the three current Xingchen workflows for student profiling, learning explanations, and remediation; legacy v4/v5 files are retained for reference.
- workflows/history: retained v2 and v3 workflow versions.
- test-data: workflow debugging payloads.
- docs: workflow, knowledge-base, search, and integration documentation.
- workflow-nodes: custom workflow node code.
- tools/builders-and-validators: workflow builders and validation scripts.
- references: competition PDF files and rendered direction-4 pages.
- migration-manifest.csv: source path, destination path, size, and SHA256 for every migrated file.

## Start the system

Run in PowerShell:

    Set-Location -LiteralPath "D:\jbgs\2"
    .\启动系统.ps1

Then open http://127.0.0.1:4173/.
