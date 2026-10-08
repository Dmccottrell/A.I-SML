# Scorecard: how well each Emvryx model does, and where it falls short

These are our own measurements, on our own computer, using public test sets and our own question sheets. Public tests are scored differently by different people, so compare these numbers with each other, not with scores you see elsewhere. Small samples wobble by a few points: a gap smaller than that means "about the same". "Not measured yet" means exactly that.

## The numbers

| Model | Common sense (HellaSwag) | Our rules sheet (30 questions) | Python code (MBPP) | Where it falls short |
|---|---|---|---|---|
| **Ember 2** | 28.4% | not measured yet | not measured yet | The smallest model, trained from scratch. Good for simple questions and speed, weak at facts and anything long. |
| **Flare 2** | 36.2% | 10 to 11 of 30 | not measured yet | Trained from scratch. Needs the notes it looks up to answer facts; weak at following detailed instructions. |
| **Flare 2.5** | 65.3% | 22 of 30 | 38% | Weak at harder maths and at writing code, and its answers are short. Fast and light. |
| **Equinox 2** | 69.1% | 24 of 30 | 62% | The everyday model. Weaker than Solstice on hard reasoning; best kept to one function or one file at a time in VryxCode. |
| **Solstice 2** | 73.6% | 26 of 30 | 66% | Stronger on hard questions and code, but slower, and not perfect: it still invents things when it has no notes. |
| **Apogee 2** | not measured yet | not measured yet | not measured yet | The strongest and slowest. In beta: it answers who it is correctly, but its scores have not been measured yet. |

## Other things we measured
- **Grade-school maths (GSM8K, 8 worked examples):** Flare 2.5 got 42.5%, Equinox 2 got 76.5%.
- **Following instructions on our rules sheet:** after our training, Equinox 2 scored 24 of 30 and Solstice 2 scored 26 of 30, where the plain base models they started from scored 7 and 9. Flare 2.5 scored 22, about the same as its base (23).
- **Writing and fixing code in VryxCode (10 small Python exercises, a second try allowed):** Solstice 2 solved 5 of the 10, all on the first try. Equinox 2 solved 4 on the first try and 5 after a second try. For comparison, a specialised outside coding model solved 8 on the first try and 9 after a second. So half the exercises are still beyond our models.
- **Who it is:** Equinox 2, Solstice 2 and Apogee 2 all answered our 16 "who are you, who made you" questions correctly.

## Where Emvryx is weakest right now (the honest list)
1. **Facts it does not look up.** Without notes from a lookup, small models make up details with confidence. The app looks things up and says where an answer came from, but a lookup can find the wrong page.
2. **Recent events.** Models know nothing after their training. Sports, news and prices need the lookup tools, and those need keys that the person running Emvryx has to set up.
3. **Other programming languages.** All our code measurements so far are Python. A twelve-program test for nine languages is built but no model has been run on it yet.
4. **Long documents and long chats.** The everyday setting keeps about 8,000 tokens in mind; Pro and Mega can ask for more, which is slower.
5. **Arithmetic by hand.** It uses an exact calculator for sums it recognises, but a long chain of its own arithmetic can still go wrong.

We re-measure after every retrain and keep this page in step with what we find.
