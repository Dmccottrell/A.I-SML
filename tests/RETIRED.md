# Retired tests

Tests are the judge of whether the code is right, so they are not deleted or weakened to make a change pass (tools/guard_repo.py checks this on
every pull request). When a test is really wrong, or the feature it tested is gone, it is retired here in the open, one line each, written as a
dash, the file path, a colon and the reason (for example: dash, tests/test_old_thing.py, colon, "the old thing was removed in #400").

Checks changed, not removed (the files keep every test and check):

- tests/test_flags.py: the owner changed how releases are numbered and pushed (new features and bug fixes go out separately, features add 0.5 and fixes 0.1, versions like 1.5 instead of 1.1.0); the version numbers and kinds these tests expected (1.0.0 -> 1.1.0 minor, 1.0.1 patch, the Patch/Minor/Major dialog) were the old rule. The new rule is in tests/test_release_split.py.
- tests/test_model_publish.py: the app's starting version is now written 1.0 (was 1.0.0), by the same change.
- tests/test_vryxcode_model.py: a VryxCode features push now makes 1.0 -> 1.5 (was 1.1), and the next versions are named features and fixes (were minor and major), by the same change.
- tests/test_release_fixes.py: fix notes now go out only with a bug-fix push, never with new features (they used to ride along with any release), by the same change.
