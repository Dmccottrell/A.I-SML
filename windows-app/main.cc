// The Emvryx app for Windows (flag app_updates for its "new version" note): a window of its own for chat.emvryx.app, like Claude's desktop app.
// The models stay on the owner's PC; this is only the window. It uses WebView2, the browser engine built into Windows 10 and 11, through the
// webview library (MIT), so the program is small. GitHub builds it (.github/workflows/windows-app.yml) and stamps the commit it was built from,
// which the page compares with the newest build (windows-latest/version.json) to say when a newer app is ready.
#include "webview/webview.h"

#include <string>

#ifndef EMVRYX_BUILT_FROM
#define EMVRYX_BUILT_FROM ""
#endif

int WINAPI WinMain(HINSTANCE, HINSTANCE, LPSTR, int) {
  try {
    webview::webview w(false, nullptr);
    w.set_title("Emvryx");
    w.set_size(1200, 820, WEBVIEW_HINT_NONE);
    w.set_size(420, 560, WEBVIEW_HINT_MIN);
    // the page learns it is inside this app, and which build (web/js/pwa.js winAppUpdate)
    w.init("window.EMVRYX_APP = {platform: 'windows', builtFrom: '" EMVRYX_BUILT_FROM "'};");
    w.navigate("https://chat.emvryx.app/");
    w.run();
  } catch (const webview::exception &e) {
    MessageBoxA(nullptr, (std::string("Emvryx could not open its window: ") + e.what() +
                          "\n\nIt needs Microsoft Edge WebView2, which comes with Windows 10 and 11 (or from microsoft.com/edge/webview2).").c_str(),
                "Emvryx", MB_ICONERROR);
    return 1;
  }
  return 0;
}
