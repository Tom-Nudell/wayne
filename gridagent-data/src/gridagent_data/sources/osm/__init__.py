"""OpenStreetMap ``power=*`` bronze loader.

OSM is the most complete open source of fine-grained electrical
infrastructure geometry — especially at sub-69 kV voltages where HIFLD
was silent. We use the Overpass API for scoped region pulls (state or
ISO bounding boxes) and write the raw JSON responses into bronze;
silver dbt models extract ``power=substation``, ``power=line``,
``power=plant``, ``power=generator`` features into canonical form.

For continental-scale pulls the Overpass API is the wrong tool — switch
to a Geofabrik PBF extract + ``osmium`` filter, wrapped by a follow-on
loader. The CLI continues to treat OSM as one source layer regardless
of extraction backend.

Attribution: every downstream row MUST carry
``sources=['osm']`` and ``licenses=['ODbL-1.0']`` so the atlas can
display "© OpenStreetMap contributors" on any tile that shows these
features.
"""

from __future__ import annotations

from .bronze import REGIONS, OverpassRegion, fetch_region

__all__ = ["REGIONS", "OverpassRegion", "fetch_region"]
