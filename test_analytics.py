"""Flask-free tests. Run with:  python -m unittest -v   (or pytest)"""
import unittest

import analytics as a


def recs(*pairs):
    return [{"month": m, "kwh": float(v)} for m, v in pairs]


SAMPLE = recs(("2026-01", 150), ("2026-02", 200), ("2026-03", 180))


class SpecResults(unittest.TestCase):
    def test_sample_data_matches_spec(self):
        s = a.summarise(SAMPLE)
        self.assertEqual(s["total"], 530)
        self.assertEqual(s["average"], 176.67)
        self.assertEqual(s["highest"]["label"], "February 2026")  # 200 > 180
        self.assertEqual(s["lowest"]["label"], "January 2026")
        self.assertEqual(s["forecast"]["value"], 176.67)
        self.assertEqual(s["forecast"]["label"], "April 2026")

    def test_forecast_uses_latest_three(self):
        r = recs(("2026-01", 1000), ("2026-02", 100), ("2026-03", 200), ("2026-04", 300))
        self.assertEqual(a.forecast(r)["value"], 200)

    def test_fewer_than_three_uses_all(self):
        self.assertEqual(a.forecast(recs(("2026-01", 100), ("2026-02", 200)))["value"], 150)
        self.assertEqual(a.forecast(recs(("2026-01", 100)))["value"], 100)

    def test_empty(self):
        self.assertIsNone(a.forecast([]))
        self.assertEqual(a.summarise([]), {"count": 0})

    def test_year_rollover(self):
        self.assertEqual(a.forecast(recs(("2026-12", 10)))["month"], "2027-01")


class Methods(unittest.TestCase):
    def test_trend_perfect_line(self):
        r = recs(("2026-01", 100), ("2026-02", 110), ("2026-03", 120), ("2026-04", 130))
        f = a.forecast(r, "trend")
        self.assertEqual(f["method"], "trend")
        self.assertAlmostEqual(f["value"], 140, places=2)

    def test_trend_falls_back(self):
        f = a.forecast(recs(("2026-01", 100), ("2026-02", 110)), "trend")
        self.assertEqual(f["method"], "avg3")
        self.assertTrue(f["note"])

    def test_trend_never_negative(self):
        r = recs(("2026-01", 30), ("2026-02", 20), ("2026-03", 10))
        self.assertEqual(a.forecast(r, "trend")["value"], 0)

    def test_seasonal(self):
        r = recs(("2025-04", 100), ("2026-01", 150), ("2026-02", 200), ("2026-03", 180))
        f = a.forecast(r, "seasonal")
        self.assertEqual(f["method"], "seasonal")
        self.assertEqual(f["value"], 100.0)

    def test_seasonal_falls_back(self):
        self.assertEqual(a.forecast(SAMPLE, "seasonal")["method"], "avg3")

    def test_avg6(self):
        r = recs(*[(f"2026-{m:02d}", m * 10) for m in range(1, 9)])
        self.assertEqual(a.forecast(r, "avg6")["value"], 55)  # months 3-8: 30..80

    def test_unknown_method_defaults(self):
        self.assertEqual(a.forecast(SAMPLE, "bogus")["method"], "avg3")

    def test_range_brackets_value(self):
        f = a.forecast(SAMPLE)
        self.assertLessEqual(f["low"], f["value"])
        self.assertGreaterEqual(f["high"], f["value"])


class ChangeAndInsights(unittest.TestCase):
    def test_enrich(self):
        r = recs(("2025-02", 100), ("2026-01", 100), ("2026-02", 120))
        e = a.enrich(r)
        self.assertIsNone(e[1]["mom_pct"])      # no Dec 2025
        self.assertEqual(e[2]["mom_pct"], 20.0)
        self.assertEqual(e[2]["yoy_pct"], 20.0)

    def test_budget_status(self):
        st = {"rate": 2.0, "budget": 300.0, "method": "avg3"}
        s = a.summarise(SAMPLE, st)
        self.assertEqual(s["cost"], 353.34)  # 2 x displayed forecast 176.67
        self.assertEqual(s["budget_status"], "over")
        self.assertEqual(a.summarise(SAMPLE, {**st, "budget": 1000})["budget_status"], "ok")

    def test_insights_run(self):
        s = a.summarise(SAMPLE)
        out = a.insights(SAMPLE, s)
        self.assertTrue(out and all({"level", "text"} <= set(i) for i in out))
        self.assertEqual(a.insights([], {})[0]["level"], "info")


class Validation(unittest.TestCase):
    def test_record(self):
        self.assertIsNone(a.parse_record({"month": "2026-01", "kwh": 5})[2])
        for bad in [{"month": "2026-13", "kwh": 5}, {"month": "x", "kwh": 5},
                    {"month": "2026-01", "kwh": -1}, {"month": "2026-01", "kwh": "abc"},
                    {"month": "2026-01", "kwh": "nan"}, {"month": "2026-01", "kwh": "inf"},
                    {"month": "2026-01", "kwh": True}, {"month": "2026-01", "kwh": 10 ** 9},
                    {"month": 5, "kwh": 5}, "nope", None]:
            self.assertIsNotNone(a.parse_record(bad)[2], bad)

    def test_settings(self):
        ok, err = a.validate_settings({"rate": "0.15", "budget": 100, "method": "trend"})
        self.assertIsNone(err)
        self.assertEqual(ok, {"rate": 0.15, "budget": 100.0, "method": "trend"})
        for bad in [{"rate": -1}, {"rate": "x"}, {"method": "magic"}, {"budget": float("nan")}, []]:
            self.assertIsNotNone(a.validate_settings(bad)[1], bad)

    def test_csv(self):
        text = "month,kwh\n2026-01,150\nFeb 2026, 200\n2026/3;180\nbad,1\n2026-04,-5\n\n"
        recs_, errs = a.parse_csv(text)
        self.assertEqual(recs_, {"2026-01": 150.0, "2026-02": 200.0, "2026-03": 180.0})
        self.assertEqual(len(errs), 2)

    def test_normalise_month(self):
        self.assertEqual(a.normalise_month("January 2026"), "2026-01")
        self.assertEqual(a.normalise_month("2026-1"), "2026-01")
        self.assertIsNone(a.normalise_month("2026-00"))
        self.assertIsNone(a.normalise_month("Foo 2026"))


if __name__ == "__main__":
    unittest.main()
