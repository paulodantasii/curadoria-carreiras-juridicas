import requests
from bs4 import BeautifulSoup
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

urls = [
    "https://www.pciconcursos.com.br/noticias/funpresp-jud-df-abre-concurso-publico-com-salarios-de-ate-11-4-mil",
    "https://cj.estrategia.com/portal/concurso-advogado-tres-barras-sc/",
]

for url in urls:
    print(f"\n=== {url} ===")
    try:
        resp = requests.get(url, timeout=20, headers=HEADERS)
        print(f"Status: {resp.status_code}")
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        texto = soup.get_text(separator=" ", strip=True)
        texto = re.sub(r"\s+", " ", texto).strip()
        print(f"Tamanho: {len(texto)} chars")
        print(f"Texto:\n{texto[:1500]}")
    except Exception as e:
        print(f"ERRO: {e}")
