"""Video düzenleme ilanı tarayıcısı.

Herkese açık kaynaklardan İngilizce, uzaktan video düzenleme ilanlarını toplar,
daha önce görülenleri ayıklar, yeni ilanları data/ilanlar.jsonl dosyasına ekler
ve rapor/index.html özet sayfasını yeniden üretir.

Yalnızca Python'un kendi kütüphanelerini kullanır (ek kurulum gerekmez).
Çalıştırma:  python tara.py
Telefon bildirimi için NTFY_KONU ortam değişkeni ayarlanmalıdır (bkz. CLAUDE.md).
"""

import html
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

KOK = Path(__file__).resolve().parent
VERI = KOK / "data"
ILANLAR = VERI / "ilanlar.jsonl"
GORULDU = VERI / "goruldu.json"
RAPOR = KOK / "rapor" / "index.html"

UA = "video-is-takibi/0.1 (personal job-market research; low frequency)"
SIMDI = datetime.now(timezone.utc)

# ---------------------------------------------------------------- yardımcılar


def getir(url, deneme=3):
    """URL'yi indirir; 429 (çok fazla istek) gelirse bekleyip tekrar dener."""
    for i in range(deneme):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < deneme - 1:
                time.sleep(15 * (i + 1))
                continue
            raise
        except (TimeoutError, urllib.error.URLError):  # geçici ağ sorunu
            if i < deneme - 1:
                time.sleep(10)
                continue
            raise


