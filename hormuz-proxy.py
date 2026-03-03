#!/usr/bin/env python3
import asyncio
import json
import time
import email.utils
import os
from datetime import datetime
from pathlib import Path

# ── CONFIG ──────────────────────────────────────────────────
API_KEY = "6849ec11e4586d04fda9dc68ede5d7ac62dc4a4c"
BBOX = [[[23.0, 52.0], [28.0, 60.0]]] 
PORT = int(os.environ.get("PORT", 8080))

# ── STATE ───────────────────────────────────────────────────
ais_state = {
    "connected": False,
    "vessels": {},        
    "news_general": [],  
    "news_us": [],       
    "news_iran": [],     
    "brent": "0.00",
    "brent_change": "+0.00",
    "threat_level": "MODERATE",
    "last_update": None,
}

# ── MARKET DATA (BRENT) ─────────────────────────────────────
async def fetch_market_data():
    try:
        import aiohttp
        headers = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession() as session:
            while True:
                async with session.get("https://query1.finance.yahoo.com/v8/finance/chart/BZ=F", headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        price = data['chart']['result'][0]['meta']['regularMarketPrice']
                        prev = data['chart']['result'][0]['meta']['previousClose']
                        diff = price - prev
                        ais_state["brent"] = f"{price:.2f}"
                        ais_state["brent_change"] = f"{'+' if diff > 0 else ''}{diff:.2f}"
                await asyncio.sleep(600)
    except Exception as e: print(f"⚠️ Market Error: {e}")

# ── NEWS & THREAT ANALYSIS (WAR ROOM ENGINE) ────────────────
async def fetch_news_loop():
    try:
        import aiohttp
        import xml.etree.ElementTree as ET
        headers = {"User-Agent": "Mozilla/5.0"}
        
        feeds = [
            "https://news.google.com/rss/search?q=(Hormuz+OR+%22Gulf+of+Oman%22+OR+%22Red+Sea%22)+AND+(attack+OR+strike+OR+vessel)+when:2d&hl=en-US",
            "https://news.google.com/rss/search?q=(IRGC+OR+Houthi+OR+Iran)+AND+(military+OR+navy+OR+warns+OR+claims)+when:2d&hl=en-US",
            "https://news.google.com/rss/search?q=(CENTCOM+OR+%22US+Navy%22+OR+Pentagon+OR+UKMTO)+AND+(intercepts+OR+strikes+OR+deploys)+when:2d&hl=en-US"
        ]

        while True:
            temp_us, temp_iran, temp_general = [], [], []
            threat_score = 0
            seen_titles = set()

            async with aiohttp.ClientSession() as session:
                for url in feeds:
                    async with session.get(url, headers=headers) as resp:
                        if resp.status == 200:
                            root = ET.fromstring(await resp.text())
                            for item in root.findall('.//item'):
                                title = item.findtext('title', '')
                                clean_title = title.split(" - ")[0].strip()
                                
                                # 1. FILTRO ANTI-DUPLICATI
                                if clean_title in seen_titles: continue
                                seen_titles.add(clean_title)

                                link = item.findtext('link', '#')
                                source_name = item.findtext('source', '')
                                if not source_name and " - " in title:
                                    source_name = title.split(" - ")[-1].strip()

                                text_lower = clean_title.lower()
                                src_lower = source_name.lower()

                                # 2. FILTRO "IMMONDIZIA" E OPINIONI
                                blacklist = ['facebook', 'twitter', 'youtube', 'opinion', 'letter', 'editorial', 'podcast', 'blog', 'dispatch']
                                if any(b in text_lower or b in src_lower for b in blacklist): continue

                                # 3. FILTRO "CINETICO" (Solo vera intelligence)
                                kinetic_keywords = ['hormuz', 'tanker', 'vessel', 'ship', 'attack', 'strike', 'missile', 'drone', 'navy', 'irgc', 'centcom', 'ukmto', 'idf', 'war', 'base', 'intercept', 'target', 'destroy']
                                if not any(k in text_lower for k in kinetic_keywords): continue

                                # ESTRAZIONE DATA REALE
                                pub_date_raw = item.findtext('pubDate', '')
                                try:
                                    parsed_date = email.utils.parsedate_to_datetime(pub_date_raw)
                                    time_str = parsed_date.strftime("%d %b %H:%M")
                                    timestamp = parsed_date.timestamp()
                                except:
                                    time_str = datetime.now().strftime("%d %b %H:%M")
                                    timestamp = time.time()

                                # CALCOLO MINACCIA
                                if any(k in text_lower for k in ["attack", "missile", "explosion", "strike", "sinks"]): 
                                    threat_score += 2
                                badge = "ALERT" if any(k in text_lower for k in ["attack", "strike", "missile"]) else "UPDATE"
                                
                                news_obj = {"time": time_str, "timestamp": timestamp, "badge": badge, "src": source_name, "text": clean_title, "url": link}
                                temp_general.append(news_obj)

                                # 4. MOTORE NARRATIVO FAZIONI
                                iran_state_media = ['mehr', 'fars', 'irna', 'press tv', 'tasnim', 'al manar', 'al mayadeen', 'tehran times', 'saba']
                                us_state_media = ['centcom', 'ukmto', 'us navy', 'pentagon', 'idf', 'times of israel', 'jpost', 'reuters', 'ap']

                                is_iran_source = any(x in src_lower for x in iran_state_media)
                                is_us_source = any(x in src_lower for x in us_state_media)
                                
                                narrative_iran = any(x in text_lower for x in ['irgc', 'houthi', 'iran says', 'iran claims', 'iran warns', 'hezbollah'])
                                narrative_us = any(x in text_lower for x in ['centcom', 'us navy', 'ukmto', 'idf', 'israel says', 'us strikes'])

                                if is_iran_source or (narrative_iran and not is_us_source):
                                    news_obj["color"] = "#f97316" # Orange
                                    temp_iran.append(news_obj)
                                elif is_us_source or narrative_us or not narrative_iran:
                                    news_obj["color"] = "#3b82f6" # Blue
                                    temp_us.append(news_obj)

            # ORDINAMENTO CRONOLOGICO ASSOLUTO
            temp_general.sort(key=lambda x: x["timestamp"], reverse=True)
            temp_us.sort(key=lambda x: x["timestamp"], reverse=True)
            temp_iran.sort(key=lambda x: x["timestamp"], reverse=True)

            ais_state["news_general"] = temp_general[:15]
            ais_state["news_us"] = temp_us[:15]
            ais_state["news_iran"] = temp_iran[:15]
            
            ais_state["threat_level"] = "CRITICAL" if threat_score > 4 else "HIGH" if threat_score > 0 else "MODERATE"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 📰 News Pulite -> USA: {len(temp_us)} | IRAN: {len(temp_iran)} | Minaccia: {ais_state['threat_level']}")
            
            await asyncio.sleep(600)
    except Exception as e: print(f"⚠️ News Error: {e}")

# ── AIS STREAM ──────────────────────────────────────────────
async def ais_stream():
    import websockets
    while True:
        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔌 Connessione AIS in corso...")
            async with websockets.connect("wss://stream.aisstream.io/v0/stream") as ws:
                await ws.send(json.dumps({"Apikey": API_KEY, "BoundingBoxes": BBOX, "FilterMessageTypes": ["PositionReport"]}))
                ais_state["connected"] = True
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ AIS Connesso e in ascolto.")
                async for message in ws:
                    data = json.loads(message)
                    meta = data.get("MetaData", {})
                    pos = data.get("Message", {}).get("PositionReport", {})
                    if meta and pos:
                        mmsi = str(meta.get("MMSI"))
                        ais_state["vessels"][mmsi] = {
                            "mmsi": mmsi, "name": meta.get("ShipName", "Unknown"),
                            "lat": pos.get("Latitude"), "lng": pos.get("Longitude"),
                            "sog": pos.get("Sog"), "cog": pos.get("Cog"),
                            "last_seen": time.time()
                        }
                        now = time.time()
                        ais_state["vessels"] = {k: v for k, v in ais_state["vessels"].items() if now - v["last_seen"] < 1800}
        except Exception:
            ais_state["connected"] = False
            await asyncio.sleep(10)

# ── WEB SERVER ──────────────────────────────────────────────
async def web_server():
    from aiohttp import web
    app = web.Application()
    async def index(r): return web.FileResponse(Path(__file__).parent / "hormuz-service.html")
    async def api_ais(r):
        v_list = list(ais_state["vessels"].values())
        return web.json_response({
            "connected": ais_state["connected"],
            "brent": ais_state["brent"],
            "brent_change": ais_state["brent_change"],
            "threat": ais_state["threat_level"],
            "active_vessels": len([v for v in v_list if v['sog'] > 1.0]),
            "queued_vessels": len([v for v in v_list if v['sog'] <= 1.0]),
            "vessels": v_list,
            "news_general": ais_state["news_general"],
            "news_us": ais_state["news_us"],
            "news_iran": ais_state["news_iran"]
        }, headers={"Access-Control-Allow-Origin": "*"})
    
    app.router.add_get("/", index)
    app.router.add_get("/api/ais", api_ais)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🌐 Dashboard web avviata su http://localhost:{PORT}")

async def main():
    print("⚓ HORMUZ MONITOR — Avvio proxy service...")
    await asyncio.gather(web_server(), ais_stream(), fetch_news_loop(), fetch_market_data())

if __name__ == "__main__":

    asyncio.run(main())
