"""Rule-based product vs service company classifier."""

SERVICE_SIGNALS = [
    "TCS", "Tata Consultancy", "Infosys", "Wipro", "Cognizant", "HCL",
    "Tech Mahindra", "Accenture", "Capgemini", "IBM", "LTIMindtree",
    "Mphasis", "Hexaware", "NIIT Technologies", "Mindtree",
    "outsourcing", "staffing", "consulting services", "IT services",
    "manpower", "body shopping",
]


def classify_company(name: str, description: str = "") -> str:
    """
    Classify a company as 'product', 'service', or 'consulting'.

    Rule-based only — no LLM calls. Defaults to 'product' for unknown companies.

    Args:
        name: Company name
        description: Optional company description / JD text for additional signals

    Returns:
        'service' if any service signal found, else 'product'
    """
    text = f"{name} {description}".lower()
    for signal in SERVICE_SIGNALS:
        if signal.lower() in text:
            return "service"
    return "product"  # default assumption for unknown companies
