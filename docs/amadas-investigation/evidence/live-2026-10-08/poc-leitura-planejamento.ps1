param(
    [string[]]$CsvPaths = @(
        '\\192.168.0.218\Arquivos\SIGMANEST\SNDATA_serv\eReport\9379.CSV',
        '\\192.168.0.218\Arquivos\SIGMANEST\SNDATA_serv\eReport\9380.CSV',
        '\\192.168.0.218\Arquivos\SIGMANEST\SNDATA_serv\eReport\9381.CSV'
    )
)
# Leitura pontual de planejamento. Nao consulta CNC, banco ou API do MES.
$ErrorActionPreference = 'Stop'
if ($CsvPaths.Count -gt 5) { throw 'Limite: cinco arquivos por execucao.' }
$samples = foreach ($path in $CsvPaths) {
    $item = Get-Item -LiteralPath $path
    if ($item.Length -gt 204800) { throw "Arquivo excede 200 KiB: $path" }
    $bytes = [IO.File]::ReadAllBytes($item.FullName)
    if ($bytes.Length -gt 204800) { throw "Arquivo cresceu durante a leitura: $path" }
    $text = [Text.Encoding]::UTF8.GetString($bytes)
    $header = @{}
    $orders = @()
    foreach ($line in ($text -split '\r?\n')) {
        if (-not $line.Contains(';')) { continue }
        $content = if ($line.EndsWith(';')) { $line.Substring(0, $line.Length - 1) } else { $line }
        $tokens = $content.Split(';')
        if ($tokens.Length % 2) { throw "Linha incompleta no CSV: $path" }
        $fields = @{}
        for ($i = 0; $i -lt $tokens.Length; $i += 2) {
            $fields[$tokens[$i]] = $tokens[$i + 1]
        }
        if ($fields.ContainsKey('OS')) {
            $orders += [pscustomobject]@{
                op_observada = $fields.OS
                peca_observada = $fields.Peca
                quantidade_requerida_declarada = [int]$fields.Quant_Requerida
                quantidade_arranjada_declarada = [int]$fields.Quant_Arranjada
                tempo_unitario_estimado_original = $fields.Tempo_Unitario
            }
        } else {
            foreach ($key in $fields.Keys) { $header[$key] = $fields[$key] }
        }
    }
    if (-not $header.Tarefa -or -not $header.Programa -or -not $orders.Count) {
        throw "Schema esperado nao encontrado: $path"
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $hash = ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '') }
    finally { $sha.Dispose() }
    [pscustomobject]@{
        fonte = $item.FullName
        sha256_original = $hash
        tarefa = $header.Tarefa
        programa = $header.Programa
        maquina_cam = $header.Maquina
        material_planejado = $header.Material
        espessura_original = $header.Espessura
        chapa_codigo_cam = $header.Cod_Chapa
        repeticoes_declaradas = $header.Repeticoes
        tempo_estimado_original = $header.Tempo
        data_criacao_original_sem_fuso = $header.Data_Criacao
        ordens = $orders
    }
}
[pscustomobject]@{
    recebido_em = (Get-Date).ToString('o')
    tipo = 'PLANEJAMENTO_EXPORTADO'
    telemetria_cnc = $false
    escrita_mes = $false
    amostras = @($samples)
} | ConvertTo-Json -Depth 7
