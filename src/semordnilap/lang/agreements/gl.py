AGREEMENT_RULES = [
    {
        "name": "nominal_agreement",
        "pos": {"D", "N", "A"},
        "features": {
            # Galician neuter-aware agreement
            "gender": lambda a, b: (
                a == b
                or a in {"C", "N"}  # common + neuter wildcards
                or b in {"C", "N"}
            ),
            "number": lambda a, b: a == b or a == "N" or b == "N",
        },
    }
]
