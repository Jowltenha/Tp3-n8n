"""Gera e publica os workflows do TP3 (DR4) no n8n local via API publica.

Uso: python3 -I build.py [chave ...]      (sem argumentos = todos, na ordem de dependencia)
     python3 -I build.py ex08 --janela 1  (variante do Ex08 usada no teste de janela pequena)

Os IDs ficam em state.json; reexecutar atualiza os workflows no lugar.

Evolucao dos workflows (cada exercicio parte do anterior):
  ex04  Webhook -> Agent (LLM + tool Data Table de pedidos) -> resposta
  ex05  ex04 + LLM Chain com Structured Output Parser + validacao + log em Data Table
  ex06  ex05 com as duas logicas extraidas para sub-workflows:
          sub_pedidos        (consulta de status, usada como tool do agente)
          sub_classificacao  (LLM Chain + parser + validacao + log)
        ex06_teste chama sub_pedidos fora do agente (relatorio proativo)
  ex07  lote -> Split Out -> sub_classificacao (chain em paralelo) -> Merge -> Summarize
  ex08  Webhook -> Agent (LLM + memoria de janela + tool sub_pedidos) -> resposta
  ex09  ex08 com o historico persistido em JSON na Data Table tp3_conversas_estado
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import nodes as N
from nodes import Flow
from api import call

STATE_PATH = os.path.join(os.path.dirname(__file__), 'state.json')
STATE = json.load(open(STATE_PATH))
STATE.setdefault('workflows', {})

MODELO = N.DEFAULT_MODEL


def wid(key):
    w = STATE['workflows'].get(key, {}).get('id')
    if not w:
        raise SystemExit(f'workflow {key} ainda nao foi criado; rode build.py {key} antes')
    return w


def wname(key):
    return STATE['workflows'][key]['name']


NOMES = {
    'sub_pedidos': 'TP3 - Sub-workflow - Consulta de Status de Pedido',
    'sub_classificacao': 'TP3 - Sub-workflow - Classificacao Estruturada de Mensagem',
    'ex04': 'TP3 - Exercicio 04 - Agente de Atendimento com Tool de Status de Pedido',
    'ex05': 'TP3 - Exercicio 05 - Classificacao Estruturada (LLM Chain + JSON) com Log',
    'ex06': 'TP3 - Exercicio 06 - Agente de Atendimento com Sub-workflows',
    'ex06_teste': 'TP3 - Exercicio 06 - Teste de Reutilizacao (Relatorio Proativo de Pedido)',
    'ex07': 'TP3 - Exercicio 07 - Pipeline em Lote com Split, Join e Agregacao',
    'ex08': 'TP3 - Exercicio 08 - Agente Conversacional com Memoria de Janela',
    'ex09': 'TP3 - Exercicio 09 - Agente com Estado Persistente em JSON',
}

# ====================================================================== prompts
SYSTEM_AGENTE = (
    "Voce e o agente de atendimento da Vortice Logistica, uma transportadora. Responda em portugues do Brasil, "
    "de forma cordial, objetiva e em poucas frases.\n"
    "Regras:\n"
    "1. Sempre que o cliente perguntar sobre um pedido (status, localizacao, previsao, atraso, avaria ou entrega), "
    "chame a ferramenta consultar_status_pedido com o codigo do pedido ANTES de responder. Nunca invente status, "
    "datas ou localizacao: use apenas o que a ferramenta devolver.\n"
    "2. Se o cliente nao informar o codigo do pedido (formato PED-0000), peca o codigo.\n"
    "3. Se a ferramenta nao encontrar o pedido, diga isso e peca para o cliente conferir o codigo.\n"
    "4. Em caso de avaria, informe que o caso segue para a equipe de sinistros. Em caso de atraso, informe a nova "
    "previsao e o motivo registrado."
)

SYSTEM_MEMORIA = (
    "\n5. Esta e uma conversa com varias mensagens. Use o que o cliente ja informou antes (nome, codigo do pedido, "
    "problema relatado) e nao peca de novo uma informacao que ja foi dada."
)

SYSTEM_CLASSIFICACAO = (
    "Voce e o classificador de mensagens do atendimento da Vortice Logistica, uma transportadora. "
    "Classifique a mensagem do cliente em EXATAMENTE UMA categoria e defina a urgencia. "
    "Nao responda ao cliente e nao reescreva a mensagem.\n\n"
    "Categorias permitidas:\n"
    "- atraso: a entrega ou coleta passou do prazo, ou o cliente reclama da demora.\n"
    "- avaria: carga ou embalagem danificada, violada, molhada, quebrada ou incompleta.\n"
    "- rastreamento: o cliente quer saber onde esta o pedido, o status ou a previsao, sem relatar problema.\n"
    "- outros: qualquer outro assunto (cadastro, cobranca, elogio etc.).\n\n"
    "Raciocine nesta ordem e preencha os campos do JSON na mesma ordem:\n"
    "1. assunto: diga em uma frase curta do que a mensagem trata, sem classificar ainda.\n"
    "2. evidencias: liste os fatos da mensagem que indicam cada problema relatado.\n"
    "3. categoria: escolha UMA categoria. Se mais de uma se aplicar, use a prioridade "
    "avaria > atraso > rastreamento > outros (dano fisico exige abrir sinistro, a acao mais urgente).\n"
    "4. urgencia: alta para avaria, ou atraso com cliente insatisfeito; media para atraso sem reclamacao forte; "
    "baixa para rastreamento e outros.\n"
    "5. pedido_id_mencionado: o codigo do pedido no formato PED-0000, ou string vazia se nao houver.\n"
    "6. justificativa: uma frase explicando a decisao."
)

SCHEMA_CLASSIFICACAO = {
    'type': 'object',
    'properties': {
        'assunto': {'type': 'string', 'description': 'Assunto da mensagem em uma frase curta'},
        'evidencias': {'type': 'array', 'items': {'type': 'string'},
                       'description': 'Fatos da mensagem que sustentam a classificacao'},
        'categoria': {'type': 'string', 'enum': ['atraso', 'avaria', 'rastreamento', 'outros']},
        'urgencia': {'type': 'string', 'enum': ['baixa', 'media', 'alta']},
        'pedido_id_mencionado': {'type': 'string', 'description': 'Codigo PED-0000 citado ou string vazia'},
        'justificativa': {'type': 'string'},
    },
    'required': ['assunto', 'evidencias', 'categoria', 'urgencia', 'pedido_id_mencionado', 'justificativa'],
}

DESC_TOOL = ('Consulta o status de um pedido da Vortice Logistica na base de pedidos. Use sempre que o cliente '
             'perguntar sobre um pedido. Entrada: o codigo do pedido no formato PED-0000 (ex.: PED-3001). '
             'Devolve status, localizacao atual, previsao de entrega, transportadora e observacoes.')


# ============================================================ blocos reutilizados
def bloco_classificacao(f, origem_node, x, y, batch_size=None):
    """Chain + modelo + parser + validacao (usado inline no Ex05 e dentro do sub-workflow)."""
    chain = f.add(N.chain_llm_node('[IA] Classificar Mensagem (LLM Chain)',
                                   '=Mensagem do cliente: "{{ $json.mensagem }}"', (x, y),
                                   system_message=SYSTEM_CLASSIFICACAO, has_parser=True, batch_size=batch_size))
    llm = f.add(N.lm_chat_openai('[IA] Modelo de Linguagem (Classificacao)', (x - 60, y + 220), MODELO, 0))
    parser = f.add(N.output_parser_structured('[IA] Parser JSON Estruturado (categoria e urgencia)',
                                              SCHEMA_CLASSIFICACAO, (x + 140, y + 220)))
    f.attach_model(chain, llm)
    f.attach_parser(chain, parser)
    val = f.add(N.code('[FUNCAO] Validar Campos da Classificacao', """
