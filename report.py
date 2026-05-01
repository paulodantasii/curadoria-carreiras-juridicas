from urllib.parse import urlparse
from html import escape
from ia import STATUS_LABELS

def get_site_name(url: str) -> str:
    """Extrai apenas o nome principal do site para mostrar na etiqueta visual"""
    host = urlparse(url).netloc.replace("www.", "")
    return host.upper()

def clean_title(title: str) -> str:
    """Remove nomes de jornais e sites do final dos títulos das matérias"""
    suffixes = [
        " - PCI Concursos", " | PCI Concursos",
        " - JC Concursos", " | JC Concursos",
        " | Folha Dirigida", " - Concursos no Brasil",
        " | Acheconcursos", " - Acheconcursos",
        " - Magistrar", " | Magistrar",
        " - MDC Concursos", " | MDC Concursos",
        " - Estratégia Concursos", " | Estratégia Concursos",
        " - Concurso News", " | Concurso News",
        " - Uniten", " | Uniten", " - G1", " | G1",
        " - Folha PE", " | Folha PE", " - iG", " - iG Economia",
        " - Conjur", " | Conjur", " - Folha Vitória", " | Folha Vitória",
        " - Correio Braziliense", " - Itatiaia", " | Itatiaia",
        " - Mídia Bahia", " | Mídia Bahia", " - Roraima na Rede",
        " - Portal Piauí Hoje", " - Tribuna Online", " - ND Mais", " | ND Mais",
    ]
    for suffix in suffixes:
        if title.endswith(suffix):
            return title[: -len(suffix)].strip()
    return title.strip()

def group_relevant_items(relevant_items: list) -> list:
    """Agrupa as matérias por concurso baseado na tag 'grupo' gerada pela IA"""
    groups = {}
    for item in relevant_items:
        group_id = (item.get("grupo") or "").strip().lower()
        if not group_id:
            group_id = f"_isolated_{id(item)}"
            
        if group_id not in groups:
            groups[group_id] = []
        groups[group_id].append(item)

    group_list = [
        {"group_id": gid, "items": items, "size": len(items)}
        for gid, items in groups.items()
    ]
    # Ordena para os concursos com mais matérias aparecerem primeiro
    group_list.sort(key=lambda g: g["size"], reverse=True)
    return group_list

def render_group_card(idx: int, group: dict) -> str:
    """Gera o HTML interno de um 'Card' de concurso, criando o carrossel se necessário"""
    items = group["items"]
    size = group["size"]
    
    highlight_class = " highlight" if size >= 3 else ""
    sources_badge = f'<div class="sources-badge">📰 {size} fontes</div>' if size > 1 else ""

    slides_html = ""
    for item in items:
        title = item.get("real_title") or item.get("title") or "Ver link"
        title = escape(clean_title(title))
        url = item.get("url", "")
        reason = escape(item.get("motivo", ""))
        site = get_site_name(url)
        status = item.get("estado", "")
        
        status_label, status_color = STATUS_LABELS.get(status, ("", "#6c757d"))
        status_html = f'<span class="status-tag" style="background:{status_color};">{status_label}</span>' if status_label else ""

        slides_html += f"""
            <div class="slide">
                {status_html}<span class="site-tag">{site}</span>
                <h2><a href="{url}" target="_blank">{title}</a></h2>
                <p class="reason">{reason}</p>
                <a href="{url}" target="_blank" class="btn">Acessar matéria →</a>
            </div>
        """

    controls_html = ""
    if size > 1:
        indicators = "".join(f'<span class="indicator{" active" if i == 0 else ""}"></span>' for i in range(size))
        controls_html = f"""
            <div class="controls">
                <button class="arrow arrow-left" aria-label="Anterior">‹</button>
                <div class="indicators">{indicators}</div>
                <button class="arrow arrow-right" aria-label="Próxima">›</button>
            </div>
        """

    return f"""
        <div class="group-card{highlight_class}">
            {sources_badge}
            <div class="carousel">
                <div class="slides">
                    {slides_html}
                </div>
            </div>
            {controls_html}
        </div>
    """

