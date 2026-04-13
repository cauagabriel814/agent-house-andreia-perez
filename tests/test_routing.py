"""Testes unitarios do roteamento condicional do grafo."""
from src.agent.edges.conditions import route_entry


def _state(**kwargs) -> dict:
    """Helper: estado minimo para testes de roteamento."""
    base = {
        "phone": "+5511999999999",
        "current_node": "",
        "last_question": None,
        "message_type": "text",
    }
    base.update(kwargs)
    return base


# ---------- Casos ja cobertos pelo codigo atual (regressao) ----------


def test_new_conversation_goes_to_greeting():
    assert route_entry(_state()) == "greeting"


def test_after_greeting_goes_to_active_listen():
    assert route_entry(_state(current_node="greeting")) == "active_listen"


def test_flow_in_progress_stays_in_flow():
    state = _state(current_node="sale", last_question="sale_regiao")
    assert route_entry(state) == "sale"


def test_timeout_event():
    assert route_entry(_state(message_type="timeout")) == "timeout"


# ---------- Novos casos da correcao ----------


def test_buyer_encerrado_routes_to_completed():
    """Apos fluxo buyer encerrado, nova mensagem vai para completed."""
    state = _state(current_node="buyer", last_question="buyer_encerrado")
    assert route_entry(state) == "completed"


def test_launch_encerrado_routes_to_completed():
    state = _state(current_node="launch", last_question="launch_encerrado")
    assert route_entry(state) == "completed"


def test_sale_encerrado_routes_to_completed():
    state = _state(current_node="sale", last_question="sale_encerrado")
    assert route_entry(state) == "completed"


def test_already_completed_stays_completed():
    """Lead ja silenciado continua no completed."""
    state = _state(
        current_node="completed", last_question=None, is_silenced=True
    )
    assert route_entry(state) == "completed"


def test_completed_without_silence_still_routes_completed():
    """Primeira mensagem pos-encerramento cai em completed para enviar handoff."""
    state = _state(current_node="completed", is_silenced=False)
    assert route_entry(state) == "completed"


def test_active_flow_mid_conversation_not_routed_to_completed():
    """Regressao: fluxo em andamento com last_question normal NAO vai p/ completed."""
    state = _state(current_node="buyer", last_question="buyer_tipo")
    assert route_entry(state) == "buyer"