// Confere se cada saida do LLM tem os campos esperados com valores validos.
// Itens que falharam no parser (onError = continuar) chegam com o campo error.
const entradas = $('%s').all();
const CATEGORIAS = ['atraso', 'avaria', 'rastreamento', 'outros'];
const URGENCIAS = ['baixa', 'media', 'alta'];
const OBRIGATORIOS = ['assunto', 'categoria', 'urgencia', 'justificativa'];
return $input.all().map((item, i) => {
  const e = entradas[i] ? entradas[i].json : {};
  const s = item.json || {};
  const p = (s.output && typeof s.output === 'object') ? s.output : s;
  const faltando = OBRIGATORIOS.filter(c => p[c] === undefined || p[c] === null || String(p[c]).trim() === '');
  const categoria = String(p.categoria || '').toLowerCase().trim();
  const urgencia = String(p.urgencia || '').toLowerCase().trim();
  const valida = !s.error && faltando.length === 0 && CATEGORIAS.includes(categoria) && URGENCIAS.includes(urgencia);
  return { json: {
    pergunta_id: e.pergunta_id,
    cliente_id: e.cliente_id,
    mensagem: e.mensagem,
    origem: e.origem,
    assunto: p.assunto || '',
    evidencias: Array.isArray(p.evidencias) ? p.evidencias : [],
    categoria: valida ? categoria : 'nao_classificado',
    urgencia: valida ? urgencia : 'alta',
    pedido_id_mencionado: (p.pedido_id_mencionado || '').toUpperCase(),
    justificativa: p.justificativa || (s.error ? 'Falha no parsing: ' + String(s.error).slice(0, 200) : ''),
    classificacao_valida: valida,
    campos_faltando: faltando,
    registrado_em: $now.toISO()
  } };
});""" % origem_node, (x + 300, y)))
    log = f.add(N.dt_insert('[SAIDA] Registrar Classificacao em tp3_log_classificacoes', 'tp3_log_classificacoes', {
        'pergunta_id': '={{ $json.pergunta_id }}',
        'exercicio': '={{ $json.origem }}',
        'cliente_id': '={{ $json.cliente_id }}',
        'mensagem': '={{ $json.mensagem }}',
        'assunto': '={{ $json.assunto }}',
        'categoria': '={{ $json.categoria }}',
        'urgencia': '={{ $json.urgencia }}',
        'pedido_id_mencionado': '={{ $json.pedido_id_mencionado }}',
        'justificativa': '={{ $json.justificativa }}',
        'classificacao_valida': '={{ String($json.classificacao_valida) }}',
        'registrado_em': '={{ $json.registrado_em }}',
    }, (x + 520, y)))
    f.chain(chain, val, log)
    return chain, val, log


NORMALIZAR_WEBHOOK = """
const b = $json.body || {};
return [{ json: {
  pergunta_id: b.pergunta_id || ('PERG-' + $now.toFormat('yyyyMMdd-HHmmss') + '-' + $execution.id),
  cliente_id: b.cliente_id || 'nao_informado',
  session_id: b.session_id || b.cliente_id || ('sessao-' + $execution.id),
  mensagem: String(b.mensagem || '').trim(),
  origem: '%s',
  recebido_em: $now.toISO()
} }];"""


def agente(f, nome, prompt, system, x, y):
    ag = f.add(N.agent_node(nome, prompt, system, (x, y)))
    llm = f.add(N.lm_chat_openai('[IA] Modelo de Linguagem (Agente)', (x - 120, y + 220), MODELO, 0))
    f.attach_model(ag, llm)
    return ag


def tool_sub_pedidos(f, pos):
    return f.add(N.tool_workflow('consultar_status_pedido', DESC_TOOL, wid('sub_pedidos'),
                                 {'pedido_id': "={{ $fromAI('pedido_id', `Codigo do pedido no formato PED-0000`, 'string') }}"},
                                 pos, cached_name=wname('sub_pedidos')))


RESPOSTA_AGENTE = """
const a = $input.first().json;
const passos = (a.intermediateSteps || []).map(p => ({
  ferramenta: p.action && p.action.tool,
  entrada: p.action && p.action.toolInput,
}));
return [{ json: {
  ...$('%s').first().json,
  resposta: a.output,
  agente_usou_ferramenta: passos.length > 0,
  ferramentas_acionadas: passos,
} }];"""


# =============================================================== sub-workflows
def sub_pedidos():
    f = Flow()
    t = f.add(N.subworkflow_trigger('[ENTRADA] Receber pedido_id', (0, 0), fields=['pedido_id']))
    h = f.add(N.set_fields('[FUNCAO] Padronizar Codigo do Pedido', [
        ('pedido_id_original', '={{ $json.pedido_id }}', 'string'),
        ('pedido_id', "={{ (() => { const d = String($json.pedido_id || '').replace(/[^0-9]/g, ''); return d ? 'PED-' + d : ''; })() }}", 'string'),
    ], (220, 0)))
    b = f.add(N.dt_get('[INTEGRACAO] Buscar Pedido em tp3_pedidos_clientes', 'tp3_pedidos_clientes',
                       'pedido_id', '={{ $json.pedido_id }}', (440, 0)))
    m = f.add(N.code('[FUNCAO] Montar Resposta Padronizada', """
