# Instagram Baixar

App desktop (Windows) para baixar fotos, reels, posts e destaques do Instagram
usando a sua sessao logada. Lista midias, baixa com progresso e salva tudo em
uma pasta unica.

## Como abrir

Duplo clique em `ABRIR.bat` (cria o `.venv` e instala dependencias na primeira vez).

## Fluxo

1. A sessao conecta sozinha em segundo plano (Chrome headless).
   Se precisar login manual: **Abrir navegador e logar**.
2. Cole `@usuario`, URL de perfil, post, reel (`/reel/` ou `/reels/`) ou destaque.
3. **Listar** (Posts / Reels / Destaques) ou **Baixar URL**.
4. Marque o que quiser e baixe. Videos usam DASH na qualidade maxima disponivel.

Downloads ficam em `downloads/` (pasta unica). Use **Abrir pasta destino** no app.

## Teste sem login

```bat
.venv\Scripts\python test_smoke.py
```

## Dependencias

Ver `requirements.txt` (PySide6, gallery-dl, yt-dlp, playwright, browser-cookie3, ...).

## Pastas locais (nao sobem no git)

- `.session/` - cookies e perfil do Chrome do app
- `downloads/` - midias baixadas
- `.venv/` - ambiente Python

## Avisos

- Use no seu conteudo / conta. Respeite a privacidade de terceiros.
- Nao compartilhe `cookies.txt` nem a pasta `.session/`.
- O Instagram pode limitar ou bloquear automacao; reconecte a sessao se falhar.
