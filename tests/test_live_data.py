"""Tests for live_data.py (exact and live facts) and how the server uses it. No test touches the real internet."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import json
import os
import time
import unittest

import app_engine as E
import live_data as L
from tests.test_app_server import Base

NOW = time.mktime((2026, 10, 7, 12, 0, 0, 0, 0, -1))      # Wednesday, October 7, 2026


class FakeNet:
    """Answers by a piece of the URL: {"frankfurter": {...json...}, "stooq": "csv text"}."""

    def __init__(self, data=None, fail=False):
        self.data, self.fail, self.urls = data or {}, fail, []

    def _get(self, url):
        self.urls.append(url)
        if self.fail:
            raise OSError("offline")
        for key, value in self.data.items():
            if key in url:
                return value
        raise OSError("not in the fake: " + url)

    def json(self, url):
        v = self._get(url)
        return json.loads(v) if isinstance(v, str) else v

    def text(self, url):
        return self._get(url)


def ask(question, net=None, online=True, now=NOW):
    return L.gather(question, now, online=online, net=net or FakeNet())


def first(question, **kw):
    notes, _ = ask(question, **kw)
    return notes[0]["text"] if notes else None


class Calculator(unittest.TestCase):
    def test_sums_are_exact(self):
        self.assertEqual(first("What is 15% of 240?", online=False), "15% of 240 = 36")
        self.assertEqual(first("calculate 0.1+0.2", online=False), "0.1 + 0.2 = 0.3")
        self.assertEqual(first("what's 12*13+4", online=False), "12 * 13 + 4 = 160")
        self.assertEqual(first("what is 1,000 divided by 8", online=False), "1000 / 8 = 125")
        self.assertEqual(first("what is 7 x 8", online=False), "7 * 8 = 56")
        self.assertEqual(first("square root of 144", online=False), "sqrt(144) = 12")
        self.assertEqual(first("what is 2 to the power of 10", online=False), "2^10 = 1,024")
        self.assertEqual(first("what is (3+4)*2", online=False), "(3 + 4) * 2 = 14")

    def test_tips(self):
        self.assertIn("$8.64", first("tip on $48 at 18%", online=False))
        self.assertIn("$56.64", first("tip on $48 at 18%", online=False))

    def test_units(self):
        self.assertEqual(first("convert 5 miles to km", online=False), "5 miles = 8.04672 km")
        self.assertIn("22.2222°C", first("72 f to c", online=False))
        self.assertIn("16 tablespoons", first("how many tablespoons in a cup", online=False))
        self.assertIsNone(first("convert 5 miles to kilograms", online=False))          # different kinds of unit

    def test_ordinary_text_is_left_alone(self):
        for q in ("what is 2026-10-07", "I have 3 dogs and 2 cats", "who is gordon ramsay", "explain photosynthesis", "my number is 555-1234", "hi",
                  "what is the capital of France", "what is a 5-star hotel"):
            self.assertIsNone(first(q, online=False), q)

    def test_bad_sums_give_nothing(self):
        for q in ("what is 5/0", "what is 10 ** 99999", "square root of -4"):
            self.assertIsNone(first(q, online=False), q)


class Dates(unittest.TestCase):
    def test_holidays(self):
        self.assertIn("Friday, December 25, 2026", first("What day is christmas this year?", online=False))
        self.assertIn("Thursday, November 26, 2026", first("when is thanksgiving", online=False))
        self.assertIn("79 days", first("how many days until christmas", online=False))
        self.assertIn("Sunday, March 28, 2027", first("what day is easter 2027", online=False))
        self.assertIn("Monday, May 25, 2026", first("what day was memorial day this year", online=False))
        self.assertIn("Thursday, November 25, 2027", first("when is thanksgiving next year", online=False))

    def test_a_past_holiday_rolls_to_next_year_when_asked_when(self):
        self.assertIn("2027", first("when is valentine's day", online=False))
        self.assertIn("February 14, 2026", first("what day was valentine's day this year", online=False))

    def test_explicit_dates(self):
        self.assertIn("Sunday", first("what day of the week was July 4, 1976", online=False))
        self.assertIn("59 days", first("how many days between March 3, 2026 and May 1, 2026", online=False))
        self.assertIn("Friday", first("what day is 2026-12-25", online=False))

    def test_unrelated_questions_are_left_alone(self):
        for q in ("why do we celebrate christmas", "what is thanksgiving about", "tell me about easter eggs"):
            self.assertIsNone(first(q, online=False), q)


class TimeAndCurrency(unittest.TestCase):
    def test_local_time_works_offline(self):
        self.assertIn("Wednesday, October 7, 2026", first("what time is it", online=False))

    def test_time_in_a_city(self):
        net = FakeNet({"geocoding": {"results": [{"name": "Tokyo", "country": "Japan", "admin1": "Tokyo", "timezone": "Asia/Tokyo", "latitude": 35.7, "longitude": 139.7}]}})
        text = first("what time is it in Tokyo?", net=net)
        self.assertIn("Tokyo", text)
        self.assertIn("Asia/Tokyo", text)
        self.assertIn("9:00 PM", text)                                     # 12:00 UTC + 9 (the test machine's own zone is not used)
        self.assertIsNone(first("what time is it in Tokyo?", net=net, online=False))

    def test_currency(self):
        net = FakeNet({"frankfurter": {"amount": 100.0, "base": "USD", "date": "2026-10-06", "rates": {"EUR": 92.5}}})
        self.assertIn("100 USD = 92.5 EUR", first("convert 100 usd to eur", net=net))
        self.assertIn("100 USD = 92.5 EUR", first("how much is 100 dollars in euros", net=net))
        self.assertIn("from=USD", net.urls[0])
        self.assertIsNone(first("convert 100 usd to eur", net=net, online=False))
        self.assertIsNone(first("I paid in dollars and euros", net=net))
        self.assertIsNone(first("convert 100 usd to eur", net=FakeNet(fail=True)))

    def test_crypto(self):
        net = FakeNet({"coingecko": {"bitcoin": {"usd": 67123.5, "usd_24h_change": 1.234, "usd_market_cap": 1.3e12}}})
        text = first("what is the price of bitcoin", net=net)
        self.assertIn("$67,123.50", text)
        self.assertIn("+1.2%", text)
        self.assertIsNone(first("who invented bitcoin", net=net))

    def test_stocks(self):
        csv = "Symbol,Date,Time,Open,High,Low,Close,Volume\nAAPL.US,2026-10-06,22:00:09,225.1,228.3,224.9,227.5,1000\n"
        net = FakeNet({"stooq": csv})
        text = first("what is apple's stock price", net=net)
        self.assertIn("227.50 USD", text)
        self.assertIn("2026-10-06", text)
        self.assertIsNone(first("I ate an apple", net=net))
        self.assertIn("points", first("how is the s&p 500 doing", net=FakeNet({"stooq": csv.replace("AAPL.US", "^SPX")})))
        self.assertIsNone(first("stock price of apple", net=FakeNet({"stooq": "Symbol,Date,Time,Open,High,Low,Close,Volume\nAAPL.US,N/D,N/D,N/D,N/D,N/D,N/D,N/D\n"})))


class OtherSources(unittest.TestCase):
    def test_sports(self):
        net = FakeNet({"searchteams": {"teams": [{"idTeam": "1", "strTeam": "Arsenal"}]},
                       "eventslast": {"results": [{"strEvent": "Arsenal vs Chelsea", "dateEvent": "2026-10-04", "strHomeTeam": "Arsenal", "strAwayTeam": "Chelsea",
                                                   "intHomeScore": "2", "intAwayScore": "1"}]}})
        self.assertIn("Arsenal 2 - 1 Chelsea on 2026-10-04", first("who won the Arsenal game", net=net))

    def test_dictionary(self):
        net = FakeNet({"dictionaryapi": [{"word": "serendipity", "phonetic": "/x/", "meanings": [{"partOfSpeech": "noun", "definitions": [{"definition": "a happy accident"}]}]}]})
        self.assertIn("a happy accident", first("define serendipity", net=net))
        self.assertIn("a happy accident", first("what does serendipity mean?", net=net))
        self.assertIsNone(first("what does the fox say about the weather", net=net))

    def test_countries(self):
        net = FakeNet({"restcountries": [{"name": {"common": "Japan", "official": "Japan"}, "capital": ["Tokyo"], "population": 125000000, "area": 377930,
                                           "region": "Asia", "subregion": "Eastern Asia", "currencies": {"JPY": {"name": "Japanese yen"}}, "languages": {"jpn": "Japanese"}}]})
        text = first("what is the population of Japan?", net=net)
        self.assertIn("population 125,000,000", text)
        self.assertIn("Japanese yen (JPY)", text)

    def test_public_holidays(self):
        net = FakeNet({"nager": [{"date": "2026-10-12", "name": "Thanksgiving Day", "localName": "Thanksgiving"}]})
        self.assertIn("Thanksgiving Day: Monday, October 12, 2026", first("what are the public holidays in Canada", net=net))
        self.assertIsNone(first("what are the public holidays in Narnia", net=net))

    def test_news(self):
        rss = ("<rss><channel><item><title>Big thing happens - Wire</title><pubDate>Tue, 06 Oct 2026 10:00:00 GMT</pubDate></item>"
               "<item><title>Other thing - Daily</title></item></channel></rss>")
        net = FakeNet({"news.google.com": rss})
        text = first("latest news about the election", net=net)
        self.assertIn("Big thing happens - Wire", text)
        self.assertIn("q=election+when%3A2d", net.urls[0])
        self.assertIn("Big thing", first("what's in the news", net=FakeNet({"news.google.com": rss})))

    def test_books(self):
        net = FakeNet({"openlibrary": {"docs": [{"title": "Dune", "author_name": ["Frank Herbert"], "first_publish_year": 1965}]}})
        self.assertIn("Dune by Frank Herbert, first published 1965", first("who wrote the book Dune", net=net))

    def test_recipes(self):
        net = FakeNet({"themealdb": {"meals": [{"strMeal": "Arrabiata", "strCategory": "Pasta", "strArea": "Italian", "strIngredient1": "penne", "strMeasure1": "1 pound",
                                                 "strIngredient2": "garlic", "strMeasure2": "3 cloves", "strInstructions": "Boil. Mix."}]}})
        text = first("recipe for arrabiata", net=net)
        self.assertIn("1 pound penne", text)
        self.assertIsNone(first("how do I make a website", net=net))

    def test_air_quality(self):
        net = FakeNet({"geocoding": {"results": [{"name": "Delhi", "country": "India", "latitude": 28.6, "longitude": 77.2}]},
                       "air-quality": {"current": {"us_aqi": 160, "pm2_5": 70, "pm10": 90, "uv_index": 3}}})
        self.assertIn("US AQI 160 (unhealthy)", first("what is the air quality in Delhi", net=net))

    def test_on_this_day_and_earthquakes(self):
        net = FakeNet({"onthisday/events/10/07": {"events": [{"year": 1949, "text": "East Germany is founded."}]}})
        self.assertIn("1949: East Germany is founded.", first("what happened on this day in history", net=net))
        net = FakeNet({"4.5_week": {"features": [{"properties": {"mag": 5.1, "place": "Chile", "time": 1760000000000}}]}})
        self.assertIn("M5.1 Chile", first("any recent earthquakes", net=net))

    def test_release_dates_need_a_key(self):
        net = FakeNet({"rawg.io": {"results": [{"name": "Grand Theft Auto VI", "released": "2026-11-19", "tba": False}]}})
        old = os.environ.pop("RAWG_API_KEY", None)
        try:
            self.assertIsNone(first("when is gta 6 coming out", net=net))
            os.environ["RAWG_API_KEY"] = "test-key"
            self.assertIn("Grand Theft Auto VI: released/releasing 2026-11-19", first("when is gta 6 coming out", net=net))
        finally:
            os.environ.pop("RAWG_API_KEY", None)
            if old:
                os.environ["RAWG_API_KEY"] = old


class Pipeline(unittest.TestCase):
    def test_online_providers_never_run_when_offline_and_nothing_is_sent(self):
        net = FakeNet({"frankfurter": {"rates": {"EUR": 1}}})
        notes, info = ask("convert 100 usd to eur", net=net, online=False)
        self.assertEqual((notes, net.urls, info["asked"]), ([], [], False))

    def test_offline_ok_false_gives_nothing(self):
        self.assertEqual(L.gather("what is 2+2", NOW, online=False, net=FakeNet(), offline_ok=False)[0], [])

    def test_a_failing_provider_does_not_break_the_chat(self):
        notes, info = ask("convert 100 usd to eur", net=FakeNet(fail=True))
        self.assertEqual(notes, [])
        self.assertFalse(info["asked"])

    def test_info_names_the_source(self):
        notes, info = ask("what is 15% of 240", online=False)
        self.assertEqual((info["live"], info["names"], info["asked"]), (1, ["Calculator"], True))
        self.assertEqual(info["sources"][0]["kind"], "live")

    def test_no_more_than_two_providers(self):
        notes, info = ask("what day is christmas and what is 2+2 and the time", online=False)
        self.assertLessEqual(len(info["names"]), L.MAX_PROVIDERS)


class Server(Base):
    backend = None

    def factory(model, question):                                   # noqa: N805
        Server.backend = E.FakeBackend()
        return Server.backend

    factory = staticmethod(factory)

    def setUp(self):
        super().setUp()
        self.state.live_net = FakeNet({"frankfurter": {"amount": 100.0, "base": "USD", "date": "2026-10-06", "rates": {"EUR": 92.5}}})

    def decode(self, ids):
        return self.state.tok_for({"id": "flare-2"}).decode(ids)

    def test_a_sum_reaches_the_model_and_the_page_is_told(self):
        cid = self.new_chat(self.sam)
        status, _, events = self.ask(self.sam, cid, "what is 15% of 240?")
        self.assertIn("15% of 240 = 36", self.decode(Server.backend.prompts[-1]))
        notes = [d for e, d in events if e == "notes"][0]
        self.assertEqual((notes["live"], notes["names"]), (1, ["Calculator"]))

    def test_online_facts_come_from_the_source(self):
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "convert 100 usd to eur")
        self.assertIn("100 USD = 92.5 EUR", self.decode(Server.backend.prompts[-1]))

    def test_private_chats_only_get_offline_facts(self):
        cid = self.new_chat(self.sam, private=True)
        self.ask(self.sam, cid, "convert 100 usd to eur")
        self.assertNotIn("92.5", self.decode(Server.backend.prompts[-1]))
        self.assertEqual(self.state.live_net.urls, [])
        self.ask(self.sam, cid, "what is 15% of 240?")
        self.assertIn("= 36", self.decode(Server.backend.prompts[-1]))

    def test_settings_can_turn_it_off(self):
        self.sam.call("POST", "/api/settings", {"live_data": False})
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "what is 15% of 240?")
        self.assertNotIn("= 36", self.decode(Server.backend.prompts[-1]))
        self.sam.call("POST", "/api/settings", {"live_data": True, "web_search": "none"})
        self.ask(self.sam, cid, "what is 15% of 240?")
        self.assertNotIn("= 36", self.decode(Server.backend.prompts[-1]))

    def test_ordinary_questions_are_unchanged(self):
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "tell me a story about a fox")
        self.assertEqual(self.state.live_net.urls, [])


if __name__ == "__main__":
    unittest.main()