// Contrato unico de saida, consumido pelo agente (tool) e pelo relatorio proativo.
const buscado = $('[FUNCAO] Padronizar Codigo do Pedido').first().json;
const p = $input.all().map(i => i.json).find(r => r.pedido_id);
if (!p) {
  return [{ json: {
    encontrado: false,
    pedido_id: buscado.pedido_id || buscado.pedido_id_original,
    mensagem: 'Pedido nao encontrado na base da Vortice Logistica. Confira o codigo informado.'
  } }];
}
return [{ json: {
  encontrado: true,
  pedido_id: p.pedido_id,
  cliente_id: p.cliente_id,
  cliente_nome: p.cliente_nome,
  produto: p.produto,
  status: p.status,
  transportadora: p.transportadora,
  origem: p.origem,
  destino: p.destino,
  localizacao_atual: p.localizacao_atual,
  previsao_entrega: p.previsao_entrega,
  ultima_atualizacao: p.ultima_atualizacao,
  observacao: p.observacao,
  consultado_em: $now.toISO()
} }];""", (660, 0)))
    f.chain(t, h, b, m)
    return f.workflow(NOMES['sub_pedidos'])


def sub_classificacao():
    f = Flow()
    t = f.add(N.subworkflow_trigger('[ENTRADA] Receber Mensagens (1 ou varias)', (0, 0)))
    n = f.add(N.code('[FUNCAO] Normalizar Mensagens', """
