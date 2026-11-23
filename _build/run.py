"""Dispara os testes de cada exercicio via webhook de producao e salva o resultado em saidas/.

Uso: python3 -I run.py ex04|ex05|ex06|ex06_teste|ex07|ex08|ex08_janela1|ex09|all
Requer os workflows publicados (build.py) e ativos (este script ativa os necessarios).
"""
import json, os, sys, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(__file__))
from api import call

STATE = json.load(open(os.path.join(os.path.dirname(__file__), 'state.json')))
SAIDAS = os.path.join(os.path.dirname(__file__), '..', 'saidas')
os.makedirs(SAIDAS, exist_ok=True)

MSGS_EX02 = [  # mesmas quatro mensagens do Exercicio 2
    ('M1', 'atraso', 'Meu pedido PED-3002 deveria ter chegado no dia 20 e até agora nada. Já são três dias de atraso e meus clientes estão me cobrando.'),
    ('M2', 'avaria', 'Recebi o pedido PED-3003 ontem, mas a caixa veio toda amassada e a tela do monitor chegou trincada.'),
    ('M3', 'rastreamento', 'Boa tarde! Vocês conseguem me dizer em que cidade está o meu pedido PED-3001 agora e se ele já saiu para entrega?'),
    ('M4', 'avaria', 'Chegou só hoje, três dias depois do prazo, e a embalagem veio rasgada. E agora?'),
]

LOTE_EX07 = [
    ('L01', 'CLI-002', 'atraso', 'O pedido PED-3002 era para o dia 20 e ainda não chegou. Preciso de uma posição urgente.'),
    ('L02', 'CLI-003', 'avaria', 'O monitor do pedido PED-3003 chegou com a tela trincada.'),
    ('L03', 'CLI-001', 'rastreamento', 'Onde está o meu pedido PED-3001 agora?'),
    ('L04', 'CLI-004', 'rastreamento', 'Meu celular já saiu para entrega? Pedido PED-3005.'),
    ('L05', 'CLI-005', 'atraso', 'Faz uma semana que espero a entrega e ninguém me dá retorno. Isso é um absurdo.'),
    ('L06', 'CLI-006', 'avaria', 'A caixa chegou molhada e dois itens vieram quebrados.'),
    ('L07', 'CLI-007', 'outros', 'Gostaria de atualizar o endereço de cobrança do meu cadastro.'),
    ('L08', 'CLI-001', 'rastreamento', 'Qual a previsão de coleta do pedido PED-3004?'),
    ('L09', 'CLI-008', 'avaria', 'Chegou com dois dias de atraso e com a embalagem violada.'),
    ('L10', 'CLI-009', 'outros', 'Parabéns pelo atendimento de ontem, o motorista foi muito educado.'),
]

CONVERSA = [
    'Oi, meu nome é Bruno e tenho uma dúvida sobre o meu pedido PED-3002.',
    'Ele já deveria ter chegado. Qual é a nova previsão de entrega?',
    'E qual transportadora está com ele e por que atrasou?',
    'Obrigado. Só para confirmar: qual é mesmo o número do meu pedido e qual o meu nome?',
]


def wf(key):
    return STATE['workflows'][key]['id']


def ativar(*keys):
    for k in keys:
        call('POST', f'/workflows/{wf(k)}/activate', {})


def post(path, body, timeout=240):
    req = urllib.request.Request(f'http://localhost:5678/webhook/{path}', method='POST',
                                 data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or '{}')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:2000]


def ultima_exec(key):
    ex = call('GET', f'/executions?workflowId={wf(key)}&limit=1')['data']
    return ex[0]['id'] if ex else None


def salvar(nome, dados):
    with open(os.path.join(SAIDAS, nome), 'w', encoding='utf-8') as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    print(json.dumps(dados, ensure_ascii=False, indent=2)[:6000])


