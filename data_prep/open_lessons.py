"""
open_lessons.py - Lessons written for models that are built on Qwen (Flare, Equinox, Solstice, Apogee), not for the tiny from-scratch models.

WHY THIS FILE EXISTS
    data/v3/chat.jsonl was made to repair the mistakes of Ember 2 and Flare 2, models trained from scratch that knew almost nothing: it taught them to answer only from
    their notes, to say "I don't know" when the notes were silent, to doubt themselves when corrected, and to call unknown names "fictional". A Qwen model already knows far
    more. Trained on those lessons it over-trusted a wrong note and hedged about real people ("Gordon Ramsey ... might be fictional, or too rare for me to know").

    These lessons teach the opposite habits, and nothing else about the world (the model keeps what it knows; we only change how it behaves):
      facts          well-known facts, answered plainly and confidently, in a sentence or two
      names          well-known people, also when the name is spelt wrongly: the answer gives the right spelling, then the answer
      unknowable     live or personal things it really cannot know (the time, your phone number, tomorrow's weather): say so briefly and say who can help
      unfamiliar     a name that is made up: "I'm not familiar with that. Could you check the spelling?" (never "it might be fictional")
    Lessons that use the app's notes (notes_use, notes_ignored, stand_firm) are built in make_chat_data_open.py from the teacher examples.

    Every fact below is one the author is sure of; keep it that way when adding more (a wrong fact here would be taught as true).
"""
import re

# ------------------------------------------------------------------ plain facts
CAPITALS = [
    ("France", "Paris"), ("Germany", "Berlin"), ("Italy", "Rome"), ("Spain", "Madrid"), ("Portugal", "Lisbon"), ("the United Kingdom", "London"),
    ("Ireland", "Dublin"), ("the Netherlands", "Amsterdam"), ("Belgium", "Brussels"), ("Switzerland", "Bern"), ("Austria", "Vienna"), ("Poland", "Warsaw"),
    ("Sweden", "Stockholm"), ("Norway", "Oslo"), ("Denmark", "Copenhagen"), ("Finland", "Helsinki"), ("Greece", "Athens"), ("Turkey", "Ankara"),
    ("Russia", "Moscow"), ("Ukraine", "Kyiv"), ("Egypt", "Cairo"), ("Nigeria", "Abuja"), ("Kenya", "Nairobi"), ("Ethiopia", "Addis Ababa"), ("Ghana", "Accra"),
    ("Morocco", "Rabat"), ("Japan", "Tokyo"), ("China", "Beijing"), ("India", "New Delhi"), ("Pakistan", "Islamabad"), ("Bangladesh", "Dhaka"),
    ("Thailand", "Bangkok"), ("Vietnam", "Hanoi"), ("Indonesia", "Jakarta"), ("the Philippines", "Manila"), ("South Korea", "Seoul"),
    ("Australia", "Canberra"), ("New Zealand", "Wellington"), ("Canada", "Ottawa"), ("the United States", "Washington, D.C."), ("Mexico", "Mexico City"),
    ("Brazil", "Brasília"), ("Argentina", "Buenos Aires"), ("Chile", "Santiago"), ("Peru", "Lima"), ("Colombia", "Bogotá"), ("Cuba", "Havana"),
    ("Saudi Arabia", "Riyadh"), ("Iran", "Tehran"), ("Iraq", "Baghdad"), ("Afghanistan", "Kabul"), ("Hungary", "Budapest"), ("Romania", "Bucharest"),
]

BOOKS = [
    ("Pride and Prejudice", "Jane Austen", "published in 1813"), ("1984", "George Orwell", "published in 1949"), ("Hamlet", "William Shakespeare", "a play from around 1600"),
    ("The Great Gatsby", "F. Scott Fitzgerald", "published in 1925"), ("Moby-Dick", "Herman Melville", "published in 1851"),
    ("Frankenstein", "Mary Shelley", "published in 1818"), ("The Hobbit", "J.R.R. Tolkien", "published in 1937"), ("War and Peace", "Leo Tolstoy", "a Russian novel"),
    ("Don Quixote", "Miguel de Cervantes", "a Spanish novel from the early 1600s"), ("Great Expectations", "Charles Dickens", "published in 1861"),
    ("To Kill a Mockingbird", "Harper Lee", "published in 1960"), ("The Odyssey", "Homer", "an ancient Greek epic poem"),
    ("Alice's Adventures in Wonderland", "Lewis Carroll", "published in 1865"), ("Dracula", "Bram Stoker", "published in 1897"),
    ("Romeo and Juliet", "William Shakespeare", "a tragedy from the 1590s"), ("Harry Potter and the Philosopher's Stone", "J.K. Rowling", "published in 1997"),
]

