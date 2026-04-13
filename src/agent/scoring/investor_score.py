"""
investor_score.py - Sistema de pontuacao para leads investidores.

Escala: 0 a 100 pontos.
  - INVESTIMENTO : 0-30 pts
  - PAGAMENTO    : 0-20 pts
  - URGENCIA     : 0-25 pts
  - SITUACAO     : 0-10 pts
  - DADOS        : 0-15 pts

Classificacao:
  - 85-100 pts -> quente
  - 60-84  pts -> morno
  - 0-59   pts -> frio

As categorias devem ser classificadas pelo LLM dentro do investor_node
antes de chamar esta funcao. Valores esperados por campo:

  investimento_categoria : "acima_2m" | "1m_2m" | "500k_1m" | "400k_500k"
                           | "abaixo_400k" | "nao_informado"
  pagamento_categoria    : "a_vista" | "permuta" | "financiamento_aprovado"
                           | "vai_financiar" | "nao_informado"
  urgencia_categoria     : "30_dias" | "1_3_meses" | "3_6_meses"
                           | "sem_urgencia" | "nao_informado"
  situacao_categoria     : "pronto" | "lancamento" | "tanto_faz"
                           | "nao_informado"
  dados_preenchidos      : int (qtd de campos chave preenchidos)
"""

_INVESTIMENTO_TABLE: dict[str, int] = {
    "acima_2m": 30,
    "1m_2m": 25,
    "500k_1m": 20,
    "400k_500k": 10,
    "abaixo_400k": 0,
    "nao_informado": 0,
}

_PAGAMENTO_TABLE: dict[str, int] = {
    "a_vista": 20,
    "permuta": 15,
    "financiamento_aprovado": 10,
    "vai_financiar": 5,
    "nao_informado": 0,
}

_URGENCIA_TABLE: dict[str, int] = {
    "30_dias": 25,
    "1_3_meses": 20,
    "3_6_meses": 10,
    "sem_urgencia": 5,
    "nao_informado": 0,
}

_SITUACAO_TABLE: dict[str, int] = {
    "pronto": 10,
    "lancamento": 8,
    "tanto_faz": 5,
    "nao_informado": 0,
}


def calculate_investor_score(data: dict) -> dict:
    """
    Calcula score do investidor (0-100 pts) a partir de categorias pre-classificadas.

    Parametros:
        data (dict): dicionario com as chaves descritas no modulo.

    Retorna:
        dict com pontuacoes parciais, total e classificacao.
    """
    investimento_pts = _INVESTIMENTO_TABLE.get(
        data.get("investimento_categoria", "nao_informado"), 0
    )
    pagamento_pts = _PAGAMENTO_TABLE.get(
        data.get("pagamento_categoria", "nao_informado"), 0
    )
    urgencia_pts = _URGENCIA_TABLE.get(
        data.get("urgencia_categoria", "nao_informado"), 0
    )
    situacao_pts = _SITUACAO_TABLE.get(
        data.get("situacao_categoria", "nao_informado"), 0
    )
    dados_pts = _score_dados(int(data.get("dados_preenchidos", 0)))

    total_score = (
        investimento_pts + pagamento_pts + urgencia_pts + situacao_pts + dados_pts
    )
    classification = _classify(total_score)

    return {
        "investimento_pts": investimento_pts,
        "pagamento_pts": pagamento_pts,
        "urgencia_pts": urgencia_pts,
        "situacao_pts": situacao_pts,
        "dados_pts": dados_pts,
        "total_score": total_score,
        "classification": classification,
    }


def _score_dados(preenchidos: int) -> int:
    if preenchidos >= 7:
        return 15
    if preenchidos >= 4:
        return 10
    if preenchidos >= 1:
        return 5
    return 0


def _classify(total: int) -> str:
    if total >= 85:
        return "quente"
    if total >= 60:
        return "morno"
    return "frio"
