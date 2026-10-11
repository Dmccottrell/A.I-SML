# Feature flags: test new things before everyone gets them

A feature flag hides a new feature from everyone except the people you choose. Build the feature behind a flag, try it yourself, widen the audience, and
switch it off again in one tap if something is wrong.

## Where
**Settings > Owner > Features and testing** (owner and admins). Each feature shows who sees it and a row of choices:

| Audience | Who sees it |
|---|---|
| **Off** | Nobody. A quick roll-back. |
| **Owner** | Only the PC owner account. |
| **Admins** | The owner and every admin. **New features start here.** |
| **Everyone** | All signed-in people. |

Changes apply at once (no restart) and are written to the security log. They are kept in `.emvryx/flags.json`.

## Add a flag when you build a feature
1. Add one line to `FLAGS` in `app/flags.py`: `{"id": "my_feature", "title": "...", "desc": "...", "default": "admins"}`.
2. In the page, wrap the feature in `featureOn('my_feature')` (the server sends `features` in `/api/state`).
3. If the server must refuse the feature too, check `state.flags.on("my_feature", who)` in the route.
4. Try it as the owner. Move it to Everyone when you are happy.

## The welcome tour
`welcome_tour` is the first flag: the animated introduction shown the first time someone signs in. It is on for owner and admins now. When you are happy,
choose **Everyone**. People can replay it from Settings > About. To show it again to everyone after you change it, raise `TOUR_VERSION` in `web/index.html`.


The tour is remembered per person and per kind of device (desktop browser, installed app, phone browser), so it shows once on each. 

## Publishing to everyone, now or on a date

Each feature on the Features page has a **Publish to everyone** area:

- **Publish now** (asks to confirm) moves it to Everyone at once.
- **Schedule:** pick a date and time (your local time, up to a year ahead) and press Schedule. The feature goes live for everyone by itself at that time; the page then shows who scheduled it. **Cancel schedule** removes it.
- Changing the audience by hand (Off, Owner, Admins or Everyone) replaces any schedule.
- Nothing runs in the background: the time is checked whenever the app asks about the feature, so it goes live on the first look after the time has passed (in practice within seconds, since every page load asks). The change and who scheduled it appear in the security log.
- To pull a feature back after publishing, choose Off, Owner or Admins.

## The Admin screen (owner and admins)

Open it from the account menu (bottom of the side panel) > **Admin**. It has four tabs:

- **Previews:** the current version, **Publish all**, and two lists: *In preview* (each feature with who can see it: Off, Owner or Admins, plus Schedule and Publish) and *Published* (live for everyone, with a "Pull back to admins" button). Below is the **Release history**: every time features go live (now, scheduled, or Publish all) the version goes up (a feature or Publish all is a minor step, for example 1.0.0 to 1.1.0) and the release records what went live and who did it.
- **People:** everyone with an account, with search by name or email. Each person shows their email (with a Copy button), when they joined, when they were last active, plan and rights. Buttons: **Reset password** (the old password stops working, they are signed out everywhere, and a one-time link lets them choose a new one; it is emailed when mail is set up, otherwise shown for you to send), Sign-in link, Reset two-step, Make admin / Remove admin and Plan and rights (owner and the owner's email account only), Delete and Turn off. Admins can reset or delete ordinary accounts; admin and no-limits accounts need the owner.
- **Sign-ups:** who may create an account, and invite codes.
- **Activity:** the security log.

## What people see when something is published

Every release (publish now, a schedule coming due, or Publish all) is shown to each person once, as a **What's new in Emvryx** sheet, the next time they open the app or return to it (checked at most once a minute). Everyone can reread the history under account menu > What's new. The sheet is skipped while the welcome tour is showing and appears right after it. Only the version, date, what went live and any notes are shown to ordinary people.

## Publishing a model (Admin > Models)

Models have their own switch, separate from the feature flags, and a model release does not change the app's version (1.1.0 and so on).

- **Add a new build in preview:** add its entry to `models.json` with `"status": "preview"` (for example `flare-2.6`, version 2.6) and put its `.gguf` file in place. Only the owner and admins see it, as the Flare card marked **Preview** (the previous version moves under Other models for them too, so they can compare); everyone else keeps using Flare 2.5.
- **Publish:** Admin > Models > Publish (or Schedule a date and time). It needs the model file to be on the PC. The model goes live for everyone, becomes the new card for its name, and the older versions of that name move to **Other models**, still usable. Plans follow the model's name (Free has Flare and Equinox, so a new Flare is on Free at once).
- **Other models keeps the newest 6 older versions** of each name (`keep_older_versions` in `models.json`).
- **A new version or an update?** A new version when the training lessons change (several things together, a retrain, a new base). Otherwise it is an update and the version stays: Admin > Models > Live models > **Record an update** writes what changed into the release history.
- Both kinds appear in **What's new** for everyone ("Flare 2.6 is here...", "Flare 2.5 was updated...") and in the release history. The choices are kept in `models_state.json` in the data folder, so updating the code never overwrites them.
