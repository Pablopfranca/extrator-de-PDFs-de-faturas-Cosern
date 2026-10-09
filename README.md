# Módulo 1B — ingestão por PDF

Extrai faturas (DANFE de energia) da Neoenergia/Cosern direto do **PDF** e grava
**JSON** no mesmo formato do Módulo 1, para o Módulo 2 ler as duas origens com o
mesmo parser.

É uma **alternativa e conferência** ao Módulo 1 (API): o PDF é a fonte de verdade.

## Por que existe

A API da Cosern devolve, no campo de demanda **medida**, a demanda **faturada** —
que tem piso no contrato. Quando o consumidor usa menos que o contratado, a API
repete o valor do contrato mês após mês, e o estudo de demanda ótima perde o sentido.

O PDF traz a tabela do **MEDIDOR**, com a demanda realmente registrada.

| UC | Demanda medida (PDF) | O que a API devolve | Contrato |
|---|---|---|---|
| `UC-A` | 11,34 / 53,04 kW | 90 / 90 kW | 90 kW |
| `UC-B` | 22,72 / 28,80 kW | 131 / 131 kW | 131 kW |
| `UC-C` | 11,93 / 19,82 kW | 150 / 150 kW | 150 kW |

(Números de UC reais omitidos; valores ilustrativos do problema.)

O PDF também cobre **muito mais unidades**: 139 UCs do Grupo A, contra 9 disponíveis
pela API hoje.

## Instalação

```bash
cd modulo1b
pip install -r requirements.txt
```

Depende de `pdfplumber`.

## Uso

```bash
# Um ou vários PDFs (JSON é o padrão)
py ingest.py fatura.pdf
py ingest.py fatura1.pdf fatura2.pdf

# Pasta inteira, recursivo
py ingest.py --pasta data

# Recriar a saída em vez de acumular
py ingest.py --pasta data --overwrite

# CSV legado (ou os dois formatos)
py ingest.py --formato csv fatura.pdf
py ingest.py --formato ambos fatura.pdf
```

Saída padrão:

```text
modulo1b/data/output/json/faturas_pdf/<instalacao>.json
```

Um arquivo por instalação ou UC (formato antigo: instalação com 10 dígitos;
formato novo: número da unidade consumidora no cabeçalho). A ligação com o
cadastro da API usa `uc.instalacao` ou `uc.codigo_uc`.
na listagem da API, que é a chave de ligação no Módulo 2.

A carga é **incremental**: um PDF novo funde competências novas no arquivo
existente, sem perder o que já havia.

## Formato do JSON

Mesmas seções do Módulo 1, mais o que só existe no PDF:

```jsonc
{
  "origem": "PDF",
  "dadosHistorico": { "instalacao": "...", "contaColetiva": "...", "nomeCliente": "..." },
  "dadosGerais":    { "subGrupo": "A4", "modalidadeUc": "Horo-sazonal Verde", "endereco": "..." },
  "dadosAtiva":     [ { "valorP": "...", "valorFP": "...", "medidaP": "...", "tusdP": "..." } ],
  "dadosReativa":   [ ... ],
  "dadosDemanda":   [ { "valorP": "...", "contratadaP": "...", "faturadaP": "...", "ociosaP": "..." } ],
  "dadosMontante":  [ ... ],
  "faturasPdf":     [ { /* todos os campos extraídos, sem descarte */ } ]
}
```

### Convenções que seguem a API

- Números como string com 7 casas decimais.
- Grupo B sem posto horário usa `valorP` (a API faz igual).
- `dadosAtiva.valorP/valorFP` é o consumo **faturado** (com perda de transformação),
  igual ao que a API publica. A leitura crua do medidor fica em `medidaP`/`medidaFP`.

### Onde o PDF vai além

`dadosDemanda.valorP`/`valorFP` recebem a demanda **medida** real. A faturada, que
é o que a API entrega, fica separada em `faturadaP`/`faturadaFP`, e a parcela ociosa
em `ociosaP`/`ociosaFP`.

Nada do PDF é descartado: `faturasPdf` guarda o registro completo, incluindo tributos,
encargos, leituras, medidor e as colunas dinâmicas que o extrator descobre sozinho.

## Auditoria

```bash
py auditar.py --pasta data
py listar_campos.py
```

`auditar.py` aponta itens da fatura que ainda não estão mapeados e separa os PDFs
que precisam de atenção.

## Integração

O Módulo 2 lê esta pasta automaticamente:

```bash
cd ..
py -m modulo2.tratamento
```

Ele grava `consumo_pdf_mensal`, `fatura_pdf` e `divergencia_pdf_api`, e monta a view
`v_consumo_a_efetivo`, que prefere o PDF e cai na API quando não há PDF para o mês.

Para ignorar o PDF: `py -m modulo2.tratamento --sem-pdf`.

## Dados sensíveis

`data/` (PDFs, CSV e `data/output/`) **não vai para o Git**. As faturas contêm nome
do cliente, endereço e CNPJ.
