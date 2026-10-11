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