return $input.all().map((it, i) => {
  const j = it.json;
  return { json: {
    pergunta_id: j.pergunta_id || ('PERG-' + $execution.id + '-' + (i + 1)),
    cliente_id: j.cliente_id || 'nao_informado',
    mensagem: String(j.mensagem || j.texto || '').trim(),
    origem: j.origem || 'sub_classificacao'
  } };
});""", (220, 0)))
    chain, val, log = bloco_classificacao(f, '[FUNCAO] Normalizar Mensagens', 460, 0, batch_size=4)
    out = f.add(N.code('[SAIDA] Devolver Classificacoes ao Chamador', """
return $('[FUNCAO] Validar Campos da Classificacao').all().map(i => ({ json: i.json }));""", (1200, 0)))
    f.chain(t, n, chain)
    f.link(log, out)
    return f.workflow(NOMES['sub_classificacao'])


# ================================================================== Exercicio 4
def ex04():
    f = Flow()
    wh = f.add(N.webhook('[ENTRADA] Webhook Mensagem do Cliente', 'tp3-ex04-atendimento', (0, 0)))
    no = f.add(N.code('[FUNCAO] Normalizar Mensagem', NORMALIZAR_WEBHOOK % 'ex04', (220, 0)))
    ag = agente(f, '[AGENTE] Agente de Atendimento', '={{ $json.mensagem }}', SYSTEM_AGENTE, 480, 0)
    tool = f.add(N.data_table_tool('consultar_status_pedido', 'tp3_pedidos_clientes', 'pedido_id',
                                   'Codigo do pedido no formato PED-0000', DESC_TOOL, (560, 220)))
    f.attach_tool(ag, tool)
    rs = f.add(N.code('[FUNCAO] Montar Resposta Final', RESPOSTA_AGENTE % '[FUNCAO] Normalizar Mensagem', (800, 0)))
    rp = f.add(N.respond('[SAIDA] Responder ao Webhook', '={{ $json }}', (1020, 0)))
    f.chain(wh, no, ag, rs, rp)
    return f.workflow(NOMES['ex04'])


# ================================================================== Exercicio 5
def ex05():
    f = Flow()
    wh = f.add(N.webhook('[ENTRADA] Webhook Mensagem do Cliente', 'tp3-ex05-atendimento', (0, 0)))
    no = f.add(N.code('[FUNCAO] Normalizar Mensagem', NORMALIZAR_WEBHOOK % 'ex05', (220, 0)))
    chain, val, log = bloco_classificacao(f, '[FUNCAO] Normalizar Mensagem', 460, 0)
    ok = f.add(N.if_cond('[FUNCAO] Classificacao Valida?', '={{ $json.classificacao_valida }}',
                         'boolean', 'true', '', (1200, 0)))
    prompt = ("={{ $('[FUNCAO] Normalizar Mensagem').first().json.mensagem }}\n\n"
              "[Classificacao automatica: categoria {{ $json.categoria }}, urgencia {{ $json.urgencia }}]")
    ag = agente(f, '[AGENTE] Agente de Atendimento', prompt, SYSTEM_AGENTE, 1460, -60)
    tool = f.add(N.data_table_tool('consultar_status_pedido', 'tp3_pedidos_clientes', 'pedido_id',
                                   'Codigo do pedido no formato PED-0000', DESC_TOOL, (1540, 160)))
    f.attach_tool(ag, tool)
    rs = f.add(N.code('[FUNCAO] Montar Resposta Final', """
