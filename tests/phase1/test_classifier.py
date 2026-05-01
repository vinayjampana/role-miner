"""Tests for rule-based company classifier."""
import pytest
from roleminer.pipeline.classifier import classify_company


def test_tcs_is_service():
    assert classify_company("TCS") == "service"


def test_infosys_is_service():
    assert classify_company("Infosys") == "service"


def test_accenture_is_service():
    assert classify_company("Accenture") == "service"


def test_wipro_is_service():
    assert classify_company("Wipro") == "service"


def test_cognizant_is_service():
    assert classify_company("Cognizant") == "service"


def test_hcl_is_service():
    assert classify_company("HCL Technologies") == "service"


def test_tech_mahindra_is_service():
    assert classify_company("Tech Mahindra") == "service"


def test_sarvam_ai_is_product():
    assert classify_company("Sarvam AI") == "product"


def test_razorpay_is_product():
    assert classify_company("Razorpay") == "product"


def test_unknown_company_defaults_to_product():
    """Unknown companies default to 'product' (assumption)."""
    assert classify_company("Some Random Startup XYZ") == "product"


def test_service_signal_in_description():
    """Service signal in description text (not just name) is caught."""
    assert classify_company("PeoplePower", "IT services and outsourcing company") == "service"


def test_staffing_in_description():
    assert classify_company("TalentCo", "staffing and manpower solutions") == "service"


def test_product_company_with_it_in_name():
    """Company name containing 'IT' but not a service signal → product."""
    assert classify_company("Reckit Technologies") == "product"
