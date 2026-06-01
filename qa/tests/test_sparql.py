from qa_service.sparql import question_to_sparql


def test_question_to_sparql_customers_targets_asserted_and_inferred() -> None:
    result = question_to_sparql("Who are the customers?")
    assert "urn:graph:asserted" in result.sparql
    assert "urn:graph:inferred" in result.sparql
    assert "ex:Customer" in result.sparql


def test_question_to_sparql_top_products_intent() -> None:
    result = question_to_sparql("What are the top products?")
    assert "SUM(?qty)" in result.sparql
    assert "ex:OrderLine" in result.sparql


def test_question_to_sparql_product_mix_intent() -> None:
    result = question_to_sparql("Show the product mix")
    assert "Product mix query generated" in result.answer
    assert "GROUP BY ?productName" in result.sparql


def test_question_to_sparql_repeat_customers_intent() -> None:
    result = question_to_sparql("Who are repeat customers?")
    assert "Repeat customers query generated" in result.answer
    assert "HAVING (COUNT(?order) > 1)" in result.sparql


def test_question_to_sparql_daily_revenue_intent() -> None:
    result = question_to_sparql("What is store daily revenue?")
    assert "Store daily revenue query generated" in result.answer
    assert "SUM(?total)" in result.sparql
    assert "ex:orderDate" in result.sparql


def test_question_to_sparql_unknown_intent() -> None:
    result = question_to_sparql("What is the weather?")
    assert result.sparql == ""
    assert result.answer.startswith("I do not understand")