def duz_metin(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def ilan(kaynak, kimlik, baslik, url, metin, sirket="", konum="", ucret="", etiketler=()):
    return {
        "id": f"{kaynak}:{kimlik}",
        "kaynak": kaynak,
        "baslik": duz_metin(baslik),
        "sirket": sirket or "",
        "url": url,
        "konum": konum or "",
        "ucret_alani": ucret or "",
        "etiketler": list(etiketler),
        "metin": duz_metin(metin)[:4000],
    }


# ---------------------------------------------------------------- kaynaklar
# Her kaynağın koşulu: ilanın kendi sayfasına bağlantı verilir ve kaynak adı
# belirtilir (RemoteOK ve Remotive bunu açıkça istiyor). Remotive günde en çok
# 4 istek öneriyor; bu betik günde 1 kez çalışacak şekilde tasarlandı.

ALAKASIZ = re.compile(r"annotation|engineer|analyst|account executive|dean|service desk", re.I)
BASLIK_VIDEO = re.compile(
    r"video|youtube|reels?\b|tiktok|short[- ]?form|\bshorts\b|motion (design|graphic)"
    r"|post[- ]?production|videograph|film edit|premiere|davinci|capcut|after effects",
    re.I,
)


def remoteok():
    veri = json.loads(getir("https://remoteok.com/api"))
    for j in veri[1:]:
        if not BASLIK_VIDEO.search(j.get("position", "")) or ALAKASIZ.search(j.get("position", "")):
            continue
        ucret = ""
        if j.get("salary_min"):
            ucret = f"${j['salary_min']:,}–${j.get('salary_max') or j['salary_min']:,} / yıl"
        yield ilan("Remote OK", j["id"], j.get("position"), j.get("url"), j.get("description"),
                   j.get("company"), j.get("location"), ucret, j.get("tags") or [])


def weworkremotely():
    kok = ET.fromstring(getir("https://weworkremotely.com/remote-jobs.rss"))
    for it in kok.iter("item"):
        baslik = it.findtext("title") or ""
        if not BASLIK_VIDEO.search(baslik) or ALAKASIZ.search(baslik):
            continue
        sirket, _, unvan = baslik.partition(": ")
        yield ilan("We Work Remotely", it.findtext("guid") or it.findtext("link"), unvan or baslik,
                   it.findtext("link"), it.findtext("description"), sirket,
                   it.findtext("region"), "", [it.findtext("category") or ""])


def remotive():
    veri = json.loads(getir("https://remotive.com/api/remote-jobs?search=video"))
    for j in veri["jobs"]:
        if not BASLIK_VIDEO.search(j["title"]) or ALAKASIZ.search(j["title"]):
            continue
        yield ilan("Remotive", j["id"], j["title"], j["url"], j.get("description"),
                   j.get("company_name"), j.get("candidate_required_location"),
                   j.get("salary"), j.get("tags") or [])


def himalayas():
    for sayfa in (1, 2):
        veri = json.loads(getir(f"https://himalayas.app/jobs/api/search?q=video%20editor&page={sayfa}"))
        for j in veri["jobs"]:
            kat = " ".join(j.get("categories") or [])
            if not BASLIK_VIDEO.search(f"{j['title']} {kat}") or ALAKASIZ.search(j["title"]):
                continue
            ucret = ""
            if j.get("minSalary"):
                ucret = f"{j.get('currency') or '$'} {j['minSalary']:,}–{j.get('maxSalary') or j['minSalary']:,} / {j.get('salaryPeriod') or ''}"
            yield ilan("Himalayas", j["guid"], j["title"], j["applicationLink"],
                       f"{j.get('excerpt', '')} {j.get('description', '')}", j.get("companyName"),
                       ", ".join(j.get("locationRestrictions") or []) or "Worldwide", ucret,
                       (j.get("seniority") or []) + (j.get("categories") or []))
        time.sleep(2)


ATOM = "{http://www.w3.org/2005/Atom}"
ISVEREN = re.compile(r"hiring|looking for|need(ed|s)?\b|paying|\bpaid\b|\bpay\b|budget|\$\s?\d|retainer", re.I)
HIZMET_SUNAN = re.compile(r"\[for hire\]|i'?m (a )?(video )?editor|offering|who needs|need a video editor\?|anyone need", re.I)
UCRETSIZ = re.compile(r"\bfree\b|unpaid|for credit|credit given|portfolio only|\[free", re.I)


def reddit(alt, sadece_hiring):
    # Reddit'in herkese açık RSS akışı; giriş gerektirmez. Seyrek istek yapılır.
    kok = ET.fromstring(getir(f"https://www.reddit.com/r/{alt}/new/.rss?limit=100"))
    for e in kok.iter(ATOM + "entry"):
        baslik = e.findtext(ATOM + "title") or ""
        icerik = e.findtext(ATOM + "content") or ""
        metin = f"{baslik} {duz_metin(icerik)}"
        if sadece_hiring and not (re.match(r"\s*\[hiring\]", baslik, re.I) and BASLIK_VIDEO.search(metin)):
            continue
        # Kendi hizmetini sunan editörleri, ücretsiz/karşılıksız istekleri, soruları ve
        # sohbet gönderilerini ele: başlık iş arıyor olmalı ya da en azından "editor" geçmeli
        isveren = ISVEREN.search(baslik) or (re.search(r"editor", baslik, re.I) and ISVEREN.search(metin))
        if not isveren or HIZMET_SUNAN.search(baslik) or UCRETSIZ.search(metin):
            continue
        link = e.find(ATOM + "link").get("href")
        yield ilan(f"Reddit r/{alt}", e.findtext(ATOM + "id"), baslik, link, icerik,
                   e.findtext(f"{ATOM}author/{ATOM}name"), "", "", [])


KAYNAKLAR = [
    ("Remote OK", remoteok),
    ("We Work Remotely", weworkremotely),
    ("Remotive", remotive),
    ("Himalayas", himalayas),
    # Reddit bulut sunucularını sık sınırlıyor; daha değerli olan video grubu önce gelsin
    ("Reddit r/VideoEditingRequests", lambda: reddit("VideoEditingRequests", False)),
    ("Reddit r/forhire", lambda: reddit("forhire", True)),
]

# ---------------------------------------------------------------- sınıflandırma

IS_TURLERI = {
    "YouTube (uzun video)": r"youtube|long[- ]form|vlog",
    "Kısa video (Reels/TikTok/Shorts)": r"short[- ]?form|\bshorts\b|reels?\b|tiktok",
    "Reklam / UGC / sosyal medya": r"\bugc\b|\bads?\b|advertis|social media|paid social|marketing",
    "Podcast": r"podcast",
    "Motion graphics / animasyon": r"motion graphic|motion design|animat",
    "Kurumsal / eğitim videosu": r"corporate|training video|explainer|e-?learning|course",
    "Oyun videosu": r"gaming|game(play)?\b|twitch|stream",
    "Düğün / etkinlik": r"wedding|event",
    "Belgesel / film": r"documentar|film\b|narrative",
    "Renk düzenleme": r"colou?r grad|colorist",
    "Altyazı / basit kesim": r"caption|subtitle|trim|simple cut|basic edit",
}
PROGRAMLAR = {
    "Premiere Pro": r"premiere",
    "DaVinci Resolve": r"davinci|resolve",
    "CapCut": r"capcut",
    "After Effects": r"after ?effects",
    "Final Cut Pro": r"final ?cut",
    "Photoshop": r"photoshop",
    "Canva": r"canva\b",
    "Descript": r"descript",
    "Yapay zekâ araçları": r"\bai\b|runway|midjourney|eleven ?labs",
}
GIRIS = re.compile(r"entry[- ]level|junior|beginner|no experience|new editors?|student|intern\b|trainee|will train|newbie|first job", re.I)
KOLAY = re.compile(r"simple|basic|caption|subtitle|trim|short[- ]?form|\bshorts\b|reels|tiktok", re.I)
KIDEMLI = re.compile(r"senior|\blead\b|head of|director|manager|principal|[3-9]\+? ?years|10\+ ?years", re.I)
ACIK_KONUM = re.compile(r"^$|worldwide|anywhere|global|europe|emea|turkey|türkiye|remote$", re.I)
UCRET = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?\s?[kK]?(?:\s?(?:-|–|to)\s?\$?\s?\d[\d,]*(?:\.\d+)?\s?[kK]?)?"
    r"(?:\s?(?:/|per|an?)\s?(?:hr|hour|video|vid|min(?:ute)?|month|mo|year|yr|project|edit))?",
    re.I,
)


