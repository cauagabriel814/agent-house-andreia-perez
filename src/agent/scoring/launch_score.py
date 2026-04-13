"""
launch_score.py - Sistema de pontuacao para leads de lancamento imobiliario.

Escala: 0 a 100 pontos.
  - PAGAMENTO  : 0-30 pts
  - URGENCIA   : 0-30 pts
  - CONTATO    : 0-20 pts
  - PLANTA     : 0-10 pts
  - DADOS      : 0-10 pts

Classificacao:
  - 85-100 pts -> quente  (agendar apresentacao, SLA 1h)
  - 60-84  pts -> morno   (enviar material, follow-up 24h)
  - 0-59   pts -> frio    (nao utilizado neste fluxo; cai no morno por padrao)

As categorias devem ser classificadas pelo LLM dentro do launch_node
antes de chamar esta funcao. Valores esperados por campo:

  pagamento_categoria : "a_vista" | "fgts" | "parcelas_direto"
                        | "financiamento" | "nao_informado"
  urgencia_categoria  : "30_dias" | "1_3_meses" | "3_6_meses"
                        | "sem_urgencia" | "nao_informado"
  contato_nivel       : "completo" | "whatsapp" | "email" | "basico"
  planta_informada    : bool (True se informou tipo de unidade)
  conhece_regiao      : bool (True se conhece a regiao do empreendimento)
  empreendimento_id   : bool (True se veio de anuncio especifico do empreendimento)
"""

_PAGAMENTO_TABLE: dict[str, int] = {
    "a_vista": 30,
    "fgts": 25,
    "parcelas_direto": 20,
    "financiamento": 15,
    "nao_informado": 5,
}

_URGENCIA_TABLE: dict[str, int] = {
    "30_dias": 30,
    "1_3_meses": 25,
    "3_6_meses": 15,
    "sem_urgencia": 5,
    "nao_informado": 0,
}

_CONTATO_TABLE: dict[str, int] = {
    "completo": 20,   # nome + email
    "whatsapp": 15,   # nome (apenas WhatsApp ja conhecido)
    "email": 12,      # apenas email
    "basico": 5,      # sem contato adicional
}


def calculate_launch_score(data: dict) -> dict:
    """
    Calcula score de lancamento (0-100 pts) a partir de dados pre-extraidos.

    Parametros:
        data (dict): dicionario com as chaves descritas no modulo.

    Retorna:
        dict com pontuacoes parciais, total e classificacao.
    """
    pagamento_pts = _PAGAMENTO_TABLE.get(
        data.get("pagamento_categoria", "nao_informado"), 5
    )
    urgencia_pts = _URGENCIA_TABLE.get(
        data.get("urgencia_categoria", "nao_informado"), 0
    )
    contato_pts = _CONTATO_TABLE.get(data.get("contato_nivel", "basico"), 5)

    # PLANTA INTERESSE (0-10 pts)
    planta_pts = 10 if data.get("planta_informada") else 0

    # DADOS (0-10 pts): conhecimento da regiao + identificacao no empreendimento
    dados_pts = 0
    if data.get("conhece_regiao"):
        dados_pts += 5
    if data.get("empreendimento_id"):
        dados_pts += 5

    total_score = pagamento_pts + urgencia_pts + contato_pts + planta_pts + dados_pts
    classification = _classify(total_score)

    return {
        "pagamento_pts": pagamento_pts,
        "urgencia_pts": urgencia_pts,
        "contato_pts": contato_pts,
        "planta_pts": planta_pts,
        "dados_pts": dados_pts,
        "total_score": total_score,
        "classification": classification,
    }


def _classify(total: int) -> str:
    if total >= 85:
        return "quente"
    if total >= 60:
        return "morno"
    return "frio"
