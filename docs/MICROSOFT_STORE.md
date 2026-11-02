# Emvryx in the Microsoft Store (free)

Why: the plain installer (`Emvryx-Setup.exe`) is not code-signed, so Windows warns "Windows protected your PC". A Store app is signed by Microsoft when it
is published, so people get no warning, and the Store updates it. A person's individual developer account is free (no registration fee since 2025).

## What the project already does
`.github/workflows/windows-app.yml` builds `Emvryx.msix` (the Store package) on every run that touches `windows-app/`, next to the installer. Download it
from the run page: Artifacts > `emvryx-msix`. Without the three variables below it is built with test names (fine for checking that packaging works,
not for the Store).

## What the owner does (needs the owner's ID, so Claude cannot)
1. Sign up at **storedeveloper.microsoft.com** with a personal Microsoft account (an ID and a selfie are checked). Choose **Individual**: free.
2. In Partner Center: **Apps and games > New product > MSIX or PWA app**, and reserve the name **Emvryx** (a taken name needs another, such as "Emvryx AI").
3. Open **Product management > Product identity** and copy three values into the repository's **Settings > Secrets and variables > Actions > Variables**
   (variables, not secrets; they are not secret):
   - `MSIX_IDENTITY_NAME`: the "Package/Identity/Name"
   - `MSIX_PUBLISHER`: the "Package/Identity/Publisher" (looks like `CN=XXXXXXXX-XXXX-...`)
   - `MSIX_PUBLISHER_DISPLAY`: the "Package/Properties/PublisherDisplayName"
4. Re-run the `windows-app` workflow (Actions > windows-app > Run workflow) and download `emvryx-msix`.
5. In Partner Center start a **submission**: upload `Emvryx.msix`, fill in the listing (description, 1 to 4 screenshots of the app, the category "Productivity" or
   "Developer tools"), the age rating questions, and the privacy policy address: `https://chat.emvryx.app/privacy`.
6. In "Notes for certification" give the testers a test account (a name and sign-in key made for them) and say the app needs the internet and the
   owner's server on. **If the server is off when they test, the app is rejected**, so keep the PC on during review (usually a few days).

## Things to know
- The app is a window onto `chat.emvryx.app`. Microsoft expects an app to be "fully functional"; web-wrapper apps have been refused before. The listing should
  say what it adds on a PC (its own window, the taskbar icon, start with Windows) and the test account should show real use.
- The app compares itself with the newest build on GitHub and may say "a new version is ready" and point to the installer. In the Store version the
  Store updates it; that note can be switched off with the `app_updates` switch if it confuses people.
- If Microsoft refuses it: the fallbacks are Azure Artifact Signing (about $10 a month) or SignPath's free signing for open-source projects. Ask the owner first.
