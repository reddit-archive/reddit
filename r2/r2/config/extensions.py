from pylons import c

def api_type(subtype = ''):
    return 'api-' + subtype if subtype else 'api'

def is_api(subtype = ''):
    return c.render_style and c.render_style.startswith(api_type(subtype))

def get_api_subtype():
    if is_api() and c.render_style.startswith('api-'):
        return c.render_style[4:]

extension_mapping = {
    "rss": ("xml", "text/xml; charset=UTF-8"),
    "xml": ("xml", "text/xml; charset=UTF-8"),
    "js": ("js", "text/javascript; charset=UTF-8"),
    "wired": ("wired", "text/javascript; charset=UTF-8"),
    "embed": ("htmllite", "text/javascript; charset=UTF-8"),
    "mobile": ("mobile", "text/html; charset=UTF-8"),
    "png": ("png", "image/png"),
    "css": ("css", "text/css"),
    "csv": ("csv", "text/csv; charset=UTF-8"),
    "api": (api_type(), "application/json; charset=UTF-8"),
    "json-html": (api_type("html"), "application/json; charset=UTF-8"),
    "json-compact": (api_type("compact"), "application/json; charset=UTF-8"),
    "compact": ("compact", "text/html; charset=UTF-8"),
    "json": (api_type(), "application/json; charset=UTF-8"),
    "i": ("compact", "text/html; charset=UTF-8"),
}

API_TYPES = ('api', 'json')

def set_extension(environ, ext):
    environ["extension"] = ext
    environ["render_style"], environ["content_type"] = extension_mapping[ext]
