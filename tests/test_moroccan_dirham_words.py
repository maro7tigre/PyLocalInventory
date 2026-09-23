from decimal import Decimal
import unittest

from core.moroccan_dirham_words import amount_to_words


class MoroccanDirhamWordsTests(unittest.TestCase):
    def test_zero_and_currency_number(self):
        self.assertEqual(amount_to_words(0), "ZÉRO DIRHAM")
        self.assertEqual(amount_to_words("1.01"), "UN DIRHAM ET UN CENTIME")
        self.assertEqual(amount_to_words("2.02"), "DEUX DIRHAMS ET DEUX CENTIMES")

    def test_standard_french_tens(self):
        self.assertEqual(amount_to_words(70), "SOIXANTE-DIX DIRHAMS")
        self.assertEqual(amount_to_words(71), "SOIXANTE ET ONZE DIRHAMS")
        self.assertEqual(amount_to_words(80), "QUATRE-VINGTS DIRHAMS")
        self.assertEqual(amount_to_words(81), "QUATRE-VINGT-UN DIRHAMS")
        self.assertEqual(amount_to_words(90), "QUATRE-VINGT-DIX DIRHAMS")

    def test_hundreds_thousands_and_millions(self):
        self.assertEqual(amount_to_words(200), "DEUX CENTS DIRHAMS")
        self.assertEqual(amount_to_words(201), "DEUX CENT UN DIRHAMS")
        self.assertEqual(amount_to_words(1_000), "MILLE DIRHAMS")
        self.assertEqual(amount_to_words(2_001), "DEUX MILLE UN DIRHAMS")
        self.assertEqual(amount_to_words(80_000), "QUATRE-VINGT MILLE DIRHAMS")
        self.assertEqual(amount_to_words(2_000_000), "DEUX MILLIONS DIRHAMS")

    def test_rounds_to_centimes_with_half_up(self):
        self.assertEqual(
            amount_to_words(Decimal("12.345")),
            "DOUZE DIRHAMS ET TRENTE-CINQ CENTIMES",
        )
        self.assertEqual(amount_to_words("1.995"), "DEUX DIRHAMS")

    def test_rejects_negative_and_non_finite_values(self):
        with self.assertRaises(ValueError):
            amount_to_words("-0.01")
        with self.assertRaises(ValueError):
            amount_to_words("NaN")


if __name__ == "__main__":
    unittest.main()
