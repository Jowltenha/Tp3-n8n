"""
TP3 (DR4) - Exercicio 2 - Teste de prompts de classificacao de mensagens de clientes
Vortice Logistica

Compara dois prompts para o mesmo LLM:
  - prompt SIMPLES   : pedido direto de classificacao (equivalente ao prompt do estagiario,
                        ja com a lista de categorias permitidas).
  - prompt GUIADO    : inferencia guiada passo a passo (assunto -> evidencias -> categorias
                        candidatas -> regra de desempate -> decisao final em formato fixo).

Cada mensagem de teste e enviada N vezes para cada prompt (temperatura > 0, como em producao),
para medir a CONSISTENCIA das respostas, e nao apenas o acerto de uma execucao isolada.

Uso:
    python3 ex02_teste_prompts.py [--repeticoes 5] [--temperatura 0.7]

Configuracao (arquivo .env na raiz do TP3, ver .env.example):
    LLM_BASE_URL  endpoint compativel com a API da OpenAI (ex.: http://localhost:20128/v1)
    LLM_API_KEY   chave de acesso
    LLM_MODEL     modelo (ex.: cc/claude-haiku-5-5)

Saidas:
    saidas/ex02_resultados.json   todas as respostas brutas + metricas
    saidas/ex02_resumo.txt        resumo legivel (o mesmo impresso no terminal)
"""
import argparse
import collections
import datetime as dt
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SAIDAS = os.path.join(RAIZ, 'saidas')


def carregar_env():
    env = {}
    caminho = os.path.join(RAIZ, '.env')
    if os.path.exists(caminho):
        for linha in open(caminho, encoding='utf-8'):
            if '=' in linha and not linha.strip().startswith('#'):
                k, v = linha.strip().split('=', 1)
                env[k] = v
    env.update({k: v for k, v in os.environ.items() if k.startswith('LLM_')})
    return env


ENV = carregar_env()
BASE_URL = ENV.get('LLM_BASE_URL', 'http://localhost:20128/v1').rstrip('/')
API_KEY = ENV.get('LLM_API_KEY', '')
MODELO = ENV.get('LLM_MODEL', 'cc/claude-haiku-5-5')

CATEGORIAS = ['atraso', 'avaria', 'rastreamento', 'outros']

# ------------------------------------------------------------ mensagens --
MENSAGENS = [
    {'id': 'M1', 'tipo': 'atraso', 'esperado': 'atraso',
     'texto': 'Meu pedido PED-3002 deveria ter chegado no dia 20 e até agora nada. '
              'Já são três dias de atraso e meus clientes estão me cobrando.'},
    {'id': 'M2', 'tipo': 'avaria', 'esperado': 'avaria',
     'texto': 'Recebi o pedido PED-3003 ontem, mas a caixa veio toda amassada e a tela '
              'do monitor chegou trincada.'},
    {'id': 'M3', 'tipo': 'duvida de rastreamento', 'esperado': 'rastreamento',
     'texto': 'Boa tarde! Vocês conseguem me dizer em que cidade está o meu pedido '
              'PED-3001 agora e se ele já saiu para entrega?'},
    {'id': 'M4', 'tipo': 'ambigua', 'esperado': 'avaria',
     'texto': 'Chegou só hoje, três dias depois do prazo, e a embalagem veio rasgada. E agora?'},
]

# --------------------------------------------------------------- prompts --
PROMPT_SIMPLES = (
    'Classifique a mensagem do cliente da transportadora em uma destas categorias: '
    'atraso, avaria, rastreamento ou outros.\n\n'
    'Mensagem: "{mensagem}"'
)