SYMBOLS = [("hydrogen", "H"), ("helium", "He"), ("carbon", "C"), ("nitrogen", "N"), ("oxygen", "O"), ("sodium", "Na"), ("iron", "Fe"), ("gold", "Au"),
           ("silver", "Ag"), ("copper", "Cu"), ("lead", "Pb"), ("potassium", "K")]

# (question variants, answer): each one is something the author is certain of
GENERAL_FACTS = [
    (["What is the largest planet in our solar system?", "Which planet is the biggest?"], "Jupiter is the largest planet in our solar system."),
    (["How many planets are in the solar system?", "How many planets orbit the Sun?"], "There are eight planets: Mercury, Venus, Earth, Mars, Jupiter, Saturn, Uranus and Neptune."),
    (["What is the closest star to Earth?"], "The Sun is the closest star to Earth."),
    (["What is the boiling point of water?", "At what temperature does water boil?"], "Water boils at 100 degrees Celsius (212 degrees Fahrenheit) at sea level."),
    (["What is the freezing point of water?", "At what temperature does water freeze?"], "Water freezes at 0 degrees Celsius (32 degrees Fahrenheit)."),
    (["What is the speed of light?", "How fast does light travel?"], "Light travels at about 299,792 kilometres per second (roughly 186,000 miles per second) in a vacuum."),
    (["What gas do plants take in for photosynthesis?", "What do plants absorb from the air?"], "Plants take in carbon dioxide and, using sunlight, turn it into sugars and oxygen."),
    (["What is the largest ocean?", "Which is the biggest ocean on Earth?"], "The Pacific Ocean is the largest ocean on Earth."),
    (["What is the longest river in the world?"], "The Nile and the Amazon are the two longest rivers; the Nile has traditionally been named the longest, at about 6,650 kilometres."),
    (["What is the tallest mountain on Earth?", "What is the highest mountain in the world?"], "Mount Everest, in the Himalayas, is the highest mountain above sea level at about 8,849 metres."),
    (["How many continents are there?"], "There are seven continents: Africa, Antarctica, Asia, Australia (Oceania), Europe, North America and South America."),
    (["How many days are in a leap year?"], "A leap year has 366 days, with an extra day, 29 February."),
    (["Who was the first president of the United States?", "Who was the first US president?"], "George Washington was the first president of the United States. He served two terms, from 1789 to 1797."),
    (["Who was the first person to walk on the Moon?", "Who landed on the Moon first?"], "Neil Armstrong was the first person to walk on the Moon, on 20 July 1969, during the Apollo 11 mission."),
    (["When did World War II end?", "What year did the Second World War end?"], "World War II ended in 1945: in Europe in May and in the Pacific in September."),
    (["When did the Berlin Wall fall?"], "The Berlin Wall fell on 9 November 1989."),
    (["When did the Titanic sink?", "What year did the Titanic sink?"], "The Titanic sank on 15 April 1912 after hitting an iceberg on its first voyage."),
    (["What year was the United States Declaration of Independence adopted?"], "It was adopted on 4 July 1776."),
    (["What is the chemical formula for water?", "What is water made of?"], "Water is H2O: two hydrogen atoms and one oxygen atom."),
    (["What is the hardest natural material?", "What is the hardest natural substance?"], "Diamond is the hardest natural material."),
    (["What is the powerhouse of the cell?"], "The mitochondria are often called the powerhouse of the cell because they produce most of its usable energy."),
    (["What does DNA stand for?"], "DNA stands for deoxyribonucleic acid. It carries the genetic instructions of living things."),
    (["How many bones are in the adult human body?"], "An adult human body has 206 bones."),
    (["What is the square root of 144?"], "The square root of 144 is 12."),
    (["What is the value of pi?", "What is pi?"], "Pi is the ratio of a circle's circumference to its diameter, about 3.14159."),
    (["Who painted the Mona Lisa?", "Who painted the Mona Lisa and when?"], "Leonardo da Vinci painted the Mona Lisa, in the early 1500s."),
    (["Who wrote the theory of general relativity?", "Who came up with general relativity?"], "Albert Einstein published the general theory of relativity in 1915."),
    (["What is the currency of Japan?"], "The currency of Japan is the yen."),
    (["What is the currency of the United Kingdom?"], "The currency of the United Kingdom is the pound sterling."),
    (["What language is spoken in Brazil?", "What is the main language of Brazil?"], "Portuguese is the main language of Brazil."),
]

