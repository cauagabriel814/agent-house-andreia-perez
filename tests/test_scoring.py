from src.agent.scoring.investor_score import calculate_investor_score
from src.agent.scoring.launch_score import calculate_launch_score


def test_investor_score_returns_structure():
    result = calculate_investor_score({})
    assert "total_score" in result
    assert "classification" in result


def test_launch_score_returns_structure():
    result = calculate_launch_score({})
    assert "total_score" in result
    assert "classification" in result