PROMPT_GUIADO_SISTEMA = (
    'Você é o classificador de mensagens do atendimento da Vórtice Logística, uma transportadora. '
    'Sua única tarefa é classificar a mensagem do cliente em EXATAMENTE UMA categoria. '
    'Não responda ao cliente e não reescreva a mensagem.\n\n'
    'Categorias permitidas:\n'
    '- atraso: a entrega ou coleta passou do prazo combinado, ou o cliente reclama da demora.\n'
    '- avaria: a carga ou a embalagem chegou danificada, violada, molhada, quebrada ou incompleta.\n'
    '- rastreamento: o cliente quer saber onde está o pedido, o status ou a previsão, sem relatar problema.\n'
    '- outros: qualquer assunto fora das três categorias acima (cobrança, cadastro, elogio etc.).\n\n'
    'Raciocine passo a passo, nesta ordem:\n'
    'PASSO 1 - ASSUNTO: em uma frase curta, diga do que a mensagem trata, sem classificar ainda.\n'
    'PASSO 2 - EVIDENCIAS: liste os trechos ou fatos da mensagem que indicam cada problema relatado.\n'
    'PASSO 3 - CANDIDATAS: liste as categorias que se aplicam às evidências (pode haver mais de uma).\n'
    'PASSO 4 - DESEMPATE: se houver mais de uma candidata, escolha pela prioridade '
    'avaria > atraso > rastreamento > outros, porque dano físico exige a ação mais urgente '
    '(abertura de sinistro). Se houver uma só, repita-a.\n'
    'PASSO 5 - DECISAO: escreva a categoria final, uma única palavra da lista permitida.\n\n'
    'Responda SOMENTE neste formato, com uma linha por passo e nada além disso:\n'
    'ASSUNTO: ...\n'
    'EVIDENCIAS: ...\n'
    'CANDIDATAS: ...\n'
    'DESEMPATE: ...\n'
    'CATEGORIA: <atraso|avaria|rastreamento|outros>'
)
PROMPT_GUIADO_USUARIO = 'Mensagem do cliente: "{mensagem}"'


def montar_mensagens(tipo_prompt, texto):
    if tipo_prompt == 'simples':
        return [{'role': 'user', 'content': PROMPT_SIMPLES.format(mensagem=texto)}]
    return [{'role': 'system', 'content': PROMPT_GUIADO_SISTEMA},
            {'role': 'user', 'content': PROMPT_GUIADO_USUARIO.format(mensagem=texto)}]


# ------------------------------------------------------------ chamada LLM --
def chamar_llm(mensagens, temperatura, tentativas=4):
    corpo = json.dumps({'model': MODELO, 'messages': mensagens, 'temperature': temperatura,
                        'stream': False, 'max_tokens': 600}).encode()
    for t in range(1, tentativas + 1):
        req = urllib.request.Request(f'{BASE_URL}/chat/completions', data=corpo, method='POST',
                                     headers={'Content-Type': 'application/json',
                                              'Authorization': f'Bearer {API_KEY}'})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read().decode())
            return d['choices'][0]['message'].get('content') or '', d.get('model', MODELO)
        except (urllib.error.URLError, KeyError, json.JSONDecodeError) as e:
            if t == tentativas:
                return f'[ERRO NA CHAMADA: {e}]', MODELO
            time.sleep(3 * t)


