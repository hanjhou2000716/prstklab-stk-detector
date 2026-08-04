from src.paper_portfolio import PaperPortfolio, PaperPosition


def test_paper_portfolio_tracks_observed_outcomes():
    portfolio = PaperPortfolio()
    portfolio.add(PaperPosition("A", "2026-01-01", 100, "break support"))
    portfolio.update({"A": 110})
    result = portfolio.snapshot()[0]
    assert result["latest_price"] == 110
    assert result["max_favorable"] == 0.1
    assert result["research_only"]
