"""Fabricas de nos n8n compativeis com a versao 2.42 do n8n para o TP3."""
import json, os, uuid

STATE_PATH = os.path.join(os.path.dirname(__file__), 'state.json')
STATE = json.load(open(STATE_PATH)) if os.path.exists(STATE_PATH) else {'tables': {}, 'workflows': {}}
TZ = 'America/Sao_Paulo'

NS = uuid.UUID('8a2b3c4d-5e6f-7081-92a3-b4c5d6e7f801')
CTX = ['tp3']

# Credencial OpenAI existente no n8n (aponta para http://local:20128/v1 via 9router)
OPENAI_CRED_ID = 'X4WCOOQMDXqxOZAj'
OPENAI_CRED_NAME = 'OpenAI account'
DEFAULT_MODEL = 'cc/claude-haiku-5-5'


def reload_state():
    global STATE
    if os.path.exists(STATE_PATH):
        STATE = json.load(open(STATE_PATH))


def nid(*seed):
    return str(uuid.uuid5(NS, '|'.join([CTX[0], *map(str, seed)])))


def node(name, type_, version, params, pos, **extra):
    n = {'parameters': params, 'id': nid(name), 'name': name, 'type': type_,
         'typeVersion': version, 'position': list(pos)}
    n.update(extra)
    return n


# ------------------------------------------------------------------ triggers
def webhook(name, path, pos, method='POST'):
    return node(name, 'n8n-nodes-base.webhook', 2.2,
                {'httpMethod': method, 'path': path, 'responseMode': 'responseNode', 'options': {}},
                pos, webhookId=nid(name, 'webhook'))


def manual_trigger(name, pos):
    return node(name, 'n8n-nodes-base.manualTrigger', 1, {}, pos)


def subworkflow_trigger(name, pos, fields=None):
    """Gatilho de sub-workflow chamavel. Com fields (lista de nomes) declara as entradas
    (necessario para a Call n8n Workflow Tool mapear os campos); sem fields aceita tudo."""
    if fields:
        p = {'workflowInputs': {'values': [{'name': f, 'type': 'string'} for f in fields]}}
    else:
        p = {'inputSource': 'passthrough'}
    return node(name, 'n8n-nodes-base.executeWorkflowTrigger', 1.2, p, pos)


def split_out(name, field, pos):
    return node(name, 'n8n-nodes-base.splitOut', 1, {'fieldToSplitOut': field, 'include': 'noOtherFields',
                                                     'options': {}}, pos)


def merge_by_field(name, field, pos, join='enrichInput1'):
    return node(name, 'n8n-nodes-base.merge', 3.2, {
        'mode': 'combine', 'combineBy': 'combineByFields', 'fieldsToMatchString': field,
        'joinMode': join, 'options': {}}, pos)


# --------------------------------------------------------------- transforms
def set_fields(name, fields, pos, include_other=False):
    """fields: lista de (nome, expressao_ou_valor, tipo)."""
    assigns = [{'id': nid(name, f), 'name': f, 'value': v, 'type': t} for f, v, t in fields]
    p = {'mode': 'manual', 'includeOtherFields': include_other,
         'assignments': {'assignments': assigns}, 'options': {}}
    if include_other:
        p['include'] = 'all'
    return node(name, 'n8n-nodes-base.set', 3.4, p, pos)


def code(name, js, pos):
    return node(name, 'n8n-nodes-base.code', 2, {'jsCode': js.strip()}, pos)


def if_cond(name, left_expr, op_type, op_name, right_val, pos):
    return node(name, 'n8n-nodes-base.if', 2.2, {
        'conditions': {
            'options': {'caseSensitive': True, 'leftValue': '', 'typeValidation': 'loose', 'version': 2},
            'conditions': [{'id': nid(name, 'cond'), 'leftValue': left_expr, 'rightValue': right_val,
                            'operator': {'type': op_type, 'operation': op_name}}],
            'combinator': 'and'},
        'options': {}}, pos)


def split_in_batches(name, batch_size, pos):
    return node(name, 'n8n-nodes-base.splitInBatches', 3,
                {'batchSize': batch_size, 'options': {}}, pos)