const a = $input.first().json;
const c = $('[FUNCAO] Validar Campos da Classificacao').first().json;
return [{ json: {
  pergunta_id: c.pergunta_id,
  mensagem: c.mensagem,
  classificacao: { assunto: c.assunto, categoria: c.categoria, urgencia: c.urgencia,
                   pedido_id_mencionado: c.pedido_id_mencionado, justificativa: c.justificativa,
                   classificacao_valida: c.classificacao_valida },
  resposta: a.output,
  agente_usou_ferramenta: (a.intermediateSteps || []).length > 0
} }];""", (1780, -60)))
    rp = f.add(N.respond('[SAIDA] Responder ao Webhook', '={{ $json }}', (2000, -60)))
    inv = f.add(N.respond('[SAIDA] Responder Classificacao Invalida',
                          "={{ { pergunta_id: $json.pergunta_id, classificacao_valida: false, campos_faltando: $json.campos_faltando, resposta: 'Recebemos sua mensagem. Um atendente vai analisar seu caso.' } }}",
                          (1460, 240), code_=202))
    f.chain(wh, no, chain)
    f.link(log, ok)
    f.link(ok, ag, out=0)
    f.link(ok, inv, out=1)
    f.chain(ag, rs, rp)
    return f.workflow(NOMES['ex05'])


# ================================================================== Exercicio 6
def ex06():
    f = Flow()
    wh = f.add(N.webhook('[ENTRADA] Webhook Mensagem do Cliente', 'tp3-ex06-atendimento', (0, 0)))
    no = f.add(N.code('[FUNCAO] Normalizar Mensagem', NORMALIZAR_WEBHOOK % 'ex06', (220, 0)))
    cl = f.add(N.execute_subworkflow('[SUBWORKFLOW] Classificar Mensagem', wid('sub_classificacao'),
                                     (440, 0), cached_name=wname('sub_classificacao')))
    ok = f.add(N.if_cond('[FUNCAO] Classificacao Valida?', '={{ $json.classificacao_valida }}',
                         'boolean', 'true', '', (660, 0)))
    prompt = ("={{ $('[FUNCAO] Normalizar Mensagem').first().json.mensagem }}\n\n"
              "[Classificacao automatica: categoria {{ $json.categoria }}, urgencia {{ $json.urgencia }}]")
    ag = agente(f, '[AGENTE] Agente de Atendimento', prompt, SYSTEM_AGENTE, 920, -60)
    f.attach_tool(ag, tool_sub_pedidos(f, (1000, 160)))
    rs = f.add(N.code('[FUNCAO] Montar Resposta Final', """
const a = $input.first().json;
const c = $('[SUBWORKFLOW] Classificar Mensagem').first().json;
return [{ json: {
  pergunta_id: c.pergunta_id,
  mensagem: c.mensagem,
  classificacao: { categoria: c.categoria, urgencia: c.urgencia, assunto: c.assunto },
  resposta: a.output,
  ferramentas_acionadas: (a.intermediateSteps || []).map(p => ({ ferramenta: p.action && p.action.tool, entrada: p.action && p.action.toolInput }))
} }];""", (1240, -60)))
    rp = f.add(N.respond('[SAIDA] Responder ao Webhook', '={{ $json }}', (1460, -60)))
    inv = f.add(N.respond('[SAIDA] Responder Classificacao Invalida',
                          "={{ { pergunta_id: $json.pergunta_id, classificacao_valida: false, resposta: 'Recebemos sua mensagem. Um atendente vai analisar seu caso.' } }}",
                          (920, 240), code_=202))
    f.chain(wh, no, cl, ok)
    f.link(ok, ag, out=0)
    f.link(ok, inv, out=1)
    f.chain(ag, rs, rp)
    return f.workflow(NOMES['ex06'])


def ex06_teste():
    f = Flow()
    wh = f.add(N.webhook('[ENTRADA] Webhook Relatorio Proativo', 'tp3-ex06-relatorio-proativo', (0, 0)))
    sp = f.add(N.code('[FUNCAO] Listar Pedidos do Relatorio', """
