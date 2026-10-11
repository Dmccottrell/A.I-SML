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
| **Testers** | Admins plus the people named under *Named testers*. |
| **Everyone** | All signed-in people. |

Changes apply at once (no restart) and are written to the security log. They are kept in `.emvryx/flags.json`.

## Add a flag when you build a feature
1. Add one line to `FLAGS` in `app/flags.py`: `{"id": "my_feature", "title": "...", "desc": "...", "default": "admins"}`.
2. In the page, wrap the feature in `featureOn('my_feature')` (the server sends `features` in `/api/state`).
3. If the server must refuse the feature too, check `state.flags.on("my_feature", who)` in the route.
4. Try it as the owner. Move it to Testers, then Everyone, when you are happy.

## The welcome tour
`welcome_tour` is the first flag: the animated introduction shown the first time someone signs in. It is on for owner and admins now. When you are happy,
choose **Everyone**. People can replay it from Settings > About. To show it again to everyone after you change it, raise `TOUR_VERSION` in `web/index.html`.


The tour is remembered per person and per kind of device (desktop browser, installed app, phone browser), so it shows once on each. Each flag has an **On for everyone** switch on the Features page; it asks to confirm and switching off returns the flag to admins.