def sinifla(i):
    metin = f"{i['baslik']} {' '.join(i['etiketler'])} {i['metin']}"
    i["is_turleri"] = [ad for ad, rx in IS_TURLERI.items() if re.search(rx, metin, re.I)]
    i["programlar"] = [ad for ad, rx in PROGRAMLAR.items() if re.search(rx, metin, re.I)]
    ucretler = [u.strip() for u in UCRET.findall(metin) if re.search(r"\d", u)]
    i["ucret"] = i["ucret_alani"] or ", ".join(dict.fromkeys(ucretler[:3]))
    i["konum_acik"] = bool(ACIK_KONUM.search(i["konum"].strip()))
    puan = 0
    if GIRIS.search(metin):
        puan += 3
    if KOLAY.search(metin):
        puan += 1
    if i["ucret"]:
        puan += 1
    if i["konum_acik"]:
        puan += 1
    if KIDEMLI.search(f"{i['baslik']} {' '.join(i['etiketler'])}"):
        puan -= 4
    i["giris_puani"] = puan
    i["giris_uygun"] = puan >= 3 and i["konum_acik"]
    return i


def saatlik_ucretler(ilanlar):
    """'$25/hr' gibi saatlik ücretleri sayıya çevirir (aralıklarda ortası alınır)."""
    sonuc = []
    for i in ilanlar:
        for m in re.finditer(r"\$\s?(\d+(?:\.\d+)?)(?:\s?(?:-|–|to)\s?\$?\s?(\d+(?:\.\d+)?))?\s?(?:/|per|an?)\s?(?:hr|hour)", i["ucret"], re.I):
            a, b = float(m.group(1)), float(m.group(2) or m.group(1))
            if 3 <= a <= 200:
                sonuc.append((a + b) / 2)
    return sonuc


def video_basi_ucretler(ilanlar):
    sonuc = []
    for i in ilanlar:
        for m in re.finditer(r"\$\s?(\d+(?:\.\d+)?)(?:\s?(?:-|–|to)\s?\$?\s?(\d+(?:\.\d+)?))?\s?(?:/|per|an?)\s?(?:video|vid|edit|project)", i["ucret"], re.I):
            a, b = float(m.group(1)), float(m.group(2) or m.group(1))
            if 1 <= a <= 5000:
                sonuc.append((a + b) / 2)
    return sonuc


# ---------------------------------------------------------------- bildirim