def summarize_count(name, split_by_field, count_field, pos):
    """Agrupa por um campo e conta os itens (Ex 7)."""
    return node(name, 'n8n-nodes-base.summarize', 1.1, {
        'fieldsToSummarize': {'values': [{'aggregation': 'count', 'field': count_field}]},
        'fieldsToSplitBy': split_by_field,
        'options': {}}, pos)


def respond(name, body_expr, pos, code_=200):
    return node(name, 'n8n-nodes-base.respondToWebhook', 1.5, {
        'respondWith': 'json', 'responseBody': body_expr, 'options': {'responseCode': code_}}, pos)


def execute_subworkflow(name, subworkflow_id, pos, cached_name='', inputs=None):
    """Execute Workflow (modo 'once': todos os itens vao numa unica chamada).
    inputs: dict campo -> expressao, quando o gatilho do sub-workflow declara campos."""
    p = {'workflowId': {'__rl': True, 'mode': 'id', 'value': subworkflow_id, 'cachedResultName': cached_name},
         'options': {'waitForSubWorkflow': True}}
    if inputs:
        p['workflowInputs'] = {'mappingMode': 'defineBelow', 'value': inputs, 'matchingColumns': [],
                               'schema': [{'id': k, 'displayName': k, 'required': False, 'defaultMatch': False,
                                           'display': True, 'canBeUsedToMatch': True, 'type': 'string',
                                           'removed': False} for k in inputs],
                               'attemptToConvertTypes': False, 'convertFieldsToString': True}
    return node(name, 'n8n-nodes-base.executeWorkflow', 1.2, p, pos)


# --------------------------------------------------------------- data table
def _table(tname):
    reload_state()
    t = STATE['tables'][tname]
    return t['id'], t['columns']


def _dt_ref(tname):
    tid, _ = _table(tname)
    return {'__rl': True, 'mode': 'id', 'value': tid, 'cachedResultName': tname}


def _schema(tname):
    _, cols = _table(tname)
    return [{'id': c, 'displayName': c, 'required': False, 'defaultMatch': False, 'display': True,
             'type': t, 'readOnly': False, 'removed': False} for c, t in cols]


def dt_get(name, tname, key, key_expr, pos):
    """Busca linhas por uma condicao de igualdade."""
    return node(name, 'n8n-nodes-base.dataTable', 1.1, {
        'resource': 'row', 'operation': 'get', 'dataTableId': _dt_ref(tname),
        'matchType': 'allConditions',
        'filters': {'conditions': [{'keyName': key, 'condition': 'eq', 'keyValue': key_expr}]},
        'returnAll': True}, pos, alwaysOutputData=True)


def dt_get_all(name, tname, pos):
    return node(name, 'n8n-nodes-base.dataTable', 1.1, {
        'resource': 'row', 'operation': 'get', 'dataTableId': _dt_ref(tname),
        'matchType': 'allConditions', 'filters': {}, 'returnAll': True}, pos, alwaysOutputData=False)


def dt_insert(name, tname, values, pos):
    return node(name, 'n8n-nodes-base.dataTable', 1.1, {
        'resource': 'row', 'operation': 'insert', 'dataTableId': _dt_ref(tname),
        'columns': {'mappingMode': 'defineBelow', 'value': values, 'matchingColumns': [],
                    'schema': _schema(tname), 'attemptToConvertTypes': False, 'convertFieldsToString': False},
        'options': {}}, pos)


def dt_update(name, tname, key, key_expr, values, pos):
    return node(name, 'n8n-nodes-base.dataTable', 1.1, {
        'resource': 'row', 'operation': 'update', 'dataTableId': _dt_ref(tname),
        'matchType': 'allConditions',
        'filters': {'conditions': [{'keyName': key, 'condition': 'eq', 'keyValue': key_expr}]},
        'columns': {'mappingMode': 'defineBelow', 'value': values, 'matchingColumns': [],
                    'schema': _schema(tname), 'attemptToConvertTypes': False, 'convertFieldsToString': False},
        'options': {}}, pos, alwaysOutputData=True)