const b = $json.body || {};
const pedidos = Array.isArray(b.pedidos) && b.pedidos.length ? b.pedidos : ['PED-3002', 'PED-3005'];
return pedidos.map(p => ({ json: { pedido_id: p } }));""", (220, 0)))
    ex = f.add(N.execute_subworkflow('[SUBWORKFLOW] Consultar Status do Pedido', wid('sub_pedidos'), (440, 0),
                                     cached_name=wname('sub_pedidos'),
                                     inputs={'pedido_id': '={{ $json.pedido_id }}'}))
    ex['parameters']['mode'] = 'each'
    rel = f.add(N.code('[FUNCAO] Montar Relatorio Proativo', """
// Mensagem enviada ao cliente antes de qualquer contato com o atendimento.
const linhas = $input.all().map(i => i.json).map(p => p.encontrado
  ? { pedido_id: p.pedido_id, cliente: p.cliente_nome, status: p.status,
      aviso_ao_cliente: `Ola, ${p.cliente_nome}! Seu pedido ${p.pedido_id} (${p.produto}) esta com status "${p.status}". ` +
        `Local atual: ${p.localizacao_atual}. Previsao de entrega: ${p.previsao_entrega}.` }
  : { pedido_id: p.pedido_id, status: 'nao_encontrado', aviso_ao_cliente: null });
return [{ json: { relatorio: 'status_proativo', gerado_em: $now.toISO(), origem_dos_dados: 'sub-workflow de consulta de status (mesmo usado pelo agente)', total: linhas.length, pedidos: linhas } }];""", (660, 0)))
    rp = f.add(N.respond('[SAIDA] Responder Relatorio', '={{ $json }}', (880, 0)))
    f.chain(wh, sp, ex, rel, rp)
    return f.workflow(NOMES['ex06_teste'])


# ================================================================== Exercicio 7
def ex07():
    f = Flow()
    wh = f.add(N.webhook('[ENTRADA] Webhook Lote de Mensagens', 'tp3-ex07-lote', (0, 0)))
    so = f.add(N.split_out('[FUNCAO] Dividir Lote em Itens (Split Out)', 'body.mensagens', (220, 0)))
    pr = f.add(N.set_fields('[FUNCAO] Preparar Item', [
        ('pergunta_id', '={{ $json.pergunta_id }}', 'string'),
        ('cliente_id', '={{ $json.cliente_id }}', 'string'),
        ('mensagem', '={{ $json.mensagem }}', 'string'),
        ('categoria_esperada', '={{ $json.categoria_esperada }}', 'string'),
        ('origem', 'ex07', 'string'),
    ], (440, 0)))
    cl = f.add(N.execute_subworkflow('[SUBWORKFLOW] Classificar Itens em Paralelo', wid('sub_classificacao'),
                                     (680, -100), cached_name=wname('sub_classificacao')))
    mg = f.add(N.merge_by_field('[FUNCAO] Recombinar Itens com a Classificacao (Merge)', 'pergunta_id', (920, 0)))
    sm = f.add(N.summarize_count('[FUNCAO] Agregar por Categoria (Summarize)', 'categoria', 'pergunta_id', (1140, 0)))
    rs = f.add(N.code('[FUNCAO] Montar Resumo e Conferir Contagem', """
const itens = $('[FUNCAO] Recombinar Itens com a Classificacao (Merge)').all().map(i => i.json);
const porCategoria = {};
for (const g of $input.all()) porCategoria[g.json.categoria] = g.json.count_pergunta_id;
const esperado = {};
for (const it of itens) esperado[it.categoria_esperada] = (esperado[it.categoria_esperada] || 0) + 1;
const cats = [...new Set([...Object.keys(porCategoria), ...Object.keys(esperado)])].sort();
const conferencia = cats.map(c => ({ categoria: c, obtido: porCategoria[c] || 0, esperado: esperado[c] || 0,
                                     confere: (porCategoria[c] || 0) === (esperado[c] || 0) }));
