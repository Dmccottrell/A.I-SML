"""Tests for live_more.py (the second batch of live facts). No test touches the real internet."""
import os
import time
import unittest

import live_data as L
import live_more as M
from tests.test_live_data import FakeNet, ask, first, NOW


def geo(name="Denver", country="United States", admin="Colorado", lat=39.74, lon=-104.99, tz="America/Denver", cc="US", elevation=1600):
    return {"geocoding": {"results": [{"name": name, "country": country, "admin1": admin, "latitude": lat, "longitude": lon, "timezone": tz, "country_code": cc, "elevation": elevation}]}}


class FinanceAndOffline(unittest.TestCase):
    def test_loan_payments_match_the_standard_formula(self):
        self.assertIn("$1,896.20 a month", first("monthly payment on a $300,000 mortgage at 6.5% for 30 years", online=False))
        self.assertIn("$460.41 a month", first("monthly payment on a 25000 car loan at 4% for 5 years", online=False))

    def test_compound_interest(self):
        self.assertIn("grows to $1,628.89", first("if I invest $1000 at 5% for 10 years", online=False))
        self.assertIn("grows to $20,193.69", first("invest 5k at 7% for 20 years compounded monthly", online=False))
        self.assertIn("grows to $17,175.24", first("invest $1000 at 5% for 10 years and add $100 a month", online=False))

    def test_bmi_and_percentages(self):
        self.assertIn("BMI = 22.9 (healthy range", first("bmi 70 kg 175 cm", online=False))
        self.assertIn("BMI = 25.8", first("bmi for 180 lbs and 70 inches", online=False))
        self.assertIn("rise of 50.00%", first("percent change from 50 to 75", online=False))
        self.assertIn("drop of 20.00%", first("percentage decrease from 50 to 40", online=False))
        self.assertIn("30 is 25.00% of 120", first("what percent is 30 of 120", online=False))

    def test_time_zone_conversion(self):
        self.assertIn("12:00 PM", first("3pm EST in PST", online=False))
        self.assertIn("5:00 PM in Tokyo", first("what is 9 am London time in Tokyo", online=False))
        self.assertIn("the next day", first("11pm PST in Tokyo", online=False))
        self.assertIsNone(first("my train leaves at 3pm", online=False))

    def test_moon(self):
        text = first("what's the moon phase", online=False)
        self.assertIn("waning crescent", text)
        self.assertIn("full moon is around", text)
        # a known full moon: 2026-10-26 (about)
        self.assertIn("October 26, 2026", text)

    def test_dice_coins_random(self):
        self.assertRegex(first("roll 2d6", online=False), r"Rolled 2d6: \d, \d \(total \d+\)")
        self.assertRegex(first("roll a die", online=False), r"Rolled 1d6: [1-6]\.")
        self.assertRegex(first("flip a coin", online=False), r"landed on (heads|tails)")
        self.assertRegex(first("pick a number between 5 and 10", online=False), r"is (5|6|7|8|9|10)\.")
        self.assertIsNone(first("roll 500d6", online=False))

    def test_bases_and_roman_numerals(self):
        self.assertIn("is FF", first("what is 255 in hex", online=False))
        self.assertIn("11111111", first("255 in binary", online=False))
        self.assertIn("MMXXVI", first("2026 in roman numerals", online=False))
        self.assertIn("XIV is 14", first("what is XIV in numbers", online=False))
        self.assertIn("is 10 in decimal", first("binary 1010 to decimal", online=False).replace("Binary 1010 is 10 in decimal", "is 10 in decimal"))

    def test_nothing_triggers_on_ordinary_questions(self):
        for q in ("I need a loan for my car", "what is a mortgage", "tell me about the moon landing", "what's a good name for a dog", "how do I roll a pie crust"):
            self.assertIsNone(first(q, online=False), q)