def dt_upsert(name, tname, key, key_expr, values, pos):
    return node(name, 'n8n-nodes-base.dataTable', 1.1, {
        'resource': 'row', 'operation': 'upsert', 'dataTableId': _dt_ref(tname),
        'matchType': 'allConditions',
        'filters': {'conditions': [{'keyName': key, 'condition': 'eq', 'keyValue': key_expr}]},
        'columns': {'mappingMode': 'defineBelow', 'value': values, 'matchingColumns': [],
                    'schema': _schema(tname), 'attemptToConvertTypes': False, 'convertFieldsToString': False},
        'options': {}}, pos, alwaysOutputData=True)


# ------------------------------------------------------------- AI / LangChain
def lm_chat_openai(name, pos, model=DEFAULT_MODEL, temperature=0.0):
    return node(name, '@n8n/n8n-nodes-langchain.lmChatOpenAi', 1.3, {
        'model': {'__rl': True, 'mode': 'id', 'value': model},
        'responsesApiEnabled': False,
        'options': {'temperature': temperature}}, pos,
        credentials={'openAiApi': {'id': OPENAI_CRED_ID, 'name': OPENAI_CRED_NAME}})


def agent_node(name, prompt_expr, system_message, pos, has_parser=False, intermediate_steps=True):
    p = {
        'promptType': 'define',
        'text': prompt_expr,
        'hasOutputParser': has_parser,
        'options': {'systemMessage': system_message, 'returnIntermediateSteps': intermediate_steps,
                    'enableStreaming': False}}
    return node(name, '@n8n/n8n-nodes-langchain.agent', 3.1, p, pos)


def data_table_tool(name, tname, key, ai_desc, tool_desc, pos):
    """No Data Table usado diretamente como tool do agente (busca por igualdade em uma coluna).
    O valor do filtro e preenchido pelo LLM via $fromAI."""
    return node(name, 'n8n-nodes-base.dataTableTool', 1.1, {
        'descriptionType': 'manual', 'toolDescription': tool_desc,
        'resource': 'row', 'operation': 'get', 'dataTableId': _dt_ref(tname),
        'matchType': 'allConditions',
        'filters': {'conditions': [{'keyName': key, 'condition': 'eq',
                                    'keyValue': "={{ $fromAI('%s', `%s`, 'string') }}" % (key, ai_desc)}]},
        'returnAll': True}, pos)


def chain_llm_node(name, prompt_expr, pos, system_message=None, has_parser=True, batch_size=None):
    """Basic LLM Chain. O texto do usuario vai em 'text'; a mensagem de sistema vai em messages.
    batch_size > 1 processa os itens do lote em paralelo (Promise.allSettled, v1.7+).
    onError=continueRegularOutput: falha de parsing de um item nao derruba o lote."""
    p = {'promptType': 'define', 'text': prompt_expr, 'hasOutputParser': has_parser}
    if system_message:
        p['messages'] = {'messageValues': [
            {'type': 'SystemMessagePromptTemplate', 'message': system_message}]}
    if batch_size:
        p['batching'] = {'batchSize': batch_size, 'delayBetweenBatches': 0}
    return node(name, '@n8n/n8n-nodes-langchain.chainLlm', 1.9, p, pos, onError='continueRegularOutput')


def output_parser_structured(name, json_schema_dict, pos, auto_fix=False):
    """Structured Output Parser com JSON Schema manual (v1.3: schemaType=manual + inputSchema)."""
    p = {'schemaType': 'manual',
         'inputSchema': json.dumps(json_schema_dict, indent=2, ensure_ascii=False)}
    if auto_fix:
        p['autoFix'] = True
    return node(name, '@n8n/n8n-nodes-langchain.outputParserStructured', 1.3, p, pos)


def memory_buffer_window(name, pos, context_window_length=5, session_key_expr='={{ $json.sessionId }}'):
    """Memoria de janela conversacional para o Agent node (Ex 8)."""
    p = {'sessionIdType': 'customKey',
         'sessionKey': session_key_expr,
         'contextWindowLength': context_window_length}
    return node(name, '@n8n/n8n-nodes-langchain.memoryBufferWindow', 1.4, p, pos)


