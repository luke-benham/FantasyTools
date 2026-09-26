"""Bundle site/ + site/data into one self-contained HTML page (for a quick preview without hosting)."""
import json, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.path.join(ROOT, "site")
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "preview.html")
html = open(os.path.join(S, "index.html")).read()
body = html.split("<!--BODY-->")[1].split("<!--/BODY-->")[0]
data = {n: json.load(open(os.path.join(S, "data", f"{n}.json"))) for n in ("players", "leagues", "meta", "model")}
blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
page = ("<title>Front Office</title>\n"
        '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800&family=Barlow:wght@400;500;600;700&display=swap">\n'
        f"<style>{open(os.path.join(S, 'app.css')).read()}</style>\n{body}\n"
        f'<script type="application/json" id="fo-data">{blob}</script>\n'
        f"<script>{open(os.path.join(S, 'app.js')).read()}</script>\n")
open(out, "w").write(page)
print(out, len(page))
