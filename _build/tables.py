"""Cria (idempotente) as Data Tables do TP3 e popula a tabela de pedidos simulados.

Uso: python3 -I tables.py [--reseed]
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from api import call

STATE = os.path.join(os.path.dirname(__file__), 'state.json')
state = json.load(open(STATE)) if os.path.exists(STATE) else {}
state.setdefault('tables', {})
state.setdefault('workflows', {})

S, N = 'string', 'number'
TABLES = {
    # Ex4 em diante: base de pedidos consultada pela tool / sub-workflow
    'tp3_pedidos_clientes': [
        ('pedido_id', S), ('cliente_id', S), ('cliente_nome', S), ('produto', S), ('status', S),
        ('transportadora', S), ('origem', S), ('destino', S), ('localizacao_atual', S),
        ('previsao_entrega', S), ('ultima_atualizacao', S), ('observacao', S)],
    # Ex5 e Ex7: log da classificacao estruturada
    'tp3_log_classificacoes': [
        ('pergunta_id', S), ('exercicio', S), ('cliente_id', S), ('mensagem', S), ('assunto', S),
        ('categoria', S), ('urgencia', S), ('pedido_id_mencionado', S), ('justificativa', S),
        ('classificacao_valida', S), ('registrado_em', S)],
    # Ex9: estado persistente da conversa (historico serializado em JSON)
    'tp3_conversas_estado': [
        ('session_id', S), ('cliente_id', S), ('historico_json', S), ('contexto_json', S),
        ('total_mensagens', N), ('criado_em', S), ('atualizado_em', S)],
}

SEED = {
    'tp3_pedidos_clientes': [
        dict(pedido_id='PED-3001', cliente_id='CLI-001', cliente_nome='Ana Souza', produto='Notebook Dell Inspiron 15',
             status='em_transito', transportadora='Rodovia Express', origem='Curitiba/PR', destino='Sao Paulo/SP',
             localizacao_atual='Centro de distribuicao de Campinas/SP', previsao_entrega='2026-11-24',
             ultima_atualizacao='2026-11-22 18:40', observacao='Carga dentro do prazo'),
        dict(pedido_id='PED-3002', cliente_id='CLI-002', cliente_nome='Bruno Lima', produto='Kit de ferramentas industriais',
             status='atrasado', transportadora='TransSul Cargas', origem='Porto Alegre/RS', destino='Florianopolis/SC',
             localizacao_atual='Centro de distribuicao de Joinville/SC', previsao_entrega='2026-11-25',
             ultima_atualizacao='2026-11-22 09:15',
             observacao='Previsao original era 2026-11-20. Carga retida por excesso de volume no CD de Joinville'),
        dict(pedido_id='PED-3003', cliente_id='CLI-003', cliente_nome='Carla Mendes', produto='Monitor LG 27 polegadas',
             status='entregue_com_avaria', transportadora='Rodovia Express', origem='Sao Paulo/SP', destino='Belo Horizonte/MG',
             localizacao_atual='Entregue ao destinatario', previsao_entrega='2026-11-21',
             ultima_atualizacao='2026-11-21 16:02', observacao='Cliente relatou tela trincada. Sinistro SIN-0778 aberto'),
        dict(pedido_id='PED-3004', cliente_id='CLI-001', cliente_nome='Ana Souza', produto='Cadeira de escritorio ergonomica',
             status='aguardando_coleta', transportadora='Norte Log', origem='Manaus/AM', destino='Sao Paulo/SP',
             localizacao_atual='Remetente (coleta agendada para 2026-11-24)', previsao_entrega='2026-11-30',
             ultima_atualizacao='2026-11-22 11:00', observacao='Coleta agendada na janela 08h-12h'),
        dict(pedido_id='PED-3005', cliente_id='CLI-004', cliente_nome='Diego Ramos', produto='Smartphone Samsung A56',
             status='saiu_para_entrega', transportadora='Via Cerrado Transportes', origem='Goiania/GO', destino='Brasilia/DF',
             localizacao_atual='Em rota de entrega - Asa Sul, Brasilia/DF', previsao_entrega='2026-11-23',
             ultima_atualizacao='2026-11-23 07:30', observacao='Entrega prevista ate 18h'),
        dict(pedido_id='PED-3006', cliente_id='CLI-002', cliente_nome='Bruno Lima', produto='Impressora termica de etiquetas',
             status='entregue', transportadora='TransSul Cargas', origem='Porto Alegre/RS', destino='Florianopolis/SC',
             localizacao_atual='Entregue ao destinatario', previsao_entrega='2026-11-18',
             ultima_atualizacao='2026-11-18 14:25', observacao='Recebido por Marcos (portaria)'),
    ],
}

existing = {t['name']: t for t in call('GET', '/data-tables?limit=100')['data']}
for name, cols in TABLES.items():
    if name in existing:
        tid = existing[name]['id']
    else:
        tid = call('POST', '/data-tables', {'name': name, 'columns': [{'name': c, 'type': t} for c, t in cols]})['id']
        print('criada', name, tid)
    state['tables'][name] = {'id': tid, 'columns': cols}
    if name in SEED and ('--reseed' in sys.argv or name not in existing):
        call('DELETE', f'/data-tables/{tid}/rows/clear')
        r = call('POST', f'/data-tables/{tid}/rows', {'data': SEED[name], 'returnType': 'count'})
        print('populada', name, r)
    if '--clear-logs' in sys.argv and name != 'tp3_pedidos_clientes':
        call('DELETE', f'/data-tables/{tid}/rows/clear')
        print('limpa', name)

json.dump(state, open(STATE, 'w'), indent=1)
print(json.dumps({k: v['id'] for k, v in state['tables'].items()}, indent=1))