# ------------------------------------------------------------------ well-known people, also when the name is spelt wrongly
# (right spelling, [typed variants], one plain description)
PEOPLE = [
    ("Gordon Ramsay", ["gordon ramsey", "gordan ramsay", "gordon ramsay"],
     "a Scottish-born British chef, restaurateur and television personality, known for shows such as Hell's Kitchen, Kitchen Nightmares and MasterChef"),
    ("Albert Einstein", ["albert einstien", "albert einstine", "einstein"],
     "a German-born theoretical physicist who developed the theory of relativity and won the 1921 Nobel Prize in Physics"),
    ("Marie Curie", ["marie curry", "madame curie", "marie curie"],
     "a Polish-born physicist and chemist who researched radioactivity and won Nobel Prizes in both Physics (1903) and Chemistry (1911)"),
    ("Leonardo da Vinci", ["leonardo divinci", "leonardo da vinchi", "leonardo davinci"],
     "an Italian Renaissance painter, inventor and scientist, famous for the Mona Lisa and The Last Supper"),
    ("William Shakespeare", ["william shakespear", "shakespear", "william shakespere"],
     "an English playwright and poet, author of plays such as Hamlet, Macbeth and Romeo and Juliet"),
    ("Isaac Newton", ["issac newton", "isaac newtin", "sir isaac newton"],
     "an English mathematician and physicist who formulated the laws of motion and universal gravitation"),
    ("Nelson Mandela", ["nelson mandella", "nelson mandela", "mandela"],
     "a South African anti-apartheid leader who became the country's first Black president, serving from 1994 to 1999"),
    ("Martin Luther King Jr.", ["martin luther king", "martin luthor king", "mlk"],
     "an American Baptist minister and civil rights leader, known for his \"I Have a Dream\" speech in 1963"),
    ("Abraham Lincoln", ["abraham lincon", "abe lincoln", "abraham lincoln"],
     "the 16th president of the United States, who led the country through the Civil War and issued the Emancipation Proclamation"),
    ("Wolfgang Amadeus Mozart", ["wolfgang amadeus mozert", "mozart", "mozzart"],
     "an Austrian composer of the Classical era (1756 to 1791) who wrote symphonies, operas and concertos"),
    ("Ludwig van Beethoven", ["ludwig van beethovan", "beethoven", "beethovan"],
     "a German composer (1770 to 1827) who bridged the Classical and Romantic eras and wrote nine symphonies"),
    ("Vincent van Gogh", ["vincent van go", "vincent van gough", "van gogh"],
     "a Dutch post-impressionist painter, famous for The Starry Night and his sunflower paintings"),
    ("Pablo Picasso", ["pablo picaso", "pablo piccasso", "picasso"],
     "a Spanish painter and sculptor who co-founded Cubism and painted Guernica"),
    ("Steve Jobs", ["steve jobbs", "steven jobs", "steve jobs"],
     "a co-founder of Apple, who helped create products such as the iPhone, the iPad and the Macintosh"),
    ("Bill Gates", ["bill gate", "bil gates", "bill gates"],
     "a co-founder of Microsoft and, later, a philanthropist through the Gates Foundation"),
    ("Serena Williams", ["serena willams", "serena williams", "serena willimas"],
     "an American tennis player who won 23 Grand Slam singles titles"),
    ("Lionel Messi", ["lionel messy", "leo messi", "lionel mesi"],
     "an Argentine footballer, widely regarded as one of the greatest players ever, who won the World Cup with Argentina in 2022"),
    ("Cleopatra", ["cleopatra", "cleopatrah", "cleapatra"],
     "the last active ruler of Ptolemaic Egypt, who lived from 69 to 30 BC"),
    ("Winston Churchill", ["winston churchil", "winston churchhill", "churchill"],
     "the British prime minister who led the United Kingdom through most of World War II"),
    ("Galileo Galilei", ["galileo galilie", "galilleo", "galileo"],
     "an Italian astronomer and physicist who made key telescope observations, including Jupiter's four largest moons"),
]

LIVING = {"Gordon Ramsay", "Bill Gates", "Serena Williams", "Lionel Messi"}      # the rest are described in the past tense

UNKNOWABLE = [
    ("What is my phone number?", "I don't know your phone number. I can only see what you tell me in this chat."),
    ("What did I have for breakfast?", "I can't know that. I only know what you tell me in this chat."),
    ("What will the weather be like tomorrow?", "I can't see live forecasts myself. Ask me with lookups turned on, or check a weather app."),
    ("Who won the game last night?", "I can't see live scores myself. If lookups are on I can try to find it, or a sports site will have it."),
    ("What time is it?", "I can't see a clock. Your phone or computer will show the time."),
    ("What's in the news today?", "I can't see today's news myself. A news site will have it, and I can look it up if lookups are turned on."),
    ("How much money is in my bank account?", "I can't see your accounts or any personal information, so I don't know."),
    ("What's my email password?", "I don't know it, and you should never share a password with anyone, including me."),
    ("What am I thinking right now?", "I can't know what you're thinking. I only know what you type here."),
    ("What is the price of Bitcoin right now?", "I can't see live prices myself. A finance site will have the current figure, and I can look it up if lookups are on."),
]

