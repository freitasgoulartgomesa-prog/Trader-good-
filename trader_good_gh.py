#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TRADER GOOD — versão GitHub Actions.
Cada execução é UM PULSO: acorda, olha o gráfico real, decide, aprende,
salva o estado em arquivo, e termina. A continuidade entre execuções vem
do GitHub Actions rodando este script a cada ~5 minutos e do estado ser
salvo em estado.json (commitado de volta no repositório).

REGRAS DE HONESTIDADE (não negociáveis):
  - Preço só vem da Binance, de verdade. Se não conectar, este pulso não
    finge dado — ele anota a falha no relatório e termina sem inventar nada.
  - Não existe "acelerar o gráfico". Cada vela M5 só conta quando fechou de
    verdade. Sem aceleração nesta versão nem em nenhuma outra.
  - Tudo é PAPEL. Nenhuma ordem é enviada à Binance.
"""

import urllib.request, json, math, random, os, sys
from datetime import datetime, timezone

ATIVOS      = [("BTC","BTCUSDT",1), ("ETH","ETHUSDT",1), ("SOL","SOLUSDT",2), ("XRP","XRPUSDT",4)]
INTERVALO   = "5m"
VELAS_HIST  = 500
CUSTO_PCT   = 0.0006
SALDO_INI   = 100.0
STAKE_FRAC  = 0.06
LR          = 0.035
JANELA_MAX  = 30          # quantas velas recentes ficam guardadas no estado p/ calcular features
ULTIMAS_OPS_MAX = 25       # quantas operações recentes ficam visíveis no RELATORIO.md

ENDPOINTS = ["https://api.binance.com", "https://data-api.binance.vision"]
ACOES   = ["FORA", "COMPRA_5", "COMPRA_15", "VENDE_5", "VENDE_15"]
HOLD    = [0, 1, 3, 1, 3]
EH_LONG = [False, True, True, False, False]
EH_OP   = [False, True, True, True, True]
FEATS   = ["zscore","momentum","rsi","volReg","corpo","pavio","tendencia","hora_sin","hora_cos"]
NOMES_PT = {"zscore":"distância da média","momentum":"força recente","rsi":"sobrecompra/venda",
            "volReg":"regime de volatilidade","corpo":"tamanho do corpo da vela",
            "pavio":"pavios (sombras)","tendencia":"tendência curta","hora_sin":"hora (ciclo)",
            "hora_cos":"hora (ciclo)"}

ESTADO_PATH    = "estado.json"
LOG_PATH       = "historico_operacoes.jsonl"
RELATORIO_PATH = "RELATORIO.md"

# ------------------------------------------------------------------ Binance
def baixar_velas(par, intervalo=INTERVALO, limite=VELAS_HIST):
    caminho = "/api/v3/klines?symbol=%s&interval=%s&limit=%d" % (par, intervalo, limite)
    for base in ENDPOINTS:
        try:
            req = urllib.request.Request(base+caminho, headers={"User-Agent":"trader-good-gh/1.0"})
            with urllib.request.urlopen(req, timeout=12) as r:
                bruto = json.loads(r.read().decode())
            if not isinstance(bruto, list) or not bruto: continue
            return [{"t":int(k[0]),"o":float(k[1]),"h":float(k[2]),"l":float(k[3]),
                     "c":float(k[4]),"v":float(k[5])} for k in bruto]
        except Exception:
            continue
    return None

# ------------------------------------------------------------------ features
def _media(xs): return sum(xs)/len(xs) if xs else 0.0
def _desvio(xs):
    if len(xs)<2: return 0.0
    m=_media(xs); return math.sqrt(sum((x-m)**2 for x in xs)/(len(xs)-1))
def _clip(x,a,b): return a if x<a else (b if x>b else x)
def _rsi(closes,n=14):
    if len(closes)<n+1: return 50.0
    g=p=0.0
    for i in range(-n,0):
        d=closes[i]-closes[i-1]
        if d>=0: g+=d
        else: p-=d
    if p==0: return 100.0
    rs=(g/n)/(p/n); return 100-100/(1+rs)

def calcular_features(velas, idx):
    if idx<25 or idx>=len(velas): return None
    jan=velas[idx-25:idx+1]; closes=[v["c"] for v in jan]; atual=jan[-1]
    m20=_media(closes[-20:]); sd20=_desvio(closes[-20:]) or 1e-9
    zscore=_clip((atual["c"]-m20)/sd20,-1.5,1.5)
    base=closes[-6] if len(closes)>=6 else closes[0]
    momentum=_clip(((atual["c"]-base)/base)*60,-1.5,1.5)
    rsi=_clip((_rsi(closes)-50)/50,-1.0,1.0)
    sdc=_desvio(closes[-6:]); sdl=_desvio(closes[-20:]) or 1e-9
    volReg=_clip((sdc/sdl)-1.0,-1.0,1.0)
    rng=(atual["h"]-atual["l"]) or 1e-9
    corpo=_clip((atual["c"]-atual["o"])/rng,-1.0,1.0)
    pc=atual["h"]-max(atual["c"],atual["o"]); pb=min(atual["c"],atual["o"])-atual["l"]
    pavio=_clip((pb-pc)/rng,-1.0,1.0)
    emc=_media(closes[-5:]); eml=_media(closes[-20:]) or 1e-9
    tendencia=_clip(((emc-eml)/eml)*120,-1.5,1.5)
    hora=datetime.fromtimestamp(atual["t"]/1000,timezone.utc).hour
    return [zscore,momentum,rsi,volReg,corpo,pavio,tendencia,
            math.sin(2*math.pi*hora/24), math.cos(2*math.pi*hora/24)]

# ------------------------------------------------------------------ agente (dict puro -> JSON-friendly)
def agente_novo():
    return {"bias":{str(a):(3.0 if a==0 else -0.8) for a in range(5)},
            "w":{str(a):{f:0.0 for f in FEATS} for a in range(5)},
            "eps":0.12,"baseline":0.0,"passos":0}

def _logits(ag,x):
    return [ag["bias"][str(a)]+sum(ag["w"][str(a)][f]*x[i] for i,f in enumerate(FEATS)) for a in range(5)]
def _softmax(lg):
    mx=max(lg); ex=[math.exp(l-mx) for l in lg]; tot=sum(ex); return [e/tot for e in ex]
def agente_escolher(ag,x):
    probs=_softmax(_logits(ag,x))
    if random.random()<ag["eps"]:
        a=random.randrange(5)
    else:
        r=random.random(); acc=0; a=4
        for i,p in enumerate(probs):
            acc+=p
            if r<=acc: a=i; break
    return a,probs
def agente_aprender(ag,x,a,recompensa):
    ag["passos"]+=1
    ag["baseline"]+=0.01*(recompensa-ag["baseline"])
    vant=recompensa-ag["baseline"]; probs=_softmax(_logits(ag,x))
    for ac in range(5):
        grad=(1.0 if ac==a else 0.0)-probs[ac]
        ag["bias"][str(ac)]+=LR*vant*grad
        for i,f in enumerate(FEATS):
            ag["w"][str(ac)][f]+=LR*vant*grad*x[i]
    if ag["eps"]>0.03: ag["eps"]*=0.99985

# ------------------------------------------------------------------ estado
def estado_inicial():
    return {
        "versao":1, "criado_em":datetime.now(timezone.utc).isoformat(),
        "fase1_concluida": False,
        "agente": agente_novo(),
        "saldo": SALDO_INI,
        "stats": {"n":0,"acertos":0,"net_total":0.0,
                  "por_acao":{str(a):{"n":0,"acertos":0,"net":0.0} for a in range(1,5)}},
        "posicoes": {nome:None for nome,_,_ in ATIVOS},
        "ultimo_ts": {nome:None for nome,_,_ in ATIVOS},
        "janela": {nome:[] for nome,_,_ in ATIVOS},
        "ultimas_ops": [],
        "ultima_verificacao": None,
        "ultimo_status_conexao": None,
    }

def carregar_estado():
    if os.path.exists(ESTADO_PATH):
        with open(ESTADO_PATH,"r",encoding="utf-8") as f: return json.load(f)
    return estado_inicial()

def salvar_estado(est):
    est["atualizado_em"]=datetime.now(timezone.utc).isoformat()
    with open(ESTADO_PATH,"w",encoding="utf-8") as f: json.dump(est,f,ensure_ascii=False,indent=2)

def registrar_log(registro):
    with open(LOG_PATH,"a",encoding="utf-8") as f: f.write(json.dumps(registro,ensure_ascii=False)+"\n")

# ------------------------------------------------------------------ fechar operação (compartilhado)
def fechar_operacao(est, nome, pos, preco_saida, fase):
    a=pos["a"]; entrada=pos["entrada"]
    bruto=((preco_saida-entrada)/entrada) if EH_LONG[a] else ((entrada-preco_saida)/entrada)
    net=bruto-CUSTO_PCT; win=net>0
    stake=max(1.0, est["saldo"]*STAKE_FRAC)
    pnl=_clip(stake*(net/0.003), -stake*0.95, stake*1.5)
    est["saldo"]+=pnl
    st=est["stats"]; st["n"]+=1; st["net_total"]+=net*100
    if win: st["acertos"]+=1
    pa=st["por_acao"][str(a)]; pa["n"]+=1; pa["net"]+=net*100
    if win: pa["acertos"]+=1
    agente_aprender(est["agente"], pos["x"], a, _clip(net/0.003,-3,3))
    registro={"ts":datetime.now(timezone.utc).isoformat(),"fase":fase,"ativo":nome,"acao":ACOES[a],
              "entrada":round(entrada,6),"saida":round(preco_saida,6),
              "net_pct":round(net*100,4),"win":win,"pnl":round(pnl,3),"saldo_apos":round(est["saldo"],2)}
    registrar_log(registro)
    est["ultimas_ops"].append(registro)
    est["ultimas_ops"]=est["ultimas_ops"][-ULTIMAS_OPS_MAX:]
    return registro

# ------------------------------------------------------------------ FASE 1 — histórico real (uma vez)
def rodar_fase1(est):
    print("Fase 1: baixando histórico real e treinando o agente...")
    velas_por_ativo={}
    for nome,par,_ in ATIVOS:
        v=baixar_velas(par, INTERVALO, VELAS_HIST)
        if not v:
            print("  Falhou baixar histórico de %s — tento de novo no próximo pulso." % nome)
            return False
        velas_por_ativo[nome]=v
        print("  %s: %d velas reais." % (nome, len(v)))
    ag=est["agente"]
    maxlen=max(len(v) for v in velas_por_ativo.values())
    total=0
    for idx in range(26, maxlen):
        for nome,_,_ in ATIVOS:
            velas=velas_por_ativo.get(nome)
            if not velas or idx>=len(velas): continue
            x=calcular_features(velas, idx)
            if x is None: continue
            a,_=agente_escolher(ag, x)
            if not EH_OP[a]:
                agente_aprender(ag, x, a, 0.0); continue
            hold=HOLD[a]
            if idx+hold>=len(velas): continue
            entrada=velas[idx]["c"]; saida=velas[idx+hold]["c"]
            pos={"a":a,"entrada":entrada,"x":x}
            fechar_operacao(est, nome, pos, saida, "historico")
            total+=1
    for nome,_,_ in ATIVOS:
        v=velas_por_ativo[nome]
        est["janela"][nome]=v[-JANELA_MAX:]
        est["ultimo_ts"][nome]=v[-1]["t"]
    est["fase1_concluida"]=True
    print("  Fase 1 concluída: %d operações sobre dado real, %d passos de treino." % (total, ag["passos"]))
    return True

# ------------------------------------------------------------------ PULSO AO VIVO (a cada execução)
def rodar_pulso_ao_vivo(est):
    algo_mudou=False
    for nome,par,casas in ATIVOS:
        recentes=baixar_velas(par, INTERVALO, 8)
        if not recentes:
            print("  %s: sem resposta da Binance neste pulso." % nome); continue
        fechadas=recentes[:-1]  # a última do array ainda pode estar se formando
        novas=[v for v in fechadas if est["ultimo_ts"][nome] is None or v["t"]>est["ultimo_ts"][nome]]
        if not novas: continue
        for vela in novas:
            jan=est["janela"][nome]; jan.append(vela); est["janela"][nome]=jan[-JANELA_MAX:]
            est["ultimo_ts"][nome]=vela["t"]
            pos=est["posicoes"].get(nome)
            if pos:
                pos["faltam"]-=1
                if pos["faltam"]<=0:
                    reg=fechar_operacao(est, nome, pos, vela["c"], "ao_vivo")
                    est["posicoes"][nome]=None
                    print("  %s %s fechou %+.3f%% líq | saldo R$%.2f" % (nome, ACOES[pos["a"]], reg["net_pct"], est["saldo"]))
                    algo_mudou=True
            if est["posicoes"].get(nome) is None:
                x=calcular_features(est["janela"][nome], len(est["janela"][nome])-1)
                if x is not None:
                    a,_=agente_escolher(est["agente"], x)
                    if EH_OP[a]:
                        est["posicoes"][nome]={"a":a,"entrada":vela["c"],"faltam":HOLD[a],"x":x}
                        print("  %s abriu %s @ %.*f" % (nome, ACOES[a], casas, vela["c"]))
                        algo_mudou=True
    return algo_mudou

# ------------------------------------------------------------------ RELATÓRIO (sempre atualizado)
def escrever_relatorio(est, status_conexao):
    st=est["stats"]; n=st["n"]; wr=(st["acertos"]/n*100) if n else 0.0
    net_medio=(st["net_total"]/n) if n else 0.0
    agora=datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    L=[]; a=L.append
    a("# 🤖 Trader Good — status do agente\n")
    a("_Atualiza automaticamente a cada ~5 minutos via GitHub Actions. Tudo em **papel** — nenhuma ordem real é enviada._\n")
    a("**Última verificação:** %s  " % agora)
    a("**Conexão com a Binance:** %s\n" % status_conexao)
    if not est["fase1_concluida"]:
        a("\n⏳ Ainda estudando o histórico real (Fase 1). Isso deve terminar em poucos pulsos.\n")
    else:
        resultado=est["saldo"]-SALDO_INI
        a("\n**Saldo de papel:** R$%.2f (%+.2f%%)  |  **Operações:** %d  |  **Acerto:** %.1f%%  |  **Líquido médio:** %+.4f%%/op\n"
          % (est["saldo"], resultado/SALDO_INI*100, n, wr, net_medio))
        a("\n## Posições abertas agora\n")
        abertas=[(nome,p) for nome,p in est["posicoes"].items() if p]
        if not abertas:
            a("Nenhuma — o agente está observando o gráfico.\n")
        else:
            for nome,p in abertas:
                a("- **%s**: %s @ %s — faltam %d vela(s) (~%d min)\n"
                  % (nome, ACOES[p["a"]], p["entrada"], p["faltam"], p["faltam"]*5))
        a("\n## Desempenho por tipo de operação\n")
        a("| Ação | Operações | Acerto | Líquido médio |\n|---|---|---|---|\n")
        for ac in range(1,5):
            d=st["por_acao"][str(ac)]
            if d["n"]==0:
                a("| %s | — | — | — |\n" % ACOES[ac]); continue
            a("| %s | %d | %.1f%% | %+.4f%% |\n" % (ACOES[ac], d["n"], d["acertos"]/d["n"]*100, d["net"]/d["n"]))
        a("\n## Últimas operações\n")
        if est["ultimas_ops"]:
            a("| Quando (UTC) | Ativo | Ação | Líquido | P&L |\n|---|---|---|---|---|\n")
            for op in reversed(est["ultimas_ops"][-12:]):
                hora=op["ts"][11:16]
                a("| %s | %s | %s | %+.3f%% | %+.2f |\n" % (hora, op["ativo"], op["acao"], op["net_pct"], op["pnl"]))
        else:
            a("Nenhuma operação fechada ainda.\n")
        a("\n## O que o agente está valorizando agora\n")
        ag=est["agente"]
        pc={f:(ag["w"]["1"][f]+ag["w"]["2"][f])/2 for f in FEATS}
        ordc=sorted(FEATS,key=lambda f:abs(pc[f]),reverse=True)[:4]
        for f in ordc:
            a("- %s: peso de compra %+.2f\n" % (NOMES_PT[f], pc[f]))
        a("\n_eps (exploração) = %.3f · passos de treino = %d_\n" % (ag["eps"], ag["passos"]))
    with open(RELATORIO_PATH,"w",encoding="utf-8") as f: f.write("".join(L))

# ------------------------------------------------------------------ principal
def main():
    random.seed()
    est=carregar_estado()
    agora_iso=datetime.now(timezone.utc).isoformat()
    print("=== Trader Good — pulso em %s ===" % agora_iso)

    teste=baixar_velas("BTCUSDT", INTERVALO, 2)
    if not teste:
        status="❌ bloqueada neste pulso (tentando de novo no próximo)"
        print("Sem conexão com a Binance neste pulso.")
        est["ultima_verificacao"]=agora_iso; est["ultimo_status_conexao"]=status
        escrever_relatorio(est, status)
        # não salva estado se a fase 1 nunca rodou (nada mudou de fato);
        # se já passou da fase 1, também não há mudança de estado real este pulso.
        sys.exit(0)
    status="✅ ok (BTC real = %.1f)" % teste[-1]["c"]
    est["ultima_verificacao"]=agora_iso; est["ultimo_status_conexao"]=status

    if not est["fase1_concluida"]:
        ok=rodar_fase1(est)
        salvar_estado(est)
        escrever_relatorio(est, status)
        sys.exit(0)

    rodar_pulso_ao_vivo(est)
    salvar_estado(est)
    escrever_relatorio(est, status)
    print("Pulso concluído. Saldo atual: R$%.2f" % est["saldo"])

if __name__=="__main__":
    main()
