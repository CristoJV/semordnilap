AGREEMENT_RULES = [
    {
        "name": "nominal_agreement",
        # POS categories affected
        "pos": {"D", "N", "A"},
        # Feature compatibility logic
        "features": {
            # Gender agreement
            "gender": lambda a, b: (
                a == b
                or a == "C"  # common gender wildcard
                or b == "C"
            ),
            # Number agreement
            "number": lambda a, b: (
                a == b
                or a == "N"  # invariable wildcard
                or b == "N"
            ),
        },
    }
]