UNFAMILIAR = [
    "What is the capital of {name}?", "Who invented the {name}?", "Who is {name}?", "What is {name} famous for?", "Tell me about {name}.",
]
UNFAMILIAR_REPLY = [
    "I'm not familiar with \"{name}\". Could you check the spelling, or tell me where you saw it?",
    "I don't recognise \"{name}\". Is it spelled differently, or can you tell me a bit more about it?",
    "I'm not sure what \"{name}\" is. Can you give me more detail, or check the spelling?",
]
SYLLABLES = ["zor", "blax", "vel", "tor", "quin", "dra", "mox", "ly", "thar", "ren", "skel", "vo", "prin", "gal", "zu", "kest", "orn", "bri", "fen", "wex"]

# answers that sound like a chatbot disclaimer or a refusal: not taught for ordinary questions
OVERCAUTIOUS = re.compile(r"\bas an ai( language model| assistant)?\b|\bi (do not|don't|can't|cannot) have (personal|access|the ability|real-time)\b|"
                          r"\bi'?m (just )?an ai\b.{0,40}\b(can't|cannot|unable)\b|\bi (cannot|can't) (browse|access the internet)\b", re.I)
SOURCE_TAG = re.compile(r"\s*\((?:source|sources)\s*:[^)]*\)", re.I)


def strip_source(text):
    """The answer without a trailing "(Source: ...)" tag (the app shows where an answer came from; the model need not write it)."""
    return SOURCE_TAG.sub("", text).strip()


def is_overcautious(text):
    return bool(OVERCAUTIOUS.search(text or ""))


def _chat(question, answer):
    return [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]


def messy(text, rng):
    """How people often type it: sometimes all lower case and without the question mark."""
    if rng.random() < 0.3:
        text = text.lower().rstrip("?")
    return text


def fact_conversations(rng, n):
    """n short chats with a plain, confident fact (capitals, books, symbols, general knowledge)."""
    out = []
    for _ in range(n):
        r = rng.random()
        if r < 0.35:
            country, capital = rng.choice(CAPITALS)
            q = rng.choice([f"What is the capital of {country}?", f"What's the capital of {country}?", f"Which city is the capital of {country}?"])
            a = rng.choice([f"The capital of {country} is {capital}.", f"{capital} is the capital of {country}."])
        elif r < 0.50:
            title, author, note = rng.choice(BOOKS)
            q = rng.choice([f"Who wrote {title}?", f"Who is the author of {title}?"])
            a = f"{author} wrote {title}, {note}."
        elif r < 0.58:
            element, symbol = rng.choice(SYMBOLS)
            q = rng.choice([f"What is the chemical symbol for {element}?", f"What's the symbol for {element} on the periodic table?"])
            a = f"The chemical symbol for {element} is {symbol}."
        else:
            questions, a = rng.choice(GENERAL_FACTS)
            q = rng.choice(questions)
        out.append(_chat(messy(q, rng), a))
    return out


def people_conversations(rng, n):
    """n chats about well-known people. A misspelt name gets the right spelling, then the answer (no doubt, no "fictional")."""
    out = []
    for _ in range(n):
        name, variants, about = rng.choice(PEOPLE)
        typed = rng.choice(variants + [name.lower()])
        q = rng.choice([f"Who is {typed}?", f"who is {typed}", f"Tell me about {typed}.", f"What is {typed} known for?", f"who was {typed}"])
        verb = "is" if name in LIVING else "was"
        if typed.lower() == name.lower() or typed.lower().rstrip(".") == name.lower().rstrip("."):
            a = f"{name} {verb} {about}."
        else:
            a = f"I think you mean {name}. {name} {verb} {about}."
        out.append(_chat(q, a))
    return out


def unknowable_conversations(rng, n):
    return [_chat(messy(q, rng), a) for q, a in (rng.choice(UNKNOWABLE) for _ in range(n))]


def fake_name(rng):
    return "".join(rng.choice(SYLLABLES) for _ in range(rng.randint(2, 3))).capitalize()


def unfamiliar_conversations(rng, n):
    """A made-up name: ask about the spelling instead of declaring it fictional."""
    out = []
    for _ in range(n):
        name = fake_name(rng)
        out.append(_chat(rng.choice(UNFAMILIAR).format(name=name), rng.choice(UNFAMILIAR_REPLY).format(name=name)))
    return out
