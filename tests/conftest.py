# Shared pytest configuration for ALL test modules.
#
# Strips proxy env vars: on dev boxes behind v2rayN/Hiddify the system proxy
# points at 127.0.0.1:<socks port>, which urllib/requests cannot speak (and
# shouldn't use -- tests talk to CF directly or to localhost relays).
# The app itself still respects proxies via connection.get_effective_proxy.
import os

for _k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy",
           "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

# NO_PROXY=* beats even the Windows registry proxy (v2rayN system mode),
# so tests always talk directly to CF / localhost relays.
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
