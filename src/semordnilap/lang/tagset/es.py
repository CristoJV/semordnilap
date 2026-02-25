from semordnilap.lang.tagset.base import FeatureSpec, POSSpec

POS_FEATURE_SLOTS = {
    # =========================================================
    # ADJECTIVES (A)
    # Tag structure: A + type + degree + gender + number + possessor_pers + possessor_num
    # =========================================================
    "A": POSSpec(
        features={
            "type": FeatureSpec(
                1,
                (
                    # O: ordinal (primer, segundo...)
                    # Q: qualificative (grande, rojo...)
                    # P: possessive (mi, tu, su...)
                    "O",
                    "Q",
                    "P",
                ),
            ),
            "degree": FeatureSpec(
                2,
                (
                    # S: superlative (grandísimo)
                    # V: evaluative (diminutives / augmentatives)
                    "S",
                    "V",
                ),
            ),
            "gender": FeatureSpec(
                3,
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
            "possessor_pers": FeatureSpec(
                5,
                (
                    # 1: first person possessor
                    # 2: second person possessor
                    # 3: third person possessor
                    "1",
                    "2",
                    "3",
                ),
            ),
            "possessor_num": FeatureSpec(
                6,
                (
                    # S: singular possessor
                    # P: plural possessor
                    # N: invariable
                    "S",
                    "P",
                    "N",
                ),
            ),
        }
    ),
    # =========================================================
    # DETERMINERS (D)
    # Tag structure: D + type + person + gender + number + possessor_num
    # =========================================================
    "D": POSSpec(
        features={
            "type": FeatureSpec(
                1,
                (
                    # A: article (el, la...)
                    # D: demonstrative (este, ese...)
                    # I: indefinite (uno, algún...)
                    # P: possessive (mi, tu...)
                    # T: interrogative (qué, cuál...)
                    # E: exclamative (qué, cuánto...)
                    "A",
                    "D",
                    "I",
                    "P",
                    "T",
                    "E",
                ),
            ),
            "person": FeatureSpec(2, ("1", "2", "3")),
            "gender": FeatureSpec(3, ("F", "M", "C")),
            "number": FeatureSpec(4, ("S", "P", "N")),
            "possessor_num": FeatureSpec(
                5,
                (
                    # S: singular possessor
                    # P: plural possessor
                    # N: invariable
                    "S",
                    "P",
                    "N",
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
            "gender": FeatureSpec(2, ("F", "M", "C")),
            "number": FeatureSpec(3, ("S", "P", "N")),
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
    # PRONOUNS (P)
    # Tag structure: P + type + person + gender + number + case + polite
    # =========================================================
    "P": POSSpec(
        features={
            "type": FeatureSpec(
                1,
                (
                    # D: demonstrative
                    # E: exclamative
                    # I: indefinite
                    # P: personal
                    # R: relative
                    # T: interrogative
                    "D",
                    "E",
                    "I",
                    "P",
                    "R",
                    "T",
                ),
            ),
            "person": FeatureSpec(2, ("1", "2", "3")),
            "gender": FeatureSpec(3, ("F", "M", "C")),
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
            "polite": FeatureSpec(
                6,
                (
                    # P: polite form (usted)
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
                    # P: participle
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
                    # C: conditional
                    "P",
                    "I",
                    "F",
                    "S",
                    "C",
                ),
            ),
            "person": FeatureSpec(4, ("1", "2", "3")),
            "number": FeatureSpec(5, ("S", "P")),
            "gender": FeatureSpec(6, ("F", "M", "C")),
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
                    # N: negative (no, nunca...)
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
            )
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
                    # p: percentage
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
