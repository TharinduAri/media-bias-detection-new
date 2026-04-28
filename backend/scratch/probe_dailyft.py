import httpx
import xml.etree.ElementTree as ET

async def probe():
    async with httpx.AsyncClient() as client:
        # Try to find the latest english sitemap
        # We'll probe in jumps
        for i in [1000, 2000, 3000, 4000, 5000, 6000, 7000]:
            url = f"https://www.ft.lk/sitemaps/english-{i}"
            try:
                resp = await client.get(url, timeout=10.0)
                if resp.status_code == 200:
                    root = ET.fromstring(resp.text)
                    # Get first url lastmod
                    first_url = root.find(".//{http://www.sitemaps.org/schemas/sitemap/0.9}url")
                    if first_url is not None:
                        news = first_url.find("{http://www.google.com/schemas/sitemap-news/0.9}news")
                        if news is not None:
                            pub_date = news.find("{http://www.google.com/schemas/sitemap-news/0.9}publication_date")
                            print(f"Page {i}: PubDate={pub_date.text if pub_date is not None else 'None'}")
                        else:
                            print(f"Page {i}: No news element")
                else:
                    print(f"Page {i}: {resp.status_code}")
            except Exception as e:
                print(f"Page {i}: Error {e}")

import asyncio
asyncio.run(probe())
