"""Tavily search and the Open-Meteo weather note (no network: fetchers are faked)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import os
import unittest
from unittest import mock

import lookup_auto
import web_search as W

GEO = {"results": [{"name": "Paris", "admin1": "Ile-de-France", "country": "France", "latitude": 48.85, "longitude": 2.35},
                   {"name": "Paris", "admin1": "Texas", "country": "United States", "latitude": 33.66, "longitude": -95.55}]}
FORECAST = {"current": {"time": "2026-10-06T14:00", "temperature_2m": 17.2, "apparent_temperature": 16.0, "relative_humidity_2m": 60,
                        "weather_code": 2, "wind_speed_10m": 12.0},
            "daily": {"time": ["2026-10-06", "2026-10-07", "2026-10-08"], "weather_code": [2, 61, 3], "temperature_2m_max": [19, 15, 14],
                      "temperature_2m_min": [9, 8, 7], "precipitation_probability_max": [10, 70, 20]}}


def fake_fetch(calls):
    def fetch(url, headers=None):
        calls.append(url)
        return GEO if "geocoding" in url else FORECAST
    return fetch


class WeatherTests(unittest.TestCase):
    def test_which_questions_are_weather(self):
        for q in ("what is the weather today?", "weather in Paris", "will it rain tomorrow", "how hot is it", "forecast for Austin"):
            self.assertTrue(W.is_weather_question(q), q)
        for q in ("what is the capital of France?", "who invented the telephone?", "temperature of the sun"):
            self.assertFalse(W.is_weather_question(q), q)

    def test_place_from_the_question_or_default(self):
        self.assertEqual(W.weather_place("what is the weather in Paris today?"), "Paris")
        self.assertEqual(W.weather_place("weather in New York, USA tomorrow"), "New York, USA")
        self.assertEqual(W.weather_place("what is the weather today?", "Austin, Texas"), "Austin, Texas")
        self.assertEqual(W.weather_place("will it rain in the morning?", "Rome"), "Rome")
        self.assertEqual(W.weather_place("what is the weather today?"), "")

    def test_note_has_both_units_and_three_days(self):
        calls = []
        notes = W.weather_notes("weather in Paris", fetch=fake_fetch(calls))
        self.assertEqual(len(notes), 1)
        text = notes[0]["text"]
        self.assertIn("17°C (63°F)", text)
        self.assertIn("Tomorrow", text)
        self.assertIn("70% chance of rain", text)
        self.assertIn("Paris, Ile-de-France, France", notes[0]["title"])
        self.assertEqual(notes[0]["url"], "https://open-meteo.com/")
        self.assertTrue(any("forecast" in c for c in calls))

    def test_region_picks_the_right_city(self):
        notes = W.weather_notes("weather in Paris, Texas", fetch=fake_fetch([]))
        self.assertIn("Texas", notes[0]["title"])

    def test_no_place_or_failure_gives_no_note(self):
        self.assertEqual(W.weather_notes("what is the weather today?"), [])
        def boom(url, headers=None):
            raise OSError("offline")
        self.assertEqual(W.weather_notes("weather in Paris", fetch=boom), [])
        self.assertEqual(W.weather_notes("weather in Nowhereville", fetch=lambda u, h=None: {"results": []}), [])

    def test_web_answer_uses_weather_first_and_search_otherwise(self):
        with mock.patch.object(W, "weather_notes", return_value=[{"title": "w", "text": "t", "url": "u"}]), \
                mock.patch.object(W, "web_notes", return_value=["search"]) as search:
            self.assertEqual(W.web_answer("weather in Paris", 3)[0]["title"], "w")
            self.assertEqual(W.web_answer("who won the game?", 3), ["search"])
            search.assert_called_once()
        with mock.patch.object(W, "weather_notes", return_value=[]), mock.patch.object(W, "web_notes", return_value=["search"]):
            self.assertEqual(W.web_answer("weather in Paris", 3), ["search"])

    def test_a_weather_message_is_looked_up(self):
        self.assertTrue(lookup_auto.wants_lookup("weather in Paris"))
        self.assertTrue(lookup_auto.time_sensitive("weather in Paris"))


class TavilyTests(unittest.TestCase):
    def test_results_become_notes_and_the_key_is_sent_as_a_header(self):
        seen = {}

        def post(url, body, headers=None):
            seen.update(url=url, body=body, headers=headers)
            return {"results": [{"title": "Tigers win", "url": "https://www.apnews.com/x", "content": "<b>The Tigers</b> won 3-1.",
                                 "published_date": "2026-09-30"}, {"title": "no text", "url": "https://a.com", "content": ""}]}
        out = W.search_tavily("who won", 3, key="k123", post=post)
        self.assertEqual(seen["url"], "https://api.tavily.com/search")
        self.assertEqual(seen["headers"], {"Authorization": "Bearer k123"})
        self.assertEqual(seen["body"]["query"], "who won")
        self.assertEqual(out, [{"title": "Tigers win", "url": "https://www.apnews.com/x", "date": "Sep 30, 2026", "text": "The Tigers won 3-1."}])

    def test_needs_a_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                W.search_tavily("q")

    def test_auto_prefers_tavily_then_brave_then_wikipedia(self):
        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": "a", "BRAVE_API_KEY": "b"}, clear=True):
            self.assertEqual(W.pick_source(), "tavily")
        with mock.patch.dict(os.environ, {"BRAVE_API_KEY": "b"}, clear=True):
            self.assertEqual(W.pick_source(), "brave")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(W.pick_source(), "wikipedia")


if __name__ == "__main__":
    unittest.main()


class GeminiTests(unittest.TestCase):
    def test_one_note_with_the_page_it_used(self):
        seen = {}

        def post(url, body, headers=None):
            seen.update(url=url, body=body, headers=headers)
            return {"candidates": [{"content": {"parts": [{"text": "The Tigers won 3-1 on Sep 30."}]},
                                    "groundingMetadata": {"groundingChunks": [{"web": {"uri": "https://apnews.com/x", "title": "AP"}}]}}]}
        out = W.search_gemini("who won", key="g1", post=post)
        self.assertEqual(seen["headers"], {"x-goog-api-key": "g1"})
        self.assertIn("generateContent", seen["url"])
        self.assertEqual(seen["body"]["tools"], [{"google_search": {}}])
        self.assertEqual(out[0]["url"], "https://apnews.com/x")
        self.assertTrue(out[0]["text"].startswith("The Tigers won"))

    def test_empty_answer_and_missing_key(self):
        self.assertEqual(W.search_gemini("q", key="k", post=lambda *a, **k: {"candidates": []}), [])
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                W.search_gemini("q")

    def test_auto_order_includes_gemini_last_before_wikipedia(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "g"}, clear=True):
            self.assertEqual(W.pick_source(), "gemini")
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "g", "BRAVE_API_KEY": "b"}, clear=True):
            self.assertEqual(W.pick_source(), "brave")
