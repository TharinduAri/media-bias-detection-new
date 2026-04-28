import httpx
import xml.etree.ElementTree as ET

async def probe():
    async with httpx.AsyncClient() as client:
        url = "https://www.ft.lk/sitemap.xml"
        try:
            resp = await client.get(url, timeout=10.0)
            if resp.status_code == 200:
                root = ET.fromstring(resp.text)
                sitemaps = root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}sitemap")
                print(f"Total sitemaps in index: {len(sitemaps)}")
                # Print last few sitemap locs
                for s in sitemaps[-5:]:
                    loc = s.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
                    print(f"Sitemap: {loc.text if loc is not None else 'None'}")
            else:
                print(f"Main sitemap status: {resp.status_code}")
        except Exception as e:
            print(f"Error {e}")

import asyncio
asyncio.run(probe())
