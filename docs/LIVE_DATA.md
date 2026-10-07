# Live facts (`app/live_data.py`)

Questions where a **number must be right** are answered from code or a real source, and the model only puts it into words. The answer shows "Used live data: Calculator" (or the source's name) under the message. Settings has a **Live facts** switch (On by default). They are off in "Model only" mode. In private chats and "Wikipedia only" mode only the offline ones run.

| Source | Asks like | Needs |
|---|---|---|
| Calculator | "what is 15% of 240", "12*13+4", "square root of 144", "tip on $48 at 18%" | nothing, offline, exact |
| Unit conversion | "convert 5 miles to km", "72 f to c", "how many cups in 2 liters" | nothing, offline |
| Dates | "what day is Christmas this year", "how many days until Thanksgiving", "what day was July 4, 1976", "days between March 3 and May 1", Easter, Mother's Day, Memorial Day and more | nothing, offline |
| Time | "what time is it" (this computer), "what time is it in Tokyo" | offline / free Open-Meteo geocoding (Windows needs `tzdata`) |
| Exchange rates | "convert 100 usd to eur", "how much is 50 euros in dollars" | free, Frankfurter (European Central Bank) |
| Crypto | "price of bitcoin" (BTC, ETH, SOL, DOGE, XRP and more) | free, CoinGecko |
| Stocks | "apple's stock price", "how is the S&P 500 doing" (about 70 well-known companies, indexes, or `$TICKER`) | free, Stooq (delayed) |
| Sports | "who won the Arsenal game", "when do the Lakers play" | free, TheSportsDB |
| Dictionary | "define serendipity", "what does ephemeral mean" | free, dictionaryapi.dev |
| Countries | "population of Japan", "currency of Brazil", "languages in Switzerland" | free, REST Countries |
| Public holidays | "public holidays in Canada" | free, Nager.Date |
| News | "latest news about the election", "what's in the news" | free, Google News RSS |
| Books | "who wrote the book Dune" | free, Open Library |
| Recipes | "recipe for arrabiata" | free, TheMealDB |
| Air quality | "air quality in Delhi" | free, Open-Meteo |
| On this day | "what happened on this day" | free, Wikimedia |
| Earthquakes | "any recent earthquakes" | free, USGS |
| Release dates | "when is GTA 6 coming out" | optional free keys: `RAWG_API_KEY` (games, rawg.io), `TMDB_API_KEY` (films, themoviedb.org) |

Weather already has its own source (Open-Meteo). Web search (Tavily and others) is separate and covers everything else.

**Privacy:** only the part the source needs is sent (a place, a currency pair, a team, a word), never the chat. **Failures:** a source that is offline or changes its format returns nothing and the chat carries on. The sources are built from each service's documentation and tested with fakes; they have not all been tried against the live services, so tell me if one misbehaves.

**Adding a source:** write a function `name(question, now, net, online)` that returns a list of notes, and add it to `PROVIDERS` in `app/live_data.py` (with `True` if it works offline). `tests/test_live_data.py` shows how to fake the internet.


## Second batch (`app/live_more.py`)

| Source | Asks like | Needs |
|---|---|---|
| Finance calculator | "monthly payment on a $300,000 mortgage at 6.5% for 30 years", "invest $1000 at 5% for 10 years and add $100 a month", "bmi 70 kg 175 cm", "percent change from 50 to 75" | offline, exact |
| Time zones | "3pm EST in PST", "9 am London time in Tokyo" (daylight saving for today included) | offline |
| Moon | "what's the moon phase", "when is the next full moon" (calculated, about a day accurate) | offline |
| Dice and coins | "roll 2d6", "flip a coin", "pick a number between 1 and 10" (truly random, which a model can't do) | offline |
| Number bases | "255 in hex", "2026 in roman numerals", "what is XIV in numbers" | offline |
| People | "how old is Tom Hanks", "when did X die", "how tall is X" (age worked out exactly) | free, Wikidata |
| Packages | "latest version of requests", "latest version of react", "latest version of owner/repo" | free, PyPI / npm / GitHub |
| TV | "when is the next episode of Severance" | free, TVmaze |
| Steam | "is dota 2 free on steam", "price of Hades on steam" (say Steam) | free |
| Music | "albums by Adele", "who sings easy on me" | free, iTunes search |
| Nutrition | "calories in a banana" | free, Open Food Facts; better with a free `USDA_API_KEY` |
| Sun | "when does the sun set in Denver" | free, Open-Meteo |
| Distance | "how far is Paris from London", "how long to drive from Austin to Dallas" | free, Open-Meteo + OSRM |
| Past weather, elevation, surf | "what was the weather in Austin on October 1, 2026", "elevation of Denver", "how are the waves in Malibu" | free, Open-Meteo |
| US weather alerts | "any weather alerts in Miami" (US only) | free, weather.gov |
| Country statistics | "GDP of Japan", "inflation in Brazil", "life expectancy in Japan" | free, World Bank |
| US economy | "US unemployment rate", "30 year mortgage rate", "fed funds rate" | free `FRED_API_KEY` |
| Research | "latest papers on language models", "pubmed studies on diabetes" (titles only, not medical advice) | free, arXiv / PubMed |
| Coding errors | "stack overflow KeyError", or any message with an error name | free, Stack Exchange (titles and links) |
| Trivia | "give me 5 trivia questions" | free, Open Trivia DB |
| SEC filings | "latest 10-K for Apple" | free, SEC EDGAR |
| Hard maths and science | "boiling point of nitrogen", "integral of x^2" | free `WOLFRAM_APPID` (Wolfram|Alpha) |
| More currencies | "100 usd to aed" falls back to open.er-api.com when the European Central Bank does not have it | free |

Keys are optional: set them with `setx NAME "value"` and sign out and in. Without a key those providers simply do nothing.