def ex04():
    ativar('ex04')
    st, r = post('tp3-ex04-atendimento', {'cliente_id': 'CLI-001', 'session_id': 'ex04-teste',
                                          'mensagem': 'Oi! Cadê meu pedido PED-3001? Quando ele chega?'})
    salvar('ex04_teste_agente_tool.json', {'http': st, 'execucao': ultima_exec('ex04'), 'resposta': r})


def ex05():
    ativar('ex05')
    res = []
    for mid, esperado, txt in MSGS_EX02:
        st, r = post('tp3-ex05-atendimento', {'pergunta_id': f'EX05-{mid}', 'cliente_id': 'CLI-TESTE', 'mensagem': txt})
        res.append({'id': mid, 'esperado': esperado, 'http': st, 'execucao': ultima_exec('ex05'), 'resposta': r})
    salvar('ex05_teste_quatro_mensagens.json', res)


def ex06():
    ativar('sub_pedidos', 'sub_classificacao', 'ex06')
    st, r = post('tp3-ex06-atendimento', {'pergunta_id': 'EX06-AGENTE', 'cliente_id': 'CLI-003',
                                          'mensagem': 'Meu monitor do pedido PED-3003 chegou trincado. O que vocês vão fazer?'})
    salvar('ex06_teste_agente_subworkflow.json', {'http': st, 'execucao': ultima_exec('ex06'), 'resposta': r})


def ex06_teste():
    ativar('sub_pedidos', 'ex06_teste')
    st, r = post('tp3-ex06-relatorio-proativo', {'pedidos': ['PED-3002', 'PED-3005', 'PED-9999']})
    salvar('ex06_teste_relatorio_proativo.json', {'http': st, 'execucao': ultima_exec('ex06_teste'), 'resposta': r})


def ex07():
    ativar('sub_classificacao', 'ex07')
    lote = [{'pergunta_id': i, 'cliente_id': c, 'categoria_esperada': e, 'mensagem': m} for i, c, e, m in LOTE_EX07]
    t0 = time.time()
    st, r = post('tp3-ex07-lote', {'mensagens': lote}, timeout=600)
    salvar('ex07_resumo_lote.json', {'http': st, 'execucao': ultima_exec('ex07'),
                                     'duracao_segundos': round(time.time() - t0, 1), 'resposta': r})


def conversa(key, path, arquivo, sessao):
    ativar('sub_pedidos', key)
    turnos = []
    for i, msg in enumerate(CONVERSA, 1):
        st, r = post(path, {'cliente_id': 'CLI-002', 'session_id': sessao, 'mensagem': msg})
        turnos.append({'turno': i, 'mensagem': msg, 'http': st, 'execucao': ultima_exec(key), 'resposta': r})
        time.sleep(1)
    salvar(arquivo, {'session_id': sessao, 'turnos': turnos})


def ex08():
    conversa('ex08', 'tp3-ex08-conversa', 'ex08_conversa_janela5.json', f'ex08-bruno-{int(time.time())}')


def ex08_janela1():
    conversa('ex08', 'tp3-ex08-conversa', 'ex08_conversa_janela1.json', f'ex08-janela1-{int(time.time())}')


def ex09():
    # Cada POST e uma execucao nova e independente do workflow; o contexto so pode vir da Data Table.
    conversa('ex09', 'tp3-ex09-conversa', 'ex09_conversa_estado_persistente.json', f'ex09-bruno-{int(time.time())}')


TESTES = {'ex04': ex04, 'ex05': ex05, 'ex06': ex06, 'ex06_teste': ex06_teste, 'ex07': ex07,
          'ex08': ex08, 'ex08_janela1': ex08_janela1, 'ex09': ex09}

if __name__ == '__main__':
    alvos = sys.argv[1:] or ['all']
    for a in (list(k for k in TESTES if k != 'ex08_janela1') if alvos == ['all'] else alvos):
        print(f'\n===== {a} =====')
        TESTES[a]()