return [{ json: {
  resumo: 'lote_matinal',
  gerado_em: $now.toISO(),
  total_mensagens: itens.length,
  total_por_categoria: porCategoria,
  conferencia_contagem_manual: conferencia,
  resumo_bate_com_contagem_manual: conferencia.every(c => c.confere),
  itens: itens.map(i => ({ pergunta_id: i.pergunta_id, categoria: i.categoria, esperado: i.categoria_esperada, urgencia: i.urgencia }))
} }];""", (1360, 0)))
    rp = f.add(N.respond('[SAIDA] Responder Resumo do Lote', '={{ $json }}', (1580, 0)))
    f.chain(wh, so, pr)
    f.link(pr, cl)
    f.link(pr, mg, inp=0)
    f.link(cl, mg, inp=1)
    f.chain(mg, sm, rs, rp)
    return f.workflow(NOMES['ex07'])


# ================================================================== Exercicio 8
def ex08(janela=5):
    f = Flow()
    wh = f.add(N.webhook('[ENTRADA] Webhook Mensagem do Cliente', 'tp3-ex08-conversa', (0, 0)))
    no = f.add(N.code('[FUNCAO] Normalizar Mensagem', NORMALIZAR_WEBHOOK % 'ex08', (220, 0)))
    ag = agente(f, '[AGENTE] Agente de Atendimento', '={{ $json.mensagem }}', SYSTEM_AGENTE + SYSTEM_MEMORIA, 480, 0)
    mem = f.add(N.memory_buffer_window(f'[MEMORIA] Memoria de Janela (ultimas {janela} trocas)', (480, 240),
                                       context_window_length=janela, session_key_expr='={{ $json.session_id }}'))
    f.attach_memory(ag, mem)
    f.attach_tool(ag, tool_sub_pedidos(f, (640, 240)))
    rs = f.add(N.code('[FUNCAO] Montar Resposta Final', RESPOSTA_AGENTE % '[FUNCAO] Normalizar Mensagem', (800, 0)))
    rp = f.add(N.respond('[SAIDA] Responder ao Webhook', '={{ $json }}', (1020, 0)))
    f.chain(wh, no, ag, rs, rp)
    return f.workflow(NOMES['ex08'])


# ================================================================== Exercicio 9
MAX_TURNOS = 10


def ex09():
    f = Flow()
    wh = f.add(N.webhook('[ENTRADA] Webhook Mensagem do Cliente', 'tp3-ex09-conversa', (0, 0)))
    no = f.add(N.code('[FUNCAO] Normalizar Mensagem', NORMALIZAR_WEBHOOK % 'ex09', (220, 0)))
    ld = f.add(N.dt_get('[ESTADO] Carregar Estado da Conversa', 'tp3_conversas_estado',
                        'session_id', '={{ $json.session_id }}', (440, 0)))
    ct = f.add(N.code('[ESTADO] Reconstruir Historico (JSON)', """
// Roda ANTES do agente: le o estado salvo por execucoes anteriores (talvez em outro servidor n8n).
const msg = $('[FUNCAO] Normalizar Mensagem').first().json;
const linha = $input.all().map(i => i.json).find(r => r.session_id);
let historico = [];
let contexto = {};
if (linha) {
  try { historico = JSON.parse(linha.historico_json || '[]'); } catch (e) { historico = []; }
  try { contexto = JSON.parse(linha.contexto_json || '{}'); } catch (e) { contexto = {}; }
}
const recente = historico.slice(-%d);
const texto = recente.map(t => `Cliente: ${t.cliente}\\nAgente: ${t.agente}`).join('\\n\\n');
const prompt = (recente.length
  ? `Historico desta conversa, recuperado do estado persistido (${recente.length} trocas):\\n${texto}\\n\\n`
  : 'Esta e a primeira mensagem desta conversa (nenhum estado salvo).\\n\\n')
  + `Nova mensagem do cliente: ${msg.mensagem}`;