# --------------------------------------------------------- interpretacao --
def sem_acento(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn').lower()


def categorias_citadas(trecho):
    """Rotulos permitidos que aparecem como palavra inteira no trecho."""
    t = sem_acento(trecho)
    return [c for c in CATEGORIAS if re.search(rf'\b{c}\b', t)]


def interpretar(tipo_prompt, resposta):
    """Simula o que o proximo no do fluxo conseguiria extrair da resposta.

    - simples: o fluxo so tem o texto livre; procura os rotulos permitidos na resposta inteira.
    - guiado : o fluxo le apenas a linha 'CATEGORIA:' (formato combinado no prompt).
    Resultado: categoria (str ou None) e situacao: 'unica', 'mista' ou 'sem_categoria'.
    """
    if tipo_prompt == 'guiado':
        m = re.search(r'^\s*\**\s*CATEGORIA\s*\**\s*:\s*(.+)$', resposta, re.I | re.M)
        trecho = m.group(1) if m else ''
    else:
        trecho = resposta
    cats = categorias_citadas(trecho)
    if len(cats) == 1:
        return cats[0], 'unica'
    if len(cats) > 1:
        return '+'.join(cats), 'mista'
    return None, 'sem_categoria'


def extrair_assunto(resposta):
    m = re.search(r'^\s*\**\s*ASSUNTO\s*\**\s*:\s*(.+)$', resposta, re.I | re.M)
    return m.group(1).strip() if m else None


# ------------------------------------------------------------------ main --
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repeticoes', type=int, default=5)
    ap.add_argument('--temperatura', type=float, default=0.7)
    args = ap.parse_args()

    os.makedirs(SAIDAS, exist_ok=True)
    inicio = dt.datetime.now()
    linhas_resumo = [
        f'TP3 - Exercicio 2 - Teste de prompts ({inicio:%Y-%m-%d %H:%M:%S})',
        f'Modelo: {MODELO} | endpoint: {BASE_URL} | repeticoes por mensagem: {args.repeticoes} '
        f'| temperatura: {args.temperatura}', '']

    resultados = {'executado_em': inicio.isoformat(timespec='seconds'), 'modelo': MODELO,
                  'temperatura': args.temperatura, 'repeticoes': args.repeticoes,
                  'prompts': {'simples': PROMPT_SIMPLES,
                              'guiado_sistema': PROMPT_GUIADO_SISTEMA,
                              'guiado_usuario': PROMPT_GUIADO_USUARIO},
                  'mensagens': []}
    metricas_gerais = {p: collections.Counter() for p in ('simples', 'guiado')}

    for msg in MENSAGENS:
        reg = {**msg, 'execucoes': {}}
        linhas_resumo.append(f'[{msg["id"]}] ({msg["tipo"]}, esperado: {msg["esperado"]}) {msg["texto"]}')
        for tipo_prompt in ('simples', 'guiado'):
            execs = []
            for i in range(args.repeticoes):
                resposta, modelo_real = chamar_llm(montar_mensagens(tipo_prompt, msg['texto']), args.temperatura)
                cat, situacao = interpretar(tipo_prompt, resposta)
                execs.append({'rodada': i + 1, 'modelo': modelo_real, 'categoria_extraida': cat,
                              'situacao': situacao, 'acertou': cat == msg['esperado'],
                              'assunto': extrair_assunto(resposta) if tipo_prompt == 'guiado' else None,
                              'resposta_bruta': resposta})
                print(f'  {msg["id"]} {tipo_prompt:8s} rodada {i + 1}: {situacao:13s} -> {cat}', flush=True)
            dist = collections.Counter(e['categoria_extraida'] or 'sem_categoria' for e in execs)
            moda, qtd_moda = dist.most_common(1)[0]
            met = {'distribuicao': dict(dist),
                   'respostas_com_categoria_unica': sum(e['situacao'] == 'unica' for e in execs),
                   'respostas_mistas': sum(e['situacao'] == 'mista' for e in execs),
                   'respostas_sem_categoria': sum(e['situacao'] == 'sem_categoria' for e in execs),
                   'acertos': sum(e['acertou'] for e in execs),
                   'consistencia_pct': round(100 * qtd_moda / len(execs)),
                   'resposta_mais_frequente': moda,
                   'tamanho_medio_resposta_caracteres': round(sum(len(e['resposta_bruta']) for e in execs) / len(execs))}
            reg['execucoes'][tipo_prompt] = {'metricas': met, 'rodadas': execs}
            for k in ('respostas_com_categoria_unica', 'respostas_mistas', 'respostas_sem_categoria', 'acertos'):
                metricas_gerais[tipo_prompt][k] += met[k]
            metricas_gerais[tipo_prompt]['total'] += len(execs)
            linhas_resumo.append(
                f'    {tipo_prompt:8s} unica={met["respostas_com_categoria_unica"]} mista={met["respostas_mistas"]} '
                f'sem_categoria={met["respostas_sem_categoria"]} acertos={met["acertos"]}/{len(execs)} '
                f'consistencia={met["consistencia_pct"]}% distribuicao={dict(dist)}')
            exemplo = execs[0]['resposta_bruta'].strip().replace('\n', ' | ')
            linhas_resumo.append(f'             exemplo rodada 1: {exemplo[:260]}')
        resultados['mensagens'].append(reg)
        linhas_resumo.append('')

    linhas_resumo.append('TOTAIS')
    for p, m in metricas_gerais.items():
        tot = m['total']
        linhas_resumo.append(
            f'    {p:8s} categoria unica {m["respostas_com_categoria_unica"]}/{tot} | mistas {m["respostas_mistas"]}/{tot} '
            f'| sem categoria {m["respostas_sem_categoria"]}/{tot} | acertos {m["acertos"]}/{tot}')
    resultados['totais'] = {p: dict(m) for p, m in metricas_gerais.items()}
    resultados['duracao_segundos'] = round((dt.datetime.now() - inicio).total_seconds(), 1)

    with open(os.path.join(SAIDAS, 'ex02_resultados.json'), 'w', encoding='utf-8') as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)
    resumo = '\n'.join(linhas_resumo)
    with open(os.path.join(SAIDAS, 'ex02_resumo.txt'), 'w', encoding='utf-8') as f:
        f.write(resumo + '\n')
    print('\n' + resumo)
    print(f'\nArquivos gerados: saidas/ex02_resultados.json e saidas/ex02_resumo.txt '
          f'({resultados["duracao_segundos"]}s)')


if __name__ == '__main__':
    sys.exit(main())
