# Arquitetura

## Camadas

```
 Navegador (HTML/CSS/JS + Chart.js local)
        │  GET /api/*  (somente leitura)
        ▼
 security/middleware ── Host loopback? método GET? → cabeçalhos CSP → audit/
        │
        ▼
 api/routes/*          rotas finas: validam parâmetros, embrulham em Envelope{origem, aviso, dados}
        │
        ▼
 monitor.py            camada de aplicação: decide a fonte (coletor ou SQLite) e aplica o domínio
        │                         │
        ▼                         ▼
 collectors/ (interfaces)    domain/ (regras puras)         storage/ (SQLite)
   simulated.py  ← MVP         thresholds.py  limiares        metricas
   future.py     ← bloqueado   criticality.py criticidade     eventos
   registry.py                 timeline.py    transições      auditoria
                               diagnostics.py evidência→hipótese   processos
                               processes.py   consumo, tendência,  processos_amostras
                                              sinais
```

## Análise de processos

Regras em `domain/processes.py`, todas cobertas por `tests/test_processos.py`:

- **Grupo** = unidade systemd do processo, ou o nome dele quando não há unidade. Os workers
  do Apache somam juntos, e um serviço reiniciado (pid novo) continua no mesmo grupo. A
  API devolve o campo `grupo` já resolvido; o frontend não repete a regra.
- **Amostragem:** em cada leitura são gravados os 15 maiores por CPU ∪ os 15 maiores por
  memória. Num host com centenas de processos, o volume fica previsível.
- **Instância** = pid + horário de início (o kernel reaproveita pids). É "encerrada"
  quando não aparece na leitura mais recente do período.
- **Sinais** são achados medidos, não hipóteses:

  | Código | Regra |
  |---|---|
  | `MEMORIA_CRESCENTE` | regressão linear da RSS nas leituras recentes da instância (janela de 1 h; se não qualificar, 2 h) com ≥ 30 MiB/h, R² ≥ 0,7 e pelo menos 10 leituras em 30 min. A projeção de quando a RAM acabaria aparece só se for ≤ 72 h e é rotulada como estimativa. |
  | `REINICIO` | instância encerrada e outra de mesmo nome iniciada até 10 min depois |
  | `ENCERRADO` | instância encerrada sem substituta |
  | `CPU_SUSTENTADA` | CPU do grupo ≥ 50% por ≥ 10 min seguidos |
  | `PICO_MEMORIA` | grupo chegou a ≥ 20% da RAM (alto a partir de 40%) |

- Os limiares são constantes no topo do módulo, para revisar com dados reais.

Endpoints: `GET /api/processes` (com `busca` e `categoria`), `GET /api/processes/summary`
e `GET /api/processes/analysis?grupo=...&horas=6`. Um grupo sem leituras no período
responde 404 no formato padrão.

Regras de dependência:

- `domain/` não conhece API, banco nem coletor concreto; recebe modelos e devolve modelos.
- `api/` não tem regra de negócio: só chama o `Monitor`.
- Só `storage/repositories.py` escreve SQL, sempre parametrizado.
- Todo modelo carrega `origem` (`SIMULADO` | `REAL`). O SQLite também guarda a origem,
  e `limpar_origem(SIMULADO)` nunca toca dados reais.

## Fluxo de dados

**Inicialização (`lifespan`):**

1. `Settings` valida o modo e o host; se algo estiver errado, o servidor nem sobe.
2. `construir_coletores` cria o `CenarioSimulado`, ancorado no instante atual.
3. `Monitor.semear_historico` gera 24 h de pontos, um por minuto. Ao mesmo tempo,
   `domain/timeline` cria um evento a cada mudança de nível, e os eventos roteirizados
   do cenário são gravados.
4. Uma tarefa assíncrona grava uma amostra simulada a cada 15 s enquanto o processo roda.

**Consulta:** a rota chama o `Monitor`, que lê o coletor (estado atual) ou o
SQLite (histórico e eventos), aplica o domínio e devolve um `Envelope`.

## Evidência × hipótese

O diagnóstico roda em duas etapas, separadas também no código
(`domain/diagnostics.py`):

| | Evidência | Hipótese |
|---|---|---|
| Natureza | Fato observado (valor, estado, evento) | Interpretação possível |
| Campos próprios | `fonte`, `valor`, `limiar`, `observado_em` | `confianca`, `evidencias_ids`, `verificacoes_sugeridas` |
| Status | — | sempre `nao_confirmada` |

