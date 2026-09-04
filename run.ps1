param(
    # 127.0.0.1 = so esta maquina. 0.0.0.0 = exposto na rede (precisa de regra de firewall).
    [string]$Bind = "127.0.0.1",
    [int]$Porta = 8787
)

$env:HOST = $Bind
$env:PORT = $Porta

Push-Location $PSScriptRoot
try {
    uv run run.py
}
finally {
    Pop-Location
}
