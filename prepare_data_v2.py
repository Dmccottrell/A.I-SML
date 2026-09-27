"""
prepare_data_v2.py - Kept so the v2 instructions still work.

It simply runs prepare_web_data.py for v2 (see that file for details):
    python prepare_data_v2.py           ==  python prepare_web_data.py --version v2
    python prepare_data_v2.py --test    ==  python prepare_web_data.py --version v2 --test
"""
import sys

from prepare_web_data import main

if __name__ == "__main__":
    main(["--version", "v2"] + sys.argv[1:])
