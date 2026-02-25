from semordnilap.lang.tagset.base import FeatureSpec, POSSpec

POS_FEATURE_SLOTS = {
    # =========================================================
    # DETERMINERS (D)
    # Tag structure: D + type + person + gender + number + possessor_num
    # =========================================================
    "D": POSSpec(
        features={
            "type": FeatureSpec(
                1,
                (
                    # A: article
                    # D: demonstrative
                    # E: exclamative
                    # I: indefinite
                    # T: interrogative
                    # N: numeral
                    # P: possessive
                    "A",
                    "D",
                    "E",
                    "I",
                    "T",
                    "N",
                    "P",
                ),
            ),
            "person": FeatureSpec(
                2,
                (
                    # 1: first person
                    # 2: second person
                    # 3: third person
                    "1",
                    "2",
                    "3",
                ),
            ),
            "gender": FeatureSpec(
                3,
                (
                    # F: feminine
                    # M: masculine
                    # C: common
                    # N: neuter
                    "F",
                    "M",
                    "C",
                    "N",
                ),
            ),
            "number": FeatureSpec(
                4,
                (
                    # S: singular
                    # P: plural
                    # N: invariable
                    "S",
                    "P",
                    "N",
                ),
            ),
            "possessor_num": FeatureSpec(
                5,
                (
                    # S: singular possessor
                    # P: plural possessor
                    "S",
                    "P",
                ),
            ),
        }
    ),
    # =========================================================
    # NOUNS (N)
    # Tag structure: N + type + gender + number + neclass + nesubclass + degree
    # =========================================================
    "N": POSSpec(
        features={
            "type": FeatureSpec(
                1,
                (
                    # C: common noun
                    # P: proper noun
                    "C",
                    "P",
                ),
            ),
            "gender": FeatureSpec(
                2,
                (
                    # F: feminine
                    # M: masculine
                    # C: common
                    "F",
                    "M",
                    "C",
                ),
            ),
            "number": FeatureSpec(
                3,
                (
                    # S: singular
                    # P: plural
                    # N: invariable
                    "S",
                    "P",
                    "N",
                ),
            ),
            "neclass": FeatureSpec(
                4,
                (
                    # S: person
                    # G: location
                    # O: organization
                    # V: other
                    "S",
                    "G",
                    "O",
                    "V",
                ),
            ),
            "nesubclass": FeatureSpec(5, ()),
            "degree": FeatureSpec(
                6,
                (
                    # V: evaluative
                    "V",
                ),
            ),
        }
    ),
    # =========================================================
    # ADJECTIVES (A)
    # Tag structure: A + type + degree + gender + number
    # =========================================================
    "A": POSSpec(
        features={
            "type": FeatureSpec(
                1,
                (
                    # O: ordinal
                    # Q: qualificative
                    "O",
                    "Q",
                ),
            ),
            "degree": FeatureSpec(
                2,
                (
                    # S: superlative
                    "S",
                ),
            ),
            "gender": FeatureSpec(
                3,
                (
                    # F: feminine
                    # M: masculine
                    # C: common
                    # N: neuter
                    "F",
                    "M",
                    "C",
                    "N",
                ),
            ),
            "number": FeatureSpec(
                4,
                (
                    # S: singular
                    # P: plural
                    # N: invariable
                    "S",
                    "P",
                    "N",
                ),
            ),
        }
    ),
    # =========================================================
    # PRONOUNS (P)
    # Tag structure: P + type + person + gender + number + case + possessor_num + polite
    # =========================================================
    "P": POSSpec(
        features={
            "type": FeatureSpec(
                1,
                (
                    # D: demonstrative
                    # E: exclamative
                    # I: indefinite
                    # T: interrogative
                    # N: numeral
                    # P: personal
                    # X: possessive
                    # R: relative
                    "D",
                    "E",
                    "I",
                    "T",
                    "N",
                    "P",
                    "X",
                    "R",
                ),
            ),
            "person": FeatureSpec(2, ("1", "2", "3")),
            "gender": FeatureSpec(3, ("F", "M", "C", "N")),
            "number": FeatureSpec(4, ("S", "P", "N")),
            "case": FeatureSpec(
                5,
                (
                    # N: nominative
                    # A: accusative
                    # D: dative
                    # O: oblique
                    "N",
                    "A",
                    "D",
                    "O",
                ),
            ),
            "possessor_num": FeatureSpec(
                6,
                (
                    # S: singular possessor
                    # P: plural possessor
                    "S",
                    "P",
                ),
            ),
            "polite": FeatureSpec(
                7,
                (
                    # P: polite form
                    "P",
                ),
            ),
        }
    ),
    # =========================================================
    # VERBS (V)
    # Tag structure: V + type + mood + tense + person + number + gender
    # =========================================================
    "V": POSSpec(
        features={
            "type": FeatureSpec(
                1,
                (
                    # M: main verb
                    # A: auxiliary
                    # S: semiauxiliary
                    "M",
                    "A",
                    "S",
                ),
            ),
            "mood": FeatureSpec(
                2,
                (
                    # I: indicative
                    # S: subjunctive
                    # M: imperative
                    # P: past participle
                    # G: gerund
                    # N: infinitive
                    "I",
                    "S",
                    "M",
                    "P",
                    "G",
                    "N",
                ),
            ),
            "tense": FeatureSpec(
                3,
                (
                    # P: present
                    # I: imperfect
                    # F: future
                    # S: past
                    # M: plusquamperfect
                    # C: conditional
                    "P",
                    "I",
                    "F",
                    "S",
                    "M",
                    "C",
                ),
            ),
            "person": FeatureSpec(4, ("1", "2", "3")),
            "number": FeatureSpec(5, ("S", "P")),
            "gender": FeatureSpec(6, ("F", "M", "C", "N")),
        }
    ),
    # =========================================================
    # ADVERBS (R)
    # =========================================================
    "R": POSSpec(
        features={
            "type": FeatureSpec(
                1,
                (
                    # N: negative
                    # G: general
                    "N",
                    "G",
                ),
            )
        }
    ),
    # =========================================================
    # CONJUNCTIONS (C)
    # =========================================================
    "C": POSSpec(
        features={
            "type": FeatureSpec(
                1,
                (
                    # C: coordinating
                    # S: subordinating
                    "C",
                    "S",
                ),
            )
        }
    ),
    # =========================================================
    # ADPOSITIONS (S)
    # =========================================================
    "S": POSSpec(
        features={
            "type": FeatureSpec(
                1,
                (
                    # P: preposition
                    "P",
                ),
            ),
            "contracted": FeatureSpec(
                2,
                (
                    # C: contracted form
                    "C",
                ),
            ),
            "gender": FeatureSpec(
                3,
                (
                    # M: masculine (fixed in tagset)
                    "M",
                ),
            ),
            "number": FeatureSpec(
                4,
                (
                    # S: singular (fixed in tagset)
                    "S",
                ),
            ),
        }
    ),
    # =========================================================
    # NUMBERS (Z)
    # =========================================================
    "Z": POSSpec(
        features={
            "type": FeatureSpec(
                1,
                (
                    # d: partitive
                    # m: currency
                    # p: ratio
                    # u: unit
                    "d",
                    "m",
                    "p",
                    "u",
                ),
            )
        }
    ),
    "W": POSSpec(features={}),  # Date
    "I": POSSpec(features={}),  # Interjection
}
