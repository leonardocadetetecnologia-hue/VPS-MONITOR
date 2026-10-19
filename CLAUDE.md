# Regras do projeto — VPS Insight

## 1. REGRA ACIMA DE TODAS: NÃO INTERFERIR NA VPS

A VPS monitorada é **produção corporativa**. Nenhuma ação deste projeto pode
impactar, interferir ou alterar qualquer coisa nela — aplicações, serviços,
bancos, containers, arquivos, rede, desempenho ou disponibilidade.

Esta regra prevalece sobre qualquer outra deste arquivo e do
`MASTER_PROMPT.md`. Se houver conflito, ela vence.

**Proibido, sem exceção implícita:**

- acessar a VPS por qualquer meio (SSH, SCP, SFTP, RDP, painel do provedor, API do provedor);
- executar comandos nela, local ou remotamente;
- instalar, atualizar ou remover pacotes, agentes, exporters ou bibliotecas nela;
- iniciar, parar, reiniciar, recarregar, habilitar ou desabilitar unidades systemd,
  containers, sites do Apache ou processos;
- alterar arquivos, configurações, permissões, usuários, cron, timers, firewall,
  portas, certificados ou DNS;
- conectar nos bancos (MariaDB, PostgreSQL) da VPS, nem com usuário somente leitura;
- usar o Docker da VPS, nem em modo leitura;
- gerar carga contra ela: varredura de portas, teste de stress, benchmark,
  crawler, requisições automatizadas às aplicações;
- fazer deploy do VPS Insight na VPS ou expor o dashboard à internet.

**O que vale no lugar:** só dados simulados, gerados localmente e marcados
como `SIMULADO`. As salvaguardas do código são parte desta regra: modo só
`simulado`, escuta só em loopback, API só de leitura, coletores reais
bloqueados e a varredura estática em `tests/test_security.py`.
**Não afrouxe nenhuma delas** (nem os testes que as provam) sem aprovação
explícita do Leo.

**Quando a coleta real for discutida:** qualquer passo que toque a VPS
precisa de aprovação explícita e por escrito do Leo **para aquela ação
específica**, depois de apresentar:

- o que exatamente será executado;
- com qual usuário e permissão;
- o impacto esperado em CPU, memória, disco e rede;
- como desfazer.

Aprovar uma ação não autoriza a próxima. Na dúvida se algo toca a VPS, trate
como se tocasse e pergunte.

## 2. Constituição técnica

As regras permanentes de engenharia, arquitetura, segurança, documentação e
qualidade estão no `MASTER_PROMPT.md` e valem para toda tarefa:

@MASTER_PROMPT.md