def bildir(yeni_uygunlar):
    konu = os.environ.get("NTFY_KONU")
    if not konu or not yeni_uygunlar:
        return
    ilk = yeni_uygunlar[0]
    govde = f"{ilk['baslik']} — {ilk['kaynak']}"
    if ilk["ucret"]:
        govde += f" ({ilk['ucret']})"
    if len(yeni_uygunlar) > 1:
        govde += f"\n+{len(yeni_uygunlar) - 1} uygun ilan daha"
    req = urllib.request.Request(
        f"https://ntfy.sh/{konu}", data=govde.encode("utf-8"), method="POST",
        headers={"Title": "Yeni giris seviyesi video ilani", "Click": ilk["url"], "Tags": "movie_camera"},
    )
    urllib.request.urlopen(req, timeout=30)


# ---------------------------------------------------------------- rapor


def e(s):
    return html.escape(str(s or ""))


def sayim_tablosu(baslik, sayac, toplam):
    if not sayac:
        return f"<h3>{e(baslik)}</h3><p class='bos'>Henüz veri yok.</p>"
    satirlar = "".join(
        f"<tr><td>{e(ad)}</td><td class='sayi'>{n}</td><td><div class='bar' style='width:{100 * n / toplam:.0f}%'></div></td></tr>"
        for ad, n in sayac.most_common()
    )
    return f"<h3>{e(baslik)}</h3><table class='sayim'>{satirlar}</table>"


def ilan_kartlari(ilanlar):
    if not ilanlar:
        return "<p class='bos'>Bu dönemde ilan yok.</p>"
    parcalar = []
    for i in ilanlar:
        rozet = "<span class='rozet'>yeni başlayana uygun</span>" if i["giris_uygun"] else ""
        ayrinti = " · ".join(x for x in [i["sirket"], i["konum"], i["ucret"]] if x)
        turler = ", ".join(i["is_turleri"] + i["programlar"])
        parcalar.append(
            f"<li><a href='{e(i['url'])}' rel='follow'>{e(i['baslik'])}</a> {rozet}"
            f"<div class='alt'>{e(ayrinti)}</div>"
            f"<div class='alt'>Kaynak: {e(i['kaynak'])} · ilk görülme {e(i['ilk_gorulme'][:10])}"
            f"{' · ' + e(turler) if turler else ''}</div></li>"
        )
    return "<ul class='ilanlar'>" + "".join(parcalar) + "</ul>"


def rapor_yaz(tum, kaynak_durumu):
    hafta = (SIMDI - timedelta(days=7)).isoformat()
    son = sorted((i for i in tum if i["ilk_gorulme"] >= hafta), key=lambda i: -i["giris_puani"])
    is_s = Counter(t for i in son for t in i["is_turleri"])
    prog_s = Counter(p for i in son for p in i["programlar"])
    kaynak_s = Counter(i["kaynak"] for i in son)
    saatlik = saatlik_ucretler(son)
    video = video_basi_ucretler(son)

    def aralik(liste, birim):
        if not liste:
            return "veri yok"
        return f"{len(liste)} ilan · en düşük ${min(liste):.0f} · ortanca ${statistics.median(liste):.0f} · en yüksek ${max(liste):.0f} {birim}"

    durum = "".join(f"<li>{e(ad)}: {e(d)}</li>" for ad, d in kaynak_durumu.items())
    uygun = [i for i in son if i["giris_uygun"]]
    sayfa = f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Video İş Takibi</title>
