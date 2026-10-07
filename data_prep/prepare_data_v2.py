"""
prepare_data_v2.py - Kept so the v2 instructions still work.

It simply runs prepare_web_data.py for v2 (see that file for details):
    python data_prep/prepare_data_v2.py           ==  python data_prep/prepare_web_data.py --version v2
    python data_prep/prepare_data_v2.py --test    ==  python data_prep/prepare_web_data.py --version v2 --test
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import sys

from prepare_web_data import main

if __name__ == "__main__":
    main(["--version", "v2"] + sys.argv[1:])
