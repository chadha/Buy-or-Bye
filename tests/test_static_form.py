from pathlib import Path


HTML = (Path(__file__).parents[1] / "app" / "static" / "index.html").read_text()


def test_extracted_values_replace_existing_form_values_and_clear_missing_ones():
    assert '$("#price").value = x.price ?? "";' in HTML
    assert '$("#was").value = x.was_price ?? "";' in HTML


def test_extraction_explains_missing_required_fields_without_guessing():
    assert "Couldn't detect " in HTML
    assert 'The claimed “was” price is optional.' in HTML


def test_read_handler_checks_response_and_handles_errors():
    assert 'if (!r.ok) throw new Error("Extraction failed.' in HTML
    assert 'Please enter the details manually.' in HTML


def test_submission_validates_positive_prices_and_required_product():
    assert 'if (body.product.length < 2) missing.push("#product");' in HTML
    assert 'if (!body.price) missing.push("#price");' in HTML
