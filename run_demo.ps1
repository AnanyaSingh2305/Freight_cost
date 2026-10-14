$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    $workspacePython = Join-Path $PSScriptRoot '../../work/venv/Scripts/python.exe'
    if (Test-Path -LiteralPath $workspacePython) {
        $taskPython = (Resolve-Path -LiteralPath $workspacePython).Path
    } else {
        $taskPython = 'python'
    }
}
& $taskPython -c "import numpy, pandas, streamlit, onnxruntime, tokenizers"
if ($LASTEXITCODE -ne 0) {
    throw 'The selected Python environment cannot load the app dependencies. Install requirements.txt using this same interpreter before launching.'
}
Write-Host 'Starting FreightTiger at http://127.0.0.1:8501'
& $taskPython -m streamlit run app.py
exit $LASTEXITCODE
