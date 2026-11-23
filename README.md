# TP3 - Orquestração de Agentes Inteligentes com LLMs e Sub-workflows no n8n (DR4)
**Empresa / Contexto:** Vórtice Logística  
**Aluno:** João Pedro Barboza  
**Data:** 2026-11-23  
**Ambiente:** n8n 2.42.4 (Docker, self-hosted), Data Tables do n8n e modelo de linguagem `cc/claude-haiku-5-5` (família Claude, Anthropic), acessado por um proxy local compatível com a API da OpenAI (9router).

---

## 1. Ferramentas de Inteligência Artificial Utilizadas
Conforme os critérios de entrega, todas as partes deste trabalho contaram com apoio de ferramentas de IA. Todas as saídas foram revisadas, executadas e validadas manualmente pelo autor, inclusive as execuções no n8n, os dados gravados nas Data Tables e os prints de evidência.

* **Agente / Ambiente de apoio:** Claude Code (Anthropic), extensão do VSCode, em ambiente WSL2.
* **Modelo de linguagem do agente de apoio:** Claude Opus (família Claude, Anthropic).
* **Modelo usado dentro dos workflows e dos testes:** `cc/claude-haiku-5-5` (Claude Haiku, Anthropic), via proxy local compatível com a API da OpenAI. Ele é o LLM do Agent node, da LLM Chain e do script de testes do Exercício 2. Não é ferramenta de apoio ao trabalho, e sim parte da solução.
* **Uso por parte do trabalho:**
  * **Exercício 1 (automação x agente):** levantamento dos nós dos workflows do TP1 e do TP2 e apoio na redação da análise. A identificação das oito regras e do nível de agência foi conferida pelo autor nos workflows originais.
  * **Exercício 2 (inferência guiada):** escrita do script `scripts/ex02_teste_prompts.py`, dos dois prompts comparados e da métrica de consistência. O script foi executado pelo autor e a análise foi feita sobre os resultados reais registrados em `saidas/`.
  * **Exercício 3 (mapa de sub-workflows):** apoio no desenho do diagrama `diagramas/exercicio_03_arquitetura.svg` e na redação da justificativa.
  * **Exercícios 4 a 9 (workflows):** geração dos workflows pelo script `_build/build.py` via API pública do n8n, incluindo a configuração do Agent node, da tool, da LLM Chain com Structured Output Parser, dos sub-workflows, do pipeline em lote, da memória de janela e do estado persistente. Também os testes automatizados por webhook (`_build/run.py`).
  * **Documentação discursiva:** apoio na redação técnica dos arquivos `exercicio_XX.md`, seguindo a regra de não usar blocos de código.
* **Validação humana:** cada workflow foi aberto e executado no n8n local, a saída de cada nó foi conferida no painel de execuções, as Data Tables foram verificadas e os prints foram capturados pelo autor, em tela cheia, com data e hora visíveis.

---

## 2. Estrutura da Entrega
* `README.md`: identificação, estrutura e declaração de uso de IA.
* `exercicio_01.md` a `exercicio_09.md`: texto discursivo de cada exercício, com referência aos prints.
* `scripts/ex02_teste_prompts.py`: script Python de teste de prompts (Exercício 2).
* `diagramas/exercicio_03_arquitetura.svg`: mapa da estrutura agêntica (Exercício 3).
* `workflows/`: workflows exportados do n8n em JSON.
  * `sub_pedidos.json`: sub-workflow de consulta de status de pedido.
  * `sub_classificacao.json`: sub-workflow de classificação estruturada.
  * `workflow_exercicio_04.json` a `workflow_exercicio_09.json` e `workflow_exercicio_06_teste.json`.
* `saidas/`: resultados dos testes em JSON e texto.
* `prints/`: capturas de tela em tela cheia, com data e hora.

---

## 3. Organização dos Workflows no n8n
* **Sub-workflows** (chamados por outros workflows, sem lógica duplicada):
  * `TP3 - Sub-workflow - Consulta de Status de Pedido`: usado como tool pelo agente (Exercícios 6, 8 e 9) e pelo relatório proativo (Exercício 6).
  * `TP3 - Sub-workflow - Classificacao Estruturada de Mensagem`: usado pelo agente do Exercício 6 e pelo pipeline em lote do Exercício 7.
* **Workflows dos exercícios**: `TP3 - Exercicio 04` a `TP3 - Exercicio 09`, um por exercício, cada um partindo do anterior como pede o enunciado.

---

## 4. Data Tables Utilizadas
* `tp3_pedidos_clientes`: pedidos simulados consultados pela tool (Exercícios 4 a 9).
* `tp3_log_classificacoes`: log da classificação estruturada de cada mensagem (Exercícios 5 a 7).
* `tp3_conversas_estado`: estado persistido das conversas, com o histórico em JSON (Exercício 9).

---

## 5. Como Reproduzir
* Criar no n8n uma credencial do tipo OpenAI apontando para um endpoint compatível com a API da OpenAI e ajustar o modelo nos nós de LLM, se necessário.
* Importar os JSONs da pasta `workflows/`, começando pelos dois sub-workflows. Depois, nos nós Execute Workflow e Call n8n Workflow Tool, selecionar de novo o sub-workflow importado, porque os IDs mudam entre instâncias.
* Recriar as três Data Tables listadas acima (as colunas aparecem nos nós Data Table) e popular `tp3_pedidos_clientes`.
* Publicar os workflows e chamar os webhooks de produção descritos em cada `exercicio_XX.md`.
* Exercício 2: configurar `LLM_BASE_URL`, `LLM_API_KEY` e `LLM_MODEL` num arquivo `.env` e executar `python3 scripts/ex02_teste_prompts.py`.
