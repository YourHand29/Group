$ErrorActionPreference = "Stop"

$env:PYTHONPATH = "src"
& .\.venv\Scripts\python.exe -m paper_atlas.aws
