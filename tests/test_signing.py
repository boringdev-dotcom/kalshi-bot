from kalshi_bot.kalshi.rest import sign_target


def test_portfolio_gets_sign_path_only():
    query = "?limit=200&cursor=abc"
    assert (
        sign_target("GET", "/trade-api/v2/portfolio/fills", query)
        == "/trade-api/v2/portfolio/fills"
    )
    assert (
        sign_target("GET", "/trade-api/v2/portfolio/orders", query)
        == "/trade-api/v2/portfolio/orders"
    )
    assert (
        sign_target("GET", "/trade-api/v2/portfolio/settlements", query)
        == "/trade-api/v2/portfolio/settlements"
    )
    assert (
        sign_target("GET", "/trade-api/v2/historical/fills", query)
        == "/trade-api/v2/historical/fills"
    )


def test_public_markets_still_sign_query():
    query = "?status=open&limit=200"
    assert (
        sign_target("GET", "/trade-api/v2/markets", query)
        == "/trade-api/v2/markets?status=open&limit=200"
    )


def test_writes_sign_path_without_body():
    assert sign_target("POST", "/trade-api/v2/portfolio/orders", "") == "/trade-api/v2/portfolio/orders"
