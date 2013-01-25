"""Move the 'banned domains' list from its current hardcache location to its
new location in Zookeeper
"""
from pylons import g

from r2.lib.zookeeper import LiveDict

zkbans = LiveDict(g.zookeeper, "/banned-domains", watch=False)

hcb = g.hardcache.backend
for domain in hcb.ids_by_category("domain", limit=5000):
    domain_info = g.hardcache.get("domain-" + domain)
    zkbans[domain] = domain_info
