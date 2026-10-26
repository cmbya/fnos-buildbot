"""Fixed-source fnOS WebUI login patch; no backend auth bypass."""
from pathlib import Path


def patch(source):
    root = Path(source) / 'packages/app/src/renderer/src'
    edits = {
        root/'pages/Login/index.vue': [
            ('  `${window.location.protocol}//${window.location.hostname}:18010`;', '  window.location.origin;'),
            ('''if (window.localStorage.getItem("api")) {
  window.localStorage.removeItem("api");
  window.location.reload();
}''', '// fnOS: do not discard same-origin configuration or reload on Login.'),
            ('if (error === "Forbidden") {', 'if (error === "Forbidden" || error === "Unauthorized" || error === 401) {'),
        ],
        root/'apis/request.ts': [
            ('    if (keyStorage) {', '    if (keyStorage && !config.headers.Authorization) {'),
            ('    if (baseURL) {\n      config.baseURL = baseURL;', '    if (baseURL && !/^https?:\\/\\//i.test(config.url || "")) {\n      config.baseURL = baseURL;'),
            ('api.defaults.baseURL = `http://127.0.0.1:18010`;', 'api.defaults.baseURL = window.location.origin;'),
        ],
    }
    # Validate every anchor before touching any source.
    updates = {}
    for path, replacements in edits.items():
        text = path.read_text()
        for old, new in replacements:
            if text.count(old) != 1:
                raise RuntimeError('Login patch anchor changed: ' + str(path))
            text = text.replace(old, new, 1)
        updates[path] = text
    for path, text in updates.items():
        path.write_text(text)


if __name__ == '__main__':
    import sys
    patch(Path(sys.argv[1]))