def generate_html(groups: list, date_str: str, total_analyzed: int, total_relevant: int) -> str:
    """Gera o HTML completo da página a ser hospedada no GitHub Pages"""
    cards = "".join(render_group_card(idx, group) for idx, group in enumerate(groups))
    if not groups:
        cards = '<div class="empty">Nenhuma oportunidade relevante encontrada nesta verificação.</div>'

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CuradorIA de Carreiras Jurídicas</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🤖</text></svg>">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f0f2f5; color: #1a1a2e; min-height: 100vh; }}
        header {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: white; padding: 2rem 1.5rem 1.5rem; text-align: center; }}
        header h1 {{ font-size: 1.5rem; font-weight: 700; margin-bottom: 0.4rem; }}
        header p {{ font-size: 0.85rem; opacity: 0.75; }}
        .badge {{ display: inline-block; background: #e94560; color: white; font-size: 0.8rem; font-weight: 600; padding: 0.3rem 0.8rem; border-radius: 20px; margin-top: 0.8rem; }}
        .container {{ max-width: 680px; margin: 0 auto; padding: 1.5rem 1rem; }}
        .group-card {{ background: white; border-radius: 12px; margin-bottom: 1rem; box-shadow: 0 2px 8px rgba(0,0,0,0.07); border-left: 4px solid #e94560; overflow: hidden; position: relative; }}
        .group-card.highlight {{ border-left-width: 6px; }}
        .sources-badge {{ position: absolute; top: 0.8rem; right: 0.8rem; background: #1a1a2e; color: white; font-size: 0.7rem; font-weight: 600; padding: 0.25rem 0.55rem; border-radius: 12px; z-index: 2; }}
        .carousel {{ position: relative; overflow: hidden; }}
        .slides {{ display: flex; transition: transform 0.35s ease; }}
        .slide {{ min-width: 100%; padding: 1.2rem 1.3rem 0.5rem; }}
        .status-tag {{ display: inline-block; color: white; font-size: 0.7rem; font-weight: 600; padding: 0.2rem 0.55rem; border-radius: 6px; margin-bottom: 0.5rem; }}
        .site-tag {{ display: inline-block; background: #f0f2f5; color: #555; font-size: 0.7rem; font-weight: 600; padding: 0.2rem 0.55rem; border-radius: 6px; margin-bottom: 0.5rem; margin-left: 0.4rem; }}
        .slide h2 {{ font-size: 1rem; font-weight: 600; line-height: 1.4; margin-bottom: 0.5rem; color: #1a1a2e; }}
        .slide h2 a {{ color: inherit; text-decoration: none; }}
        .slide h2 a:hover {{ color: #e94560; }}
        .reason {{ font-size: 0.85rem; color: #666; line-height: 1.5; margin-bottom: 0.9rem; }}
        .btn {{ display: inline-block; background: #1a1a2e; color: white; font-size: 0.82rem; font-weight: 600; padding: 0.45rem 1rem; border-radius: 8px; text-decoration: none; }}
        .btn:hover {{ background: #e94560; }}
        .controls {{ display: flex; justify-content: space-between; align-items: center; padding: 0.6rem 1rem 1rem; border-top: 1px solid #f0f2f5; background: #fafbfc; }}
        .arrow {{ background: white; border: 1px solid #ddd; color: #1a1a2e; width: 32px; height: 32px; border-radius: 50%; font-size: 1rem; cursor: pointer; display: flex; align-items: center; justify-content: center; line-height: 1; }}
        .arrow:disabled {{ opacity: 0.3; cursor: default; }}
        .arrow:not(:disabled):hover {{ background: #1a1a2e; color: white; }}
        .indicators {{ display: flex; gap: 0.4rem; }}
        .indicator {{ width: 8px; height: 8px; border-radius: 50%; background: #ccc; }}
        .indicator.active {{ background: #e94560; }}
        .empty {{ text-align: center; color: #888; padding: 3rem 1rem; font-size: 0.95rem; }}
        footer {{ text-align: center; padding: 1.5rem; font-size: 0.78rem; color: #aaa; }}
    </style>
</head>
<body>
    <header>
        <h1>🤖 CuradorIA de Carreiras Jurídicas ⚖️</h1>
        <p>Verificação de {date_str} · {total_analyzed} artigos analisados</p>
        <div class="badge">{total_relevant} artigo(s) relevante(s) sobre {len(groups)} certame(s)</div>
    </header>
    <div class="container">
        {cards}
    </div>
    <footer>Gerado automaticamente · CuradorIA de Carreiras Jurídicas</footer>

    <script>
    document.querySelectorAll('.group-card').forEach(function(card) {{
        var slidesEl = card.querySelector('.slides');
        if (!slidesEl) return;
        var total = slidesEl.children.length;
        var current = 0;
        var leftArrow = card.querySelector('.arrow-left');
        var rightArrow = card.querySelector('.arrow-right');
        var indicators = card.querySelectorAll('.indicator');

        function update() {{
            slidesEl.style.transform = 'translateX(-' + (current * 100) + '%)';
            indicators.forEach(function(ind, i) {{
                ind.classList.toggle('active', i === current);
            }});
            if (leftArrow) leftArrow.disabled = current === 0;
            if (rightArrow) rightArrow.disabled = current === total - 1;
        }}

        if (leftArrow) leftArrow.addEventListener('click', function() {{
            if (current > 0) {{ current--; update(); }}
        }});
        if (rightArrow) rightArrow.addEventListener('click', function() {{
            if (current < total - 1) {{ current++; update(); }}
        }});
        update();
    }});
    </script>
</body>
</html>"""