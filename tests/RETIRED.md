# Retired tests

Tests are the judge of whether the code is right, so they are not deleted or weakened to make a change pass (tools/guard_repo.py checks this on
every pull request). When a test is really wrong, or the feature it tested is gone, it is retired here in the open, one line each, written as a
dash, the file path, a colon and the reason (for example: dash, tests/test_old_thing.py, colon, "the old thing was removed in #400").

(None retired yet.)