Essa separação é **garantida pelo modelo**, não só pela convenção:
`Hipotese` exige ao menos uma evidência e uma verificação, o padrão do
`status` só aceita `nao_confirmada`, e o validador de `Diagnostico` recusa
hipótese que cite evidência inexistente. Na tela, clicar numa referência
destaca a evidência correspondente.

Para criar uma regra nova:

1. registrar o fato em `levantar_evidencias`;
2. cruzar os fatos em `formular_hipoteses`;
3. adicionar um teste em `tests/test_domain.py`.

## Como plugar a coleta real (próxima etapa)

As interfaces estão em `collectors/base.py`, e os esboços já documentados em
`collectors/future.py`. O caminho previsto:

1. Implementar `ColetorMetricasPsutil` etc., marcando `origem = Origem.REAL`.
2. Adicionar o modo `real` em `config.MODOS_SUPORTADOS` e no `registry`. Isso só
   deve acontecer com aprovação explícita, porque hoje os testes exigem a recusa.
3. Rodar o coletor **na própria VPS**, sem privilégio, sem SSH a partir do dashboard,
   enviando para o dashboard por canal autenticado. Desenhar isso antes de codificar.
4. Ajustar `tests/test_security.py`: a lista de módulos proibidos passa a ter uma
   exceção explícita e revisada para o pacote do coletor, e não para o app todo.

Os modelos de `models/integrations.py` (`RegistroHttp`, `ContainerDocker`,
`EstatisticaBanco`) e as interfaces `ColetorLogsHttp`, `ColetorDocker` e
`ColetorBancos` já fixam o contrato dos logs HTTP, do Docker e dos bancos.

## Frontend

- Sem build: módulos ES nativos, uma tela por arquivo em `web/static/js/views/`.
- Cada tela exporta `{ titulo, intervaloMs?, render(container) }`. O roteador por hash
  em `app.js` cuida da troca de tela e da atualização periódica, e chama a limpeza
  (destrói os gráficos) ao sair.
- O DOM é montado com `textContent` (helper `el()`), sem `innerHTML` com dados.
- Os tokens de cor ficam em `:root`. O tema escuro tem passos próprios, e a escolha
  manual do tema fica gravada no `localStorage` (opcional).
- Os níveis aparecem sempre com forma e texto, nunca só com cor.

## Erros e rastreabilidade

- Todo erro sai no mesmo formato (`app/errors.py`):
  `{"erro": {"codigo", "mensagem", "detalhes"?, "request_id"}}`. Isso vale para
  validação (422), rota inexistente (404), bloqueios (400/405) e falha interna (500).
- O middleware gera um `request_id` por requisição e o devolve em `X-Request-ID`.
  O mesmo id aparece na linha de log (`chave=valor`) e na tabela de auditoria.
- Uma exceção não tratada é registrada no log com o stack trace e vira um 500
  genérico. A resposta nunca traz detalhe interno.
- No frontend, `api.js` traduz as falhas em mensagens legíveis. Se uma atualização
  falha, `app.js` mantém os últimos dados na tela com um aviso; se a primeira carga
  falha, mostra o erro com o botão "Tentar novamente". Uma resposta atrasada de uma
  tela anterior nunca sobrescreve a atual.

## Banco (SQLite)

**Migrações** (`storage/database.py`): a versão do esquema fica em `PRAGMA user_version`.
Cada migração é um script SQL imutável, aplicado uma única vez numa transação.
Se falhar, o banco fica exatamente como estava e a aplicação não sobe. Para mudar
o esquema, acrescente uma migração no fim de `MIGRACOES`; nunca edite uma existente.
A v2 passou a garantir o domínio no próprio banco: faixas de percentual, enums de
tipo, severidade, origem e categoria, e status HTTP válido.
`tests/test_migracoes.py` falha se um enum do Python divergir das constraints.

| Tabela | Chave | Uso |
|---|---|---|
| `metricas` | `momento` (ISO UTC) | série temporal compacta (`PontoHistorico`) |
| `eventos` | `id` determinístico | linha do tempo; `INSERT OR IGNORE` deixa a regravação idempotente |
| `auditoria` | autoincremento | requisições, bloqueios e ciclo de vida, com `request_id`; paginação por cursor (`antes_id`) |
| `processos` | autoincremento; `UNIQUE (pid, iniciado_em, origem)` | instância de processo; índice em `grupo` (v3) |
| `processos_amostras` | `(processo_id, momento)`; FK com `ON DELETE CASCADE` | série temporal de cada instância (v3) |

Para gráficos longos, o histórico é reduzido em baldes. CPU, RAM e swap usam o
**máximo** do balde, para o pico não sumir; disco e rede usam a média.
