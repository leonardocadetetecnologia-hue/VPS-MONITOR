# Segurança e restrições do MVP

O alvo futuro é uma VPS corporativa **de produção**. Esta etapa não tem
contato algum com ela. Cada restrição abaixo é garantida por código e coberta
por testes, não apenas documentada.

| Restrição | Como está garantida | Teste |
|---|---|---|
| Não acessar a VPS / não usar SSH / não executar comandos remotos | Nenhum módulo de rede, SSH ou processo é importado (`subprocess`, `socket`, `paramiko`, `requests`, `httpx`...) | `test_security.py::test_codigo_nao_importa_...` (varredura AST de todo `app/`) |
| Não consultar bancos corporativos | Nenhum driver (`psycopg`, `pymysql`, `mariadb`, `sqlalchemy`...); o único banco é o SQLite local | mesma varredura |
| Não coletar dados reais | `config` só aceita `modo=simulado`; `registry` recusa de novo; os coletores reais lançam `ColetaRealDesabilitada` | `test_config.py`, `test_collectors.py::test_coletores_reais_estao_bloqueados` |
| Não modificar o ambiente | API só aceita GET/HEAD/OPTIONS (o resto dá 405 e é auditado); nenhuma chamada a `os.system`, `os.remove`, `shutil.rmtree` | `test_api_e_somente_leitura`, varredura AST |
| Não expor à internet | Host de escuta restrito a loopback; o cabeçalho `Host` também é validado (barra DNS rebinding) | `test_recusa_host_fora_do_loopback`, `test_host_nao_confiavel_e_recusado` |
| Não instalar agente / não configurar inicialização automática | Não existe unit systemd, cron, serviço Windows nem Dockerfile; o servidor vive enquanto o terminal estiver aberto | — (ausência verificável no repositório) |
| Não usar Docker privilegiado | Docker não é usado nesta etapa | — |
| Dados simulados claramente identificados | `origem: "SIMULADO"` e `aviso` em toda resposta; cabeçalho `X-Data-Origin: SIMULADO`; faixa fixa na interface; apps marcadas `[Fictício]` | `test_toda_resposta_declara_origem_simulada`, `test_aplicacoes_corporativas_sao_marcadas_como_ficticias` |

## Cabeçalhos HTTP

- `Content-Security-Policy`: `default-src 'self'`, sem script ou estilo externo e sem
  `unsafe-inline`; `frame-ancestors 'none'`. A única exceção é `/docs` (Swagger), que
  carrega os recursos do CDN.
- `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
  `Cache-Control: no-store`.

## Auditoria

Toda requisição a `/api/*`, todo bloqueio (Host ou método) e os eventos de
inicialização e encerramento vão para a tabela `auditoria`, visível na tela
Auditoria e em `GET /api/audit`.

## Rede de saída

- O app não faz requisições de saída.
- O Chart.js é servido localmente.
- A versão instalada do FastAPI traz instrumentação OpenTelemetry (`fastapi.telemetry`),
  mas só com a API do OTel, sem SDK nem exportador instalados. A configuração automática
  de exportadores fica desligada por padrão (`FASTAPI_OTEL_AUTO_CONFIGURE` não definido),
  então nada é exportado.

## Antes de qualquer coleta real

Itens a decidir com quem administra a VPS, **antes** de escrever código:

1. Onde o coletor roda: na VPS, como usuário sem privilégio e sem SSH a partir do dashboard.
2. Como os dados chegam ao dashboard: push autenticado, nunca porta pública aberta na VPS.
3. Permissões mínimas por fonte: grupo `adm` para logs; proxy somente-GET para o Docker;
   `pg_monitor` / `PROCESS` para os bancos, sem acesso a tabelas de negócio.
4. Política de dados pessoais nos logs HTTP: IP só como hash, sem query string sensível.
5. A criticidade de cada unidade systemd corporativa, com o responsável por cada uma.
