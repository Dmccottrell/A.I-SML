"""House rules for the Emvryx 3 models (flag chat_house_rules): until Lessons 4, every chat message to them carries a short note on how to answer
(answer what was asked, no flattery, no emoji stacks, remembered facts only when they help). Older models, and anyone the flag is off for, get nothing."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import app_engine as E
import chat_turn
from tests.test_app_server import Base


class HouseRules(Base):
    backend = None

    def factory(model, question):                                   # noqa: N805
        HouseRules.backend = E.FakeBackend("ok")
        return HouseRules.backend

    factory = staticmethod(factory)

    def prompt(self, model):
        self.ask(self.owner, self.new_chat(self.owner), "can you give me steps to get it installed", model=model)
        return self.state.tok_for({"id": model}).decode(HouseRules.backend.prompts[-1])

    def test_on_for_an_emvryx_3_model(self):
        self.state.flags.data["audiences"]["chat_house_rules"] = "admins"
        self.assertIn("No praise or flattery", self.prompt("flare-3"))

    def test_off_by_flag_and_never_for_older_models(self):
        self.assertNotIn("No praise or flattery", self.prompt("flare-3"))
        self.state.flags.data["audiences"]["chat_house_rules"] = "admins"
        self.assertNotIn("No praise or flattery", self.prompt("flare-2"))

    def test_the_rules_never_name_another_ai(self):
        self.assertNotIn("qwen", chat_turn.HOUSE_HINT.lower())


if __name__ == "__main__":
    unittest.main()
