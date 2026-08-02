# Instagram Baixar

App desktop para Windows que baixa fotos, reels, posts e destaques do Instagram
com a sua sessao logada. Lista midias, baixa com progresso e salva tudo em uma
pasta unica.

**Licenca:** [MIT](LICENSE)

## Inicio rapido

```bat
git clone https://github.com/caducosilva/instagram-baixar.git
cd instagram-baixar
ABRIR.bat
```

Na primeira execucao o `ABRIR.bat` cria o `.venv`, instala as dependencias e o
Chromium do Playwright. Nas proximas, so abre o app.

## O que faz

| Recurso | Detalhe |
|---------|---------|
| Sessao automatica | Conecta em segundo plano (Chrome headless). Renova a cada 1 min sem janela |
| Login manual | Botao **Abrir navegador e logar** se a sessao automatica falhar |
| Listagem | Posts, Reels, Destaques (pastas) ou Tudo |
| Download seletivo | Marque itens ou pastas de destaque e baixe |
| URL unica | Post, reel (`/reel/` ou `/reels/`) ou destaque |
| Qualidade | Videos via DASH na maior resolucao disponivel na API |
| Pasta unica | Tudo em `downloads/` (sem subpasta por @usuario) |
| Abrir pasta | Botao **Abrir pasta destino** no Explorer |

## Fluxo basico

1. Abra o app (`ABRIR.bat`). A sessao tenta conectar sozinha.
2. Cole `@usuario`, URL de perfil, post, reel ou destaque.
3. **Listar** ou **Baixar URL**.
4. Marque o que quiser e baixe. Acompanhe o progresso no log (sem popup de fim).

## Instalacao manual (opcional)

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\playwright install chromium
.venv\Scripts\pythonw app.py
```

## Dependencias

Ver `requirements.txt`:

- PySide6 (interface)
- requests, websocket-client (API / CDP)
- gallery-dl, yt-dlp (fallback de download)
- playwright (login visivel)
- browser-cookie3 (ler cookies do Chrome em disco, sem abrir janela)

## Teste sem login

```bat
.venv\Scripts\python test_smoke.py
```

## Estrutura

```
instagram-baixar/
  ABRIR.bat
  app.py
  session.py
  instagram_api.py
  downloader.py
  requirements.txt
  test_smoke.py
  LICENSE
  README.md
```

Pastas locais (gitignore, nao sobem no git):

- `.session/` - cookies e perfil do Chrome do app
- `downloads/` - midias baixadas
- `.venv/` - ambiente Python

## Avisos

- Use no seu conteudo / conta. Respeite a privacidade de terceiros.
- Nao compartilhe `cookies.txt` nem a pasta `.session/`.
- O Instagram pode limitar ou bloquear automacao. Se a sessao cair, use
  **Abrir navegador e logar**.

## Licenca

MIT. Copyright (c) 2026 Carlos Eduardo. Veja o arquivo [LICENSE](LICENSE).