def tool_code(name, description, js_code, pos):
    """Tool local em JavaScript. Na v1.3 o nome da tool vem do nome do no (sem parametro 'name').
    O texto que o LLM manda para a tool chega na variavel `query`."""
    return node(name, '@n8n/n8n-nodes-langchain.toolCode', 1.3,
                {'description': description, 'jsCode': js_code.strip()}, pos)


def tool_workflow(name, description, subworkflow_id, inputs, pos, cached_name=''):
    """Call n8n Workflow Tool (v2.2). inputs: dict campo -> expressao, normalmente
    "={{ $fromAI('pedido_id', 'descricao', 'string') }}" para o LLM preencher.
    Na v2.2 o nome da tool que o LLM enxerga e o nome do no."""
    return node(name, '@n8n/n8n-nodes-langchain.toolWorkflow', 2.2, {
        'description': description,
        'source': 'database',
        'workflowId': {'__rl': True, 'mode': 'id', 'value': subworkflow_id, 'cachedResultName': cached_name},
        'workflowInputs': {'mappingMode': 'defineBelow', 'value': inputs, 'matchingColumns': [],
                           'schema': [{'id': k, 'displayName': k, 'required': False, 'defaultMatch': False,
                                       'display': True, 'canBeUsedToMatch': True, 'type': 'string'}
                                      for k in inputs],
                           'attemptToConvertTypes': False, 'convertFieldsToString': False}}, pos)


# ------------------------------------------------------------- sticky note
def sticky(name, content, pos, w=480, h=220, color=7):
    return node(name, 'n8n-nodes-base.stickyNote', 1,
                {'content': content, 'height': h, 'width': w, 'color': color}, pos)


# -------------------------------------------------------------- connections
class Flow:
    def __init__(self):
        self.nodes = []
        self.connections = {}

    def add(self, *ns):
        self.nodes.extend(ns)
        return ns[0] if len(ns) == 1 else ns

    def link(self, a, b, out=0, inp=0, conn_type='main'):
        a_name = a if isinstance(a, str) else a['name']
        b_name = b if isinstance(b, str) else b['name']
        conns = self.connections.setdefault(a_name, {})
        outs = conns.setdefault(conn_type, [])
        while len(outs) <= out:
            outs.append([])
        outs[out].append({'node': b_name, 'type': conn_type, 'index': inp})

    def chain(self, *ns):
        for a, b in zip(ns, ns[1:]):
            self.link(a, b)

    def attach_model(self, target_node, model_node):
        """Conecta um LmChatOpenAi na entrada 'ai_languageModel' do Agent ou Chain."""
        self.link(model_node, target_node, out=0, inp=0, conn_type='ai_languageModel')

    def attach_tool(self, agent_node_, tool_node_):
        """Conecta uma Tool (ToolCode ou ToolWorkflow) na entrada 'ai_tool' do Agent."""
        self.link(tool_node_, agent_node_, out=0, inp=0, conn_type='ai_tool')

    def attach_memory(self, agent_node_, memory_node_):
        """Conecta a memoria na entrada 'ai_memory' do Agent."""
        self.link(memory_node_, agent_node_, out=0, inp=0, conn_type='ai_memory')

    def attach_parser(self, target_node, parser_node):
        """Conecta o Structured Output Parser na entrada 'ai_outputParser'."""
        self.link(parser_node, target_node, out=0, inp=0, conn_type='ai_outputParser')

    def workflow(self, name, pin=None):
        s = {'executionOrder': 'v1', 'timezone': TZ, 'saveManualExecutions': True,
             'saveDataErrorExecution': 'all', 'saveDataSuccessExecution': 'all',
             'saveExecutionProgress': True, 'callerPolicy': 'workflowsFromSameOwner'}
        w = {'name': name, 'nodes': self.nodes, 'connections': self.connections, 'settings': s}
        if pin is not None:
            w['pinData'] = pin
        return w