return [{ json: {
  ...msg,
  estado_encontrado: !!linha,
  trocas_recuperadas: recente.length,
  historico,
  contexto,
  criado_em: linha ? linha.criado_em : $now.toISO(),
  prompt_agente: prompt
} }];""" % MAX_TURNOS, (660, 0)))
    ag = agente(f, '[AGENTE] Agente de Atendimento', '={{ $json.prompt_agente }}', SYSTEM_AGENTE + SYSTEM_MEMORIA, 900, 0)
    f.attach_tool(ag, tool_sub_pedidos(f, (980, 220)))
    up = f.add(N.code('[ESTADO] Atualizar Historico (JSON)', """
const c = $('[ESTADO] Reconstruir Historico (JSON)').first().json;
const a = $input.first().json;
const historico = [...c.historico, { cliente: c.mensagem, agente: a.output, em: $now.toISO(), execucao: $execution.id }].slice(-%d);
const pedidos = [...new Set([...(c.contexto.pedidos_citados || []),
  ...((c.mensagem + ' ' + a.output).toUpperCase().match(/PED-\\d+/g) || [])])];
return [{ json: {
  session_id: c.session_id,
  cliente_id: c.cliente_id,
  historico_json: JSON.stringify(historico),
  contexto_json: JSON.stringify({ pedidos_citados: pedidos, ultima_execucao: $execution.id }),
  total_mensagens: historico.length,
  criado_em: c.criado_em,
  atualizado_em: $now.toISO(),
  resposta: a.output,
  estado_encontrado: c.estado_encontrado,
  trocas_recuperadas: c.trocas_recuperadas,
  ferramentas_acionadas: (a.intermediateSteps || []).map(p => p.action && p.action.tool)
} }];""" % MAX_TURNOS, (1140, 0)))
    sv = f.add(N.dt_upsert('[ESTADO] Salvar Estado em tp3_conversas_estado', 'tp3_conversas_estado',
                           'session_id', '={{ $json.session_id }}', {
                               c: '={{ $json.%s }}' % c for c in
                               ('session_id', 'cliente_id', 'historico_json', 'contexto_json',
                                'total_mensagens', 'criado_em', 'atualizado_em')}, (1360, 0)))
    rp = f.add(N.respond('[SAIDA] Responder ao Webhook', """={{ { session_id: $('[ESTADO] Atualizar Historico (JSON)').first().json.session_id, resposta: $('[ESTADO] Atualizar Historico (JSON)').first().json.resposta, estado_encontrado: $('[ESTADO] Atualizar Historico (JSON)').first().json.estado_encontrado, trocas_recuperadas: $('[ESTADO] Atualizar Historico (JSON)').first().json.trocas_recuperadas, total_trocas_salvas: $('[ESTADO] Atualizar Historico (JSON)').first().json.total_mensagens, ferramentas_acionadas: $('[ESTADO] Atualizar Historico (JSON)').first().json.ferramentas_acionadas, execucao: $execution.id } }}""", (1580, 0)))
    f.chain(wh, no, ld, ct, ag, up, sv, rp)
    return f.workflow(NOMES['ex09'])


# ====================================================================== deploy
BUILDERS = {'sub_pedidos': sub_pedidos, 'sub_classificacao': sub_classificacao, 'ex04': ex04, 'ex05': ex05,
            'ex06': ex06, 'ex06_teste': ex06_teste, 'ex07': ex07, 'ex08': ex08, 'ex09': ex09}


def deploy(key, wf):
    cur = STATE['workflows'].get(key)
    if cur:
        res = call('PUT', f"/workflows/{cur['id']}", wf)
    else:
        res = call('POST', '/workflows', wf)
        STATE['workflows'][key] = {'id': res['id']}
    STATE['workflows'][key]['name'] = res['name']
    json.dump(STATE, open(STATE_PATH, 'w'), indent=1)
    print(f"{key:18s} {res['id']}  {res['name']}")
    return res


if __name__ == '__main__':
    args = sys.argv[1:]
    janela = 5
    if '--janela' in args:
        i = args.index('--janela')
        janela = int(args[i + 1])
        del args[i:i + 2]
    for k in args or list(BUILDERS):
        N.CTX[0] = k
        wf = BUILDERS[k](janela) if k == 'ex08' else BUILDERS[k]()
        deploy(k, wf)
