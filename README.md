# Telegram AI Bot

Bot leve em Python que responde perguntas, pesquisa informacoes atuais e analisa fotos.

## Arquitetura

```text
Telegram -> app.py -> busca publica -> Gemini Flash -> resposta no Telegram
                 \-> imagem em memoria (sem salvar no disco)
```

O programa usa polling localmente e muda automaticamente para webhook quando encontra
`WEBHOOK_BASE_URL` ou `KOYEB_PUBLIC_DOMAIN` no ambiente.

## Executar no Windows

```powershell
cd D:\Ias\Telegram_AI_Bot
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Mantenha o terminal aberto enquanto quiser que o bot funcione. As chaves reais ficam no
arquivo `.env`, que esta ignorado pelo Git. Depois de trocar as chaves, atualize esse arquivo.

## Publicar gratuitamente no Koyeb

1. Troque as chaves expostas anteriormente e atualize o `.env` local.
2. Crie um repositorio privado no GitHub e envie apenas os arquivos versionaveis. O `.env`
   e excluido automaticamente pelo `.gitignore` e `.dockerignore`.
3. No Koyeb, escolha **Create Web Service**, conecte o repositorio e use **Dockerfile**.
4. Selecione a instancia **Free** e exponha a porta HTTP `8000` (o Koyeb tambem fornece
   a variavel `PORT` automaticamente).
5. Cadastre como Secrets/variaveis de ambiente:

   - `TELEGRAM_BOT_TOKEN`
   - `GEMINI_API_KEY`
   - `GEMINI_MODEL=gemini-3.8-flash`
   - `TELEGRAM_WEBHOOK_SECRET` (gere com o comando abaixo)

```powershell
py -c "import secrets; print(secrets.token_urlsafe(32))"
```

Nao e necessario cadastrar `WEBHOOK_BASE_URL` no Koyeb: o programa usa automaticamente
o dominio publico fornecido em `KOYEB_PUBLIC_DOMAIN`. Depois da implantacao, abra a URL
raiz do servico; a resposta esperada e `{"mode":"webhook","status":"ok"}`.

## Comandos

- `/start` ou `/help`: mostra a ajuda.
- Texto: responde e pesquisa na web quando a pergunta indicar informacao externa.
- Foto com legenda: responde ao pedido da legenda.
- Foto sem legenda: descreve a foto e transcreve textos visiveis.