class People(unittest.TestCase):
    def net(self, died=False):
        claims = {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}],
                  "P569": [{"mainsnak": {"datavalue": {"value": {"time": "+1956-07-09T00:00:00Z", "precision": 11}}}}],
                  "P2048": [{"mainsnak": {"datavalue": {"value": {"amount": "+1.83", "unit": "http://www.wikidata.org/entity/Q11573"}}}}]}
        if died:
            claims["P570"] = [{"mainsnak": {"datavalue": {"value": {"time": "+2020-01-01T00:00:00Z", "precision": 11}}}}]
        ent = {"entities": {"Q2263": {"claims": claims, "labels": {"en": {"value": "Tom Hanks"}}, "descriptions": {"en": {"value": "American actor"}}}}}
        return FakeNet({"wbsearchentities": {"search": [{"id": "Q2263", "label": "Tom Hanks"}]}, "EntityData/Q2263": ent})

    def test_age_is_calculated_exactly(self):
        text = first("how old is Tom Hanks", net=self.net())
        self.assertIn("is 70 years old today", text)                       # 1956-07-09 -> 2026-10-07
        self.assertIn("born Monday, July 9, 1956", text)
        self.assertIn("height 1.83 m", first("how tall is Tom Hanks", net=self.net()))

    def test_died(self):
        self.assertIn("died Wednesday, January 1, 2020 at age 63", first("when did Tom Hanks die", net=self.net(died=True)))

    def test_not_a_person_or_not_a_question_about_one(self):
        net = FakeNet({"wbsearchentities": {"search": [{"id": "Q1", "label": "x"}]}, "EntityData/Q1": {"entities": {"Q1": {"claims": {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q515"}}}}]}}}}})
        self.assertIsNone(first("how old is Paris", net=net))
        self.assertIsNone(first("how old is my dog", net=net))
        self.assertIsNone(first("how old is it", net=net))
        self.assertIsNone(first("how old is Tom Hanks", net=self.net(), online=False))


class Packages(unittest.TestCase):
    def test_pypi_npm_github(self):
        net = FakeNet({"pypi.org": {"info": {"name": "requests", "version": "2.40.1", "requires_python": ">=3.9"}, "urls": [{"upload_time": "2026-09-01T10:00:00"}]}})
        text = first("what is the latest version of requests", net=net)
        self.assertIn("requests latest version on PyPI: 2.40.1, uploaded 2026-09-01", text)
        net = FakeNet({"registry.npmjs.org": {"name": "react", "version": "19.2.0"}})
        self.assertIn("react latest version on npm: 19.2.0", first("what's the latest version of react", net=net))
        net = FakeNet({"api.github.com": {"tag_name": "v1.2.3", "name": "One", "published_at": "2026-08-01T00:00:00Z", "html_url": "https://github.com/a/b"}})
        self.assertIn("v1.2.3", first("latest version of vercel/next.js", net=net))

    def test_not_a_package_question(self):
        net = FakeNet({"pypi.org": {"info": {"name": "python", "version": "3"}}})
        for q in ("what is the latest version of python", "what is the latest version of windows"):
            self.assertIsNone(first(q, net=net), q)


class Entertainment(unittest.TestCase):
    def test_tv(self):
        net = FakeNet({"tvmaze": {"name": "Severance", "status": "Running", "premiered": "2022-02-18", "url": "https://www.tvmaze.com/shows/1",
                                  "_embedded": {"nextepisode": {"season": 3, "number": 1, "name": "Return", "airdate": "2026-11-02", "airtime": "21:00"},
                                                "previousepisode": {"season": 2, "number": 10, "airdate": "2025-03-21"}}}})
        text = first("when is the next episode of Severance", net=net)
        self.assertIn("next episode: S3E1 \"Return\" airs 2026-11-02 at 21:00", text)
        self.assertIn("last episode: S2E10 aired 2025-03-21", text)
        ended = FakeNet({"tvmaze": {"name": "Lost", "status": "Ended", "premiered": "2004-09-22", "_embedded": {}}})
        self.assertIn("has ended", first("when is the next episode of Lost", net=ended))

    def test_steam(self):
        net = FakeNet({"storesearch": {"items": [{"id": 570, "name": "Dota 2"}]},
                       "appdetails": {"570": {"data": {"name": "Dota 2", "is_free": True, "release_date": {"coming_soon": False, "date": "9 Jul, 2013"}}}}})
        text = first("is dota 2 free on steam", net=net)
        self.assertIn("free to play", text)
        self.assertIn("released 9 Jul, 2013", text)
        self.assertIsNone(first("is dota 2 free", net=net))                 # only when Steam is mentioned

    def test_music(self):
        net = FakeNet({"itunes.apple.com": {"results": [{"artistName": "Adele", "collectionName": "30", "trackName": "Easy On Me", "releaseDate": "2021-11-19T08:00:00Z"}]}})
        self.assertIn("30 by Adele (2021-11-19)", first("albums by Adele", net=net))
        self.assertIn("Easy On Me by Adele", first("who sings easy on me", net=net))


class Everyday(unittest.TestCase):
    def test_nutrition_open_food_facts(self):
        net = FakeNet({"openfoodfacts": {"products": [{"product_name": "Banana", "brands": "Fresh", "nutriments": {"energy-kcal_100g": 89, "proteins_100g": 1.1, "fat_100g": 0.3,
                                                                                                             "carbohydrates_100g": 23, "sugars_100g": 12}}]}})
        text = first("how many calories are in a banana", net=net)
        self.assertIn("89 kcal", text)
        self.assertIn("protein 1.1 g", text)

    def test_nutrition_usda_with_a_key(self):
        net = FakeNet({"nal.usda.gov": {"foods": [{"description": "Bananas, raw", "foodNutrients": [{"nutrientName": "Energy", "value": 89, "unitName": "KCAL"},
                                                                                                   {"nutrientName": "Protein", "value": 1.09, "unitName": "G"}]}]}})
        os.environ["USDA_API_KEY"] = "k"
        try:
            self.assertIn("energy 89 kcal", first("calories in a banana", net=net))
        finally:
            os.environ.pop("USDA_API_KEY", None)

    def test_sun_and_distance(self):
        net = FakeNet({**geo(), "api.open-meteo.com/v1/forecast": {"daily": {"time": ["2026-10-07", "2026-10-08"], "sunrise": ["2026-10-07T07:05", "2026-10-08T07:06"],
                                                                              "sunset": ["2026-10-07T18:30", "2026-10-08T18:28"], "daylight_duration": [41100, 41000]}}})
        text = first("when does the sun set in Denver", net=net)
        self.assertIn("sunset 18:30", text)
        self.assertIn("11 h 25 min of daylight", text)
        self.assertIsNone(first("when does the sun set in Denver", net=net, online=False))

    def test_distance(self):
        net = FakeNet({"geocoding": {"results": [{"name": "Paris", "latitude": 48.8566, "longitude": 2.3522, "country": "France"}]}})
        # both lookups return Paris, so use two nets by name
        class TwoCities(FakeNet):
            def _get(self, url):
                self.urls.append(url)
                if "name=Paris" in url:
                    return {"results": [{"name": "Paris", "latitude": 48.8566, "longitude": 2.3522, "country": "France"}]}
                if "name=London" in url:
                    return {"results": [{"name": "London", "latitude": 51.5074, "longitude": -0.1278, "country": "United Kingdom"}]}
                if "osrm" in url:
                    return {"routes": [{"distance": 460000, "duration": 18000}]}
                raise OSError(url)
        text = first("how far is Paris from London", net=TwoCities())
        self.assertRegex(text, r"34\d km \(21\d miles\) in a straight line")
        self.assertIn("by road about 460 km", first("how long does it take to drive from Paris to London", net=TwoCities()))
        self.assertIsNone(first("how far is the sun from earth", net=TwoCities()))

    def test_past_weather(self):
        net = FakeNet({**geo("Austin", "United States", "Texas"), "archive-api": {"daily": {"temperature_2m_max": [31.2], "temperature_2m_min": [20.1], "precipitation_sum": [0.0], "weather_code": [1]}}})
        text = first("what was the weather in Austin on October 1, 2026", net=net)
        self.assertIn("Thursday, October 1, 2026", text)
        self.assertIn("high 31°C", text)
        self.assertIsNone(first("what was the weather in Austin on December 1, 2026", net=net))     # in the future

    def test_elevation_and_surf_and_alerts(self):
        self.assertIn("1,600 m", first("what is the elevation of Denver", net=FakeNet(geo())))
        net = FakeNet({**geo("Malibu", admin="California", cc="US"), "marine-api": {"current": {"wave_height": 1.2, "wave_period": 9, "wave_direction": 270}}})
        self.assertIn("Wave height 1.2 m", first("how are the waves in Malibu", net=net))
        net = FakeNet({**geo("Miami", admin="Florida"), "api.weather.gov": {"features": [{"properties": {"event": "Flood Watch", "severity": "Moderate", "headline": "Flood Watch until 6 PM"}}]}})
        self.assertIn("Flood Watch (Moderate)", first("any weather alerts in Miami", net=net))
        net = FakeNet({**geo("Miami", admin="Florida"), "api.weather.gov": {"features": []}})
        self.assertIn("No active weather alerts", first("any weather alerts in Miami", net=net))
        net = FakeNet({**geo("Paris", cc="FR", country="France", admin="Ile-de-France"), "api.weather.gov": {"features": []}})
        self.assertIsNone(first("any weather alerts in Paris", net=net))                 # US only


class Research(unittest.TestCase):
    def test_world_bank(self):
        net = FakeNet({"worldbank": [{"page": 1}, [{"country": {"value": "Japan"}, "date": "2024", "value": 4.1e12}]]})
        self.assertIn("$4.10 trillion", first("what is the gdp of Japan", net=net))
        net = FakeNet({"worldbank": [{"page": 1}, [{"country": {"value": "Japan"}, "date": "2024", "value": 84.5}]]})
        self.assertIn("life expectancy (years): 84.50", first("life expectancy in Japan", net=net))

    def test_fred_needs_a_key(self):
        net = FakeNet({"stlouisfed": {"observations": [{"date": "2026-09-01", "value": "4.3"}]}})
        self.assertIsNone(first("what is the us unemployment rate", net=net))
        os.environ["FRED_API_KEY"] = "k"
        try:
            self.assertIn("US unemployment rate (%): 4.3", first("what is the us unemployment rate", net=net))
        finally:
            os.environ.pop("FRED_API_KEY", None)

    def test_arxiv_and_pubmed(self):
        atom = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Better  Models</title><published>2026-10-01T00:00:00Z</published></entry></feed>')
        self.assertIn("Better Models (2026-10-01)", first("latest papers on language models", net=FakeNet({"arxiv.org": atom})))
        net = FakeNet({"esearch": {"esearchresult": {"idlist": ["1"]}}, "esummary": {"result": {"1": {"title": "Diabetes study", "source": "Lancet", "pubdate": "2026"}}}})
        self.assertIn("Diabetes study (Lancet, 2026)", first("pubmed studies on diabetes treatment", net=net))

    def test_stack_overflow_and_trivia(self):
        net = FakeNet({"stackexchange": {"items": [{"title": "How to fix KeyError", "score": 120, "link": "https://stackoverflow.com/q/1"}]}})
        self.assertIn("How to fix KeyError (score 120", first("I get KeyError: 'name' in python", net=net))
        self.assertIsNone(first("what is a key in a dictionary", net=net))
        tri = FakeNet({"opentdb": {"results": [{"question": "What%20is%202%2B2%3F", "correct_answer": "4", "incorrect_answers": ["3", "5", "22"]}]}})
        text = first("give me 3 trivia questions", net=tri)
        self.assertIn("What is 2+2?", text)
        self.assertIn("Answer: 4", text)

    def test_filings(self):
        net = FakeNet({"ticker.txt": "aapl\t320193\nmsft\t789019\n", "submissions": {"name": "Apple Inc.", "filings": {"recent": {
            "form": ["8-K", "10-K"], "filingDate": ["2026-10-01", "2026-09-30"], "accessionNumber": ["0000320193-26-000001", "0000320193-26-000002"], "primaryDocument": ["a.htm", "b.htm"]}}}})
        text = first("latest 10-K for apple", net=net)
        self.assertIn("10-K filed 2026-09-30", text)
        self.assertIn("/320193/000032019326000002/b.htm", text)

    def test_wolfram_needs_a_key(self):
        net = FakeNet({"wolframalpha": "Approximately 1.4 billion"})
        self.assertIsNone(first("what is the boiling point of nitrogen", net=net))
        os.environ["WOLFRAM_APPID"] = "k"
        try:
            self.assertIn("Approximately 1.4 billion", first("what is the boiling point of nitrogen", net=net))
        finally:
            os.environ.pop("WOLFRAM_APPID", None)


class Currency(unittest.TestCase):
    def test_second_source_for_currencies_the_ecb_does_not_have(self):
        class Net(FakeNet):
            def _get(self, url):
                self.urls.append(url)
                if "frankfurter" in url:
                    raise OSError("unsupported currency")
                return {"time_last_update_utc": "Wed, 07 Oct 2026 00:02:31 +0000", "rates": {"AED": 3.6725}}
        text = first("convert 100 usd to aed", net=Net())
        self.assertIn("100 USD = 367.25 AED", text)


class Offline(unittest.TestCase):
    def test_nothing_online_runs_when_offline(self):
        net = FakeNet(geo())
        for q in ("how old is Tom Hanks", "latest version of requests", "next episode of Severance", "calories in a banana", "how far is Paris from London", "give me a trivia question",
                  "what is the gdp of Japan", "any recent papers on language models"):
            L.gather(q, NOW, online=False, net=net)
        self.assertEqual(net.urls, [])


if __name__ == "__main__":
    unittest.main()