<style>
:root{{--bg:#fafaf7;--fg:#1d1d1b;--soluk:#6b6b66;--vurgu:#2a6f4e;--bar:#cfe3d8;--kart:#fff;--cizgi:#e4e4de}}
@media (prefers-color-scheme:dark){{:root{{--bg:#161615;--fg:#ecece8;--soluk:#9a9a94;--vurgu:#7cc4a0;--bar:#2f5242;--kart:#1f1f1d;--cizgi:#333330}}}}
body{{background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;margin:0;padding:16px;max-width:860px;margin-inline:auto}}
h1{{margin:.2em 0}} h2{{margin-top:1.8em;border-bottom:1px solid var(--cizgi);padding-bottom:.2em}}
.alt,.bos,.not{{color:var(--soluk);font-size:.9em}} a{{color:var(--vurgu)}}
.ozet{{display:flex;gap:12px;flex-wrap:wrap}} .ozet div{{background:var(--kart);border:1px solid var(--cizgi);border-radius:8px;padding:10px 14px}}
.ozet b{{font-size:1.6em;display:block}}
table.sayim{{width:100%;border-collapse:collapse}} .sayim td{{padding:3px 6px}} .sayim td:last-child{{width:45%}}
.sayi{{text-align:right;font-variant-numeric:tabular-nums}} .bar{{background:var(--bar);height:12px;border-radius:3px}}
ul.ilanlar{{padding-left:1.1em}} ul.ilanlar li{{margin:.7em 0}}
.rozet{{background:var(--vurgu);color:var(--bg);font-size:.75em;padding:1px 6px;border-radius:9px;white-space:nowrap}}
</style></head><body>
<h1>Video düzenleme iş piyasası</h1>
<p class="alt">Son güncelleme: {SIMDI:%d.%m.%Y %H:%M} (UTC) · Son 7 günde ilk kez görülen ilanlar</p>
<div class="ozet"><div><b>{len(son)}</b>yeni ilan (7 gün)</div><div><b>{len(uygun)}</b>yeni başlayana uygun</div><div><b>{len(tum)}</b>toplam kayıt</div></div>
<h2>Ne isteniyor?</h2>
{sayim_tablosu("İş türleri", is_s, max(len(son), 1))}
{sayim_tablosu("İstenen programlar", prog_s, max(len(son), 1))}
<h3>Ücretler (ilanda yazıyorsa)</h3>
<p>Saatlik: {aralik(saatlik, "/ saat")}<br>Video başına: {aralik(video, "/ video")}</p>
<p class="not">Ücretler ilan metninden otomatik çıkarılır; kaba bir fikir verir, kesin değildir.</p>
{sayim_tablosu("Kaynaklara göre", kaynak_s, max(len(son), 1))}
<h2>Yeni başlayana uygun görünenler</h2>
{ilan_kartlari(uygun)}
<h2>Son 7 günün tüm ilanları</h2>
{ilan_kartlari([i for i in son if not i["giris_uygun"]])}
<h2>Tarama durumu</h2><ul class="alt">{durum}</ul>
<p class="not">İlanlar Remote OK, We Work Remotely, Remotive, Himalayas ve Reddit'in herkese açık akışlarından alınır; her ilan kendi kaynağına bağlanır.</p>
</body></html>"""
    RAPOR.parent.mkdir(exist_ok=True)
    RAPOR.write_text(sayfa, encoding="utf-8")


# ---------------------------------------------------------------- ana akış


def main():
    VERI.mkdir(exist_ok=True)
    goruldu = set(json.loads(GORULDU.read_text(encoding="utf-8"))) if GORULDU.exists() else set()
    tum = [json.loads(s) for s in ILANLAR.read_text(encoding="utf-8").splitlines()] if ILANLAR.exists() else []
    ilk_tarama = not goruldu

    yeniler, durum = [], {}
    for ad, fonk in KAYNAKLAR:
        try:
            bulunan = list(fonk())
            taze = [i for i in bulunan if i["id"] not in goruldu]
            for i in taze:
                goruldu.add(i["id"])
                i["ilk_gorulme"] = SIMDI.isoformat()
                yeniler.append(sinifla(i))
            durum[ad] = f"{len(bulunan)} ilgili ilan, {len(taze)} yeni"
        except Exception as hata:  # bir kaynak çökerse diğerleri devam etsin
            durum[ad] = f"HATA: {hata}"
        if ad.startswith("Reddit"):
            time.sleep(8)

    with ILANLAR.open("a", encoding="utf-8") as f:
        for i in yeniler:
            f.write(json.dumps(i, ensure_ascii=False) + "\n")
    GORULDU.write_text(json.dumps(sorted(goruldu), ensure_ascii=False, indent=0), encoding="utf-8")
    tum += yeniler
    rapor_yaz(tum, durum)

    uygunlar = sorted((i for i in yeniler if i["giris_uygun"]), key=lambda i: -i["giris_puani"])
    if not ilk_tarama:  # ilk taramada eski ilanların hepsi "yeni" sayılır; bildirim atma
        bildir(uygunlar)

    for ad, d in durum.items():
        print(f"- {ad}: {d}")
    print(f"Yeni ilan: {len(yeniler)} · yeni başlayana uygun: {sum(i['giris_uygun'] for i in yeniler)}")
    print(f"Rapor: {RAPOR}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
